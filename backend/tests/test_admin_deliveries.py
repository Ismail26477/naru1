"""Phase 2B.4 — delivery order override."""
from __future__ import annotations
import asyncio
import pytest
import pytest_asyncio
import uuid as uuidm
from datetime import date as date_cls, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.user import User
from app.models.enums import UserRole, SubscriptionFrequency, SubscriptionStatus, DeliveryOrderStatus
from app.models.subscription import Subscription
from app.models.delivery import DeliveryOrder, BottleLedger
from app.models.audit_log import AuditLog
from app.core.time_utils import now_utc, today_ist, tomorrow_ist
from tests.conftest import auth_headers


OK_REASON = "Customer confirmed delivery post-cutoff today"  # 45 chars


@pytest_asyncio.fixture(loop_scope="session")
async def test_customer(db: AsyncSession) -> User:
    u = User(phone="+919077700001", name="Delivery Test Customer", role=UserRole.CUSTOMER,
             is_active=True, approved_at=now_utc())
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest_asyncio.fixture(loop_scope="session")
async def pending_order(db: AsyncSession, test_customer: User, milk_product) -> DeliveryOrder:
    sub = Subscription(
        customer_id=test_customer.id, product_id=milk_product.id, quantity=1,
        frequency=SubscriptionFrequency.DAILY, start_date=today_ist(),
        status=SubscriptionStatus.ACTIVE,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    o = DeliveryOrder(
        customer_id=test_customer.id, subscription_id=sub.id, product_id=milk_product.id,
        delivery_date=today_ist(), quantity=1, unit_price_paise=milk_product.price_paise,
        status=DeliveryOrderStatus.PENDING,
    )
    db.add(o)
    await db.commit()
    await db.refresh(o)
    return o


# ==================== OVERRIDE FLOWS ====================

@pytest.mark.asyncio
async def test_override_pending_to_delivered(client, admin_user, pending_order, test_customer, db):
    r = await client.post(
        f"/api/admin/delivery-orders/{pending_order.id}/override",
        headers=auth_headers(admin_user),
        json={"status": "delivered", "delivered_quantity": 1, "bottles_returned": 0, "reason": OK_REASON},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "delivered"
    assert d["delivered_quantity"] == 1

    # Bottle ledger +1
    sum_q = (await db.execute(
        select(func.coalesce(func.sum(BottleLedger.change), 0)).where(BottleLedger.customer_id == test_customer.id)
    )).scalar_one()
    assert int(sum_q) == 1

    # Audit row
    rows = (await db.execute(
        select(AuditLog).where(
            AuditLog.entity_type == "delivery_order",
            AuditLog.entity_id == str(pending_order.id),
        )
    )).scalars().all()
    actions = [r.action for r in rows]
    assert "delivery_order.override" in actions
    latest = [r for r in rows if r.action == "delivery_order.override"][0]
    assert "order" in latest.before_state
    assert "order" in latest.after_state
    assert latest.before_state["order"]["status"] == "pending"
    assert latest.after_state["order"]["status"] == "delivered"


@pytest.mark.asyncio
async def test_override_pending_to_skipped(client, admin_user, pending_order, test_customer, db):
    r = await client.post(
        f"/api/admin/delivery-orders/{pending_order.id}/override",
        headers=auth_headers(admin_user),
        json={"status": "skipped", "reason": "Customer travelling today unplanned"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "skipped"
    assert r.json()["skip_reason"].startswith("Customer travelling")
    # No bottle entries
    sum_q = (await db.execute(
        select(func.coalesce(func.sum(BottleLedger.change), 0)).where(BottleLedger.customer_id == test_customer.id)
    )).scalar_one()
    assert int(sum_q) == 0


@pytest.mark.asyncio
async def test_override_delivered_to_pending_compensates(client, admin_user, pending_order, test_customer, db):
    # First: deliver
    r1 = await client.post(
        f"/api/admin/delivery-orders/{pending_order.id}/override",
        headers=auth_headers(admin_user),
        json={"status": "delivered", "delivered_quantity": 1, "bottles_returned": 0, "reason": OK_REASON},
    )
    assert r1.status_code == 200
    # Confirm +1 ledger
    before_count = int((await db.execute(
        select(func.count(BottleLedger.id)).where(BottleLedger.delivery_order_id == pending_order.id)
    )).scalar_one())
    assert before_count == 1

    # Now revert → pending
    r2 = await client.post(
        f"/api/admin/delivery-orders/{pending_order.id}/override",
        headers=auth_headers(admin_user),
        json={"status": "pending", "reason": "Incorrectly marked delivered customer was away"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "pending"

    # Original entry still there + compensating entry added
    all_entries = (await db.execute(
        select(BottleLedger).where(BottleLedger.delivery_order_id == pending_order.id)
    )).scalars().all()
    assert len(all_entries) == 2
    assert sum(e.change for e in all_entries) == 0  # net zero

    # Customer total sum still 0 (we never deleted history)
    sum_q = (await db.execute(
        select(func.coalesce(func.sum(BottleLedger.change), 0)).where(BottleLedger.customer_id == test_customer.id)
    )).scalar_one()
    assert int(sum_q) == 0


@pytest.mark.asyncio
async def test_override_bypasses_cutoff(client, admin_user, pending_order, db):
    # Simulate cutoff already locked
    pending_order.cutoff_locked_at = now_utc() - timedelta(hours=1)
    await db.commit()

    r = await client.post(
        f"/api/admin/delivery-orders/{pending_order.id}/override",
        headers=auth_headers(admin_user),
        json={"status": "skipped", "reason": "Override past cutoff test scenario"},
    )
    assert r.status_code == 200
    # Audit row has bypassed_cutoff=true
    rows = (await db.execute(
        select(AuditLog).where(
            AuditLog.entity_id == str(pending_order.id),
            AuditLog.action == "delivery_order.override",
        ).order_by(AuditLog.created_at.desc())
    )).scalars().all()
    assert rows
    assert rows[0].after_state.get("bypassed_cutoff") is True


@pytest.mark.asyncio
async def test_override_requires_reason_min_10(client, admin_user, pending_order):
    # 9 chars
    r1 = await client.post(
        f"/api/admin/delivery-orders/{pending_order.id}/override",
        headers=auth_headers(admin_user),
        json={"status": "skipped", "reason": "too short"},
    )
    assert r1.status_code == 422
    # Exactly 10 chars, no noop
    r2 = await client.post(
        f"/api/admin/delivery-orders/{pending_order.id}/override",
        headers=auth_headers(admin_user),
        json={"status": "skipped", "reason": "1234567890"},
    )
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_override_missing_quantity(client, admin_user, pending_order):
    # Requesting delivered without delivered_quantity
    r = await client.post(
        f"/api/admin/delivery-orders/{pending_order.id}/override",
        headers=auth_headers(admin_user),
        json={"status": "delivered", "reason": OK_REASON},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "missing_quantity"


@pytest.mark.asyncio
async def test_override_quantity_out_of_range(client, admin_user, pending_order):
    # subscribed quantity is 1; 5 would be 5x (> 2x limit)
    r = await client.post(
        f"/api/admin/delivery-orders/{pending_order.id}/override",
        headers=auth_headers(admin_user),
        json={"status": "delivered", "delivered_quantity": 5, "bottles_returned": 0, "reason": OK_REASON},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "quantity_out_of_range"


@pytest.mark.asyncio
async def test_override_max_days_back(client, admin_user, test_customer, milk_product, db):
    sub = Subscription(
        customer_id=test_customer.id, product_id=milk_product.id, quantity=1,
        frequency=SubscriptionFrequency.DAILY, start_date=today_ist() - timedelta(days=30),
        status=SubscriptionStatus.ACTIVE,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    old = DeliveryOrder(
        customer_id=test_customer.id, subscription_id=sub.id, product_id=milk_product.id,
        delivery_date=today_ist() - timedelta(days=10),  # 10 days ago (> 7)
        quantity=1, unit_price_paise=milk_product.price_paise,
        status=DeliveryOrderStatus.PENDING,
    )
    db.add(old)
    await db.commit()
    await db.refresh(old)

    r = await client.post(
        f"/api/admin/delivery-orders/{old.id}/override",
        headers=auth_headers(admin_user),
        json={"status": "skipped", "reason": "Retroactive correction test attempt"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "too_old_to_override"


@pytest.mark.asyncio
async def test_override_bottle_ledger_integrity(engine, admin_user, test_customer, milk_product):
    """Multiple overrides on the same order — net SUM matches expected."""
    from app.services import delivery_admin_service, bottle_service

    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as s:
        sub = Subscription(
            customer_id=test_customer.id, product_id=milk_product.id, quantity=2,
            frequency=SubscriptionFrequency.DAILY, start_date=today_ist(),
            status=SubscriptionStatus.ACTIVE,
        )
        s.add(sub)
        await s.commit()
        await s.refresh(sub)
        o = DeliveryOrder(
            customer_id=test_customer.id, subscription_id=sub.id, product_id=milk_product.id,
            delivery_date=today_ist(), quantity=2, unit_price_paise=milk_product.price_paise,
            status=DeliveryOrderStatus.PENDING,
        )
        s.add(o)
        await s.commit()
        oid = o.id

    # deliver(2) → pending → deliver(2, returned=1) → skip → deliver(2, returned=0)
    cycles = [
        (DeliveryOrderStatus.DELIVERED, 2, 0),
        (DeliveryOrderStatus.PENDING, None, None),
        (DeliveryOrderStatus.DELIVERED, 2, 1),
        (DeliveryOrderStatus.SKIPPED, None, None),
        (DeliveryOrderStatus.DELIVERED, 2, 0),
    ]
    for st, q, br in cycles:
        async with SessionLocal() as s:
            await delivery_admin_service.override(
                s, order_id=oid, new_status=st, delivered_quantity=q, bottles_returned=br,
                reason=OK_REASON, actor=admin_user,
            )
            await s.commit()

    # After last: delivered qty=2 returned=0 → net +2 fresh; prior compensations bring net to +2
    async with SessionLocal() as s:
        bal = await bottle_service.bottle_balance(s, test_customer.id)
        total = int((await s.execute(
            select(func.coalesce(func.sum(BottleLedger.change), 0))
            .where(BottleLedger.customer_id == test_customer.id)
        )).scalar_one())
    assert bal == 2
    assert total == bal  # derived balance and ledger sum agree


@pytest.mark.asyncio
async def test_override_concurrency(engine, admin_user, test_customer, milk_product):
    from app.services import delivery_admin_service

    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as s:
        sub = Subscription(
            customer_id=test_customer.id, product_id=milk_product.id, quantity=1,
            frequency=SubscriptionFrequency.DAILY, start_date=today_ist(),
            status=SubscriptionStatus.ACTIVE,
        )
        s.add(sub); await s.commit(); await s.refresh(sub)
        o = DeliveryOrder(
            customer_id=test_customer.id, subscription_id=sub.id, product_id=milk_product.id,
            delivery_date=today_ist(), quantity=1, unit_price_paise=milk_product.price_paise,
            status=DeliveryOrderStatus.PENDING,
        )
        s.add(o); await s.commit(); oid = o.id

    results = []

    async def do(st, q):
        async with SessionLocal() as s:
            try:
                await delivery_admin_service.override(
                    s, order_id=oid, new_status=st, delivered_quantity=q, bottles_returned=0,
                    reason=OK_REASON, actor=admin_user,
                )
                await s.commit()
                results.append("ok")
            except Exception as e:
                await s.rollback()
                results.append(type(e).__name__)

    # Two concurrent identical attempts → one might "noop" after the first commits.
    await asyncio.gather(
        do(DeliveryOrderStatus.DELIVERED, 1),
        do(DeliveryOrderStatus.DELIVERED, 1),
    )
    # Both serialise via FOR UPDATE; the second sees the new state and yields HTTPException
    # (either noop or invalid_transition self-to-self). At least one succeeded.
    assert "ok" in results


@pytest.mark.asyncio
async def test_bulk_skip(client, admin_user, test_customer, milk_product, db):
    sub = Subscription(
        customer_id=test_customer.id, product_id=milk_product.id, quantity=1,
        frequency=SubscriptionFrequency.DAILY, start_date=today_ist(),
        status=SubscriptionStatus.ACTIVE,
    )
    db.add(sub); await db.commit(); await db.refresh(sub)
    orders: list[DeliveryOrder] = []
    for i in range(5):
        # One subscription per order to avoid uq_delivery_sub_date collision
        sub_i = Subscription(
            customer_id=test_customer.id, product_id=milk_product.id, quantity=1,
            frequency=SubscriptionFrequency.DAILY, start_date=today_ist(),
            status=SubscriptionStatus.ACTIVE,
        )
        db.add(sub_i); await db.commit(); await db.refresh(sub_i)
        o = DeliveryOrder(
            customer_id=test_customer.id, subscription_id=sub_i.id, product_id=milk_product.id,
            delivery_date=today_ist() + timedelta(days=i),
            quantity=1, unit_price_paise=milk_product.price_paise,
            status=DeliveryOrderStatus.PENDING,
        )
        db.add(o); orders.append(o)
    await db.commit()
    for o in orders:
        await db.refresh(o)

    r = await client.post(
        "/api/admin/delivery-orders/bulk-skip",
        headers=auth_headers(admin_user),
        json={"order_ids": [str(o.id) for o in orders], "reason": "Boy unavailable monsoon block"},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["applied"]) == 5
    bulk_id = body["bulk_operation_id"]

    # Each order has an audit row with matching bulk_operation_id
    rows = (await db.execute(
        select(AuditLog).where(AuditLog.action == "delivery_order.override", AuditLog.entity_id.in_([str(o.id) for o in orders]))
    )).scalars().all()
    assert len(rows) == 5
    assert all(r.after_state.get("bulk_operation_id") == bulk_id for r in rows)


@pytest.mark.asyncio
async def test_rbac_override_forbidden(client, customer_user, delivery_user, pending_order):
    payload = {"status": "skipped", "reason": "Attempted unauthorised override"}
    r1 = await client.post(
        f"/api/admin/delivery-orders/{pending_order.id}/override",
        headers=auth_headers(customer_user), json=payload,
    )
    assert r1.status_code == 403
    r2 = await client.post(
        f"/api/admin/delivery-orders/{pending_order.id}/override",
        headers=auth_headers(delivery_user), json=payload,
    )
    assert r2.status_code == 403


@pytest.mark.asyncio
async def test_audit_snapshot_completeness(client, admin_user, pending_order, db):
    await client.post(
        f"/api/admin/delivery-orders/{pending_order.id}/override",
        headers=auth_headers(admin_user),
        json={"status": "delivered", "delivered_quantity": 1, "bottles_returned": 0, "reason": OK_REASON},
    )
    row = (await db.execute(
        select(AuditLog).where(AuditLog.entity_id == str(pending_order.id), AuditLog.action == "delivery_order.override")
    )).scalars().first()
    assert row is not None
    b = row.before_state
    a = row.after_state
    for key in ("id", "status", "quantity", "delivered_quantity", "bottles_returned", "delivered_at"):
        assert key in b["order"]
        assert key in a["order"]
    assert "bypassed_cutoff" in a
    assert "ledger_delta" in a


# ---------- board GET ----------

@pytest.mark.asyncio
async def test_board_list_and_kpis(client, admin_user, pending_order):
    r = await client.get(
        f"/api/admin/delivery-orders/board?date={today_ist().isoformat()}",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 200
    d = r.json()
    assert "kpis" in d
    assert d["kpis"]["scheduled"] >= 1
    assert any(it["id"] == str(pending_order.id) for it in d["items"])
