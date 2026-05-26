"""Admin billing service — generate / regenerate / mark paid / apply wallet credit.

Money-critical. All mutations run inside the caller's AsyncSession transaction.
Uses Postgres advisory locks to serialise concurrent generation / regeneration.

Constants:
- Default due_date = issued + 15 days (matches `PHASE 2B.6` spec).
- Advisory-lock keyspace: ("billing_gen"::bigint, year*12+month) for month-level
  generation; ("invoice_regen", lower_uuid_bigint) for single-invoice regen.
"""
from __future__ import annotations
import calendar
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import select, func, delete
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import now_utc, today_ist
from app.models.billing import (
    Invoice,
    InvoiceLineItem,
    InvoiceAdjustment,
    Payment,
    WalletTransaction,
    InvoiceAdjustmentKind,
)
from app.models.delivery import DeliveryOrder
from app.models.enums import (
    DeliveryOrderStatus,
    InvoiceStatus,
    PaymentMethod,
    PaymentStatus,
    UserRole,
)
from app.models.product import Product
from app.models.user import User
from app.services import audit_service, wallet_service


BILLING_GEN_LOCK_KEY = 7_234_891  # stable random int, namespace for billing-gen advisory locks
DUE_DATE_OFFSET_DAYS = 15


# -------- exceptions / result types --------

class BillingGenerationLocked(RuntimeError):
    """Another generation is in progress for the same month."""


@dataclass
class GenerationResult:
    created_count: int
    skipped_customers: int
    regenerated_count: int
    failed: list[dict[str, Any]]
    invoice_ids: list[uuid.UUID]


# -------- helpers --------

def _month_range(year: int, month: int) -> tuple[date, date]:
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    return first, last


def _invoice_snapshot(inv: Invoice, line_items: list[InvoiceLineItem]) -> dict[str, Any]:
    return {
        "id": str(inv.id),
        "customer_id": str(inv.customer_id),
        "year": inv.year,
        "month": inv.month,
        "subtotal_paise": inv.subtotal_paise,
        "adjustments_paise": inv.adjustments_paise,
        "total_paise": inv.total_paise,
        "amount_paid_paise": inv.amount_paid_paise,
        "status": inv.status.value if hasattr(inv.status, "value") else str(inv.status),
        "issued_at": inv.issued_at.isoformat() if inv.issued_at else None,
        "due_date": inv.due_date.isoformat() if inv.due_date else None,
        "line_items": [
            {
                "date": li.date.isoformat(),
                "product_id": str(li.product_id),
                "quantity": li.quantity,
                "price_paise": li.price_paise,
                "total_paise": li.total_paise,
                "delivery_order_id": str(li.delivery_order_id) if li.delivery_order_id else None,
            }
            for li in line_items
        ],
    }


async def _try_advisory_lock(db: AsyncSession, key1: int, key2: int) -> bool:
    """Transactional advisory lock — released on COMMIT / ROLLBACK."""
    from sqlalchemy import text as _text
    row = (await db.execute(_text("SELECT pg_try_advisory_xact_lock(:k1, :k2)"), {"k1": key1, "k2": key2})).scalar()
    return bool(row)


def _due_date_for(year: int, month: int) -> date:
    """Due date = last day of the billed month + 15 days (i.e., ~mid of following month)."""
    _, last_day = _month_range(year, month)
    return last_day + timedelta(days=DUE_DATE_OFFSET_DAYS)


# -------- core: compute one customer's line items --------

