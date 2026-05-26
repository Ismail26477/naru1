"""Bottle ledger: +1 on delivery of bottled product, -1 on return."""
import pytest
from datetime import date
import uuid

from app.models.subscription import Subscription
from app.models.delivery import DeliveryOrder, BottleLedger
from app.models.enums import (
    SubscriptionFrequency, SubscriptionStatus, DeliveryOrderStatus, BottleReason,
)
from app.services import bottle_service
from app.core.time_utils import now_utc
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_delivering_bottled_product_increases_balance(db, customer_user, milk_product, delivery_user, client):
    sub = Subscription(
        customer_id=customer_user.id, product_id=milk_product.id, quantity=1,
        frequency=SubscriptionFrequency.DAILY, start_date=date(2025, 1, 1),
        status=SubscriptionStatus.ACTIVE,
    )
    db.add(sub)
    await db.flush()
    order = DeliveryOrder(
        customer_id=customer_user.id, subscription_id=sub.id, product_id=milk_product.id,
        delivery_date=date.today(), quantity=1, unit_price_paise=milk_product.price_paise,
        status=DeliveryOrderStatus.PENDING,
    )
    db.add(order)
    await db.commit()

    r = await client.post(
        f"/api/delivery/orders/{order.id}/confirm",
        json={"delivered_quantity": 1, "bottles_returned": 0},
        headers=auth_headers(delivery_user),
    )
    assert r.status_code == 200, r.text

    bal = await bottle_service.bottle_balance(db, customer_user.id)
    assert bal == 1


@pytest.mark.asyncio
async def test_returning_bottle_decreases_balance(db, customer_user):
    # Manual ledger entries
    await bottle_service.record(db, customer_user.id, 3, BottleReason.DELIVERED)
    await bottle_service.record(db, customer_user.id, -2, BottleReason.RETURNED)
    await db.commit()
    bal = await bottle_service.bottle_balance(db, customer_user.id)
    assert bal == 1


@pytest.mark.asyncio
async def test_delivery_with_bottles_returned_nets_correctly(db, customer_user, milk_product, delivery_user, client):
    sub = Subscription(
        customer_id=customer_user.id, product_id=milk_product.id, quantity=2,
        frequency=SubscriptionFrequency.DAILY, start_date=date(2025, 1, 1),
        status=SubscriptionStatus.ACTIVE,
    )
    db.add(sub)
    await db.flush()
    order = DeliveryOrder(
        customer_id=customer_user.id, subscription_id=sub.id, product_id=milk_product.id,
        delivery_date=date.today(), quantity=2, unit_price_paise=milk_product.price_paise,
        status=DeliveryOrderStatus.PENDING,
    )
    db.add(order)
    await db.commit()

    # Deliver 2, return 1 previous empty
    r = await client.post(
        f"/api/delivery/orders/{order.id}/confirm",
        json={"delivered_quantity": 2, "bottles_returned": 1},
        headers=auth_headers(delivery_user),
    )
    assert r.status_code == 200
    bal = await bottle_service.bottle_balance(db, customer_user.id)
    assert bal == 1  # +2 delivered -1 returned
