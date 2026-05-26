"""Phase 2B.5 — products CRUD + price-change history."""
from __future__ import annotations
import pytest
import pytest_asyncio
import uuid as uuidm
from datetime import date as date_cls, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.product_price_history import ProductPriceHistory
from app.models.audit_log import AuditLog
from app.models.delivery import DeliveryOrder
from app.models.subscription import Subscription
from app.models.enums import (
    ProductUnit, SubscriptionStatus, SubscriptionFrequency, DeliveryOrderStatus,
)
from app.core.time_utils import now_utc, today_ist
from tests.conftest import auth_headers


OK_REASON = "Product price reviewed with finance team"


@pytest_asyncio.fixture(loop_scope="session")
async def fresh_product(db: AsyncSession) -> Product:
    p = Product(
        name="Test Cow Milk 500ml", sku="tcm-500-{}".format(uuidm.uuid4().hex[:6]),
        unit=ProductUnit.LITRE, price_paise=3500, requires_bottle=True, active=True,
    )
    db.add(p)
    await db.commit(); await db.refresh(p)
    # Seed an old history row (365 days ago) so get_price_at works from genesis
    db.add(ProductPriceHistory(
        product_id=p.id, price_paise=3500,
        effective_from=today_ist() - timedelta(days=365),
        reason="Initial seed for test",
    ))
    await db.commit()
    return p


