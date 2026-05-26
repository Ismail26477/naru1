"""Delivery boy endpoints."""
from __future__ import annotations
from datetime import date
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.models.user import User
from app.models.route import Route, RouteStop
from app.models.delivery import DeliveryOrder
from app.models.enums import DeliveryOrderStatus, BottleReason
from app.models.product import Product
from app.middleware.auth import require_delivery
from app.schemas.delivery import DeliveryOrderOut, ConfirmDeliveryBody, SkipDeliveryBody
from app.services import bottle_service
from app.core.time_utils import now_utc, today_ist

router = APIRouter(prefix="/delivery", tags=["delivery"])


@router.get("/my-route", response_model=list[DeliveryOrderOut])
async def my_route(
    date_: date | None = Query(None, alias="date"),
    user: User = Depends(require_delivery),
    db: AsyncSession = Depends(get_db),
):
    d = date_ or today_ist()
    # routes this delivery boy owns
    route_ids = (await db.execute(select(Route.id).where(Route.delivery_boy_id == user.id))).scalars().all()
    if not route_ids:
        return []
    stops = (await db.execute(
        select(RouteStop).where(RouteStop.route_id.in_(route_ids)).order_by(RouteStop.sequence)
    )).scalars().all()
    customer_ids = [s.customer_id for s in stops]
    if not customer_ids:
        return []
    seq_map = {s.customer_id: s.sequence for s in stops}
    orders = (await db.execute(
        select(DeliveryOrder).where(
            DeliveryOrder.customer_id.in_(customer_ids),
            DeliveryOrder.delivery_date == d,
        )
    )).scalars().all()
    # Return sorted by sequence
    return sorted(orders, key=lambda o: seq_map.get(o.customer_id, 9999))


@router.post("/orders/{order_id}/confirm", response_model=DeliveryOrderOut)
async def confirm_delivery(
    order_id: uuid.UUID,
    body: ConfirmDeliveryBody,
    user: User = Depends(require_delivery),
    db: AsyncSession = Depends(get_db),
):
    order = (await db.execute(select(DeliveryOrder).where(DeliveryOrder.id == order_id))).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="order not found")
    if order.status not in (DeliveryOrderStatus.PENDING, DeliveryOrderStatus.FAILED):
        raise HTTPException(status_code=409, detail=f"order already {order.status}")

    product = (await db.execute(select(Product).where(Product.id == order.product_id))).scalar_one()
    order.status = DeliveryOrderStatus.DELIVERED
    order.delivered_quantity = body.delivered_quantity
    order.bottles_returned = body.bottles_returned
    order.notes = body.notes
    order.delivered_at = now_utc()
    order.delivery_boy_id = user.id

    # Bottle ledger: +qty for each bottle product delivered, -qty for returned
    if product.requires_bottle and body.delivered_quantity > 0:
        await bottle_service.record(
            db, order.customer_id, body.delivered_quantity, BottleReason.DELIVERED,
            delivery_order_id=order.id, note=f"delivery {order.delivery_date}",
        )
    if body.bottles_returned > 0:
        await bottle_service.record(
            db, order.customer_id, -body.bottles_returned, BottleReason.RETURNED,
            delivery_order_id=order.id, note=f"returned on {order.delivery_date}",
        )

    await db.flush()
    return order


@router.post("/orders/{order_id}/skip", response_model=DeliveryOrderOut)
async def skip_delivery(
    order_id: uuid.UUID,
    body: SkipDeliveryBody,
    user: User = Depends(require_delivery),
    db: AsyncSession = Depends(get_db),
):
    order = (await db.execute(select(DeliveryOrder).where(DeliveryOrder.id == order_id))).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="order not found")
    if order.status not in (DeliveryOrderStatus.PENDING, DeliveryOrderStatus.FAILED):
        raise HTTPException(status_code=409, detail=f"order already {order.status}")
    order.status = DeliveryOrderStatus.SKIPPED
    order.skip_reason = body.reason
    order.delivery_boy_id = user.id
    order.delivered_at = now_utc()
    await db.flush()
    return order
