"""Admin billing console endpoints (Phase 2B.6).

- GET  /admin/billing/status?year=Y&month=M   — period stats
- POST /admin/billing/generate                 — generate or regenerate
- GET  /admin/invoices                          — list with filters
- GET  /admin/invoices/{id}                     — full detail
- POST /admin/invoices/{id}/mark-paid           — record payment
- POST /admin/invoices/{id}/regenerate          — single-invoice regen
- POST /admin/invoices/{id}/apply-wallet-credit — wallet -> invoice
- GET  /admin/billing/overdue                   — customers with overdue invoices
- GET  /admin/billing/register?year=Y&month=M   — CSV-ready export rows

All routes: admin-only (see dependencies=...).
"""
from __future__ import annotations
from datetime import date, datetime
from typing import Any, Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import now_utc, today_ist
from app.db.session import get_db
from app.middleware.auth import require_admin
from app.models.audit_log import AuditLog
from app.models.billing import (
    Invoice,
    InvoiceLineItem,
    InvoiceAdjustment,
    Payment,
)
from app.models.enums import InvoiceStatus, PaymentMethod, PaymentStatus, UserRole
from app.models.product import Product
from app.models.user import User
from app.services import billing_admin_service as bas


router = APIRouter(
    prefix="/admin",
    tags=["admin-billing"],
    dependencies=[Depends(require_admin)],
)


# -------- request schemas --------

class GenerateBody(BaseModel):
    year: int = Field(..., ge=2020, le=2100)
    month: int = Field(..., ge=1, le=12)
    regenerate: bool = False
    reason: str | None = Field(None, max_length=500)


class MarkPaidBody(BaseModel):
    amount_paise: int = Field(..., gt=0)
    method: Literal["cash", "upi", "bank_transfer", "wallet", "other"]
    reference: str | None = Field(None, max_length=255)
    reason: str = Field(..., min_length=10, max_length=500)
    force: bool = False


class RegenerateBody(BaseModel):
    reason: str = Field(..., min_length=10, max_length=500)


class WalletCreditBody(BaseModel):
    amount_paise: int = Field(..., gt=0)
    reason: str = Field(..., min_length=10, max_length=500)


# -------- response schemas --------