@pytest.mark.asyncio
async def test_product_create_audit(client, admin_user, db):
    r = await client.post(
        "/api/admin/products",
        headers=auth_headers(admin_user),
        json={"name": "Goat Milk 500ml", "sku": "gm-500", "unit": "litre",
              "price_paise": 6000, "requires_bottle": True, "description": "Premium"},
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    # Audit row exists
    rows = (await db.execute(
        select(AuditLog).where(AuditLog.entity_id == pid, AuditLog.action == "product.create")
    )).scalars().all()
    assert rows
    # Initial history row seeded
    hist = (await db.execute(
        select(ProductPriceHistory).where(ProductPriceHistory.product_id == uuidm.UUID(pid))
    )).scalars().all()
    assert len(hist) == 1
    assert hist[0].price_paise == 6000


@pytest.mark.asyncio
async def test_product_update_audit_no_price_change(client, admin_user, fresh_product, db):
    r = await client.patch(
        f"/api/admin/products/{fresh_product.id}",
        headers=auth_headers(admin_user),
        json={"name": "Test Cow Milk 500ml (renamed)", "active": True, "description": "Updated"},
    )
    assert r.status_code == 200
    # Price unchanged
    assert r.json()["price_paise"] == 3500
    # Audit row for update
    rows = (await db.execute(
        select(AuditLog).where(AuditLog.entity_id == str(fresh_product.id), AuditLog.action == "product.update")
    )).scalars().all()
    assert rows
    latest = rows[0]
    # No price_change rows
    pc = (await db.execute(
        select(AuditLog).where(AuditLog.entity_id == str(fresh_product.id), AuditLog.action == "product.price_change")
    )).scalars().all()
    assert not pc


@pytest.mark.asyncio
async def test_price_change_requires_reason_min_10(client, admin_user, fresh_product):
    r = await client.post(
        f"/api/admin/products/{fresh_product.id}/price-change",
        headers=auth_headers(admin_user),
        json={"new_price_paise": 4000, "effective_from": (today_ist() + timedelta(days=1)).isoformat(),
              "reason": "too short"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_price_change_cannot_backdate(client, admin_user, fresh_product):
    r = await client.post(
        f"/api/admin/products/{fresh_product.id}/price-change",
        headers=auth_headers(admin_user),
        json={"new_price_paise": 4000, "effective_from": (today_ist() - timedelta(days=1)).isoformat(),
              "reason": OK_REASON},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "cannot_backdate"


@pytest.mark.asyncio
async def test_price_change_future_dated_does_not_update_current(client, admin_user, fresh_product, db):
    future = today_ist() + timedelta(days=7)
    r = await client.post(
        f"/api/admin/products/{fresh_product.id}/price-change",
        headers=auth_headers(admin_user),
        json={"new_price_paise": 4500, "effective_from": future.isoformat(),
              "reason": OK_REASON},
    )
    assert r.status_code == 201, r.text
    # Current price unchanged
    p = (await db.execute(select(Product).where(Product.id == fresh_product.id))).scalar_one()
    assert p.price_paise == 3500
    # History row has new effective_from
    hist = (await db.execute(
        select(ProductPriceHistory).where(ProductPriceHistory.product_id == fresh_product.id, ProductPriceHistory.effective_from == future)
    )).scalars().all()
    assert len(hist) == 1
    # Audit flags applied_immediately=False
    audit = (await db.execute(
        select(AuditLog).where(AuditLog.entity_id == str(fresh_product.id), AuditLog.action == "product.price_change")
        .order_by(AuditLog.created_at.desc())
    )).scalars().first()
    assert audit.after_state["applied_immediately"] is False


@pytest.mark.asyncio
async def test_price_change_immediate(client, admin_user, fresh_product, db):
    today = today_ist()
    r = await client.post(
        f"/api/admin/products/{fresh_product.id}/price-change",
        headers=auth_headers(admin_user),
        json={"new_price_paise": 3800, "effective_from": today.isoformat(),
              "reason": OK_REASON},
    )
    assert r.status_code == 201
    # Current price IS updated
    db.expunge_all()
    p = (await db.execute(select(Product).where(Product.id == fresh_product.id))).scalar_one()
    assert p.price_paise == 3800


@pytest.mark.asyncio
async def test_price_history_endpoint(client, admin_user, fresh_product):
    # Add two history rows
    for d, price in [(today_ist() + timedelta(days=5), 4200), (today_ist() + timedelta(days=10), 4400)]:
        r = await client.post(
            f"/api/admin/products/{fresh_product.id}/price-change",
            headers=auth_headers(admin_user),
            json={"new_price_paise": price, "effective_from": d.isoformat(), "reason": OK_REASON},
        )
        assert r.status_code == 201
    hist = (await client.get(
        f"/api/admin/products/{fresh_product.id}/price-history",
        headers=auth_headers(admin_user),
    )).json()
    # Most recent effective_from first
    dates = [h["effective_from"] for h in hist]
    assert dates == sorted(dates, reverse=True)


@pytest.mark.asyncio
async def test_historical_pricing_lookup(engine, admin_user, fresh_product):
    from app.services import product_pricing_service
    from sqlalchemy.ext.asyncio import async_sessionmaker
    SL = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    # Seed a future change: +5 days → 5000
    async with SL() as s:
        s.add(ProductPriceHistory(
            product_id=fresh_product.id, price_paise=5000,
            effective_from=today_ist() + timedelta(days=5), reason="test lookup",
        ))
        await s.commit()

    async with SL() as s:
        # On yesterday: initial genesis price (3500)
        y = await product_pricing_service.get_price_at(s, fresh_product.id, today_ist() - timedelta(days=1))
        # On day+6: should use the 5000 effective at day+5
        f = await product_pricing_service.get_price_at(s, fresh_product.id, today_ist() + timedelta(days=6))
        # On day+4: 3500 still in effect
        b = await product_pricing_service.get_price_at(s, fresh_product.id, today_ist() + timedelta(days=4))
    assert y == 3500
    assert b == 3500
    assert f == 5000


@pytest.mark.asyncio
async def test_delivery_order_locks_price(engine, admin_user, fresh_product, customer_user):
    """Change price — existing delivery_orders must retain their snapshot price."""
    from sqlalchemy.ext.asyncio import async_sessionmaker
    SL = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with SL() as s:
        sub = Subscription(
            customer_id=customer_user.id, product_id=fresh_product.id, quantity=1,
            frequency=SubscriptionFrequency.DAILY, start_date=today_ist(),
            status=SubscriptionStatus.ACTIVE,
        )
        s.add(sub); await s.commit(); await s.refresh(sub)
        o = DeliveryOrder(
            customer_id=customer_user.id, subscription_id=sub.id, product_id=fresh_product.id,
            delivery_date=today_ist(), quantity=1, unit_price_paise=3500,
            status=DeliveryOrderStatus.PENDING,
        )
        s.add(o); await s.commit(); oid = o.id

    # Apply an immediate price change
    async with SL() as s:
        p = (await s.execute(select(Product).where(Product.id == fresh_product.id))).scalar_one()
        p.price_paise = 4200
        s.add(ProductPriceHistory(
            product_id=p.id, price_paise=4200, effective_from=today_ist(), reason="hike",
        ))
        await s.commit()

    # Verify the old order still carries the snapshot
    async with SL() as s:
        o2 = (await s.execute(select(DeliveryOrder).where(DeliveryOrder.id == oid))).scalar_one()
    assert o2.unit_price_paise == 3500


@pytest.mark.asyncio
async def test_rbac_products(client, customer_user, delivery_user, fresh_product):
    payload = {
        "name": "x", "sku": "x", "unit": "litre", "price_paise": 100,
        "new_price_paise": 100, "effective_from": today_ist().isoformat(),
        "reason": "Attempting unauthorised access scan",
    }
    endpoints = [
        ("GET", "/api/admin/products"),
        ("POST", "/api/admin/products"),
        ("GET", f"/api/admin/products/{fresh_product.id}"),
        ("PATCH", f"/api/admin/products/{fresh_product.id}"),
        ("POST", f"/api/admin/products/{fresh_product.id}/price-change"),
        ("GET", f"/api/admin/products/{fresh_product.id}/price-history"),
    ]
    for tok_user in (customer_user, delivery_user):
        for method, path in endpoints:
            if method == "GET":
                r = await client.get(path, headers=auth_headers(tok_user))
            elif method == "POST":
                r = await client.post(path, headers=auth_headers(tok_user), json=payload)
            else:
                r = await client.patch(path, headers=auth_headers(tok_user), json=payload)
            assert r.status_code == 403, f"{method} {path} → {r.status_code}"


@pytest.mark.asyncio
async def test_sku_conflict(client, admin_user, fresh_product):
    r = await client.post(
        "/api/admin/products",
        headers=auth_headers(admin_user),
        json={"name": "dupe", "sku": fresh_product.sku, "unit": "litre",
              "price_paise": 1000, "requires_bottle": False},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "sku_conflict"
