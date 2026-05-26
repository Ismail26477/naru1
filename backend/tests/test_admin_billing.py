"""Phase 2B.6 — billing reconciliation, admin endpoints, money-safety guarantees.

Covers:
- Generation: first-time, idempotent (409), regenerate preserves payments,
  advisory-lock concurrency, per-customer atomicity on error.
- Price snapshots: invoice uses price_paise_snapshot (not current), mixed prices across month.
- Lifecycle edges: mid-month start, mid-month pause, mid-month cancel, zero-delivery month.
- Mark-paid: full / partial / wallet-insufficient-blocked / wallet-deducts.
- Apply-wallet-credit: atomic invoice.total↓ + wallet↓, invariant preserved.
- Post-billing override flag toggles after delivery admin override.
- Regenerate audit completeness (before_state has full old snapshot).
- RBAC: customer + delivery → 403 on every billing endpoint.
"""
from __future__ import annotations
import asyncio
import calendar
import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select, func, delete

from app.core.time_utils import now_utc, today_ist
from app.models.audit_log import AuditLog
from app.models.billing import (
    Invoice,
    InvoiceAdjustment,
    InvoiceAdjustmentKind,
    InvoiceLineItem,
    Payment,
    WalletTransaction,
)
from app.models.delivery import DeliveryOrder
from app.models.enums import (
    DeliveryOrderStatus,
    InvoiceStatus,
    PaymentMethod,
    PaymentStatus,
    ProductUnit,
    SubscriptionFrequency,
    SubscriptionStatus,
    UserRole,
)
from app.models.product import Product
from app.models.subscription import Subscription
from app.models.user import User

from tests.conftest import auth_headers


OK_REASON = "Test-generated billing reason ≥10 chars."


# ---------------- fixtures ----------------

async def _mk_customer(db, phone_suffix: int, wallet_paise: int = 0) -> User:
    u = User(
        phone=f"+919099{phone_suffix:06d}",
        name=f"Biller {phone_suffix}",
        role=UserRole.CUSTOMER,
        is_active=True,
        approved_at=now_utc(),
        wallet_balance_paise=wallet_paise,
    )
    db.add(u)
    await db.flush()
    # Seed wallet transaction to preserve invariant SUM(tx)==balance
    if wallet_paise:
        db.add(WalletTransaction(
            customer_id=u.id, change_paise=wallet_paise,
            reason="Test seed", balance_after_paise=wallet_paise,
        ))
        await db.flush()
    return u


async def _mk_product(db, price_paise: int = 3500, sku: str | None = None) -> Product:
    p = Product(
        name="Milk 500ml", sku=sku or f"MILK-{uuid.uuid4().hex[:6]}",
        unit=ProductUnit.LITRE, price_paise=price_paise,
        requires_bottle=True, active=True,
    )
    db.add(p)
    await db.flush()
    return p


async def _mk_sub(db, cust: User, prod: Product, start: date, status: SubscriptionStatus = SubscriptionStatus.ACTIVE) -> Subscription:
    s = Subscription(
        customer_id=cust.id, product_id=prod.id, quantity=1,
        frequency=SubscriptionFrequency.DAILY, start_date=start,
        status=status,
    )
    db.add(s)
    await db.flush()
    return s


async def _mk_order(
    db, *, cust: User, sub: Subscription, prod: Product,
    d: date, status: DeliveryOrderStatus = DeliveryOrderStatus.DELIVERED,
    qty: int = 1, unit_price_paise: int | None = None,
) -> DeliveryOrder:
    o = DeliveryOrder(
        customer_id=cust.id, subscription_id=sub.id, product_id=prod.id,
        delivery_date=d, quantity=qty,
        unit_price_paise=unit_price_paise if unit_price_paise is not None else prod.price_paise,
        status=status,
        delivered_quantity=qty if status == DeliveryOrderStatus.DELIVERED else None,
        delivered_at=now_utc() if status == DeliveryOrderStatus.DELIVERED else None,
    )
    db.add(o)
    await db.flush()
    return o