class InvoiceRow(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    customer_name: str | None
    customer_phone: str
    year: int
    month: int
    subtotal_paise: int
    adjustments_paise: int
    total_paise: int
    amount_paid_paise: int
    balance_due_paise: int
    status: str
    issued_at: datetime | None
    due_date: date | None
    paid_at: datetime | None
    days_overdue: int
    has_post_billing_adjustments: bool
    regenerated_count: int


class Paginated(BaseModel):
    items: list[InvoiceRow]
    total: int
    page: int
    page_size: int


class LineItemOut(BaseModel):
    id: uuid.UUID
    date: date
    product_id: uuid.UUID
    product_name: str
    product_sku: str
    quantity: int
    price_paise: int
    total_paise: int
    delivery_order_id: uuid.UUID | None


class AdjustmentOut(BaseModel):
    id: uuid.UUID
    kind: str
    amount_paise: int
    reason: str
    actor_user_id: uuid.UUID | None
    actor_name: str | None
    reference_id: str | None
    created_at: datetime


class PaymentOut(BaseModel):
    id: uuid.UUID
    amount_paise: int
    method: str
    reference: str | None
    status: str
    created_at: datetime


class AuditOut(BaseModel):
    id: uuid.UUID
    action: str
    actor_name: str | None
    before_state: dict | None
    after_state: dict | None
    reason: str | None
    created_at: datetime


class InvoiceDetail(BaseModel):
    invoice: InvoiceRow
    line_items: list[LineItemOut]
    adjustments: list[AdjustmentOut]
    payments: list[PaymentOut]
    audit_log: list[AuditOut]


class BillingStatus(BaseModel):
    year: int
    month: int
    invoice_count: int
    by_status: dict[str, int]
    subtotal_paise: int
    total_billed_paise: int
    total_collected_paise: int
    outstanding_paise: int
    last_generated_at: datetime | None
    last_generated_by: str | None
    regenerations: int
    failed_customers_last_run: int


class OverdueCustomer(BaseModel):
    customer_id: uuid.UUID
    customer_name: str | None
    customer_phone: str
    oldest_overdue_invoice_id: uuid.UUID
    oldest_due_date: date
    days_overdue: int
    overdue_count: int
    overdue_total_paise: int


class RegisterRow(BaseModel):
    invoice_id: uuid.UUID
    customer_name: str | None
    customer_phone: str
    year: int
    month: int
    subtotal_paise: int
    adjustments_paise: int
    total_paise: int
    amount_paid_paise: int
    balance_due_paise: int
    status: str
    issued_at: datetime | None
    due_date: date | None
    paid_at: datetime | None


# -------- helpers --------

def _days_overdue(inv: Invoice) -> int:
    if not inv.due_date:
        return 0
    today = today_ist()
    if today <= inv.due_date:
        return 0
    if inv.amount_paid_paise >= inv.total_paise and inv.total_paise > 0:
        return 0
    return (today - inv.due_date).days


def _invoice_row(inv: Invoice, u: User | None) -> InvoiceRow:
    return InvoiceRow(
        id=inv.id,
        customer_id=inv.customer_id,
        customer_name=u.name if u else None,
        customer_phone=u.phone if u else "",
        year=inv.year, month=inv.month,
        subtotal_paise=inv.subtotal_paise,
        adjustments_paise=inv.adjustments_paise,
        total_paise=inv.total_paise,
        amount_paid_paise=inv.amount_paid_paise,
        balance_due_paise=max(0, inv.total_paise - inv.amount_paid_paise),
        status=inv.status.value if hasattr(inv.status, "value") else str(inv.status),
        issued_at=inv.issued_at,
        due_date=inv.due_date,
        paid_at=inv.paid_at,
        days_overdue=_days_overdue(inv),
        has_post_billing_adjustments=inv.has_post_billing_adjustments,
        regenerated_count=inv.regenerated_count or 0,
    )


# -------- status --------

@router.get("/billing/status", response_model=BillingStatus)
async def billing_status(
    year: int = Query(..., ge=2020, le=2100),
    month: int = Query(..., ge=1, le=12),
    db: AsyncSession = Depends(get_db),
):
    # Invoice counts + totals
    invoices = (await db.execute(
        select(Invoice).where(Invoice.year == year, Invoice.month == month)
    )).scalars().all()

    by_status: dict[str, int] = {}
    subtotal = total_billed = total_collected = 0
    regenerations = 0
    for inv in invoices:
        by_status[inv.status.value] = by_status.get(inv.status.value, 0) + 1
        subtotal += inv.subtotal_paise
        total_billed += inv.total_paise
        total_collected += inv.amount_paid_paise
        regenerations += inv.regenerated_count or 0

    # Last generation audit
    last_audit = (await db.execute(
        select(AuditLog).where(
            AuditLog.entity_type == "billing_period",
            AuditLog.entity_id == f"{year}-{month:02d}",
        ).order_by(AuditLog.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    last_actor_name: str | None = None
    if last_audit and last_audit.actor_user_id:
        u = (await db.execute(select(User).where(User.id == last_audit.actor_user_id))).scalar_one_or_none()
        last_actor_name = u.name if u else None
    failed_last = (last_audit.after_state or {}).get("failed_customers", 0) if last_audit else 0

    return BillingStatus(
        year=year, month=month,
        invoice_count=len(invoices),
        by_status=by_status,
        subtotal_paise=subtotal,
        total_billed_paise=total_billed,
        total_collected_paise=total_collected,
        outstanding_paise=max(0, total_billed - total_collected),
        last_generated_at=last_audit.created_at if last_audit else None,
        last_generated_by=last_actor_name,
        regenerations=regenerations,
        failed_customers_last_run=int(failed_last or 0),
    )


# -------- generate / regenerate --------

@router.post("/billing/generate", status_code=201)
async def generate(
    body: GenerateBody,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await bas.generate_invoices(
        db,
        year=body.year, month=body.month,
        actor=admin,
        regenerate=body.regenerate,
        reason=body.reason,
        request=request,
    )
    return {
        "year": body.year, "month": body.month,
        "regenerate": body.regenerate,
        "created_count": result.created_count,
        "regenerated_count": result.regenerated_count,
        "skipped_customers": result.skipped_customers,
        "failed": result.failed,
    }


# -------- list invoices --------

@router.get("/invoices", response_model=Paginated)
async def list_invoices(
    year: int | None = None,
    month: int | None = None,
    status: str | None = None,
    customer_id: uuid.UUID | None = None,
    has_adjustments: bool | None = None,
    overdue: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Invoice, User).join(User, User.id == Invoice.customer_id)
    if year is not None:
        stmt = stmt.where(Invoice.year == year)
    if month is not None:
        stmt = stmt.where(Invoice.month == month)
    if status:
        try:
            st = InvoiceStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid status '{status}'")
        stmt = stmt.where(Invoice.status == st)
    if customer_id:
        stmt = stmt.where(Invoice.customer_id == customer_id)
    if has_adjustments is not None:
        stmt = stmt.where(Invoice.has_post_billing_adjustments.is_(has_adjustments))
    if overdue:
        stmt = stmt.where(
            Invoice.due_date < today_ist(),
            Invoice.amount_paid_paise < Invoice.total_paise,
        )

    total = (await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )).scalar_one()

    stmt = stmt.order_by(Invoice.year.desc(), Invoice.month.desc(), Invoice.created_at.desc()).limit(page_size).offset((page - 1) * page_size)
    rows = (await db.execute(stmt)).all()
    items = [_invoice_row(inv, u) for inv, u in rows]
    return Paginated(items=items, total=int(total), page=page, page_size=page_size)


# -------- invoice detail --------

@router.get("/invoices/{invoice_id}", response_model=InvoiceDetail)
async def invoice_detail(invoice_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(
        select(Invoice, User).join(User, User.id == Invoice.customer_id).where(Invoice.id == invoice_id)
    )).first()
    if not row:
        raise HTTPException(status_code=404, detail="invoice not found")
    inv, u = row

    items_rows = (await db.execute(
        select(InvoiceLineItem, Product)
        .join(Product, Product.id == InvoiceLineItem.product_id)
        .where(InvoiceLineItem.invoice_id == inv.id)
        .order_by(InvoiceLineItem.date.asc())
    )).all()
    line_items = [
        LineItemOut(
            id=li.id, date=li.date, product_id=li.product_id,
            product_name=p.name, product_sku=p.sku,
            quantity=li.quantity, price_paise=li.price_paise,
            total_paise=li.total_paise,
            delivery_order_id=li.delivery_order_id,
        )
        for li, p in items_rows
    ]

    adj_rows = (await db.execute(
        select(InvoiceAdjustment)
        .where(InvoiceAdjustment.invoice_id == inv.id)
        .order_by(InvoiceAdjustment.created_at.asc())
    )).scalars().all()
    actor_ids = {a.actor_user_id for a in adj_rows if a.actor_user_id}
    actor_map = {
        u2.id: u2 for u2 in (await db.execute(
            select(User).where(User.id.in_(actor_ids))
        )).scalars().all()
    } if actor_ids else {}
    adjustments = [
        AdjustmentOut(
            id=a.id, kind=a.kind, amount_paise=a.amount_paise, reason=a.reason,
            actor_user_id=a.actor_user_id,
            actor_name=actor_map[a.actor_user_id].name if a.actor_user_id in actor_map else None,
            reference_id=a.reference_id, created_at=a.created_at,
        )
        for a in adj_rows
    ]

    pay_rows = (await db.execute(
        select(Payment).where(Payment.invoice_id == inv.id).order_by(Payment.created_at.asc())
    )).scalars().all()
    payments = [
        PaymentOut(
            id=p.id, amount_paise=p.amount_paise,
            method=p.method.value if hasattr(p.method, "value") else str(p.method),
            reference=p.reference,
            status=p.status.value if hasattr(p.status, "value") else str(p.status),
            created_at=p.created_at,
        )
        for p in pay_rows
    ]

    audit_rows = (await db.execute(
        select(AuditLog).where(
            AuditLog.entity_type == "invoice", AuditLog.entity_id == str(inv.id)
        ).order_by(AuditLog.created_at.desc()).limit(100)
    )).scalars().all()
    audit_actors = {u2.id: u2 for u2 in (await db.execute(
        select(User).where(User.id.in_({a.actor_user_id for a in audit_rows if a.actor_user_id}))
    )).scalars().all()}
    audit_log = [
        AuditOut(
            id=a.id, action=a.action,
            actor_name=audit_actors[a.actor_user_id].name if a.actor_user_id in audit_actors else None,
            before_state=a.before_state, after_state=a.after_state,
            reason=a.reason, created_at=a.created_at,
        )
        for a in audit_rows
    ]

    return InvoiceDetail(
        invoice=_invoice_row(inv, u),
        line_items=line_items,
        adjustments=adjustments,
        payments=payments,
        audit_log=audit_log,
    )


# -------- mark paid --------

@router.post("/invoices/{invoice_id}/mark-paid", response_model=InvoiceDetail, status_code=201)
async def mark_paid(
    invoice_id: uuid.UUID,
    body: MarkPaidBody,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        method = PaymentMethod(body.method)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid method '{body.method}'")
    await bas.mark_invoice_paid(
        db,
        invoice_id=invoice_id, actor=admin,
        amount_paise=body.amount_paise, method=method,
        reference=body.reference, reason=body.reason, force=body.force,
        request=request,
    )
    return await invoice_detail(invoice_id, db)


# -------- regenerate single invoice --------

@router.post("/invoices/{invoice_id}/regenerate", response_model=InvoiceDetail, status_code=201)
async def regenerate_invoice(
    invoice_id: uuid.UUID,
    body: RegenerateBody,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await bas.regenerate_single_invoice(
        db, invoice_id=invoice_id, actor=admin, reason=body.reason, request=request,
    )
    return await invoice_detail(invoice_id, db)


# -------- apply wallet credit --------

@router.post("/invoices/{invoice_id}/apply-wallet-credit", response_model=InvoiceDetail, status_code=201)
async def apply_wallet_credit(
    invoice_id: uuid.UUID,
    body: WalletCreditBody,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await bas.apply_wallet_credit(
        db, invoice_id=invoice_id, actor=admin,
        amount_paise=body.amount_paise, reason=body.reason, request=request,
    )
    return await invoice_detail(invoice_id, db)


@router.get("/invoices/{invoice_id}/pdf")
async def admin_invoice_pdf(
    invoice_id: uuid.UUID,
    download: bool = Query(False),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin-only invoice PDF endpoint. Admin can fetch any invoice's PDF."""
    from fastapi.responses import Response
    from app.services.invoice_pdf_service import get_or_generate

    inv = (await db.execute(
        select(Invoice).where(Invoice.id == invoice_id)
    )).scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="invoice not found")

    pdf = await get_or_generate(db, inv)
    disposition = "attachment" if download else "inline"
    filename = f"posuhtik_invoice_{inv.year}_{inv.month:02d}_{str(inv.id)[:8]}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


# -------- overdue --------

@router.get("/billing/overdue", response_model=list[OverdueCustomer])
async def overdue_customers(db: AsyncSession = Depends(get_db)):
    today = today_ist()
    rows = (await db.execute(
        select(Invoice, User).join(User, User.id == Invoice.customer_id).where(
            Invoice.due_date < today,
            Invoice.amount_paid_paise < Invoice.total_paise,
        ).order_by(Invoice.due_date.asc())
    )).all()
    by_cust: dict[uuid.UUID, dict[str, Any]] = {}
    for inv, u in rows:
        balance = inv.total_paise - inv.amount_paid_paise
        entry = by_cust.setdefault(inv.customer_id, {
            "customer_id": inv.customer_id,
            "customer_name": u.name,
            "customer_phone": u.phone,
            "oldest_overdue_invoice_id": inv.id,
            "oldest_due_date": inv.due_date,
            "overdue_count": 0,
            "overdue_total_paise": 0,
        })
        entry["overdue_count"] += 1
        entry["overdue_total_paise"] += balance
        if inv.due_date and entry["oldest_due_date"] and inv.due_date < entry["oldest_due_date"]:
            entry["oldest_due_date"] = inv.due_date
            entry["oldest_overdue_invoice_id"] = inv.id

    out: list[OverdueCustomer] = []
    for e in by_cust.values():
        out.append(OverdueCustomer(
            customer_id=e["customer_id"],
            customer_name=e["customer_name"],
            customer_phone=e["customer_phone"],
            oldest_overdue_invoice_id=e["oldest_overdue_invoice_id"],
            oldest_due_date=e["oldest_due_date"],
            days_overdue=(today - e["oldest_due_date"]).days if e["oldest_due_date"] else 0,
            overdue_count=e["overdue_count"],
            overdue_total_paise=e["overdue_total_paise"],
        ))
    out.sort(key=lambda x: x.days_overdue, reverse=True)
    return out


# -------- register (flat CSV-ready rows) --------

@router.get("/billing/register", response_model=list[RegisterRow])
async def billing_register(
    year: int = Query(..., ge=2020, le=2100),
    month: int = Query(..., ge=1, le=12),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(Invoice, User).join(User, User.id == Invoice.customer_id).where(
            Invoice.year == year, Invoice.month == month
        ).order_by(User.name.asc())
    )).all()
    out: list[RegisterRow] = []
    for inv, u in rows:
        out.append(RegisterRow(
            invoice_id=inv.id,
            customer_name=u.name,
            customer_phone=u.phone,
            year=inv.year, month=inv.month,
            subtotal_paise=inv.subtotal_paise,
            adjustments_paise=inv.adjustments_paise,
            total_paise=inv.total_paise,
            amount_paid_paise=inv.amount_paid_paise,
            balance_due_paise=max(0, inv.total_paise - inv.amount_paid_paise),
            status=inv.status.value,
            issued_at=inv.issued_at,
            due_date=inv.due_date,
            paid_at=inv.paid_at,
        ))
    return out