async def _compute_customer_subtotal(
    db: AsyncSession, customer_id: uuid.UUID, year: int, month: int
) -> tuple[int, list[InvoiceLineItem]]:
    """Reads DELIVERED delivery_orders for the customer in (year, month) and builds
    line items using the snapshotted `unit_price_paise` (NOT current product price).

    Billing decision (documented): only orders in status=DELIVERED are billed.
    SKIPPED / FAILED / PENDING are NOT billed. Zero-delivery months produce no invoice.
    """
    first, last = _month_range(year, month)
    stmt = (
        select(DeliveryOrder)
        .where(
            DeliveryOrder.customer_id == customer_id,
            DeliveryOrder.delivery_date >= first,
            DeliveryOrder.delivery_date <= last,
            DeliveryOrder.status == DeliveryOrderStatus.DELIVERED,
        )
        .order_by(DeliveryOrder.delivery_date.asc())
    )
    orders = (await db.execute(stmt)).scalars().all()
    line_items: list[InvoiceLineItem] = []
    subtotal = 0
    for o in orders:
        qty = o.delivered_quantity if o.delivered_quantity is not None else o.quantity
        unit_price = o.unit_price_paise
        line_total = qty * unit_price
        subtotal += line_total
        line_items.append(InvoiceLineItem(
            date=o.delivery_date,
            product_id=o.product_id,
            quantity=qty,
            price_paise=unit_price,
            total_paise=line_total,
            delivery_order_id=o.id,
        ))
    return subtotal, line_items


# -------- status helpers --------

def _recompute_status(inv: Invoice) -> None:
    """Recompute invoice.status from (total, amount_paid, due_date).

    Rules:
    - amount_paid >= total → PAID (paid_at set)
    - amount_paid > 0 but < total → PARTIALLY_PAID
    - amount_paid == 0 and today > due_date → OVERDUE
    - else → ISSUED

    Side effect: invalidates the cached PDF (status + balance_due both render
    onto the document, so any status change makes the cache stale).
    """
    today = today_ist()
    _prev_status = inv.status
    if inv.amount_paid_paise >= inv.total_paise and inv.total_paise > 0:
        inv.status = InvoiceStatus.PAID
        if not inv.paid_at:
            inv.paid_at = now_utc()
    elif inv.amount_paid_paise > 0 and inv.amount_paid_paise < inv.total_paise:
        inv.status = InvoiceStatus.PARTIALLY_PAID
        inv.paid_at = None
    elif inv.total_paise == 0:
        inv.status = InvoiceStatus.PAID
        if not inv.paid_at:
            inv.paid_at = now_utc()
    elif inv.due_date and today > inv.due_date:
        inv.status = InvoiceStatus.OVERDUE
        inv.paid_at = None
    else:
        inv.status = InvoiceStatus.ISSUED
    if inv.status != _prev_status:
        inv.pdf_storage_path = None
        inv.pdf_generated_at = None
        inv.paid_at = None


async def _refresh_payment_totals(db: AsyncSession, invoice: Invoice) -> None:
    """Recalc invoice.amount_paid_paise from SUM(payments.amount where status=SUCCESS)."""
    paid = (await db.execute(
        select(func.coalesce(func.sum(Payment.amount_paise), 0)).where(
            Payment.invoice_id == invoice.id,
            Payment.status == PaymentStatus.SUCCESS,
        )
    )).scalar_one()
    invoice.amount_paid_paise = int(paid or 0)


async def _refresh_adjustments_total(db: AsyncSession, invoice: Invoice) -> None:
    """Recalc invoice.adjustments_paise + total_paise from InvoiceAdjustment rows."""
    adj = (await db.execute(
        select(func.coalesce(func.sum(InvoiceAdjustment.amount_paise), 0)).where(
            InvoiceAdjustment.invoice_id == invoice.id
        )
    )).scalar_one()
    invoice.adjustments_paise = int(adj or 0)
    invoice.total_paise = max(0, invoice.subtotal_paise + invoice.adjustments_paise)


# -------- billing generation (month-level) --------

