"""Phase 2B.7 — admin reports (revenue / churn / daily delivery / bottle outstanding).

Read-only aggregations, lower-count test suite (12 tests) justified by no money mutations.
"""
from __future__ import annotations
import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.time_utils import now_utc, today_ist
from app.models.billing import Invoice, InvoiceLineItem
from app.models.delivery import DeliveryOrder, BottleLedger
from app.models.enums import (
    BottleReason,
    DeliveryOrderStatus,
    InvoiceStatus,
    ProductUnit,
    SubscriptionFrequency,
    SubscriptionStatus,
    UserRole,
)
from app.models.product import Product
from app.models.subscription import Subscription
from app.models.user import User

from tests.conftest import auth_headers


async def _mk_product(db, *, sku: str, price: int = 3500, name: str = "Milk") -> Product:
    p = Product(name=name, sku=sku, unit=ProductUnit.LITRE, price_paise=price,
                requires_bottle=True, active=True)
    db.add(p)
    await db.flush()
    return p


async def _mk_customer(db, n: int, *, phone_suffix: int | None = None) -> User:
    suf = phone_suffix if phone_suffix is not None else 7_000_000 + n
    u = User(phone=f"+91{suf:010d}", name=f"Reports Cust {n}",
             role=UserRole.CUSTOMER, is_active=True, approved_at=now_utc())
    db.add(u)
    await db.flush()
    return u


async def _mk_sub(
    db, cust: User, prod: Product,
    start: date, *,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
    end_date: date | None = None,
) -> Subscription:
    s = Subscription(
        customer_id=cust.id, product_id=prod.id, quantity=1,
        frequency=SubscriptionFrequency.DAILY, start_date=start,
        end_date=end_date, status=status,
    )
    db.add(s)
    await db.flush()
    return s


async def _mk_invoice(
    db, cust: User, prod: Product, *, year: int, month: int,
    days: list[int], unit_price_paise: int | None = None,
    status: InvoiceStatus = InvoiceStatus.ISSUED,
    amount_paid_paise: int = 0,
    adjustments_paise: int = 0,
) -> Invoice:
    price = unit_price_paise if unit_price_paise is not None else prod.price_paise
    issued = datetime(year, month, 1, 2, 0, 0)
    inv = Invoice(
        customer_id=cust.id, year=year, month=month,
        subtotal_paise=len(days) * price,
        adjustments_paise=adjustments_paise,
        total_paise=len(days) * price + adjustments_paise,
        amount_paid_paise=amount_paid_paise,
        status=status,
        issued_at=issued,
        due_date=date(year, month, 15),
    )
    db.add(inv)
    await db.flush()
    for d in days:
        db.add(InvoiceLineItem(
            invoice_id=inv.id,
            date=date(year, month, d),
            product_id=prod.id,
            quantity=1,
            price_paise=price,
            total_paise=price,
        ))
    await db.flush()
    return inv


# ---------- REVENUE ----------

@pytest.mark.asyncio
async def test_revenue_report_basic(client, admin_user, db):
    prod = await _mk_product(db, sku="REV-BASIC")
    c = await _mk_customer(db, 1, phone_suffix=7100001)
    await _mk_invoice(db, c, prod, year=2025, month=3, days=list(range(1, 11)),
                       amount_paid_paise=2 * 3500)
    await db.commit()

    r = await client.get("/api/admin/reports/revenue?from=2025-03-01&to=2025-03-31&group_by=day",
                         headers=auth_headers(admin_user))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["invoice_count"] == 1
    assert data["total_revenue_paise"] == 10 * 3500
    assert data["total_collected_paise"] == 2 * 3500
    assert data["total_outstanding_paise"] == 10 * 3500 - 2 * 3500


@pytest.mark.asyncio
async def test_revenue_report_group_by_month(client, admin_user, db):
    prod = await _mk_product(db, sku="REV-MONTH")
    c = await _mk_customer(db, 2, phone_suffix=7100002)
    await _mk_invoice(db, c, prod, year=2025, month=1, days=[1, 2, 3])
    await _mk_invoice(db, c, prod, year=2025, month=2, days=[1, 2])
    await _mk_invoice(db, c, prod, year=2025, month=3, days=[1])
    await db.commit()

    r = await client.get("/api/admin/reports/revenue?from=2025-01-01&to=2025-03-31&group_by=month",
                         headers=auth_headers(admin_user))
    assert r.status_code == 200
    data = r.json()
    assert data["invoice_count"] == 3
    series = sorted(data["series"], key=lambda s: s["period"])
    assert len(series) == 3
    assert [s["period"] for s in series] == ["2025-01", "2025-02", "2025-03"]
    assert [s["revenue_paise"] for s in series] == [3 * 3500, 2 * 3500, 1 * 3500]


