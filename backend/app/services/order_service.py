"""Delivery order generation from active subscriptions."""
from __future__ import annotations
from datetime import date
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Subscription, SubscriptionScheduleOverride
from app.models.delivery import DeliveryOrder
from app.models.product import Product
from app.models.route import RouteStop, Route
from app.models.enums import SubscriptionStatus, DeliveryOrderStatus
from app.services.schedule_service import expand
from app.services import product_pricing_service
from app.core.time_utils import now_utc


async def generate_orders_for_date(db: AsyncSession, target_date: date) -> list[DeliveryOrder]:
    """For every active subscription, create a DeliveryOrder for `target_date` if not exists."""
    subs_stmt = (
        select(Subscription)
        .where(Subscription.status == SubscriptionStatus.ACTIVE)
        .where(Subscription.start_date <= target_date)
    )
    subs = (await db.execute(subs_stmt)).scalars().all()
    if not subs:
        return []

    # Preload products to get price at generation time
    product_ids = {s.product_id for s in subs}
    products = {p.id: p for p in (await db.execute(select(Product).where(Product.id.in_(product_ids)))).scalars().all()}

    # Preload customer → delivery_boy via routes
    cust_to_boy: dict[uuid.UUID, uuid.UUID | None] = {}
    stops_stmt = select(RouteStop, Route).join(Route, Route.id == RouteStop.route_id).where(
        RouteStop.customer_id.in_({s.customer_id for s in subs})
    )
    for stop, route in (await db.execute(stops_stmt)).all():
        cust_to_boy[stop.customer_id] = route.delivery_boy_id

    # Preload existing orders to make idempotent
    existing_stmt = select(DeliveryOrder.subscription_id).where(DeliveryOrder.delivery_date == target_date)
    existing_sub_ids: set[uuid.UUID] = set((await db.execute(existing_stmt)).scalars().all())

    # Preload overrides for this date
    ov_stmt = select(SubscriptionScheduleOverride).where(SubscriptionScheduleOverride.date == target_date)
    ov_by_sub: dict[uuid.UUID, SubscriptionScheduleOverride] = {}
    for ov in (await db.execute(ov_stmt)).scalars().all():
        ov_by_sub[ov.subscription_id] = ov

    created: list[DeliveryOrder] = []
    for sub in subs:
        if sub.id in existing_sub_ids:
            continue
        ov_list = [ov_by_sub[sub.id]] if sub.id in ov_by_sub else []
        expanded = list(expand(sub, target_date, target_date, ov_list))
        if not expanded:
            continue
        _d, qty = expanded[0]
        product = products.get(sub.product_id)
        if product is None or not product.active:
            continue
        price_at = await product_pricing_service.get_price_at(db, sub.product_id, target_date)
        order = DeliveryOrder(
            customer_id=sub.customer_id,
            subscription_id=sub.id,
            product_id=sub.product_id,
            delivery_date=target_date,
            quantity=qty,
            unit_price_paise=price_at,
            status=DeliveryOrderStatus.PENDING,
            delivery_boy_id=cust_to_boy.get(sub.customer_id),
        )
        db.add(order)
        created.append(order)

    await db.flush()
    return created


async def lock_orders_for_date(db: AsyncSession, target_date: date) -> int:
    """Stamp cutoff_locked_at on all PENDING orders for `target_date`. Returns count."""
    from sqlalchemy import update as sa_update
    stmt = (
        sa_update(DeliveryOrder)
        .where(
            DeliveryOrder.delivery_date == target_date,
            DeliveryOrder.cutoff_locked_at.is_(None),
        )
        .values(cutoff_locked_at=now_utc())
    )
    res = await db.execute(stmt)
    return res.rowcount or 0