async def generate_invoices(
    db: AsyncSession,
    *,
    year: int,
    month: int,
    actor: User,
    regenerate: bool = False,
    reason: str | None = None,
    request: Request | None = None,
) -> GenerationResult:
    """Generate (or regenerate) invoices for every customer with DELIVERED orders in (year, month).

    - Not regenerate & some invoices exist for this period → 409 conflict.
    - Concurrency: Postgres advisory xact lock.
    - Per-customer atomicity: each invoice+line_items committed together; on per-customer
      error, that customer is skipped and recorded in `failed`.
    """
    if not (1 <= month <= 12):
        raise HTTPException(status_code=400, detail={"code": "bad_month", "message": "month must be 1-12"})

    lock_key2 = year * 12 + month
    if not await _try_advisory_lock(db, BILLING_GEN_LOCK_KEY, lock_key2):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "billing_generation_locked",
                "message": f"Billing generation for {year}-{month:02d} is already in progress.",
            },
        )

    # Fetch existing invoices for this period
    existing = (await db.execute(
        select(Invoice).where(Invoice.year == year, Invoice.month == month)
    )).scalars().all()

    if existing and not regenerate:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "invoices_already_exist",
                "message": (
                    f"{len(existing)} invoices already exist for {year}-{month:02d}. "
                    "Pass regenerate=true with a reason to replace them."
                ),
                "existing_count": len(existing),
            },
        )

    if regenerate and not (reason and len(reason.strip()) >= 10):
        raise HTTPException(
            status_code=400,
            detail={"code": "reason_required", "message": "Regeneration requires reason (min 10 chars)."},
        )

    # Pre-load existing invoices by customer_id for regenerate path; snapshot before we mutate.
    existing_by_cust: dict[uuid.UUID, Invoice] = {inv.customer_id: inv for inv in existing}
    if regenerate and existing:
        # Snapshot each existing invoice (with line items) into audit log BEFORE mutating
        for inv in existing:
            items = (await db.execute(
                select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == inv.id)
            )).scalars().all()
            before = _invoice_snapshot(inv, items)
            # Delete line_items + adjustments (they'll be re-derived); preserve payments + invoice row (same id)
            await db.execute(delete(InvoiceLineItem).where(InvoiceLineItem.invoice_id == inv.id))
            # Also clear adjustments of kind=override_adjustment (re-derive freshly); preserve manual/wallet
            await db.execute(delete(InvoiceAdjustment).where(
                InvoiceAdjustment.invoice_id == inv.id,
                InvoiceAdjustment.kind == InvoiceAdjustmentKind.OVERRIDE_ADJUSTMENT,
            ))
            inv.subtotal_paise = 0
            inv.adjustments_paise = 0
            inv.total_paise = 0
            inv.has_post_billing_adjustments = False
            inv.regenerated_count = (inv.regenerated_count or 0) + 1
            inv.last_regenerated_at = now_utc()
            inv.last_regenerated_by = actor.id
            # Invalidate the cached PDF so the next fetch regenerates with fresh data.
            inv.pdf_storage_path = None
            inv.pdf_generated_at = None
            # Stash before snapshot on actor's "audit bag" so we can write it after
            inv.__dict__["_before_snapshot"] = before

    # All active customers who might have activity
    customers = (await db.execute(
        select(User).where(User.role == UserRole.CUSTOMER)
    )).scalars().all()

    result = GenerationResult(
        created_count=0, skipped_customers=0, regenerated_count=0, failed=[], invoice_ids=[]
    )

    for cust in customers:
        try:
            subtotal, items = await _compute_customer_subtotal(db, cust.id, year, month)
            if subtotal == 0 or not items:
                result.skipped_customers += 1
                continue

            if regenerate and cust.id in existing_by_cust:
                inv = existing_by_cust[cust.id]
                inv.subtotal_paise = subtotal
                # Retain any non-override adjustments
                await _refresh_adjustments_total(db, inv)
                inv.total_paise = max(0, inv.subtotal_paise + inv.adjustments_paise)
                await _refresh_payment_totals(db, inv)
                _recompute_status(inv)
                for li in items:
                    li.invoice_id = inv.id
                    db.add(li)
                await db.flush()
                result.regenerated_count += 1
                result.invoice_ids.append(inv.id)
                # Write audit for this invoice's regeneration
                before_snap = inv.__dict__.pop("_before_snapshot", None)
                after_items = (await db.execute(
                    select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == inv.id)
                )).scalars().all()
                await audit_service.log_action(
                    db, actor=actor, action="invoice.regenerate",
                    entity_type="invoice", entity_id=str(inv.id),
                    before_state=before_snap,
                    after_state=_invoice_snapshot(inv, after_items),
                    reason=reason, request=request,
                )
            else:
                due_date = _due_date_for(year, month)
                inv = Invoice(
                    customer_id=cust.id,
                    year=year, month=month,
                    subtotal_paise=subtotal,
                    adjustments_paise=0,
                    total_paise=subtotal,
                    amount_paid_paise=0,
                    status=InvoiceStatus.ISSUED,
                    issued_at=now_utc(),
                    due_date=due_date,
                )
                db.add(inv)
                await db.flush()
                for li in items:
                    li.invoice_id = inv.id
                    db.add(li)
                await db.flush()
                result.created_count += 1
                result.invoice_ids.append(inv.id)

        except Exception as e:  # noqa: BLE001
            result.failed.append({
                "customer_id": str(cust.id),
                "phone": cust.phone,
                "error": str(e),
            })

    # Write the overall audit row for the month
    await audit_service.log_action(
        db, actor=actor,
        action=("billing.regenerate" if regenerate else "billing.generate"),
        entity_type="billing_period",
        entity_id=f"{year}-{month:02d}",
        before_state={"existing_invoices": len(existing)} if regenerate else None,
        after_state={
            "year": year, "month": month,
            "created_count": result.created_count,
            "regenerated_count": result.regenerated_count,
            "skipped_customers": result.skipped_customers,
            "failed_customers": len(result.failed),
        },
        reason=reason, request=request,
    )

    await db.flush()
    return result