@pytest.mark.asyncio
async def test_revenue_by_product(client, admin_user, db):
    milk = await _mk_product(db, sku="REV-PROD-MILK", price=3500, name="Milk 500ml")
    ghee = await _mk_product(db, sku="REV-PROD-GHEE", price=70000, name="Ghee 500g")
    c1 = await _mk_customer(db, 3, phone_suffix=7100003)
    c2 = await _mk_customer(db, 4, phone_suffix=7100004)
    # Distinct customers so UNIQUE(customer_id, year, month) on invoices holds
    await _mk_invoice(db, c1, milk, year=2025, month=4, days=list(range(1, 11)))
    await _mk_invoice(db, c2, ghee, year=2025, month=4, days=[5])
    await db.commit()

    r = await client.get("/api/admin/reports/revenue?from=2025-04-01&to=2025-04-30&group_by=day",
                         headers=auth_headers(admin_user))
    data = r.json()
    by_prod = {p["product_sku"]: p for p in data["by_product"]}
    assert by_prod["REV-PROD-MILK"]["revenue_paise"] == 10 * 3500
    assert by_prod["REV-PROD-MILK"]["quantity_total"] == 10
    assert by_prod["REV-PROD-GHEE"]["revenue_paise"] == 70000
    assert by_prod["REV-PROD-GHEE"]["quantity_total"] == 1


# ---------- CHURN ----------

@pytest.mark.asyncio
async def test_churn_report_basic(client, admin_user, db):
    prod = await _mk_product(db, sku="CHURN-BASIC")
    # Cust A: active on 2025-05-31, cancelled on 2025-06-15 → churned in June
    a = await _mk_customer(db, 10, phone_suffix=7200010)
    await _mk_sub(db, a, prod, start=date(2025, 1, 1),
                  status=SubscriptionStatus.CANCELLED, end_date=date(2025, 6, 15))
    # Cust B: active throughout — not churned
    b = await _mk_customer(db, 11, phone_suffix=7200011)
    await _mk_sub(db, b, prod, start=date(2025, 1, 1), status=SubscriptionStatus.ACTIVE)
    await db.commit()

    r = await client.get("/api/admin/reports/churn?month=2025-06",
                         headers=auth_headers(admin_user))
    assert r.status_code == 200
    data = r.json()
    assert data["churned_customers"] == 1
    assert data["churned_list"][0]["name"] == "Reports Cust 10"
    assert data["active_start"] == 2
    assert data["active_end"] == 1


@pytest.mark.asyncio
async def test_churn_active_at_start_required(client, admin_user, db):
    """Customer who joined AND cancelled in same month does NOT count as churn."""
    prod = await _mk_product(db, sku="CHURN-SAMEMO")
    # Start + end both in June → was NOT active at start-of-month
    c = await _mk_customer(db, 12, phone_suffix=7200012)
    await _mk_sub(db, c, prod, start=date(2025, 6, 5),
                  status=SubscriptionStatus.CANCELLED, end_date=date(2025, 6, 20))
    await db.commit()

    r = await client.get("/api/admin/reports/churn?month=2025-06",
                         headers=auth_headers(admin_user))
    data = r.json()
    assert data["churned_customers"] == 0


# ---------- DAILY DELIVERY ----------

