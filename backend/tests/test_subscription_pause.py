"""Paused subscriptions must NOT generate delivery orders."""
import pytest
from datetime import date, timedelta

from app.models.subscription import Subscription
from app.models.enums import SubscriptionFrequency, SubscriptionStatus
from app.models.delivery import DeliveryOrder
from app.services.order_service import generate_orders_for_date
from sqlalchemy import select


@pytest.mark.asyncio
async def test_paused_subscription_generates_no_orders(db, customer_user, milk_product):
    sub = Subscription(
        customer_id=customer_user.id, product_id=milk_product.id, quantity=1,
        frequency=SubscriptionFrequency.DAILY, start_date=date(2025, 1, 1),
        status=SubscriptionStatus.PAUSED,
    )
    db.add(sub)
    await db.commit()

    target = date.today() + timedelta(days=1)
    created = await generate_orders_for_date(db, target)
    await db.commit()
    assert len(created) == 0

    orders = (await db.execute(
        select(DeliveryOrder).where(
            DeliveryOrder.subscription_id == sub.id,
            DeliveryOrder.delivery_date == target,
        )
    )).scalars().all()
    assert orders == []


@pytest.mark.asyncio
async def test_active_subscription_generates_order(db, customer_user, milk_product):
    sub = Subscription(
        customer_id=customer_user.id, product_id=milk_product.id, quantity=1,
        frequency=SubscriptionFrequency.DAILY, start_date=date(2025, 1, 1),
        status=SubscriptionStatus.ACTIVE,
    )
    db.add(sub)
    await db.commit()

    target = date.today() + timedelta(days=1)
    created = await generate_orders_for_date(db, target)
    await db.commit()
    assert len(created) == 1
    assert created[0].subscription_id == sub.id


@pytest.mark.asyncio
async def test_subscription_with_pause_window_skips_those_days(db, customer_user, milk_product):
    target = date.today() + timedelta(days=1)
    sub = Subscription(
        customer_id=customer_user.id, product_id=milk_product.id, quantity=1,
        frequency=SubscriptionFrequency.DAILY, start_date=date(2025, 1, 1),
        status=SubscriptionStatus.ACTIVE,
        pause_from=target, pause_until=target + timedelta(days=5),
    )
    db.add(sub)
    await db.commit()

    created = await generate_orders_for_date(db, target)
    await db.commit()
    assert len(created) == 0


@pytest.mark.asyncio
async def test_generate_orders_is_idempotent(db, customer_user, milk_product):
    sub = Subscription(
        customer_id=customer_user.id, product_id=milk_product.id, quantity=1,
        frequency=SubscriptionFrequency.DAILY, start_date=date(2025, 1, 1),
        status=SubscriptionStatus.ACTIVE,
    )
    db.add(sub)
    await db.commit()

    target = date.today() + timedelta(days=2)
    first = await generate_orders_for_date(db, target)
    await db.commit()
    second = await generate_orders_for_date(db, target)
    await db.commit()
    assert len(first) == 1
    assert len(second) == 0