# -------- single-invoice regeneration --------

async def regenerate_single_invoice(
    db: AsyncSession,
    *,
    invoice_id: uuid.UUID,
    actor: User,
    reason: str,
    request: Request | None = None,
) -> Invoice:
    """Regenerate one invoice. Preserves payments + manual/wallet adjustments; drops override adjustments + line items and re-derives them."""
    if not (reason and len(reason.strip()) >= 10):
        raise HTTPException(status_code=400, detail={"code": "reason_required", "message": "reason must be ≥10 chars"})

    inv = (await db.execute(
        select(Invoice).where(Invoice.id == invoice_id).with_for_update()
    )).scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="invoice not found")

    items = (await db.execute(
        select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == inv.id)
    )).scalars().all()
    before = _invoice_snapshot(inv, items)

    await db.execute(delete(InvoiceLineItem).where(InvoiceLineItem.invoice_id == inv.id))
    await db.execute(delete(InvoiceAdjustment).where(
        InvoiceAdjustment.invoice_id == inv.id,
        InvoiceAdjustment.kind == InvoiceAdjustmentKind.OVERRIDE_ADJUSTMENT,
    ))
    subtotal, new_items = await _compute_customer_subtotal(db, inv.customer_id, inv.year, inv.month)
    inv.subtotal_paise = subtotal
    inv.has_post_billing_adjustments = False
    inv.regenerated_count = (inv.regenerated_count or 0) + 1
    inv.last_regenerated_at = now_utc()
    inv.last_regenerated_by = actor.id
    for li in new_items:
        li.invoice_id = inv.id
        db.add(li)
    await _refresh_adjustments_total(db, inv)
    await _refresh_payment_totals(db, inv)
    _recompute_status(inv)
    await db.flush()

    after_items = (await db.execute(
        select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == inv.id)
    )).scalars().all()
    await audit_service.log_action(
        db, actor=actor, action="invoice.regenerate",
        entity_type="invoice", entity_id=str(inv.id),
        before_state=before, after_state=_invoice_snapshot(inv, after_items),
        reason=reason, request=request,
    )
    return inv