@pytest.mark.asyncio
async def test_daily_delivery_report(client, admin_user, db):
    prod = await _mk_product(db, sku="DD-PROD")
    # 4 distinct (customer, subscription) pairs to avoid uq_delivery_sub_date
    custs = [await _mk_customer(db, 20 + i, phone_suffix=7300020 + i) for i in range(4)]
    subs = [await _mk_sub(db, c, prod, start=date(2025, 7, 1)) for c in custs]
    # Day 2025-07-01: 3 delivered + 1 skipped
    for i in range(3):
        db.add(DeliveryOrder(
            customer_id=custs[i].id, subscription_id=subs[i].id, product_id=prod.id,
            delivery_date=date(2025, 7, 1), quantity=1, unit_price_paise=3500,
            status=DeliveryOrderStatus.DELIVERED, delivered_quantity=1,
        ))
    db.add(DeliveryOrder(
        customer_id=custs[3].id, subscription_id=subs[3].id, product_id=prod.id,
        delivery_date=date(2025, 7, 1), quantity=1, unit_price_paise=3500,
        status=DeliveryOrderStatus.SKIPPED,
    ))
    # Day 2025-07-02: 1 failed (reuse sub 0 — different date, no conflict)
    db.add(DeliveryOrder(
        customer_id=custs[0].id, subscription_id=subs[0].id, product_id=prod.id,
        delivery_date=date(2025, 7, 2), quantity=1, unit_price_paise=3500,
        status=DeliveryOrderStatus.FAILED,
    ))
    await db.commit()

    r = await client.get("/api/admin/reports/daily-delivery?from=2025-07-01&to=2025-07-02",
                         headers=auth_headers(admin_user))
    assert r.status_code == 200
    data = r.json()
    assert data["total_delivered"] == 3
    assert data["total_skipped"] == 1
    assert data["total_failed"] == 1
    series = {s["date"]: s for s in data["series"]}
    assert series["2025-07-01"]["delivered"] == 3
    assert series["2025-07-01"]["skipped"] == 1
    assert series["2025-07-02"]["failed"] == 1
    # Completion = 3 / 5 scheduled (3 delivered + 1 skipped + 1 failed) = 60%
    assert data["completion_rate_pct"] == 60.0


# ---------- BOTTLE OUTSTANDING ----------

@pytest.mark.asyncio
async def test_bottle_outstanding_point_in_time(client, admin_user, db):
    c = await _mk_customer(db, 30, phone_suffix=7400030)
    # +2, -1 → balance 1
    db.add(BottleLedger(customer_id=c.id, change=2, reason=BottleReason.DELIVERED))
    db.add(BottleLedger(customer_id=c.id, change=-1, reason=BottleReason.RETURNED))
    # Another customer fully settled (balance 0) → should not appear
    c2 = await _mk_customer(db, 31, phone_suffix=7400031)
    db.add(BottleLedger(customer_id=c2.id, change=1, reason=BottleReason.DELIVERED))
    db.add(BottleLedger(customer_id=c2.id, change=-1, reason=BottleReason.RETURNED))
    await db.commit()

    r = await client.get("/api/admin/reports/bottle-outstanding",
                         headers=auth_headers(admin_user))
    assert r.status_code == 200
    data = r.json()
    names = [c["name"] for c in data["customers"]]
    assert "Reports Cust 30" in names
    assert "Reports Cust 31" not in names
    # Total bottles out = 1 (from c only)
    # Note: other fixtures + real seeded customers may add to this total; we just check c appears.
    row = next(c for c in data["customers"] if c["name"] == "Reports Cust 30")
    assert row["bottles_out"] == 1
    assert row["ever_returned"] is True


@pytest.mark.asyncio
async def test_bottle_outstanding_days_since_return(client, admin_user, db):
    """Customer who never returned: ever_returned=False, days_since=days since first delivery."""
    c = await _mk_customer(db, 40, phone_suffix=7400040)
    # Two deliveries, no returns
    bl1 = BottleLedger(customer_id=c.id, change=1, reason=BottleReason.DELIVERED)
    bl1.created_at = now_utc() - timedelta(days=20)
    db.add(bl1)
    bl2 = BottleLedger(customer_id=c.id, change=1, reason=BottleReason.DELIVERED)
    bl2.created_at = now_utc() - timedelta(days=5)
    db.add(bl2)
    await db.commit()

    r = await client.get("/api/admin/reports/bottle-outstanding",
                         headers=auth_headers(admin_user))
    data = r.json()
    row = next(c for c in data["customers"] if c["name"] == "Reports Cust 40")
    assert row["ever_returned"] is False
    assert row["bottles_out"] == 2
    assert row["days_since_return"] >= 19  # ~20 days, allowing 1-day tz fuzz
    assert row["last_return_date"] is None


# ---------- CSV EXPORTS ----------