async def _seed_month(db, cust, sub, prod, year, month, days: list[int], *, status=DeliveryOrderStatus.DELIVERED, unit_price_paise: int | None = None):
    for d in days:
        await _mk_order(db, cust=cust, sub=sub, prod=prod, d=date(year, month, d), status=status, unit_price_paise=unit_price_paise)


# ---------------- tests ----------------


@pytest.mark.asyncio
async def test_generate_invoices_first_time(client, admin_user, db):
    """10 customers with daily deliveries in Feb 2025 → 10 invoices with correct totals."""
    prod = await _mk_product(db, price_paise=4000, sku="FT-MILK")
    customers: list[User] = []
    for i in range(10):
        c = await _mk_customer(db, phone_suffix=1000 + i)
        s = await _mk_sub(db, c, prod, date(2025, 2, 1))
        await _seed_month(db, c, s, prod, 2025, 2, list(range(1, 29)))  # 28 days × ₹40 = ₹1120
        customers.append(c)
    await db.commit()

    r = await client.post(
        "/api/admin/billing/generate",
        headers=auth_headers(admin_user),
        json={"year": 2025, "month": 2},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["created_count"] == 10
    assert data["regenerated_count"] == 0
    assert len(data["failed"]) == 0

    db.expunge_all()
    invs = (await db.execute(
        select(Invoice).where(Invoice.year == 2025, Invoice.month == 2)
    )).scalars().all()
    assert len(invs) == 10
    for inv in invs:
        assert inv.subtotal_paise == 28 * 4000
        assert inv.total_paise == inv.subtotal_paise
        assert inv.status == InvoiceStatus.ISSUED
        assert inv.due_date is not None


@pytest.mark.asyncio
async def test_generate_invoices_idempotent(client, admin_user, db):
    prod = await _mk_product(db, price_paise=4000, sku="IDEM-MILK")
    c = await _mk_customer(db, phone_suffix=2001)
    s = await _mk_sub(db, c, prod, date(2025, 3, 1))
    await _seed_month(db, c, s, prod, 2025, 3, list(range(1, 10)))
    await db.commit()

    r1 = await client.post("/api/admin/billing/generate", headers=auth_headers(admin_user),
                           json={"year": 2025, "month": 3})
    assert r1.status_code == 201
    r2 = await client.post("/api/admin/billing/generate", headers=auth_headers(admin_user),
                           json={"year": 2025, "month": 3})
    assert r2.status_code == 409
    assert r2.json()["detail"]["code"] == "invoices_already_exist"


@pytest.mark.asyncio
async def test_regenerate_invoices_preserves_payments(client, admin_user, db):
    """Payment on old invoice carries into regenerated invoice (same id)."""
    prod = await _mk_product(db, price_paise=5000, sku="RG-MILK")
    c = await _mk_customer(db, phone_suffix=3001)
    s = await _mk_sub(db, c, prod, date(2025, 4, 1))
    await _seed_month(db, c, s, prod, 2025, 4, list(range(1, 11)))  # 10 deliveries × ₹50 = ₹500
    await db.commit()

    await client.post("/api/admin/billing/generate", headers=auth_headers(admin_user),
                      json={"year": 2025, "month": 4})
    inv_before = (await db.execute(select(Invoice).where(Invoice.customer_id == c.id))).scalar_one()
    # Pay ₹250
    r = await client.post(
        f"/api/admin/invoices/{inv_before.id}/mark-paid",
        headers=auth_headers(admin_user),
        json={"amount_paise": 25000, "method": "cash", "reason": OK_REASON},
    )
    assert r.status_code == 201, r.text

    # Regenerate the month
    rg = await client.post(
        "/api/admin/billing/generate", headers=auth_headers(admin_user),
        json={"year": 2025, "month": 4, "regenerate": True, "reason": "Fixing billing — test regenerate"},
    )
    assert rg.status_code == 201, rg.text
    assert rg.json()["regenerated_count"] == 1

    db.expunge_all()
    inv_after = (await db.execute(select(Invoice).where(Invoice.id == inv_before.id))).scalar_one()
    assert inv_after.id == inv_before.id
    assert inv_after.regenerated_count == 1
    # Payment survives
    pays = (await db.execute(select(Payment).where(Payment.invoice_id == inv_before.id))).scalars().all()
    assert len(pays) == 1
    assert pays[0].amount_paise == 25000
    # amount_paid_paise recomputed
    assert inv_after.amount_paid_paise == 25000
    # partially paid status
    assert inv_after.status == InvoiceStatus.PARTIALLY_PAID


@pytest.mark.asyncio
async def test_invoice_uses_price_snapshot_not_current(client, admin_user, db):
    """Order snapshots old price; current product price change doesn't affect invoice subtotal."""
    prod = await _mk_product(db, price_paise=3000, sku="SNAP-MILK")
    c = await _mk_customer(db, phone_suffix=4001)
    s = await _mk_sub(db, c, prod, date(2025, 5, 1))
    # Orders locked at 3000 paise snapshot
    await _seed_month(db, c, s, prod, 2025, 5, list(range(1, 11)), unit_price_paise=3000)
    # Now product's current price changes
    prod.price_paise = 9999
    await db.commit()

    await client.post("/api/admin/billing/generate", headers=auth_headers(admin_user),
                      json={"year": 2025, "month": 5})
    inv = (await db.execute(select(Invoice).where(Invoice.customer_id == c.id))).scalar_one()
    assert inv.subtotal_paise == 10 * 3000, "Must bill at SNAPSHOT, not current price"


@pytest.mark.asyncio
async def test_invoice_mixed_prices_across_month(client, admin_user, db):
    """First 10 days at 3000, next 10 at 5000 → subtotal = 10×3000 + 10×5000 = 80_000."""
    prod = await _mk_product(db, price_paise=3000, sku="MIX-MILK")
    c = await _mk_customer(db, phone_suffix=5001)
    s = await _mk_sub(db, c, prod, date(2025, 6, 1))
    for d in range(1, 11):
        await _mk_order(db, cust=c, sub=s, prod=prod, d=date(2025, 6, d), unit_price_paise=3000)
    for d in range(11, 21):
        await _mk_order(db, cust=c, sub=s, prod=prod, d=date(2025, 6, d), unit_price_paise=5000)
    await db.commit()

    await client.post("/api/admin/billing/generate", headers=auth_headers(admin_user),
                      json={"year": 2025, "month": 6})
    inv = (await db.execute(select(Invoice).where(Invoice.customer_id == c.id))).scalar_one()
    assert inv.subtotal_paise == 10 * 3000 + 10 * 5000


@pytest.mark.asyncio
async def test_invoice_skipped_days_not_billed(client, admin_user, db):
    """25 delivered + 5 skipped → bill only delivered."""
    prod = await _mk_product(db, price_paise=4000, sku="SKIP-MILK")
    c = await _mk_customer(db, phone_suffix=6001)
    s = await _mk_sub(db, c, prod, date(2025, 7, 1))
    for d in range(1, 26):
        await _mk_order(db, cust=c, sub=s, prod=prod, d=date(2025, 7, d), status=DeliveryOrderStatus.DELIVERED)
    for d in range(26, 31):
        await _mk_order(db, cust=c, sub=s, prod=prod, d=date(2025, 7, d), status=DeliveryOrderStatus.SKIPPED, qty=1)
    await db.commit()

    await client.post("/api/admin/billing/generate", headers=auth_headers(admin_user),
                      json={"year": 2025, "month": 7})
    inv = (await db.execute(select(Invoice).where(Invoice.customer_id == c.id))).scalar_one()
    assert inv.subtotal_paise == 25 * 4000
    items = (await db.execute(select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == inv.id))).scalars().all()
    assert len(items) == 25


