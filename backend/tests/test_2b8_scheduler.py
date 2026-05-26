"""Phase 2B.8 Phase A: scheduler migration + system user tests."""
from __future__ import annotations
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from app.core.time_utils import now_utc, today_ist
from app.jobs.runners import get_system_user, monthly_billing
from app.models.audit_log import AuditLog
from app.models.billing import Invoice
from app.models.delivery import DeliveryOrder
from app.models.enums import (
    DeliveryOrderStatus,
    ProductUnit,
    SubscriptionFrequency,
    SubscriptionStatus,
    UserRole,
)
from app.models.product import Product
from app.models.subscription import Subscription
from app.models.user import User


async def _seeded_delivered(db, y: int, m: int) -> User:
    prod = Product(name="Milk", sku=f"SCHD-{y}-{m}", unit=ProductUnit.LITRE,
                   price_paise=4000, requires_bottle=False, active=True)
    db.add(prod); await db.flush()
    c = User(phone=f"+919{(y*100+m)%10**9:09d}", name=f"Sched Cust {y}-{m}",
             role=UserRole.CUSTOMER, is_active=True, approved_at=now_utc())
    db.add(c); await db.flush()
    s = Subscription(customer_id=c.id, product_id=prod.id, quantity=1,
                     frequency=SubscriptionFrequency.DAILY,
                     start_date=date(y, m, 1), status=SubscriptionStatus.ACTIVE)
    db.add(s); await db.flush()
    for d in range(1, 6):
        db.add(DeliveryOrder(
            customer_id=c.id, subscription_id=s.id, product_id=prod.id,
            delivery_date=date(y, m, d), quantity=1, unit_price_paise=4000,
            status=DeliveryOrderStatus.DELIVERED, delivered_quantity=1,
            delivered_at=now_utc(),
        ))
    await db.commit()
    return c


@pytest.mark.asyncio
async def test_system_user_seeded(db):
    """Alembic migration e5c1b7f2a3d8 must have seeded exactly one is_system user."""
    rows = (await db.execute(select(User).where(User.is_system.is_(True)))).scalars().all()
    assert len(rows) == 1
    assert rows[0].phone == "+910000000000"
    assert rows[0].role == UserRole.ADMIN

    # get_system_user returns it
    got = await get_system_user(db)
    assert got.id == rows[0].id


@pytest.mark.asyncio
async def test_system_user_singleton(db):
    """Attempting to create a second is_system=True user fails on the partial unique index."""
    existing = await get_system_user(db)
    assert existing is not None
    # Try to insert a duplicate
    dupe = User(
        phone="+910000000099", name="Dupe System", role=UserRole.ADMIN,
        is_active=True, approved_at=now_utc(), is_system=True,
    )
    db.add(dupe)
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


@pytest.mark.asyncio
async def test_system_user_cannot_login(client, db):
    """OTP flows refuse the system phone number."""
    sys_phone = "+910000000000"
    # request-otp → 403 (system phone is blocked at entry)
    r = await client.post("/api/auth/request-otp", json={"phone": sys_phone})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "system_account_no_login"

    # Even if a valid OTP is somehow supplied (dev backdoor), verify-otp refuses.
    r2 = await client.post("/api/auth/verify-otp", json={"phone": sys_phone, "otp": "123456"})
    assert r2.status_code == 403
    assert r2.json()["detail"]["code"] == "system_account_no_login"


@pytest.mark.asyncio
async def test_scheduled_billing_creates_audit(db):
    """monthly_billing produces a billing.generate audit row with system actor."""
    # Seed some deliveries for (previous-month-from-today)
    today = today_ist()
    if today.month == 1:
        y, m = today.year - 1, 12
    else:
        y, m = today.year, today.month - 1
    await _seeded_delivered(db, y, m)

    result = await monthly_billing(db)
    await db.commit()
    assert result.affected >= 1
    assert result.details["year"] == y
    assert result.details["month"] == m

    # Audit trail with actor=system
    system = await get_system_user(db)
    aud = (await db.execute(
        select(AuditLog).where(
            AuditLog.action == "billing.generate",
            AuditLog.entity_id == f"{y}-{m:02d}",
            AuditLog.actor_user_id == system.id,
        )
    )).scalar_one_or_none()
    assert aud is not None
    assert int((aud.after_state or {}).get("created_count", 0)) >= 1


@pytest.mark.asyncio
async def test_scheduled_billing_handles_existing(db, caplog):
    """Second run returns already-exists status gracefully (no 409, no duplicate)."""
    today = today_ist()
    if today.month == 1:
        y, m = today.year - 1, 12
    else:
        y, m = today.year, today.month - 1
    await _seeded_delivered(db, y, m)
    r1 = await monthly_billing(db)
    await db.commit()
    assert r1.affected >= 1
    # Second run
    with caplog.at_level("WARNING", logger="jobs"):
        r2 = await monthly_billing(db)
    await db.commit()
    assert r2.details.get("status") == "already_exists_skipped"
    assert any("already exist" in rec.message for rec in caplog.records)
    # No duplicate invoices for the period
    inv_count = (await db.execute(
        select(func.count()).select_from(Invoice).where(Invoice.year == y, Invoice.month == m)
    )).scalar_one()
    # 1 customer seeded → 1 invoice, not 2
    expected = (await db.execute(
        select(func.count(func.distinct(DeliveryOrder.customer_id))).where(
            func.date_trunc('month', DeliveryOrder.delivery_date) == date(y, m, 1),
            DeliveryOrder.status == DeliveryOrderStatus.DELIVERED,
        )
    )).scalar_one()
    assert inv_count == int(expected)


@pytest.mark.asyncio
async def test_deprecated_billing_service_emits_warning(db):
    """Legacy billing_service.generate_invoices_for_period raises DeprecationWarning."""
    from app.services.billing_service import generate_invoices_for_period
    with pytest.warns(DeprecationWarning, match="deprecated since Phase 2B.8"):
        await generate_invoices_for_period(db, 2020, 1)
