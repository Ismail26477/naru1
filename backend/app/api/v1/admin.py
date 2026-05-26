"""Admin endpoints."""
from __future__ import annotations
from datetime import date, datetime, timedelta
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, update, func, or_, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.db.session import get_db
from app.models.user import User
from app.models.product import Product
from app.models.subscription import Subscription
from app.models.route import Route, RouteStop
from app.models.delivery import DeliveryOrder, BottleLedger
from app.models.billing import Invoice
from app.models.enums import UserRole, DeliveryOrderStatus
from app.middleware.auth import require_admin
from app.schemas.user import AdminUserListItem
from app.schemas.product import ProductCreate, ProductOut
from app.schemas.subscription import SubscriptionOut
from app.schemas.delivery import (
    RouteCreate, RouteOut, ReorderStopsBody, RouteStopOut,
    DeliveryOrderOut, InvoiceOut, DailyDeliveryReport, DailyDeliveryReportRow,
    BottleOutstandingRow, JobRunResult,
)
from app.schemas.admin import DashboardStats, DashboardTrendPoint, AuditLogOut
from app.models.audit_log import AuditLog
from app.services.order_service import generate_orders_for_date, lock_orders_for_date
from app.services.billing_service import generate_invoices_for_period
from app.services import audit_service
from app.core.time_utils import now_utc, tomorrow_ist, today_ist, IST, to_utc, ist_datetime

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# NOTE: `GET /admin/customers` and `POST /admin/customers/{id}/approve` now live
# in `admin_customers.py` (Phase 2B.2). Bulk-ops kept here as they're not in
# the new customer router.