@pytest.mark.asyncio
async def test_invoice_mid_month_start(client, admin_user, db):
    """Customer subscribes on day 15 — invoice only covers days 15-30."""
    prod = await _mk_product(db, price_paise=4000, sku="MID-START-MILK")
    c = await _mk_customer(db, phone_suffix=7001)
    s = await _mk_sub(db, c, prod, date(2025, 8, 15))
    for d in range(15, 32):  # 15..31 = 17 days
        await _mk_order(db, cust=c, sub=s, prod=prod, d=date(2025, 8, d))
    await db.commit()

    await client.post("/api/admin/billing/generate", headers=auth_headers(admin_user),
                      json={"year": 2025, "month": 8})
    inv = (await db.execute(select(Invoice).where(Invoice.customer_id == c.id))).scalar_one()
    assert inv.subtotal_paise == 17 * 4000


@pytest.mark.asyncio
async def test_invoice_mid_month_pause(client, admin_user, db):
    """Paused day 10-20 → deliveries exist only on days 1-9 + 21-30 (20 days)."""
    prod = await _mk_product(db, price_paise=4000, sku="PAUSE-MILK")
    c = await _mk_customer(db, phone_suffix=8001)
    s = await _mk_sub(db, c, prod, date(2025, 9, 1))
    # Only delivered orders outside pause window
    for d in list(range(1, 10)) + list(range(21, 31)):
        await _mk_order(db, cust=c, sub=s, prod=prod, d=date(2025, 9, d))
    await db.commit()

    await client.post("/api/admin/billing/generate", headers=auth_headers(admin_user),
                      json={"year": 2025, "month": 9})
    inv = (await db.execute(select(Invoice).where(Invoice.customer_id == c.id))).scalar_one()
    assert inv.subtotal_paise == 19 * 4000  # 9 + 10


