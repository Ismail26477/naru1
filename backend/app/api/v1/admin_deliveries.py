"""Admin delivery-orders board + override (Phase 2B.4).

Endpoints:
- GET  /admin/delivery-orders (paginated, filtered, KPIs)
- GET  /admin/delivery-orders/{id}
- POST /admin/delivery-orders/{id}/override
- POST /admin/delivery-orders/bulk-skip
"""
from __future__ import annotations
from datetime import date, datetime, timedelta
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.middleware.auth import require_admin
from app.models.user import User
from app.models.enums import UserRole, DeliveryOrderStatus
from app.models.delivery import DeliveryOrder, BottleLedger
from app.models.product import Product
from app.models.route import Route, RouteStop
from app.models.audit_log import AuditLog
from app.schemas.admin import (
    DeliveryOrderRow, DeliveryOrderKPIs, PaginatedDeliveryOrders,
    DeliveryOrderDetail, OverrideBody, BulkSkipBody, BottleLedgerRow, AuditLogOut,
)
from app.services import delivery_admin_service, bottle_service
from app.core.time_utils import today_ist

router = APIRouter(
    prefix="/admin",
    tags=["admin-deliveries"],
    dependencies=[Depends(require_admin)],
)


async def _row_from_order(db: AsyncSession, o: DeliveryOrder) -> DeliveryOrderRow:
    cust = (await db.execute(select(User).where(User.id == o.customer_id))).scalar_one()
    prod = (await db.execute(select(Product).where(Product.id == o.product_id))).scalar_one()
    boy = None
    if o.delivery_boy_id:
        boy = (await db.execute(select(User).where(User.id == o.delivery_boy_id))).scalar_one_or_none()
    rs = (await db.execute(
        select(RouteStop, Route).join(Route, Route.id == RouteStop.route_id)
        .where(RouteStop.customer_id == o.customer_id).limit(1)
    )).first()
    route_id = rs[1].id if rs else None
    route_name = rs[1].name if rs else None
    route_seq = rs[0].sequence if rs else None

    return DeliveryOrderRow(
        id=o.id, customer_id=o.customer_id,
        customer_name=cust.name, customer_phone=cust.phone,
        product_id=o.product_id, product_name=prod.name,
        product_requires_bottle=prod.requires_bottle,
        subscription_id=o.subscription_id,
        delivery_date=o.delivery_date, quantity=o.quantity,
        delivered_quantity=o.delivered_quantity,
        bottles_returned=o.bottles_returned,
        unit_price_paise=o.unit_price_paise,
        status=o.status.value if hasattr(o.status, "value") else str(o.status),
        delivery_boy_id=o.delivery_boy_id,
        delivery_boy_name=(boy.name if boy else None),
        route_id=route_id, route_name=route_name, route_sequence=route_seq,
        cutoff_locked_at=o.cutoff_locked_at,
        delivered_at=o.delivered_at,
        skip_reason=o.skip_reason,
    )


# ---------- list with KPIs ----------