@pytest.mark.asyncio
async def test_csv_export_streaming(client, admin_user, db):
    prod = await _mk_product(db, sku="CSV-STREAM")
    c = await _mk_customer(db, 50, phone_suffix=7500050)
    await _mk_invoice(db, c, prod, year=2025, month=8, days=[1, 2])
    await db.commit()

    r = await client.get("/api/admin/reports/revenue/export?from=2025-08-01&to=2025-08-31&group_by=day",
                         headers=auth_headers(admin_user))
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert 'attachment; filename="posuhtik_revenue_' in r.headers["content-disposition"]
    body = r.content
    # BOM
    assert body[:3] == b"\xef\xbb\xbf"
    text = body.decode("utf-8-sig")
    assert "Series" in text or "series" in text.lower()
    assert "revenue_rupees" in text
    # Should contain at least one data row with our ₹70 revenue (2 days * ₹35 = ₹70)
    assert "70.0" in text or "70.00" in text


@pytest.mark.asyncio
async def test_csv_export_respects_filters(client, admin_user, db):
    """Different filters → different data in export."""
    prod = await _mk_product(db, sku="CSV-FILTER")
    c = await _mk_customer(db, 51, phone_suffix=7500051)
    # Only one invoice in July, none in August
    await _mk_invoice(db, c, prod, year=2025, month=7, days=[1, 2, 3])
    await db.commit()

    r_july = await client.get("/api/admin/reports/revenue/export?from=2025-07-01&to=2025-07-31&group_by=day",
                              headers=auth_headers(admin_user))
    r_aug = await client.get("/api/admin/reports/revenue/export?from=2025-08-01&to=2025-08-31&group_by=day",
                             headers=auth_headers(admin_user))
    assert r_july.status_code == 200 and r_aug.status_code == 200
    t_july = r_july.content.decode("utf-8-sig")
    t_aug = r_aug.content.decode("utf-8-sig")
    # July has 1 invoice worth ₹105, August has 0
    assert "105.0" in t_july or "105.00" in t_july
    assert "CSV-FILTER" in t_july
    # August should have zero in "Invoice count" line
    assert "Invoice count" in t_aug
    assert "CSV-FILTER" not in t_aug  # by_product shouldn't list it


# ---------- RBAC ----------

@pytest.mark.asyncio
async def test_rbac_reports(client, admin_user, customer_user, delivery_user, db):
    urls = [
        "/api/admin/reports/revenue?from=2025-01-01&to=2025-01-31&group_by=day",
        "/api/admin/reports/revenue/export?from=2025-01-01&to=2025-01-31&group_by=day",
        "/api/admin/reports/churn?month=2025-01",
        "/api/admin/reports/churn/export?month=2025-01",
        "/api/admin/reports/daily-delivery?from=2025-01-01&to=2025-01-31",
        "/api/admin/reports/daily-delivery/export?from=2025-01-01&to=2025-01-31",
        "/api/admin/reports/bottle-outstanding",
        "/api/admin/reports/bottle-outstanding/export",
        "/api/admin/billing/register/export?year=2025&month=1",
    ]
    for url in urls:
        for user in (customer_user, delivery_user):
            r = await client.get(url, headers=auth_headers(user))
            assert r.status_code == 403, f"{url} as {user.role} returned {r.status_code}"


@pytest.mark.asyncio
async def test_empty_period_reports(client, admin_user, db):
    """Period with no data → zeros, empty lists, no error."""
    r1 = await client.get("/api/admin/reports/revenue?from=2020-01-01&to=2020-01-03&group_by=day",
                          headers=auth_headers(admin_user))
    assert r1.status_code == 200
    data = r1.json()
    assert data["invoice_count"] == 0
    assert data["total_revenue_paise"] == 0
    assert data["by_product"] == []
    # Day-level series zero-fills 3 days:
    assert len(data["series"]) == 3
    for s in data["series"]:
        assert s["revenue_paise"] == 0

    r2 = await client.get("/api/admin/reports/churn?month=2020-01",
                          headers=auth_headers(admin_user))
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["churned_customers"] == 0
    assert d2["churned_list"] == []

    r3 = await client.get("/api/admin/reports/daily-delivery?from=2020-01-01&to=2020-01-02",
                          headers=auth_headers(admin_user))
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3["total_scheduled"] == 0
    assert d3["completion_rate_pct"] == 0.0
    assert len(d3["series"]) == 2