# -------- mark paid --------

async def mark_invoice_paid(
    db: AsyncSession,
    *,
    invoice_id: uuid.UUID,
    actor: User,
    amount_paise: int,
    method: PaymentMethod,
    reference: str | None,
    reason: str,
    force: bool = False,
    request: Request | None = None,
) -> tuple[Invoice, Payment]:
    """Record a payment against an invoice.

    - Creates `payments` row (status=SUCCESS).
    - For method=WALLET: additionally debits customer's wallet via wallet_service.adjust.
      If balance < amount and not force, returns 400 without creating payment.
    - Recomputes invoice.amount_paid_paise, invoice.status atomically.
    """
    if amount_paise <= 0:
        raise HTTPException(status_code=400, detail={"code": "bad_amount", "message": "amount_paise must be > 0"})
    if not (reason and len(reason.strip()) >= 10):
        raise HTTPException(status_code=400, detail={"code": "reason_required", "message": "reason must be ≥10 chars"})

    inv = (await db.execute(
        select(Invoice).where(Invoice.id == invoice_id).with_for_update()
    )).scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="invoice not found")

    before = {
        "status": inv.status.value,
        "amount_paid_paise": inv.amount_paid_paise,
        "total_paise": inv.total_paise,
    }

    # Block overpayment-by-accident unless force.
    remaining = inv.total_paise - inv.amount_paid_paise
    if amount_paise > remaining and not force:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "overpayment",
                "message": (
                    f"Amount {amount_paise} exceeds remaining balance {remaining}. "
                    "Retry with force=true to record anyway (excess will be credited via separate adjustment)."
                ),
                "remaining_paise": remaining,
            },
        )

    # Wallet side-effect (must come BEFORE payment row so wallet_service's lock + integrity
    # check can abort the whole transaction cleanly if balance insufficient).
    wallet_tx = None
    if method == PaymentMethod.WALLET:
        wallet_tx = await wallet_service.adjust(
            db,
            customer_id=inv.customer_id,
            change_paise=-amount_paise,
            reason=f"Paid invoice {inv.year}-{inv.month:02d} (inv {str(inv.id)[:8]})"[:120],
            actor=actor,
            force=force,  # pass-through
            reference_id=str(inv.id),
            request=request,
        )

    pay = Payment(
        customer_id=inv.customer_id,
        invoice_id=inv.id,
        amount_paise=amount_paise,
        method=method,
        reference=reference,
        status=PaymentStatus.SUCCESS,
    )
    db.add(pay)
    await db.flush()

    await _refresh_payment_totals(db, inv)
    _recompute_status(inv)
    await db.flush()

    await audit_service.log_action(
        db, actor=actor, action="invoice.mark_paid",
        entity_type="invoice", entity_id=str(inv.id),
        before_state=before,
        after_state={
            "status": inv.status.value,
            "amount_paid_paise": inv.amount_paid_paise,
            "payment_id": str(pay.id),
            "amount_paise": amount_paise,
            "method": method.value if hasattr(method, "value") else str(method),
            "reference": reference,
            "wallet_transaction_id": str(wallet_tx.id) if wallet_tx else None,
        },
        reason=reason, request=request,
    )
    return inv, pay


# -------- apply wallet credit --------