@router.post("/customers/bulk-approve")
async def bulk_approve(
    customer_ids: list[uuid.UUID],
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Approve many pending customers at once. Each approval is individually
    audit-logged. Already-approved customers are skipped without error.
    """
    from app.services import audit_service as _audit
    approved: list[str] = []
    for cid in customer_ids:
        u = (await db.execute(
            select(User).where(User.id == cid, User.role == UserRole.CUSTOMER)
        )).scalar_one_or_none()
        if not u or u.approved_at is not None:
            continue
        before = None
        u.approved_at = now_utc()
        await db.flush()
        await _audit.log_action(
            db, actor=admin, action="customer.approve",
            entity_type="customer", entity_id=str(cid),
            before_state={"approved_at": before},
            after_state={"approved_at": u.approved_at.isoformat() if u.approved_at else None},
            reason="bulk approval", request=request,
        )
        approved.append(str(cid))
    return {"approved": approved, "count": len(approved)}


@router.post("/users/{user_id}/revoke-tokens")
async def admin_revoke_user_tokens(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Force-logout any user by setting is_active=False. All their existing
    JWTs will fail the active-user check in `get_current_user`. Admin can
    re-enable via a separate activate endpoint (Phase 2B)."""
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    user.is_active = False
    await db.flush()
    return {"user_id": str(user_id), "is_active": False, "message": "all tokens invalidated"}


@router.post("/users/{user_id}/reactivate")
async def admin_reactivate_user(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    user.is_active = True
    await db.flush()
    return {"user_id": str(user_id), "is_active": True}



@router.get("/users")
async def list_users(
    role: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Lightweight user lookup used by route / assignment UIs."""
    stmt = select(User)
    if role:
        try:
            r = UserRole(role)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid role '{role}'")
        stmt = stmt.where(User.role == r)
    stmt = stmt.order_by(User.name.asc()).limit(500)
    users = (await db.execute(stmt)).scalars().all()
    return [
        {"id": str(u.id), "name": u.name, "phone": u.phone, "role": u.role.value if hasattr(u.role, "value") else str(u.role)}
        for u in users
    ]


@router.get("/subscriptions", response_model=list[SubscriptionOut])
async def list_subs(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Subscription).order_by(Subscription.created_at.desc()).limit(500))).scalars().all()
    return list(rows)


# Routes: all route endpoints moved to `admin_routes.py` in Phase 2B.3.


# Delivery orders
@router.get("/delivery-orders", response_model=list[DeliveryOrderOut])
async def list_delivery_orders(
    date_: date | None = Query(None, alias="date"),
    route_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(DeliveryOrder)
    if date_:
        stmt = stmt.where(DeliveryOrder.delivery_date == date_)
    if route_id:
        # customers on this route
        cust_stmt = select(RouteStop.customer_id).where(RouteStop.route_id == route_id)
        stmt = stmt.where(DeliveryOrder.customer_id.in_(cust_stmt))
    stmt = stmt.order_by(DeliveryOrder.delivery_date.desc(), DeliveryOrder.created_at.asc()).limit(2000)
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)


@router.post("/delivery-orders/generate", response_model=JobRunResult)
async def manual_generate_orders(
    target_date: date | None = Query(None, description="Defaults to tomorrow IST"),
    db: AsyncSession = Depends(get_db),
):
    td = target_date or tomorrow_ist()
    created = await generate_orders_for_date(db, td)
    return JobRunResult(job="generate_orders", affected=len(created), details={"date": td.isoformat()})


# Invoices
@router.get("/invoices", response_model=list[InvoiceOut])
async def list_invoices(
    month: int | None = Query(None, ge=1, le=12),
    year: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Invoice)
    if month:
        stmt = stmt.where(Invoice.month == month)
    if year:
        stmt = stmt.where(Invoice.year == year)
    stmt = stmt.order_by(Invoice.year.desc(), Invoice.month.desc()).limit(1000)
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)


@router.post("/invoices/generate", response_model=JobRunResult)
async def manual_generate_invoices(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020, le=2100),
    db: AsyncSession = Depends(get_db),
):
    created = await generate_invoices_for_period(db, year, month)
    return JobRunResult(job="generate_invoices", affected=len(created), details={"month": month, "year": year})


# Products: CRUD moved to admin_products.py (Phase 2B.5).


# Reports
@router.get("/reports/daily-delivery", response_model=DailyDeliveryReport)
async def daily_delivery_report(
    date_: date = Query(..., alias="date"),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(
            Product.id, Product.name,
            func.sum(DeliveryOrder.quantity).label("total_qty"),
            func.sum(func.coalesce(DeliveryOrder.delivered_quantity, 0)).filter(
                DeliveryOrder.status == DeliveryOrderStatus.DELIVERED
            ).label("delivered_qty"),
            func.sum(case(
                (DeliveryOrder.status == DeliveryOrderStatus.PENDING, 1), else_=0
            )).label("pending"),
            func.sum(case(
                (DeliveryOrder.status == DeliveryOrderStatus.SKIPPED, 1), else_=0
            )).label("skipped"),
            func.count(DeliveryOrder.id).label("total_orders"),
        )
        .join(Product, Product.id == DeliveryOrder.product_id)
        .where(DeliveryOrder.delivery_date == date_)
        .group_by(Product.id, Product.name)
    )
    result = (await db.execute(stmt)).all()
    rows = [
        DailyDeliveryReportRow(
            product_id=r[0], product_name=r[1],
            total_quantity=int(r[2] or 0),
            delivered_quantity=int(r[3] or 0),
            pending=int(r[4] or 0),
            skipped=int(r[5] or 0),
        )
        for r in result
    ]
    total_orders = sum(int(r[6] or 0) for r in result)
    return DailyDeliveryReport(date=date_, rows=rows, total_orders=total_orders)


@router.get("/reports/bottle-outstanding", response_model=list[BottleOutstandingRow])
async def bottle_outstanding(db: AsyncSession = Depends(get_db)):
    stmt = (
        select(User.id, User.name, User.phone, func.coalesce(func.sum(BottleLedger.change), 0).label("balance"))
        .join(BottleLedger, BottleLedger.customer_id == User.id, isouter=True)
        .where(User.role == UserRole.CUSTOMER)
        .group_by(User.id, User.name, User.phone)
        .having(func.coalesce(func.sum(BottleLedger.change), 0) > 0)
        .order_by(func.coalesce(func.sum(BottleLedger.change), 0).desc())
    )
    rows = (await db.execute(stmt)).all()
    return [BottleOutstandingRow(customer_id=r[0], customer_name=r[1], customer_phone=r[2], balance=int(r[3])) for r in rows]


# Manual job triggers
@router.post("/jobs/{job_name}/trigger", response_model=JobRunResult)
async def trigger_job(job_name: str, db: AsyncSession = Depends(get_db)):
    from app.jobs.runners import nightly_cutoff, monthly_billing, morning_reminder, revoked_token_cleanup
    if job_name == "nightly_cutoff":
        return await nightly_cutoff(db)
    if job_name == "monthly_billing":
        return await monthly_billing(db)
    if job_name == "morning_reminder":
        return await morning_reminder(db)
    if job_name == "revoked_token_cleanup":
        return await revoked_token_cleanup(db)
    raise HTTPException(status_code=404, detail="unknown job")


# ------------------- Dashboard ---------------------
@router.get("/dashboard/stats", response_model=DashboardStats)
async def dashboard_stats(db: AsyncSession = Depends(get_db)):
    """Admin dashboard headline KPIs + three trend series.

    Revenue is counted as SUM(quantity * unit_price_paise) on delivered orders
    aggregated by delivery_date. Consistent with downstream invoicing logic.
    """
    today = today_ist()
    # Month start (IST) as a UTC moment for comparisons on created_at
    ist_now = datetime.now(IST)
    month_start_ist = ist_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_start_utc = month_start_ist.astimezone(now_utc().tzinfo)

    # Today's delivery count
    today_deliv = (await db.execute(
        select(func.count(DeliveryOrder.id)).where(DeliveryOrder.delivery_date == today)
    )).scalar_one()

    # MTD revenue from delivered orders whose delivery_date falls in current IST month
    mtd_rev = (await db.execute(
        select(func.coalesce(func.sum(DeliveryOrder.quantity * DeliveryOrder.unit_price_paise), 0))
        .where(
            DeliveryOrder.status == DeliveryOrderStatus.DELIVERED,
            DeliveryOrder.delivery_date >= today.replace(day=1),
            DeliveryOrder.delivery_date <= today,
        )
    )).scalar_one()

    # New customers this month (by created_at UTC >= month_start_utc)
    new_cust = (await db.execute(
        select(func.count(User.id))
        .where(User.role == UserRole.CUSTOMER, User.created_at >= month_start_utc)
    )).scalar_one()

    # Pending approvals
    pending = (await db.execute(
        select(func.count(User.id))
        .where(User.role == UserRole.CUSTOMER, User.approved_at.is_(None))
    )).scalar_one()

    # Bottles outstanding (sum of net positive balances)
    bal_q = (
        select(func.coalesce(func.sum(BottleLedger.change), 0).label("bal"))
        .select_from(BottleLedger)
        .join(User, User.id == BottleLedger.customer_id)
        .where(User.role == UserRole.CUSTOMER)
        .group_by(BottleLedger.customer_id)
        .having(func.coalesce(func.sum(BottleLedger.change), 0) > 0)
    ).subquery()
    bottles_out = (await db.execute(
        select(func.coalesce(func.sum(bal_q.c.bal), 0))
    )).scalar_one() or 0

    # Overdue invoices: explicit overdue status OR issued + past due_date
    overdue = (await db.execute(
        select(func.count(Invoice.id)).where(
            or_(
                Invoice.status == "overdue",
                (Invoice.status == "issued") & (Invoice.due_date < today),
            )
        )
    )).scalar_one()

    # Active subscriptions
    active_subs = (await db.execute(
        select(func.count(Subscription.id)).where(Subscription.status == "active")
    )).scalar_one()

    # --- Trends -------------------------------------------------------------
    # Deliveries trend: last 14 days
    start_14 = today - timedelta(days=13)
    rows = (await db.execute(
        select(
            DeliveryOrder.delivery_date.label("d"),
            func.count(DeliveryOrder.id).label("c"),
        )
        .where(DeliveryOrder.delivery_date >= start_14, DeliveryOrder.delivery_date <= today)
        .group_by(DeliveryOrder.delivery_date)
    )).all()
    by_date_14 = {r[0]: int(r[1] or 0) for r in rows}
    deliv_trend = [
        DashboardTrendPoint(date=start_14 + timedelta(days=i), value=by_date_14.get(start_14 + timedelta(days=i), 0))
        for i in range(14)
    ]

    # Revenue trend: last 30 days (delivered orders)
    start_30 = today - timedelta(days=29)
    rev_rows = (await db.execute(
        select(
            DeliveryOrder.delivery_date.label("d"),
            func.coalesce(func.sum(DeliveryOrder.quantity * DeliveryOrder.unit_price_paise), 0).label("p"),
        )
        .where(
            DeliveryOrder.status == DeliveryOrderStatus.DELIVERED,
            DeliveryOrder.delivery_date >= start_30,
            DeliveryOrder.delivery_date <= today,
        )
        .group_by(DeliveryOrder.delivery_date)
    )).all()
    rev_by_date = {r[0]: int(r[1] or 0) for r in rev_rows}
    rev_trend = [
        DashboardTrendPoint(date=start_30 + timedelta(days=i), value=rev_by_date.get(start_30 + timedelta(days=i), 0))
        for i in range(30)
    ]

    # Signups trend: last 30 days (count customers whose created_at IST date matches)
    sign_rows = (await db.execute(
        select(User.created_at).where(
            User.role == UserRole.CUSTOMER,
            User.created_at >= (month_start_utc - timedelta(days=60)),  # generous floor
        )
    )).scalars().all()
    sign_by_date: dict[date, int] = {}
    for ts in sign_rows:
        ist_d = ts.astimezone(IST).date() if ts.tzinfo else ts.date()
        if start_30 <= ist_d <= today:
            sign_by_date[ist_d] = sign_by_date.get(ist_d, 0) + 1
    sign_trend = [
        DashboardTrendPoint(date=start_30 + timedelta(days=i), value=sign_by_date.get(start_30 + timedelta(days=i), 0))
        for i in range(30)
    ]

    return DashboardStats(
        today_deliveries=int(today_deliv or 0),
        mtd_revenue_paise=int(mtd_rev or 0),
        new_customers_mtd=int(new_cust or 0),
        pending_approvals=int(pending or 0),
        bottles_outstanding=int(bottles_out or 0),
        overdue_invoices=int(overdue or 0),
        active_subscriptions=int(active_subs or 0),
        deliveries_trend_14d=deliv_trend,
        revenue_trend_30d=rev_trend,
        signups_trend_30d=sign_trend,
        generated_at=now_utc(),
    )


# ------------------- Audit log ---------------------
@router.get("/audit-log", response_model=list[AuditLogOut])
async def list_audit_log(
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    actor: uuid.UUID | None = Query(None),
    action: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AuditLog)
    if from_:
        stmt = stmt.where(AuditLog.created_at >= from_)
    if to:
        stmt = stmt.where(AuditLog.created_at <= to)
    if actor:
        stmt = stmt.where(AuditLog.actor_user_id == actor)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)