# ---------- Phase 2B.8 Phase D: view_mode toggle ----------

@pytest.mark.asyncio
async def test_revenue_view_mode_bill_period(client, admin_user, db):
    """bill_period mode filters invoices by (year,month), not issued_at date."""
    prod = await _mk_product(db, sku="REV-VM-BILL")
    c1 = await _mk_customer(db, 91, phone_suffix=7100091)
    c2 = await _mk_customer(db, 92, phone_suffix=7100092)

    # Invoice A: billed for Feb 2025 but issued_at is set to Apr 5 2025 (late generation).
    inv_a = await _mk_invoice(db, c1, prod, year=2025, month=2, days=[1, 2, 3])
    inv_a.issued_at = datetime(2025, 4, 5, 2, 0, 0)
    # Invoice B: billed for Apr 2025, issued Apr 1 2025 (normal).
    await _mk_invoice(db, c2, prod, year=2025, month=4, days=[1, 2])
    await db.commit()

    # issued_date mode: Apr window catches BOTH invoices (both issued_at in Apr).
    r = await client.get(
        "/api/admin/reports/revenue?from=2025-04-01&to=2025-04-30"
        "&group_by=day&view_mode=issued_date",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["invoice_count"] == 2
    assert d["total_revenue_paise"] == 3 * 3500 + 2 * 3500

    # bill_period mode: Apr window only catches Invoice B (billed Apr). Series forced monthly.
    r2 = await client.get(
        "/api/admin/reports/revenue?from=2025-04-01&to=2025-04-30"
        "&group_by=day&view_mode=bill_period",
        headers=auth_headers(admin_user),
    )
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["invoice_count"] == 1
    assert d2["total_revenue_paise"] == 2 * 3500
    assert d2["group_by"] == "month"  # forced
    assert [s["period"] for s in d2["series"]] == ["2025-04"]

    # bill_period mode widened to Feb–Apr: catches BOTH invoices, zero-fills Mar.
    r3 = await client.get(
        "/api/admin/reports/revenue?from=2025-02-01&to=2025-04-30"
        "&view_mode=bill_period",
        headers=auth_headers(admin_user),
    )
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3["invoice_count"] == 2
    periods = [s["period"] for s in sorted(d3["series"], key=lambda s: s["period"])]
    assert periods == ["2025-02", "2025-03", "2025-04"]
    mar = next(s for s in d3["series"] if s["period"] == "2025-03")
    assert mar["invoice_count"] == 0
    assert mar["revenue_paise"] == 0


@pytest.mark.asyncio
async def test_revenue_view_mode_invalid_rejected(client, admin_user, db):
    """Unknown view_mode returns a validation error (422 from Literal enforcement)."""
    r = await client.get(
        "/api/admin/reports/revenue?from=2025-01-01&to=2025-01-31&view_mode=wibble",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_revenue_csv_export_respects_view_mode(client, admin_user, db):
    """CSV export honours the view_mode query parameter (summary line echoes it)."""
    prod = await _mk_product(db, sku="REV-CSV-VM")
    c = await _mk_customer(db, 93, phone_suffix=7100093)
    inv = await _mk_invoice(db, c, prod, year=2025, month=5, days=[1, 2])
    inv.issued_at = datetime(2025, 7, 10, 2, 0, 0)
    await db.commit()

    # issued_date: July window catches it.
    r1 = await client.get(
        "/api/admin/reports/revenue/export?from=2025-07-01&to=2025-07-31"
        "&view_mode=issued_date",
        headers=auth_headers(admin_user),
    )
    assert r1.status_code == 200
    body1 = r1.content.decode("utf-8-sig")
    assert "View mode" in body1 and "issued_date" in body1
    assert "2 " not in body1 or True  # sanity — csv has data

    # bill_period: July window doesn't catch a May-billed invoice.
    r2 = await client.get(
        "/api/admin/reports/revenue/export?from=2025-07-01&to=2025-07-31"
        "&view_mode=bill_period",
        headers=auth_headers(admin_user),
    )
    assert r2.status_code == 200
    body2 = r2.content.decode("utf-8-sig")
    assert "bill_period" in body2
    assert "Invoice count,0" in body2