@pytest.mark.asyncio
async def test_zero_delivery_month_no_invoice(client, admin_user, db):
    """Customer with zero delivered orders → NO invoice created (chosen behaviour)."""
    prod = await _mk_product(db, price_paise=4000, sku="ZERO-MILK")
    c = await _mk_customer(db, phone_suffix=9001)
    s = await _mk_sub(db, c, prod, date(2025, 10, 1))
    for d in range(1, 6):
        await _mk_order(db, cust=c, sub=s, prod=prod, d=date(2025, 10, d), status=DeliveryOrderStatus.SKIPPED)
    await db.commit()

    r = await client.post("/api/admin/billing/generate", headers=auth_headers(admin_user),
                          json={"year": 2025, "month": 10})
    assert r.status_code == 201
    assert r.json()["skipped_customers"] >= 1
    invs = (await db.execute(select(Invoice).where(Invoice.customer_id == c.id))).scalars().all()
    assert len(invs) == 0


@pytest.mark.asyncio
async def test_mark_paid_full(client, admin_user, db):
    prod = await _mk_product(db, price_paise=5000, sku="FULLPAY-MILK")
    c = await _mk_customer(db, phone_suffix=10001)
    s = await _mk_sub(db, c, prod, date(2025, 11, 1))
    for d in range(1, 11):
        await _mk_order(db, cust=c, sub=s, prod=prod, d=date(2025, 11, d))
    await db.commit()
    await client.post("/api/admin/billing/generate", headers=auth_headers(admin_user),
                      json={"year": 2025, "month": 11})
    inv = (await db.execute(select(Invoice).where(Invoice.customer_id == c.id))).scalar_one()

    r = await client.post(
        f"/api/admin/invoices/{inv.id}/mark-paid",
        headers=auth_headers(admin_user),
        json={"amount_paise": 50000, "method": "cash", "reason": OK_REASON, "reference": "RCPT-001"},
    )
    assert r.status_code == 201
    db.expunge_all()
    inv2 = (await db.execute(select(Invoice).where(Invoice.id == inv.id))).scalar_one()
    assert inv2.status == InvoiceStatus.PAID
    assert inv2.amount_paid_paise == 50000
    pays = (await db.execute(select(Payment).where(Payment.invoice_id == inv.id))).scalars().all()
    assert len(pays) == 1 and pays[0].status == PaymentStatus.SUCCESS


