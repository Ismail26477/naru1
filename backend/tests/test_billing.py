"""Billing arithmetic: 30 days × 500ml × ₹30 = ₹900; skips reduce correctly."""
import pytest
from datetime import date, timedelta
import uuid

from sqlalchemy import select
from app.models.user import User
from app.models.product import Product
from app.models.subscription import Subscription
from app.models.delivery import DeliveryOrder
from app.models.enums import UserRole, ProductUnit, SubscriptionFrequency, SubscriptionStatus, DeliveryOrderStatus
from app.models.billing import Invoice
from app.core.time_utils import now_utc
from app.services.billing_service import generate_invoices_for_period, compute_invoice_for_customer


async def _setup_customer_and_product(db):
    cust = User(phone=f"+9190{uuid.uuid4().int % 10_000_000:08d}", name="Biller", role=UserRole.CUSTOMER, is_active=True, approved_at=now_utc())
    db.add(cust)
    prod = Product(name="Milk 500ml", sku=f"MILK-500-{uuid.uuid4().hex[:6]}", unit=ProductUnit.LITRE, price_paise=3500, requires_bottle=True, active=True)
    db.add(prod)
    await db.flush()
    return cust, prod


async def _create_month_of_orders(db, cust, prod, year, month, delivered_days: int, skipped_days: int = 0):
    """Create delivery_orders for the given month."""
    import calendar
    days_in_month = calendar.monthrange(year, month)[1]
    total_to_create = delivered_days + skipped_days
    assert total_to_create <= days_in_month
    # We don't need a subscription row for billing, but the schema requires one due to FK.
    sub = Subscription(
        customer_id=cust.id, product_id=prod.id, quantity=1,
        frequency=SubscriptionFrequency.DAILY, start_date=date(year, month, 1),
        status=SubscriptionStatus.ACTIVE,
    )
    db.add(sub)
    await db.flush()
    # deliveries on days 1..delivered_days
    for i in range(delivered_days):
        d = date(year, month, i + 1)
        db.add(DeliveryOrder(
            customer_id=cust.id, subscription_id=sub.id, product_id=prod.id,
            delivery_date=d, quantity=1, unit_price_paise=prod.price_paise,
            status=DeliveryOrderStatus.DELIVERED,
            delivered_quantity=1, delivered_at=now_utc(),
        ))
    # skips on the next skipped_days
    for i in range(skipped_days):
        d = date(year, month, delivered_days + i + 1)
        db.add(DeliveryOrder(
            customer_id=cust.id, subscription_id=sub.id, product_id=prod.id,
            delivery_date=d, quantity=1, unit_price_paise=prod.price_paise,
            status=DeliveryOrderStatus.SKIPPED,
            skip_reason="test", delivered_at=now_utc(),
        ))
    await db.flush()


@pytest.mark.asyncio
async def test_billing_30_deliveries_at_35_rupees_equals_1050(db):
    cust, prod = await _setup_customer_and_product(db)
    # April (30 days) — 30 daily deliveries × ₹35 = ₹1050
    await _create_month_of_orders(db, cust, prod, 2025, 4, delivered_days=30)
    await db.commit()

    subtotal, items = await compute_invoice_for_customer(db, cust.id, 2025, 4)
    assert len(items) == 30
    assert subtotal == 30 * 3500  # 105_000 paise = ₹1050


@pytest.mark.asyncio
async def test_billing_25_deliveries_plus_5_skips_equals_875(db):
    cust, prod = await _setup_customer_and_product(db)
    # April 2025: 25 delivered + 5 skipped = ₹875 (only delivered are billed)
    await _create_month_of_orders(db, cust, prod, 2025, 4, delivered_days=25, skipped_days=5)
    await db.commit()

    subtotal, items = await compute_invoice_for_customer(db, cust.id, 2025, 4)
    assert len(items) == 25
    assert subtotal == 25 * 3500  # 87_500 paise = ₹875


@pytest.mark.asyncio
async def test_generate_invoices_creates_issued_invoice(db):
    cust, prod = await _setup_customer_and_product(db)
    await _create_month_of_orders(db, cust, prod, 2025, 4, delivered_days=30)
    await db.commit()

    invoices = await generate_invoices_for_period(db, 2025, 4)
    await db.commit()
    assert len(invoices) == 1
    inv = invoices[0]
    assert inv.total_paise == 105_000  # 30 × ₹35
    assert inv.status == "issued" or str(inv.status).endswith("issued")


@pytest.mark.asyncio
async def test_generate_invoices_is_idempotent(db):
    cust, prod = await _setup_customer_and_product(db)
    await _create_month_of_orders(db, cust, prod, 2025, 4, delivered_days=30)
    await db.commit()

    first = await generate_invoices_for_period(db, 2025, 4)
    await db.commit()
    second = await generate_invoices_for_period(db, 2025, 4)
    await db.commit()
    assert len(first) == 1
    assert len(second) == 0