@router.get("/delivery-orders/board", response_model=PaginatedDeliveryOrders)
async def list_delivery_orders_board(
    delivery_date: date | None = Query(None, alias="date"),
    route_id: uuid.UUID | None = None,
    status: str | None = Query(None, pattern=r"^(pending|delivered|skipped|failed)$"),
    delivery_boy_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    the_date = delivery_date or today_ist()
    base = select(DeliveryOrder).where(DeliveryOrder.delivery_date == the_date)
    if delivery_boy_id:
        base = base.where(DeliveryOrder.delivery_boy_id == delivery_boy_id)
    if customer_id:
        base = base.where(DeliveryOrder.customer_id == customer_id)
    if route_id:
        cust_on_route = select(RouteStop.customer_id).where(RouteStop.route_id == route_id)
        base = base.where(DeliveryOrder.customer_id.in_(cust_on_route))

    # KPIs (apply filters sans status)
    status_counts = {s.value: 0 for s in DeliveryOrderStatus}
    kpi_stmt = select(DeliveryOrder.status, func.count(DeliveryOrder.id)).where(
        DeliveryOrder.delivery_date == the_date,
    )
    if delivery_boy_id:
        kpi_stmt = kpi_stmt.where(DeliveryOrder.delivery_boy_id == delivery_boy_id)
    if customer_id:
        kpi_stmt = kpi_stmt.where(DeliveryOrder.customer_id == customer_id)
    if route_id:
        cust_on_route = select(RouteStop.customer_id).where(RouteStop.route_id == route_id)
        kpi_stmt = kpi_stmt.where(DeliveryOrder.customer_id.in_(cust_on_route))
    for s, c in (await db.execute(kpi_stmt.group_by(DeliveryOrder.status))).all():
        status_counts[s.value if hasattr(s, "value") else str(s)] = int(c)

    kpis = DeliveryOrderKPIs(
        scheduled=sum(status_counts.values()),
        delivered=status_counts.get("delivered", 0),
        pending=status_counts.get("pending", 0),
        skipped=status_counts.get("skipped", 0),
        failed=status_counts.get("failed", 0),
    )

    # Apply status filter AFTER KPIs so KPIs reflect the date+route scope
    if status:
        try:
            base = base.where(DeliveryOrder.status == DeliveryOrderStatus(status))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"invalid status {status}")

    total = int((await db.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one() or 0)
    offset = (page - 1) * page_size
    orders = (await db.execute(
        base.order_by(DeliveryOrder.created_at.asc()).offset(offset).limit(page_size)
    )).scalars().all()

    items = [await _row_from_order(db, o) for o in orders]
    return PaginatedDeliveryOrders(
        kpis=kpis, items=items,
        total=total, page=page, page_size=page_size,
    )


# ---------- detail ----------

@router.get("/delivery-orders/{order_id}/admin-detail", response_model=DeliveryOrderDetail)
async def delivery_order_detail(order_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    o = (await db.execute(select(DeliveryOrder).where(DeliveryOrder.id == order_id))).scalar_one_or_none()
    if not o:
        raise HTTPException(status_code=404, detail="delivery_order not found")

    row = await _row_from_order(db, o)
    balance = await bottle_service.bottle_balance(db, o.customer_id)
    entries = (await db.execute(
        select(BottleLedger).where(BottleLedger.delivery_order_id == order_id)
        .order_by(BottleLedger.created_at.asc())
    )).scalars().all()
    audit_rows = (await db.execute(
        select(AuditLog).where(
            AuditLog.entity_type == "delivery_order",
            AuditLog.entity_id == str(order_id),
        ).order_by(AuditLog.created_at.desc())
    )).scalars().all()

    return DeliveryOrderDetail(
        **row.model_dump(),
        customer_bottle_balance=balance,
        bottle_entries=[
            BottleLedgerRow(
                id=e.id, change=e.change,
                reason=e.reason.value if hasattr(e.reason, "value") else str(e.reason),
                note=e.note, delivery_order_id=e.delivery_order_id, created_at=e.created_at,
            ) for e in entries
        ],
        audit=[AuditLogOut.model_validate(a) for a in audit_rows],
    )


# ---------- override ----------

@router.post("/delivery-orders/{order_id}/override", response_model=DeliveryOrderDetail)
async def override_delivery_order(
    order_id: uuid.UUID,
    body: OverrideBody,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    new_status = DeliveryOrderStatus(body.status)
    await delivery_admin_service.override(
        db,
        order_id=order_id,
        new_status=new_status,
        delivered_quantity=body.delivered_quantity,
        bottles_returned=body.bottles_returned,
        reason=body.reason,
        actor=admin,
        request=request,
    )
    return await delivery_order_detail(order_id, db)


@router.post("/delivery-orders/bulk-skip")
async def bulk_skip(
    body: BulkSkipBody,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    bulk_id = str(uuid.uuid4())
    applied: list[str] = []
    skipped: list[dict] = []
    for oid in body.order_ids:
        try:
            await delivery_admin_service.override(
                db, order_id=oid, new_status=DeliveryOrderStatus.SKIPPED,
                delivered_quantity=None, bottles_returned=None,
                reason=body.reason, actor=admin, request=request,
                bulk_operation_id=bulk_id,
            )
            applied.append(str(oid))
        except HTTPException as e:
            skipped.append({"id": str(oid), "error": e.detail})
    return {"bulk_operation_id": bulk_id, "applied": applied, "skipped": skipped, "reason": body.reason}