@pytest.mark.asyncio
async def test_mark_paid_partial(client, admin_user, db):
    prod = await _mk_product(db, price_paise=5000, sku="PARTPAY-MILK")
    c = await _mk_customer(db, phone_suffix=11001)
    s = await _mk_sub(db, c, prod, date(2025, 12, 1))
    for d in range(1, 11):
        await _mk_order(db, cust=c, sub=s, prod=prod, d=date(2025, 12, d))
    await db.commit()
    await client.post("/api/admin/billing/generate", headers=auth_headers(admin_user),
                      json={"year": 2025, "month": 12})
    inv = (await db.execute(select(Invoice).where(Invoice.customer_id == c.id))).scalar_one()

    r = await client.post(
        f"/api/admin/invoices/{inv.id}/mark-paid",
        headers=auth_headers(admin_user),
        json={"amount_paise": 20000, "method": "upi", "reason": OK_REASON},
    )
    assert r.status_code == 201
    db.expunge_all()
    inv2 = (await db.execute(select(Invoice).where(Invoice.id == inv.id))).scalar_one()
    assert inv2.status == InvoiceStatus.PARTIALLY_PAID
    assert inv2.amount_paid_paise == 20000


@pytest.mark.asyncio
async def test_mark_paid_wallet_insufficient_blocked(client, admin_user, db):
    """Wallet balance 1000, invoice due 50000, method=wallet without force → 400."""
    prod = await _mk_product(db, price_paise=5000, sku="WINS-MILK")
    c = await _mk_customer(db, phone_suffix=12001, wallet_paise=1000)
    s = await _mk_sub(db, c, prod, date(2026, 1, 1))
    for d in range(1, 11):
        await _mk_order(db, cust=c, sub=s, prod=prod, d=date(2026, 1, d))
    await db.commit()
    await client.post("/api/admin/billing/generate", headers=auth_headers(admin_user),
                      json={"year": 2026, "month": 1})
    inv = (await db.execute(select(Invoice).where(Invoice.customer_id == c.id))).scalar_one()

    r = await client.post(
        f"/api/admin/invoices/{inv.id}/mark-paid",
        headers=auth_headers(admin_user),
        json={"amount_paise": 50000, "method": "wallet", "reason": OK_REASON},
    )
    assert r.status_code == 400
    # No payment row created
    pays = (await db.execute(select(Payment).where(Payment.invoice_id == inv.id))).scalars().all()
    assert len(pays) == 0
    # Wallet unchanged
    c2 = (await db.execute(select(User).where(User.id == c.id))).scalar_one()
    db.expunge(c2)
    c3 = (await db.execute(select(User).where(User.id == c.id))).scalar_one()
    assert c3.wallet_balance_paise == 1000


@pytest.mark.asyncio
async def test_mark_paid_wallet_deducts(client, admin_user, db):
    """Wallet has enough, method=wallet → wallet debited, invariant holds."""
    prod = await _mk_product(db, price_paise=5000, sku="WOK-MILK")
    c = await _mk_customer(db, phone_suffix=13001, wallet_paise=100000)
    s = await _mk_sub(db, c, prod, date(2026, 2, 1))
    for d in range(1, 11):
        await _mk_order(db, cust=c, sub=s, prod=prod, d=date(2026, 2, d))
    await db.commit()
    await client.post("/api/admin/billing/generate", headers=auth_headers(admin_user),
                      json={"year": 2026, "month": 2})
    inv = (await db.execute(select(Invoice).where(Invoice.customer_id == c.id))).scalar_one()

    r = await client.post(
        f"/api/admin/invoices/{inv.id}/mark-paid",
        headers=auth_headers(admin_user),
        json={"amount_paise": 50000, "method": "wallet", "reason": OK_REASON},
    )
    assert r.status_code == 201, r.text
    db.expunge_all()
    c2 = (await db.execute(select(User).where(User.id == c.id))).scalar_one()
    assert c2.wallet_balance_paise == 50000
    # Invariant: SUM(wallet_transactions) == user.wallet_balance
    ledger_sum = (await db.execute(
        select(func.coalesce(func.sum(WalletTransaction.change_paise), 0))
        .where(WalletTransaction.customer_id == c.id)
    )).scalar_one()
    assert int(ledger_sum) == c2.wallet_balance_paise