async def apply_wallet_credit(
    db: AsyncSession,
    *,
    invoice_id: uuid.UUID,
    actor: User,
    amount_paise: int,
    reason: str,
    request: Request | None = None,
) -> tuple[Invoice, InvoiceAdjustment, WalletTransaction]:
    """Deduct from customer wallet AND reduce invoice.total in one transaction.

    Creates:
    - wallet_transactions row (change=-amount)
    - invoice_adjustments row (amount=-amount, kind=wallet_credit)
    Plus the wallet_service audit + our own invoice.apply_wallet_credit audit.
    """
    if amount_paise <= 0:
        raise HTTPException(status_code=400, detail={"code": "bad_amount", "message": "amount_paise must be > 0"})
    if not (reason and len(reason.strip()) >= 10):
        raise HTTPException(status_code=400, detail={"code": "reason_required", "message": "reason must be ≥10 chars"})

    inv = (await db.execute(
        select(Invoice).where(Invoice.id == invoice_id).with_for_update()
    )).scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="invoice not found")

    remaining = inv.total_paise - inv.amount_paid_paise
    if amount_paise > remaining:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "exceeds_balance",
                "message": f"Credit {amount_paise} exceeds remaining balance {remaining}.",
                "remaining_paise": remaining,
            },
        )

    before = {
        "total_paise": inv.total_paise,
        "adjustments_paise": inv.adjustments_paise,
        "status": inv.status.value,
    }

    # Debit wallet (enforces integrity invariant + audits wallet.adjust)
    wtx = await wallet_service.adjust(
        db,
        customer_id=inv.customer_id,
        change_paise=-amount_paise,
        reason=f"Credit to invoice {inv.year}-{inv.month:02d}"[:120],
        actor=actor,
        force=False,
        reference_id=str(inv.id),
        request=request,
    )

    adj = InvoiceAdjustment(
        invoice_id=inv.id,
        kind=InvoiceAdjustmentKind.WALLET_CREDIT,
        amount_paise=-amount_paise,  # negative = reduces amount due
        reason=reason,
        actor_user_id=actor.id,
        reference_id=str(wtx.id),
    )
    db.add(adj)
    await db.flush()

    await _refresh_adjustments_total(db, inv)
    _recompute_status(inv)
    await db.flush()

    await audit_service.log_action(
        db, actor=actor, action="invoice.apply_wallet_credit",
        entity_type="invoice", entity_id=str(inv.id),
        before_state=before,
        after_state={
            "total_paise": inv.total_paise,
            "adjustments_paise": inv.adjustments_paise,
            "status": inv.status.value,
            "adjustment_id": str(adj.id),
            "wallet_transaction_id": str(wtx.id),
            "amount_paise": amount_paise,
        },
        reason=reason, request=request,
    )
    return inv, adj, wtx


# -------- post-billing flag update (called from delivery_admin override) --------

async def flag_post_billing_adjustment(
    db: AsyncSession,
    *,
    customer_id: uuid.UUID,
    delivery_date: date,
    ledger_delta_paise: int,
    reason: str,
    actor: User,
    reference_id: str | None = None,
) -> Invoice | None:
    """If an invoice exists for the (customer, year, month) of `delivery_date`,
    set has_post_billing_adjustments=true and append an override_adjustment row.

    `ledger_delta_paise` is the signed delta in billable amount caused by the override
    (positive = customer owes more, negative = less). Called from delivery_admin_service.
    """
    inv = (await db.execute(
        select(Invoice).where(
            Invoice.customer_id == customer_id,
            Invoice.year == delivery_date.year,
            Invoice.month == delivery_date.month,
        ).with_for_update()
    )).scalar_one_or_none()
    if not inv:
        return None

    inv.has_post_billing_adjustments = True
    # Invalidate the cached PDF — the override changed billable data.
    inv.pdf_storage_path = None
    inv.pdf_generated_at = None
    if ledger_delta_paise != 0:
        adj = InvoiceAdjustment(
            invoice_id=inv.id,
            kind=InvoiceAdjustmentKind.OVERRIDE_ADJUSTMENT,
            amount_paise=ledger_delta_paise,
            reason=reason,
            actor_user_id=actor.id,
            reference_id=reference_id,
        )
        db.add(adj)
        await db.flush()
        await _refresh_adjustments_total(db, inv)
        _recompute_status(inv)
    await db.flush()
    return inv
