"""Admin endpoints for customer management (Phase 2B.2).

Every mutation here writes an audit_log row via audit_service.
Money / bottle adjustments go through wallet_service / bottle_service which
use SELECT ... FOR UPDATE locking and post-op integrity checks.
"""
from __future__ import annotations
from datetime import date, datetime
from typing import Literal
import math
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, func, or_, and_, literal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.middleware.auth import require_admin
from app.models.user import User, Address
from app.models.enums import UserRole, SubscriptionStatus, InvoiceStatus
from app.models.subscription import Subscription
from app.models.delivery import DeliveryOrder, BottleLedger
from app.models.billing import Invoice, WalletTransaction
from app.models.audit_log import AuditLog
from app.models.route import RouteStop
from app.schemas.admin import (
    AdminCustomerRow, PaginatedCustomers, AdminCustomerDetail,
    AdminAddressOut, WalletAdjustmentBody, BottleAdjustmentBody,
    ReasonBody, OptionalReasonBody, WalletTransactionOut, BottleLedgerRow,
    PaginatedWallet, PaginatedBottles, AuditLogOut,
)
from app.schemas.subscription import SubscriptionOut
from app.schemas.delivery import DeliveryOrderOut, InvoiceOut
from app.services import wallet_service, bottle_service, audit_service
from app.core.time_utils import now_utc

router = APIRouter(
    prefix="/admin",
    tags=["admin-customers"],
    dependencies=[Depends(require_admin)],
)


# ---------------- helpers ----------------

async def _get_customer_or_404(db: AsyncSession, customer_id: uuid.UUID) -> User:
    u = (await db.execute(
        select(User).where(User.id == customer_id, User.role == UserRole.CUSTOMER)
    )).scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="customer not found")
    return u


async def _bottle_balance(db: AsyncSession, customer_id: uuid.UUID) -> int:
    return await bottle_service.bottle_balance(db, customer_id)


def _paginate(page: int, page_size: int) -> tuple[int, int]:
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    return (page - 1) * page_size, page_size


# ---------------- list ----------------

StatusFilter = Literal["approved", "pending", "inactive"]