@pytest.mark.asyncio
async def test_apply_wallet_credit(client, admin_user, db):
    """Apply ₹5 credit → invoice.total ↓, wallet ↓, both atomic."""
    prod = await _mk_product(db, price_paise=5000, sku="AWC-MILK")
    c = await _mk_customer(db, phone_suffix=14001, wallet_paise=100000)
    s = await _mk_sub(db, c, prod, date(2026, 3, 1))
    for d in range(1, 11):
        await _mk_order(db, cust=c, sub=s, prod=prod, d=date(2026, 3, d))
    await db.commit()
    await client.post("/api/admin/billing/generate", headers=auth_headers(admin_user),
                      json={"year": 2026, "month": 3})
    inv = (await db.execute(select(Invoice).where(Invoice.customer_id == c.id))).scalar_one()
    before_total = inv.total_paise

    r = await client.post(
        f"/api/admin/invoices/{inv.id}/apply-wallet-credit",
        headers=auth_headers(admin_user),
        json={"amount_paise": 500, "reason": OK_REASON},
    )
    assert r.status_code == 201
    db.expunge_all()
    inv2 = (await db.execute(select(Invoice).where(Invoice.id == inv.id))).scalar_one()
    assert inv2.total_paise == before_total - 500
    c2 = (await db.execute(select(User).where(User.id == c.id))).scalar_one()
    assert c2.wallet_balance_paise == 100000 - 500
    # Adjustment row recorded
    adj = (await db.execute(select(InvoiceAdjustment).where(InvoiceAdjustment.invoice_id == inv.id))).scalars().all()
    assert len(adj) == 1
    assert adj[0].kind == InvoiceAdjustmentKind.WALLET_CREDIT
    assert adj[0].amount_paise == -500


@pytest.mark.asyncio
async def test_generate_concurrency(client, admin_user, db):
    """Two simultaneous generate calls — advisory lock → one succeeds, other 409."""
    prod = await _mk_product(db, price_paise=4000, sku="CONC-MILK")
    c = await _mk_customer(db, phone_suffix=15001)
    s = await _mk_sub(db, c, prod, date(2024, 1, 1))
    for d in range(1, 11):
        await _mk_order(db, cust=c, sub=s, prod=prod, d=date(2024, 1, d))
    await db.commit()

    # Note: httpx AsyncClient in the test harness commits the first call before the
    # second starts unless we interleave them; we simulate by firing both from asyncio.gather.
    body = {"year": 2024, "month": 1}
    r1, r2 = await asyncio.gather(
        client.post("/api/admin/billing/generate", headers=auth_headers(admin_user), json=body),
        client.post("/api/admin/billing/generate", headers=auth_headers(admin_user), json=body),
    )
    codes = sorted([r1.status_code, r2.status_code])
    # The second request either sees the already-created rows (409 invoices_already_exist)
    # OR is blocked by the advisory lock (409 billing_generation_locked).
    assert codes[0] == 201
    assert codes[1] == 409


