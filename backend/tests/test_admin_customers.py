"""Phase 2B.2 — admin customer management tests.

Covers:
- wallet adjustment (happy, blocked, forced, atomicity, concurrency, integrity)
- bottle adjustment (happy, blocked, forced, integrity)
- customer approve / reject audit
- admin subscription pause audit (differentiated from customer pause)
- pg_trgm search
- RBAC on every new endpoint
- reason validation
"""
from __future__ import annotations
import asyncio
import pytest
import pytest_asyncio
import uuid as uuidm
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.models.user import User, Address
from app.models.enums import UserRole, SubscriptionStatus, SubscriptionFrequency, BottleReason
from app.models.billing import WalletTransaction
from app.models.delivery import BottleLedger
from app.models.audit_log import AuditLog
from app.models.subscription import Subscription
from app.core.time_utils import now_utc
from tests.conftest import auth_headers


ADJ_OK_REASON = "Credit for delivery issue compensation test"  # 48 chars


@pytest_asyncio.fixture(loop_scope="session")
async def seed_customer(db: AsyncSession) -> User:
    u = User(
        phone="+919777777777", name="Amit Kulkarni", role=UserRole.CUSTOMER,
        is_active=True, approved_at=now_utc(), wallet_balance_paise=0,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    db.add(Address(
        user_id=u.id, line1="Plot 42 Dharampeth",
        area="Dharampeth", city="Nagpur", pincode="440010",
    ))
    await db.commit()
    return u


@pytest_asyncio.fixture(loop_scope="session")
async def pending_customer(db: AsyncSession) -> User:
    u = User(
        phone="+919777777778", name="Priya Pending", role=UserRole.CUSTOMER,
        is_active=True, approved_at=None, wallet_balance_paise=0,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


# ==================== WALLET ====================

@pytest.mark.asyncio
async def test_wallet_adjustment_positive(client, admin_user, seed_customer):
    r = await client.post(
        f"/api/admin/customers/{seed_customer.id}/wallet-adjustment",
        headers=auth_headers(admin_user),
        json={"amount_paise": 10000, "reason": ADJ_OK_REASON},
    )
    assert r.status_code == 201, r.text
    tx = r.json()
    assert tx["change_paise"] == 10000
    assert tx["balance_after_paise"] == 10000

    # audit row
    from tests.conftest import engine as _
    from app.db.session import AsyncSessionLocal
    # Inspect via a fresh session (seed_customer is reusable)
    # We use the client-facing API to verify audit presence:
    r2 = await client.get(
        f"/api/admin/customers/{seed_customer.id}/audit-log",
        headers=auth_headers(admin_user),
    )
    assert r2.status_code == 200
    actions = [row["action"] for row in r2.json()]
    assert "wallet.adjust" in actions


@pytest.mark.asyncio
async def test_wallet_adjustment_negative_blocked(client, admin_user, seed_customer):
    # Fresh customer with 0 balance. Try to debit 1_000_000 without force
    r = await client.post(
        f"/api/admin/customers/{seed_customer.id}/wallet-adjustment",
        headers=auth_headers(admin_user),
        json={"amount_paise": -1_000_000, "reason": ADJ_OK_REASON},
    )
    assert r.status_code == 400
    body = r.json()
    assert body["detail"]["code"] == "would_go_negative"

    # Verify NO wallet txn written for that specific amount and NO extra audit
    r_txns = await client.get(
        f"/api/admin/customers/{seed_customer.id}/wallet-transactions",
        headers=auth_headers(admin_user),
    )
    assert r_txns.status_code == 200
    amounts = [t["change_paise"] for t in r_txns.json()["items"]]
    assert -1_000_000 not in amounts


@pytest.mark.asyncio
async def test_wallet_adjustment_negative_forced(client, admin_user, seed_customer):
    # Fresh customer with balance=0; forced debit goes negative
    r = await client.post(
        f"/api/admin/customers/{seed_customer.id}/wallet-adjustment",
        headers=auth_headers(admin_user),
        json={
            "amount_paise": -20000,
            "reason": "Manual debit after reconciliation review",
            "force": True,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["balance_after_paise"] == -20000

    # audit has force=true flag
    r_audit = await client.get(
        f"/api/admin/customers/{seed_customer.id}/audit-log",
        headers=auth_headers(admin_user),
    )
    rows = [a for a in r_audit.json() if a["action"] == "wallet.adjust"]
    forced = [a for a in rows if a.get("after_state", {}).get("force") is True]
    assert len(forced) >= 1


@pytest.mark.asyncio
async def test_wallet_adjustment_reason_validation(client, admin_user, seed_customer):
    # empty reason
    r1 = await client.post(
        f"/api/admin/customers/{seed_customer.id}/wallet-adjustment",
        headers=auth_headers(admin_user),
        json={"amount_paise": 500, "reason": ""},
    )
    assert r1.status_code == 422
    # too short
    r2 = await client.post(
        f"/api/admin/customers/{seed_customer.id}/wallet-adjustment",
        headers=auth_headers(admin_user),
        json={"amount_paise": 500, "reason": "too short"},
    )
    assert r2.status_code == 422
    # zero amount
    r3 = await client.post(
        f"/api/admin/customers/{seed_customer.id}/wallet-adjustment",
        headers=auth_headers(admin_user),
        json={"amount_paise": 0, "reason": ADJ_OK_REASON},
    )
    assert r3.status_code == 400


@pytest.mark.asyncio
async def test_wallet_adjustment_atomicity(engine, admin_user, monkeypatch):
    """If audit_service.log_action raises, the wallet_transaction must NOT
    be visible after rollback. Uses a fresh session so we can observe the
    aborted transaction cleanly.
    """
    from app.services import audit_service
    from app.services import wallet_service

    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    # Seed a customer just for this test
    async with SessionLocal() as s:
        u = User(
            phone="+919777777779", name="Atomic Test", role=UserRole.CUSTOMER,
            is_active=True, approved_at=now_utc(), wallet_balance_paise=0,
        )
        s.add(u)
        await s.commit()
        cid = u.id
        before_balance = u.wallet_balance_paise
        tx_count_before = int((await s.execute(
            select(func.count(WalletTransaction.id)).where(WalletTransaction.customer_id == cid)
        )).scalar_one() or 0)

    # Monkeypatch audit to raise
    orig = audit_service.log_action

    async def _boom(*a, **kw):
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr(audit_service, "log_action", _boom)

    # Wrap in a fresh session and expect RuntimeError to propagate
    with pytest.raises(RuntimeError):
        async with SessionLocal() as s:
            try:
                await wallet_service.adjust(
                    s, customer_id=cid, change_paise=500,
                    reason=ADJ_OK_REASON, actor=admin_user,
                )
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    # Restore and verify nothing persisted
    monkeypatch.setattr(audit_service, "log_action", orig)
    async with SessionLocal() as s:
        after_balance = int((await s.execute(
            select(User.wallet_balance_paise).where(User.id == cid)
        )).scalar_one() or 0)
        tx_count_after = int((await s.execute(
            select(func.count(WalletTransaction.id)).where(WalletTransaction.customer_id == cid)
        )).scalar_one() or 0)

    assert after_balance == before_balance, "balance must not change on rollback"
    assert tx_count_after == tx_count_before, "no wallet_transactions row may persist"


@pytest.mark.asyncio
async def test_wallet_concurrency(engine, admin_user):
    """Two simultaneous adjustments must both be applied; no lost update."""
    from app.services import wallet_service

    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as s:
        u = User(
            phone="+919777777780", name="Concurrency Test", role=UserRole.CUSTOMER,
            is_active=True, approved_at=now_utc(), wallet_balance_paise=0,
        )
        s.add(u)
        await s.commit()
        cid = u.id

    async def _do_adjust(amount: int):
        async with SessionLocal() as s:
            try:
                await wallet_service.adjust(
                    s, customer_id=cid, change_paise=amount,
                    reason=ADJ_OK_REASON, actor=admin_user,
                )
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    await asyncio.gather(_do_adjust(100), _do_adjust(200), _do_adjust(300))

    async with SessionLocal() as s:
        bal = int((await s.execute(
            select(User.wallet_balance_paise).where(User.id == cid)
        )).scalar_one() or 0)
        total_sum = int((await s.execute(
            select(func.coalesce(func.sum(WalletTransaction.change_paise), 0))
            .where(WalletTransaction.customer_id == cid)
        )).scalar_one() or 0)

    assert bal == 600, f"lost update: balance={bal}"
    assert total_sum == 600, f"ledger drift: sum={total_sum}"


@pytest.mark.asyncio
async def test_wallet_balance_integrity_many(engine, admin_user):
    """After a batch of mixed adjustments SUM(txns) must equal balance."""
    from app.services import wallet_service

    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as s:
        u = User(
            phone="+919777777781", name="Integrity Test", role=UserRole.CUSTOMER,
            is_active=True, approved_at=now_utc(), wallet_balance_paise=0,
        )
        s.add(u)
        await s.commit()
        cid = u.id

    deltas = [500, -200, 1500, -750, 300, 800, -100, 250]
    for d in deltas:
        async with SessionLocal() as s:
            await wallet_service.adjust(
                s, customer_id=cid, change_paise=d,
                reason=ADJ_OK_REASON, actor=admin_user, force=True,
            )
            await s.commit()

    async with SessionLocal() as s:
        bal = int((await s.execute(
            select(User.wallet_balance_paise).where(User.id == cid)
        )).scalar_one())
        ssum = int((await s.execute(
            select(func.coalesce(func.sum(WalletTransaction.change_paise), 0))
            .where(WalletTransaction.customer_id == cid)
        )).scalar_one())
    assert bal == sum(deltas)
    assert ssum == bal


# ==================== BOTTLE ====================

@pytest.mark.asyncio
async def test_bottle_adjustment_positive(client, admin_user, seed_customer):
    r = await client.post(
        f"/api/admin/customers/{seed_customer.id}/bottle-adjustment",
        headers=auth_headers(admin_user),
        json={"change": 3, "reason": "Delivered 3 extra bottles today morning"},
    )
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["change"] == 3
    assert row["reason"] == "adjustment"


@pytest.mark.asyncio
async def test_bottle_adjustment_negative_blocked(client, admin_user, pending_customer, admin_approve_done=None):
    # pending customer has 0 bottles; try to go to -5 without force
    r = await client.post(
        f"/api/admin/customers/{pending_customer.id}/bottle-adjustment",
        headers=auth_headers(admin_user),
        json={"change": -5, "reason": "Would take balance negative test"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "would_go_negative"


@pytest.mark.asyncio
async def test_bottle_adjustment_negative_forced(client, admin_user, pending_customer):
    r = await client.post(
        f"/api/admin/customers/{pending_customer.id}/bottle-adjustment",
        headers=auth_headers(admin_user),
        json={"change": -2, "reason": "Promotional return credit forced", "force": True},
    )
    assert r.status_code == 201
    assert r.json()["change"] == -2


@pytest.mark.asyncio
async def test_bottle_integrity_after_batch(engine, admin_user):
    from app.services import bottle_service

    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as s:
        u = User(
            phone="+919777777782", name="Bottle Integrity", role=UserRole.CUSTOMER,
            is_active=True, approved_at=now_utc(),
        )
        s.add(u)
        await s.commit()
        cid = u.id

    for d in [2, 1, 3, -1, 2]:
        async with SessionLocal() as s:
            await bottle_service.adjust(
                s, customer_id=cid, change=d,
                reason="Batch integrity test ledger row", actor=admin_user,
            )
            await s.commit()

    async with SessionLocal() as s:
        summed = int((await s.execute(
            select(func.coalesce(func.sum(BottleLedger.change), 0))
            .where(BottleLedger.customer_id == cid)
        )).scalar_one())
    assert summed == 7


# ==================== APPROVE / REJECT AUDIT ====================

@pytest.mark.asyncio
async def test_approve_customer_audit(client, admin_user, pending_customer):
    r = await client.post(
        f"/api/admin/customers/{pending_customer.id}/approve",
        headers=auth_headers(admin_user),
        json={"reason": None},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["approved_at"] is not None

    r2 = await client.get(
        f"/api/admin/customers/{pending_customer.id}/audit-log",
        headers=auth_headers(admin_user),
    )
    assert r2.status_code == 200
    actions = [a["action"] for a in r2.json()]
    assert "customer.approve" in actions


@pytest.mark.asyncio
async def test_reject_customer_requires_reason(client, admin_user, seed_customer):
    r = await client.post(
        f"/api/admin/customers/{seed_customer.id}/reject",
        headers=auth_headers(admin_user),
        json={},
    )
    assert r.status_code == 422  # reason required


# ==================== SUBSCRIPTION ADMIN PAUSE ====================

@pytest.mark.asyncio
async def test_subscription_admin_pause_audit(engine, client, admin_user, seed_customer, milk_product):
    # Seed an active subscription first
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    from datetime import date as _date
    async with SessionLocal() as s:
        sub = Subscription(
            customer_id=seed_customer.id, product_id=milk_product.id,
            quantity=1, frequency=SubscriptionFrequency.DAILY,
            start_date=_date.today(), status=SubscriptionStatus.ACTIVE,
        )
        s.add(sub)
        await s.commit()
        sid = sub.id

    r = await client.post(
        f"/api/admin/subscriptions/{sid}/pause",
        headers=auth_headers(admin_user),
        json={"reason": "Holiday requested via support ticket"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "paused"

    # Verify audit row exists with differentiated action name
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(AuditLog).where(
                AuditLog.entity_type == "subscription",
                AuditLog.entity_id == str(sid),
            )
        )).scalars().all()
    actions = [r.action for r in rows]
    assert "subscription.admin_pause" in actions
    assert "subscription.pause" not in actions  # customer self-pause is different


# ==================== PG_TRGM SEARCH ====================

@pytest.mark.asyncio
async def test_search_pg_trgm(client, admin_user, seed_customer):
    # Seed customer has name "Amit Kulkarni"
    r1 = await client.get(
        "/api/admin/customers?search=kul",
        headers=auth_headers(admin_user),
    )
    assert r1.status_code == 200
    phones = [c["phone"] for c in r1.json()["items"]]
    assert seed_customer.phone in phones

    r2 = await client.get(
        "/api/admin/customers?search=zzznotexist",
        headers=auth_headers(admin_user),
    )
    assert r2.status_code == 200
    phones2 = [c["phone"] for c in r2.json()["items"]]
    assert seed_customer.phone not in phones2

    # phone search
    r3 = await client.get(
        f"/api/admin/customers?search={seed_customer.phone[-6:]}",
        headers=auth_headers(admin_user),
    )
    assert r3.status_code == 200
    assert seed_customer.phone in [c["phone"] for c in r3.json()["items"]]


# ==================== RBAC PARAMETRISED ====================

NEW_ENDPOINTS = [
    ("GET", "/api/admin/customers"),
    ("GET", "/api/admin/customers/{CID}"),
    ("GET", "/api/admin/customers/{CID}/subscriptions"),
    ("GET", "/api/admin/customers/{CID}/deliveries"),
    ("GET", "/api/admin/customers/{CID}/invoices"),
    ("GET", "/api/admin/customers/{CID}/wallet-transactions"),
    ("GET", "/api/admin/customers/{CID}/bottle-ledger"),
    ("GET", "/api/admin/customers/{CID}/audit-log"),
    ("POST", "/api/admin/customers/{CID}/wallet-adjustment"),
    ("POST", "/api/admin/customers/{CID}/bottle-adjustment"),
    ("POST", "/api/admin/customers/{CID}/approve"),
    ("POST", "/api/admin/customers/{CID}/reject"),
    ("POST", "/api/admin/customers/{CID}/revoke-tokens"),
]


@pytest.mark.asyncio
async def test_rbac_customer_cannot_access_new_endpoints(client, customer_user, seed_customer):
    payload = {
        "amount_paise": 1, "change": 1,
        "reason": "Attempting unauthorised access test",
    }
    for method, path in NEW_ENDPOINTS:
        url = path.replace("{CID}", str(seed_customer.id))
        if method == "GET":
            r = await client.get(url, headers=auth_headers(customer_user))
        else:
            r = await client.post(url, headers=auth_headers(customer_user), json=payload)
        assert r.status_code == 403, f"{method} {url} → {r.status_code}"


@pytest.mark.asyncio
async def test_rbac_delivery_cannot_access_new_endpoints(client, delivery_user, seed_customer):
    payload = {
        "amount_paise": 1, "change": 1,
        "reason": "Attempting unauthorised access test",
    }
    for method, path in NEW_ENDPOINTS:
        url = path.replace("{CID}", str(seed_customer.id))
        if method == "GET":
            r = await client.get(url, headers=auth_headers(delivery_user))
        else:
            r = await client.post(url, headers=auth_headers(delivery_user), json=payload)
        assert r.status_code == 403, f"{method} {url} → {r.status_code}"


# ==================== DETAIL ENDPOINT ====================

@pytest.mark.asyncio
async def test_customer_detail_shape(client, admin_user, seed_customer):
    r = await client.get(
        f"/api/admin/customers/{seed_customer.id}",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 200
    d = r.json()
    for k in (
        "id", "phone", "name", "wallet_balance_paise", "bottle_balance",
        "addresses", "active_subs_count", "total_subs_count",
        "invoice_count", "open_invoices_paise",
    ):
        assert k in d
    assert len(d["addresses"]) >= 1


@pytest.mark.asyncio
async def test_customer_detail_404(client, admin_user):
    r = await client.get(
        f"/api/admin/customers/{uuidm.uuid4()}",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 404