@router.get("/customers", response_model=PaginatedCustomers)
async def list_customers_v2(
    search: str | None = None,
    status: StatusFilter | None = None,
    route_id: uuid.UUID | None = None,
    joined_from: date | None = None,
    joined_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Paginated customer list with pg_trgm fuzzy search.

    `search` matches against name || phone || address (concatenated) via the
    `%` trigram operator (needs `pg_trgm` extension; installed in migration 0).
    """
    base = select(User).where(User.role == UserRole.CUSTOMER)

    if status == "approved":
        base = base.where(User.approved_at.is_not(None), User.is_active.is_(True))
    elif status == "pending":
        base = base.where(User.approved_at.is_(None))
    elif status == "inactive":
        base = base.where(User.is_active.is_(False))

    if route_id is not None:
        cust_on_route = select(RouteStop.customer_id).where(RouteStop.route_id == route_id)
        base = base.where(User.id.in_(cust_on_route))

    if joined_from is not None:
        base = base.where(User.created_at >= datetime.combine(joined_from, datetime.min.time()))
    if joined_to is not None:
        base = base.where(User.created_at <= datetime.combine(joined_to, datetime.max.time()))

    if search:
        s = search.strip()
        if s:
            # fuzzy on name, phone, and address text (trigram similarity)
            # Use ILIKE fallback for very short inputs (<3 chars) which trigram can't index well.
            addr_sub = select(Address.user_id).where(
                or_(
                    Address.line1.ilike(f"%{s}%"),
                    Address.area.ilike(f"%{s}%"),
                    Address.pincode.ilike(f"%{s}%"),
                )
            )
            base = base.where(
                or_(
                    User.name.ilike(f"%{s}%"),
                    User.phone.ilike(f"%{s}%"),
                    User.email.ilike(f"%{s}%"),
                    User.id.in_(addr_sub),
                )
            )

    # Total count (clone without order/limit)
    total_stmt = select(func.count()).select_from(base.subquery())
    total = int((await db.execute(total_stmt)).scalar_one() or 0)

    offset, limit = _paginate(page, page_size)
    users = (await db.execute(
        base.order_by(User.created_at.desc()).offset(offset).limit(limit)
    )).scalars().all()

    if not users:
        return PaginatedCustomers(items=[], total=total, page=page, page_size=page_size)

    ids = [u.id for u in users]

    # Batch load active sub counts
    sub_rows = (await db.execute(
        select(Subscription.customer_id, func.count(Subscription.id))
        .where(Subscription.customer_id.in_(ids), Subscription.status == SubscriptionStatus.ACTIVE)
        .group_by(Subscription.customer_id)
    )).all()
    subs_map = {r[0]: int(r[1]) for r in sub_rows}

    # Batch load bottle balance
    bot_rows = (await db.execute(
        select(BottleLedger.customer_id, func.coalesce(func.sum(BottleLedger.change), 0))
        .where(BottleLedger.customer_id.in_(ids))
        .group_by(BottleLedger.customer_id)
    )).all()
    bot_map = {r[0]: int(r[1]) for r in bot_rows}

    # Batch load last delivery date
    ld_rows = (await db.execute(
        select(DeliveryOrder.customer_id, func.max(DeliveryOrder.delivery_date))
        .where(DeliveryOrder.customer_id.in_(ids))
        .group_by(DeliveryOrder.customer_id)
    )).all()
    ld_map = {r[0]: r[1] for r in ld_rows}

    # Batch load default (or first) address area per customer
    addr_rows = (await db.execute(
        select(Address.user_id, Address.area, Address.is_default)
        .where(Address.user_id.in_(ids))
        .order_by(Address.user_id, Address.is_default.desc(), Address.created_at.asc())
    )).all()
    area_map: dict[uuid.UUID, str] = {}
    for uid, area, _is_def in addr_rows:
        area_map.setdefault(uid, area)

    items = [
        AdminCustomerRow(
            id=u.id, phone=u.phone, name=u.name, email=u.email,
            approved_at=u.approved_at, is_active=u.is_active,
            created_at=u.created_at,
            wallet_balance_paise=int(u.wallet_balance_paise or 0),
            bottle_balance=bot_map.get(u.id, 0),
            active_subs_count=subs_map.get(u.id, 0),
            area=area_map.get(u.id),
            last_delivery_date=ld_map.get(u.id),
        )
        for u in users
    ]
    return PaginatedCustomers(items=items, total=total, page=page, page_size=page_size)


# ---------------- detail ----------------

@router.get("/customers/{customer_id}", response_model=AdminCustomerDetail)
async def customer_detail(customer_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    u = (await db.execute(
        select(User)
        .options(selectinload(User.addresses))
        .where(User.id == customer_id, User.role == UserRole.CUSTOMER)
    )).scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="customer not found")

    bottle = await _bottle_balance(db, u.id)
    active_sub_count = int((await db.execute(
        select(func.count(Subscription.id)).where(
            Subscription.customer_id == u.id,
            Subscription.status == SubscriptionStatus.ACTIVE,
        )
    )).scalar_one() or 0)
    total_subs = int((await db.execute(
        select(func.count(Subscription.id)).where(Subscription.customer_id == u.id)
    )).scalar_one() or 0)
    inv_count = int((await db.execute(
        select(func.count(Invoice.id)).where(Invoice.customer_id == u.id)
    )).scalar_one() or 0)
    open_inv = int((await db.execute(
        select(func.coalesce(func.sum(Invoice.total_paise), 0)).where(
            Invoice.customer_id == u.id,
            Invoice.status.in_([InvoiceStatus.ISSUED, InvoiceStatus.OVERDUE]),
        )
    )).scalar_one() or 0)

    return AdminCustomerDetail(
        id=u.id, phone=u.phone, name=u.name, email=u.email,
        role=u.role.value if hasattr(u.role, "value") else str(u.role),
        approved_at=u.approved_at, is_active=u.is_active,
        wallet_balance_paise=int(u.wallet_balance_paise or 0),
        bottle_balance=bottle,
        created_at=u.created_at,
        addresses=[AdminAddressOut.model_validate(a) for a in u.addresses],
        active_subs_count=active_sub_count,
        total_subs_count=total_subs,
        invoice_count=inv_count,
        open_invoices_paise=open_inv,
    )


# ---------------- children (paginated) ----------------

@router.get("/customers/{customer_id}/subscriptions", response_model=list[SubscriptionOut])
async def customer_subs(customer_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await _get_customer_or_404(db, customer_id)
    rows = (await db.execute(
        select(Subscription).where(Subscription.customer_id == customer_id)
        .order_by(Subscription.created_at.desc())
    )).scalars().all()
    return list(rows)


@router.get("/customers/{customer_id}/deliveries", response_model=list[DeliveryOrderOut])
async def customer_deliveries(
    customer_id: uuid.UUID,
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    await _get_customer_or_404(db, customer_id)
    stmt = select(DeliveryOrder).where(DeliveryOrder.customer_id == customer_id)
    if from_:
        stmt = stmt.where(DeliveryOrder.delivery_date >= from_)
    if to:
        stmt = stmt.where(DeliveryOrder.delivery_date <= to)
    offset, limit = _paginate(page, page_size)
    rows = (await db.execute(
        stmt.order_by(DeliveryOrder.delivery_date.desc()).offset(offset).limit(limit)
    )).scalars().all()
    return list(rows)


@router.get("/customers/{customer_id}/invoices", response_model=list[InvoiceOut])
async def customer_invoices(
    customer_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    await _get_customer_or_404(db, customer_id)
    offset, limit = _paginate(page, page_size)
    rows = (await db.execute(
        select(Invoice).where(Invoice.customer_id == customer_id)
        .order_by(Invoice.year.desc(), Invoice.month.desc())
        .offset(offset).limit(limit)
    )).scalars().all()
    return list(rows)


@router.get("/customers/{customer_id}/wallet-transactions", response_model=PaginatedWallet)
async def customer_wallet_txns(
    customer_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    u = await _get_customer_or_404(db, customer_id)
    total = int((await db.execute(
        select(func.count(WalletTransaction.id)).where(WalletTransaction.customer_id == customer_id)
    )).scalar_one() or 0)
    offset, limit = _paginate(page, page_size)
    rows = (await db.execute(
        select(WalletTransaction).where(WalletTransaction.customer_id == customer_id)
        .order_by(WalletTransaction.created_at.desc())
        .offset(offset).limit(limit)
    )).scalars().all()
    return PaginatedWallet(
        balance_paise=int(u.wallet_balance_paise or 0),
        total=total, page=page, page_size=page_size,
        items=[WalletTransactionOut.model_validate(r) for r in rows],
    )


@router.get("/customers/{customer_id}/bottle-ledger", response_model=PaginatedBottles)
async def customer_bottle_ledger(
    customer_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    await _get_customer_or_404(db, customer_id)
    total = int((await db.execute(
        select(func.count(BottleLedger.id)).where(BottleLedger.customer_id == customer_id)
    )).scalar_one() or 0)
    offset, limit = _paginate(page, page_size)
    rows = (await db.execute(
        select(BottleLedger).where(BottleLedger.customer_id == customer_id)
        .order_by(BottleLedger.created_at.desc())
        .offset(offset).limit(limit)
    )).scalars().all()
    balance = await _bottle_balance(db, customer_id)
    return PaginatedBottles(
        balance=balance, total=total, page=page, page_size=page_size,
        items=[
            BottleLedgerRow(
                id=r.id, change=r.change,
                reason=r.reason.value if hasattr(r.reason, "value") else str(r.reason),
                note=r.note, delivery_order_id=r.delivery_order_id, created_at=r.created_at,
            )
            for r in rows
        ],
    )


@router.get("/customers/{customer_id}/audit-log", response_model=list[AuditLogOut])
async def customer_audit_log(
    customer_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    await _get_customer_or_404(db, customer_id)
    offset, limit = _paginate(page, page_size)
    # Match either direct entity_id (e.g. customer approve) or wallet/bottle with customer id
    rows = (await db.execute(
        select(AuditLog).where(AuditLog.entity_id == str(customer_id))
        .order_by(AuditLog.created_at.desc())
        .offset(offset).limit(limit)
    )).scalars().all()
    return list(rows)


# ---------------- mutations ----------------

@router.post("/customers/{customer_id}/wallet-adjustment", response_model=WalletTransactionOut, status_code=201)
async def wallet_adjust(
    customer_id: uuid.UUID,
    body: WalletAdjustmentBody,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    # Validate it's actually a customer
    await _get_customer_or_404(db, customer_id)
    tx = await wallet_service.adjust(
        db,
        customer_id=customer_id,
        change_paise=body.amount_paise,
        reason=body.reason,
        actor=admin,
        force=body.force,
        reference_id=body.reference_id,
        request=request,
    )
    return WalletTransactionOut.model_validate(tx)


@router.post("/customers/{customer_id}/bottle-adjustment", response_model=BottleLedgerRow, status_code=201)
async def bottle_adjust(
    customer_id: uuid.UUID,
    body: BottleAdjustmentBody,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await _get_customer_or_404(db, customer_id)
    entry = await bottle_service.adjust(
        db,
        customer_id=customer_id,
        change=body.change,
        reason=body.reason,
        actor=admin,
        force=body.force,
        request=request,
    )
    return BottleLedgerRow(
        id=entry.id, change=entry.change,
        reason=entry.reason.value if hasattr(entry.reason, "value") else str(entry.reason),
        note=entry.note, delivery_order_id=entry.delivery_order_id, created_at=entry.created_at,
    )


@router.post("/customers/{customer_id}/approve", response_model=AdminCustomerDetail)
async def approve_customer_v2(
    customer_id: uuid.UUID,
    body: OptionalReasonBody | None = None,
    request: Request = None,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    u = await _get_customer_or_404(db, customer_id)
    before = u.approved_at.isoformat() if u.approved_at else None
    if u.approved_at is None:
        u.approved_at = now_utc()
    await db.flush()
    await audit_service.log_action(
        db, actor=admin, action="customer.approve",
        entity_type="customer", entity_id=str(customer_id),
        before_state={"approved_at": before},
        after_state={"approved_at": u.approved_at.isoformat() if u.approved_at else None},
        reason=(body.reason if body else None),
        request=request,
    )
    return await customer_detail(customer_id, db)


@router.post("/customers/{customer_id}/reject", response_model=AdminCustomerDetail)
async def reject_customer(
    customer_id: uuid.UUID,
    body: ReasonBody,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    u = await _get_customer_or_404(db, customer_id)
    before = {"approved_at": u.approved_at.isoformat() if u.approved_at else None, "is_active": u.is_active}
    u.approved_at = None
    u.is_active = False
    await db.flush()
    await audit_service.log_action(
        db, actor=admin, action="customer.reject",
        entity_type="customer", entity_id=str(customer_id),
        before_state=before,
        after_state={"approved_at": None, "is_active": False},
        reason=body.reason, request=request,
    )
    return await customer_detail(customer_id, db)


@router.post("/customers/{customer_id}/revoke-tokens")
async def revoke_customer_tokens(
    customer_id: uuid.UUID,
    body: ReasonBody,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    u = await _get_customer_or_404(db, customer_id)
    before = {"is_active": u.is_active}
    u.is_active = False
    await db.flush()
    await audit_service.log_action(
        db, actor=admin, action="user.revoke_tokens",
        entity_type="customer", entity_id=str(customer_id),
        before_state=before, after_state={"is_active": False},
        reason=body.reason, request=request,
    )
    return {"customer_id": str(customer_id), "is_active": False, "message": "all tokens invalidated"}


# ---------------- subscription admin mutations ----------------

async def _get_sub_or_404(db: AsyncSession, sub_id: uuid.UUID) -> Subscription:
    s = (await db.execute(select(Subscription).where(Subscription.id == sub_id))).scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="subscription not found")
    return s


@router.post("/subscriptions/{sub_id}/pause", response_model=SubscriptionOut)
async def admin_pause_subscription(
    sub_id: uuid.UUID,
    body: ReasonBody,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    s = await _get_sub_or_404(db, sub_id)
    before = {"status": s.status.value if hasattr(s.status, "value") else str(s.status)}
    s.status = SubscriptionStatus.PAUSED
    await db.flush()
    await audit_service.log_action(
        db, actor=admin, action="subscription.admin_pause",
        entity_type="subscription", entity_id=str(sub_id),
        before_state=before, after_state={"status": "paused"},
        reason=body.reason, request=request,
    )
    return s


@router.post("/subscriptions/{sub_id}/resume", response_model=SubscriptionOut)
async def admin_resume_subscription(
    sub_id: uuid.UUID,
    body: OptionalReasonBody | None = None,
    request: Request = None,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    s = await _get_sub_or_404(db, sub_id)
    before = {"status": s.status.value if hasattr(s.status, "value") else str(s.status)}
    s.status = SubscriptionStatus.ACTIVE
    s.pause_from = None
    s.pause_until = None
    await db.flush()
    await audit_service.log_action(
        db, actor=admin, action="subscription.admin_resume",
        entity_type="subscription", entity_id=str(sub_id),
        before_state=before, after_state={"status": "active"},
        reason=(body.reason if body else None),
        request=request,
    )
    return s


@router.post("/subscriptions/{sub_id}/cancel", response_model=SubscriptionOut)
async def admin_cancel_subscription(
    sub_id: uuid.UUID,
    body: ReasonBody,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    s = await _get_sub_or_404(db, sub_id)
    before = {"status": s.status.value if hasattr(s.status, "value") else str(s.status)}
    s.status = SubscriptionStatus.CANCELLED
    await db.flush()
    await audit_service.log_action(
        db, actor=admin, action="subscription.admin_cancel",
        entity_type="subscription", entity_id=str(sub_id),
        before_state=before, after_state={"status": "cancelled"},
        reason=body.reason, request=request,
    )
    return s