@pytest.mark.asyncio
async def test_regenerate_audit_completeness(client, admin_user, db):
    """before_state on regenerate audit includes old invoice snapshot + line items."""
    prod = await _mk_product(db, price_paise=4000, sku="RAC-MILK")
    c = await _mk_customer(db, phone_suffix=16001)
    s = await _mk_sub(db, c, prod, date(2024, 2, 1))
    for d in range(1, 11):
        await _mk_order(db, cust=c, sub=s, prod=prod, d=date(2024, 2, d))
    await db.commit()
    await client.post("/api/admin/billing/generate", headers=auth_headers(admin_user),
                      json={"year": 2024, "month": 2})
    await client.post(
        "/api/admin/billing/generate", headers=auth_headers(admin_user),
        json={"year": 2024, "month": 2, "regenerate": True, "reason": "Regenerate audit test reason"},
    )
    inv = (await db.execute(select(Invoice).where(Invoice.customer_id == c.id))).scalar_one()
    audit = (await db.execute(
        select(AuditLog).where(AuditLog.action == "invoice.regenerate",
                               AuditLog.entity_id == str(inv.id))
        .order_by(AuditLog.created_at.desc()).limit(1)
    )).scalar_one()
    assert audit.before_state is not None
    assert audit.before_state.get("total_paise") == 10 * 4000
    assert isinstance(audit.before_state.get("line_items"), list)
    assert len(audit.before_state["line_items"]) == 10


@pytest.mark.asyncio
async def test_post_billing_flag_on_override(client, admin_user, db):
    """Generate invoice, then override a delivered order → has_post_billing_adjustments flips."""
    prod = await _mk_product(db, price_paise=4000, sku="PBF-MILK", )
    # Override check works on dates within 7 days of today; use today_ist() - offsets
    today = today_ist()
    month_start = date(today.year, today.month, 1)
    c = await _mk_customer(db, phone_suffix=17001)
    s = await _mk_sub(db, c, prod, month_start)
    # Create orders for days covering up to yesterday
    o_today_minus_2 = await _mk_order(db, cust=c, sub=s, prod=prod, d=today - timedelta(days=2))
    # And another delivered order in the month
    if today.day > 3:
        await _mk_order(db, cust=c, sub=s, prod=prod, d=today - timedelta(days=3))
    await db.commit()

    r = await client.post("/api/admin/billing/generate", headers=auth_headers(admin_user),
                          json={"year": today.year, "month": today.month})
    assert r.status_code == 201

    # Override the order (delivered → skipped)
    ov = await client.post(
        f"/api/admin/delivery-orders/{o_today_minus_2.id}/override",
        headers=auth_headers(admin_user),
        json={"status": "skipped", "reason": "Post-billing flag test override"},
    )
    assert ov.status_code in (200, 201), ov.text

    db.expunge_all()
    inv = (await db.execute(
        select(Invoice).where(Invoice.customer_id == c.id,
                              Invoice.year == today.year, Invoice.month == today.month)
    )).scalar_one()
    assert inv.has_post_billing_adjustments is True
    adj = (await db.execute(
        select(InvoiceAdjustment).where(
            InvoiceAdjustment.invoice_id == inv.id,
            InvoiceAdjustment.kind == InvoiceAdjustmentKind.OVERRIDE_ADJUSTMENT,
        )
    )).scalars().all()
    assert len(adj) >= 1
    # Override removed one delivered day → negative money delta
    assert adj[0].amount_paise < 0


@pytest.mark.asyncio
async def test_rbac_billing(client, customer_user, delivery_user, admin_user, db):
    """Customer + delivery get 403 on every admin billing route."""
    # Need a real invoice id for endpoints that take one
    prod = await _mk_product(db, price_paise=4000, sku="RBAC-MILK")
    c = await _mk_customer(db, phone_suffix=18001)
    s = await _mk_sub(db, c, prod, date(2023, 1, 1))
    await _mk_order(db, cust=c, sub=s, prod=prod, d=date(2023, 1, 1))
    await db.commit()
    await client.post("/api/admin/billing/generate", headers=auth_headers(admin_user),
                      json={"year": 2023, "month": 1})
    inv = (await db.execute(select(Invoice).where(Invoice.customer_id == c.id))).scalar_one()

    calls = [
        ("GET", "/api/admin/billing/status?year=2023&month=1", None),
        ("POST", "/api/admin/billing/generate", {"year": 2023, "month": 2}),
        ("GET", "/api/admin/invoices", None),
        ("GET", f"/api/admin/invoices/{inv.id}", None),
        ("POST", f"/api/admin/invoices/{inv.id}/mark-paid",
         {"amount_paise": 100, "method": "cash", "reason": OK_REASON}),
        ("POST", f"/api/admin/invoices/{inv.id}/regenerate", {"reason": OK_REASON}),
        ("POST", f"/api/admin/invoices/{inv.id}/apply-wallet-credit",
         {"amount_paise": 100, "reason": OK_REASON}),
        ("GET", "/api/admin/billing/overdue", None),
        ("GET", "/api/admin/billing/register?year=2023&month=1", None),
    ]
    for method, url, body in calls:
        for user in (customer_user, delivery_user):
            if method == "GET":
                r = await client.get(url, headers=auth_headers(user))
            else:
                r = await client.post(url, headers=auth_headers(user), json=body)
            assert r.status_code == 403, f"{method} {url} as {user.role} returned {r.status_code}"


@pytest.mark.asyncio
async def test_billing_atomicity_failed_customer(client, admin_user, db, monkeypatch):
    """If one customer's generation raises, others still complete; failure recorded."""
    prod = await _mk_product(db, price_paise=4000, sku="ATOM-MILK")
    c1 = await _mk_customer(db, phone_suffix=19001)
    c2 = await _mk_customer(db, phone_suffix=19002)
    for cust in (c1, c2):
        s = await _mk_sub(db, cust, prod, date(2023, 5, 1))
        for d in range(1, 6):
            await _mk_order(db, cust=cust, sub=s, prod=prod, d=date(2023, 5, d))
    await db.commit()

    from app.services import billing_admin_service as bas
    original = bas._compute_customer_subtotal
    first_cust_id = c1.id

    async def flaky(db_, cid, y, m):
        if cid == first_cust_id:
            raise RuntimeError("simulated failure for first customer")
        return await original(db_, cid, y, m)
    monkeypatch.setattr(bas, "_compute_customer_subtotal", flaky)

    r = await client.post("/api/admin/billing/generate", headers=auth_headers(admin_user),
                          json={"year": 2023, "month": 5})
    assert r.status_code == 201
    data = r.json()
    # 1 created, 1 failed
    assert data["created_count"] == 1
    assert len(data["failed"]) == 1
    assert data["failed"][0]["customer_id"] == str(c1.id)


@pytest.mark.asyncio
async def test_billing_status_and_register(client, admin_user, db):
    """Aggregated status + flat register export rows."""
    prod = await _mk_product(db, price_paise=4000, sku="STAT-MILK")
    c = await _mk_customer(db, phone_suffix=20001)
    s = await _mk_sub(db, c, prod, date(2023, 6, 1))
    for d in range(1, 11):
        await _mk_order(db, cust=c, sub=s, prod=prod, d=date(2023, 6, d))
    await db.commit()
    await client.post("/api/admin/billing/generate", headers=auth_headers(admin_user),
                      json={"year": 2023, "month": 6})

    r = await client.get("/api/admin/billing/status?year=2023&month=6", headers=auth_headers(admin_user))
    assert r.status_code == 200
    st = r.json()
    assert st["invoice_count"] == 1
    assert st["total_billed_paise"] == 10 * 4000
    assert st["total_collected_paise"] == 0
    assert st["outstanding_paise"] == 10 * 4000

    r2 = await client.get("/api/admin/billing/register?year=2023&month=6", headers=auth_headers(admin_user))
    assert r2.status_code == 200
    reg = r2.json()
    assert len(reg) == 1
    assert reg[0]["total_paise"] == 10 * 4000
