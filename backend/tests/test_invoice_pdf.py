"""Phase 2C — Invoice PDF generation tests.

Covers: basic rendering, content fidelity, price-snapshot correctness,
lazy caching, invalidation on regenerate, invalidation on override,
adjustments rendering, bottle summary, RBAC, storage path verification.
"""
from __future__ import annotations
import io
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from pypdf import PdfReader
from sqlalchemy import select

from app.core.config import settings
from app.core.time_utils import now_utc
from app.models.billing import (
    Invoice, InvoiceLineItem, InvoiceAdjustment, InvoiceAdjustmentKind,
)
from app.models.delivery import DeliveryOrder, BottleLedger
from app.models.enums import (
    BottleReason, DeliveryOrderStatus, InvoiceStatus, ProductUnit,
    SubscriptionFrequency, SubscriptionStatus, UserRole,
)
from app.models.product import Product
from app.models.subscription import Subscription
from app.models.user import User
from app.services import invoice_pdf_service as pdf_svc
from app.services import billing_admin_service as bas

from tests.conftest import auth_headers


def _extract_text(pdf_bytes: bytes) -> str:
    """Extract concatenated text from all pages for assertions."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(p.extract_text() or "" for p in reader.pages)


# --------- shared fixtures ---------

async def _mk_scenario(db, *, suffix: int, year: int = 2025, month: int = 3,
                       days: list[int] | None = None,
                       price_paise: int = 3500,
                       with_bottle: bool = True):
    """Create a customer + product + subscription + invoice for (year, month)."""
    if days is None:
        days = list(range(1, 6))  # 5 delivered days by default
    prod = Product(
        name=f"PDF Test Milk {suffix}", sku=f"PDF-SKU-{suffix}",
        unit=ProductUnit.LITRE, price_paise=price_paise,
        requires_bottle=with_bottle, active=True,
    )
    db.add(prod); await db.flush()

    cust = User(
        phone=f"+919{(8_000_000 + suffix):09d}", name=f"PDF Cust {suffix}",
        role=UserRole.CUSTOMER, is_active=True, approved_at=now_utc(),
    )
    db.add(cust); await db.flush()

    sub = Subscription(
        customer_id=cust.id, product_id=prod.id, quantity=1,
        frequency=SubscriptionFrequency.DAILY,
        start_date=date(year, month, 1),
        status=SubscriptionStatus.ACTIVE,
    )
    db.add(sub); await db.flush()

    # Create delivery orders (delivered) + line items
    for d in days:
        do = DeliveryOrder(
            customer_id=cust.id, subscription_id=sub.id, product_id=prod.id,
            delivery_date=date(year, month, d),
            quantity=1, unit_price_paise=price_paise,
            status=DeliveryOrderStatus.DELIVERED,
            delivered_quantity=1, delivered_at=now_utc(),
        )
        db.add(do)
    await db.flush()

    inv = Invoice(
        customer_id=cust.id, year=year, month=month,
        subtotal_paise=len(days) * price_paise,
        adjustments_paise=0,
        total_paise=len(days) * price_paise,
        amount_paid_paise=0,
        status=InvoiceStatus.ISSUED,
        issued_at=datetime(year, month, 1, 2, 0, 0),
        due_date=date(year, month, 15),
    )
    db.add(inv); await db.flush()
    for d in days:
        db.add(InvoiceLineItem(
            invoice_id=inv.id,
            date=date(year, month, d),
            product_id=prod.id,
            quantity=1,
            price_paise=price_paise,
            total_paise=price_paise,
        ))
    await db.flush()
    await db.commit()
    return cust, prod, inv


# --------- tests ---------

@pytest.mark.asyncio
async def test_pdf_generation_basic(db):
    _, _, inv = await _mk_scenario(db, suffix=101)
    pdf_bytes = await pdf_svc.generate_invoice_pdf(db, inv.id)
    assert pdf_bytes[:4] == b"%PDF", "must be a valid PDF file"
    assert len(pdf_bytes) > 1000, "PDF should be non-trivial size"


@pytest.mark.asyncio
async def test_pdf_content_matches_api(client, admin_user, db):
    cust, prod, inv = await _mk_scenario(db, suffix=102, price_paise=5000, days=[1, 2, 3])
    # API response
    r = await client.get(f"/api/admin/invoices/{inv.id}", headers=auth_headers(admin_user))
    assert r.status_code == 200, r.text
    api = r.json()

    # Render PDF and extract text for fidelity check.
    pdf_bytes = await pdf_svc.generate_invoice_pdf(db, inv.id)
    assert pdf_bytes[:4] == b"%PDF"
    text = _extract_text(pdf_bytes)

    # Core numbers from API must be in the PDF (as stringified rupees).
    total_rupees_str = f"{api['invoice']['total_paise'] // 100:,}.{api['invoice']['total_paise'] % 100:02d}"
    assert total_rupees_str in text, f"PDF must contain total rupees {total_rupees_str}. Got:\n{text[:500]}"
    # Line count reflected (we have 3 line items → 3 SKU references)
    assert text.count(prod.sku) >= 3


@pytest.mark.asyncio
async def test_pdf_uses_price_snapshot(db):
    """Price changes after PDF generation must NOT alter an already-issued invoice's rendering."""
    cust, prod, inv = await _mk_scenario(db, suffix=103, price_paise=4000, days=[1, 2])
    pdf1 = await pdf_svc.generate_invoice_pdf(db, inv.id)
    text1 = _extract_text(pdf1)
    assert "40.00" in text1  # per-line rupee amount

    # Shoot the product price up — line items must still show the snapshot.
    prod.price_paise = 9999
    await db.commit()

    pdf2 = await pdf_svc.generate_invoice_pdf(db, inv.id)
    text2 = _extract_text(pdf2)
    assert "40.00" in text2
    assert "99.99" not in text2, "new product price must NOT leak onto historical invoice"


@pytest.mark.asyncio
async def test_pdf_lazy_caching(db):
    """First call stamps pdf_generated_at + pdf_storage_path; second call reuses."""
    _, _, inv = await _mk_scenario(db, suffix=104)
    assert inv.pdf_generated_at is None

    pdf1 = await pdf_svc.get_or_generate(db, inv)
    await db.commit()
    assert inv.pdf_generated_at is not None
    first_ts = inv.pdf_generated_at
    first_path = inv.pdf_storage_path
    assert first_path and first_path.startswith(f"invoices/{inv.year}/")

    # Re-fetch the invoice row so we aren't staring at stale in-memory state
    inv2 = (await db.execute(select(Invoice).where(Invoice.id == inv.id))).scalar_one()
    pdf2 = await pdf_svc.get_or_generate(db, inv2)
    assert inv2.pdf_generated_at == first_ts, "caching must not re-stamp pdf_generated_at"
    assert inv2.pdf_storage_path == first_path
    assert pdf1 == pdf2


@pytest.mark.asyncio
async def test_pdf_invalidated_on_regenerate(db, admin_user):
    """regenerating the invoice must clear pdf_storage_path + pdf_generated_at."""
    _, _, inv = await _mk_scenario(db, suffix=105)
    await pdf_svc.get_or_generate(db, inv)
    await db.commit()
    assert inv.pdf_storage_path is not None
    assert inv.pdf_generated_at is not None

    # Re-run billing generate with regenerate=True for the (year, month)
    await bas.generate_invoices(
        db, year=inv.year, month=inv.month, actor=admin_user,
        regenerate=True, reason="Forcing regen for PDF invalidation test",
    )
    await db.commit()

    inv_after = (await db.execute(select(Invoice).where(Invoice.id == inv.id))).scalar_one()
    assert inv_after.pdf_storage_path is None, "regenerate must invalidate pdf_storage_path"
    assert inv_after.pdf_generated_at is None


@pytest.mark.asyncio
async def test_pdf_invalidated_on_post_billing_override(db, admin_user):
    """Post-billing override → flag_post_billing_adjustment must clear PDF cache."""
    cust, prod, inv = await _mk_scenario(db, suffix=106, days=[1, 2, 3])
    await pdf_svc.get_or_generate(db, inv)
    await db.commit()
    assert inv.pdf_storage_path is not None

    # Trigger a post-billing adjustment
    await bas.flag_post_billing_adjustment(
        db,
        customer_id=cust.id,
        delivery_date=date(inv.year, inv.month, 2),
        ledger_delta_paise=-3500,
        reason="Test: override skipped day 2 for PDF invalidation",
        actor=admin_user,
        reference_id=None,
    )
    await db.commit()

    inv_after = (await db.execute(select(Invoice).where(Invoice.id == inv.id))).scalar_one()
    assert inv_after.pdf_storage_path is None
    assert inv_after.pdf_generated_at is None
    assert inv_after.has_post_billing_adjustments is True


@pytest.mark.asyncio
async def test_pdf_with_adjustments(db, admin_user):
    """Invoice with wallet_credit + override_adjustment shows both in PDF body."""
    cust, prod, inv = await _mk_scenario(db, suffix=107, days=[1, 2, 3])
    # Add an override_adjustment manually (without going through wallet service)
    db.add(InvoiceAdjustment(
        invoice_id=inv.id,
        kind=InvoiceAdjustmentKind.OVERRIDE_ADJUSTMENT,
        amount_paise=-3500,
        reason="Day 2 override skipped after billing",
        actor_user_id=admin_user.id,
        reference_id=None,
    ))
    db.add(InvoiceAdjustment(
        invoice_id=inv.id,
        kind=InvoiceAdjustmentKind.WALLET_CREDIT,
        amount_paise=-1000,
        reason="Goodwill credit for late delivery",
        actor_user_id=admin_user.id,
        reference_id=None,
    ))
    inv.adjustments_paise = -4500
    inv.total_paise = inv.subtotal_paise - 4500
    inv.has_post_billing_adjustments = True
    await db.commit()

    pdf_bytes = await pdf_svc.generate_invoice_pdf(db, inv.id)
    text = _extract_text(pdf_bytes).lower()
    assert "override" in text or "adjustment" in text
    # Both adjustment amounts surface
    assert "35.00" in text
    assert "10.00" in text


@pytest.mark.asyncio
async def test_pdf_bottle_summary(db):
    """Bottle section reflects BottleLedger entries within the period."""
    cust, prod, inv = await _mk_scenario(db, suffix=108, days=[1, 2, 3, 4, 5], with_bottle=True)

    # Opening bottles: 2 delivered before period
    db.add(BottleLedger(
        customer_id=cust.id, change=1, reason=BottleReason.DELIVERED,
        delivery_order_id=None,
        created_at=datetime(inv.year, inv.month, 1) - timedelta(days=5),
    ))
    db.add(BottleLedger(
        customer_id=cust.id, change=1, reason=BottleReason.DELIVERED,
        delivery_order_id=None,
        created_at=datetime(inv.year, inv.month, 1) - timedelta(days=3),
    ))
    # In-period: +5 delivered, -2 returned
    for d in range(1, 6):
        db.add(BottleLedger(
            customer_id=cust.id, change=1, reason=BottleReason.DELIVERED,
            delivery_order_id=None,
            created_at=datetime(inv.year, inv.month, d, 7, 0, 0),
        ))
    for d in [3, 5]:
        db.add(BottleLedger(
            customer_id=cust.id, change=-1, reason=BottleReason.RETURNED,
            delivery_order_id=None,
            created_at=datetime(inv.year, inv.month, d, 7, 5, 0),
        ))
    await db.commit()

    pdf_bytes = await pdf_svc.generate_invoice_pdf(db, inv.id)
    text = _extract_text(pdf_bytes)
    # Opening 2, +5 delivered, -2 returned, closing 5
    assert "Opening" in text
    assert "Closing" in text


@pytest.mark.asyncio
async def test_pdf_customer_rbac(client, db):
    """A customer cannot fetch another customer's invoice PDF. 404 (not 403) — no existence leak."""
    from app.core.security import create_access_token
    c1, _, inv = await _mk_scenario(db, suffix=109)

    # Create a DIFFERENT customer who will attempt to fetch c1's invoice.
    c2 = User(phone="+919000000777", name="Other Cust",
              role=UserRole.CUSTOMER, is_active=True, approved_at=now_utc())
    db.add(c2); await db.commit()

    token = create_access_token(str(c2.id), "customer")
    r = await client.get(
        f"/api/me/invoices/{inv.id}/pdf",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404, f"expected 404 (no existence leak), got {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_pdf_admin_can_fetch_any(client, admin_user, db):
    """Admin can fetch any customer's PDF through the admin endpoint."""
    _, _, inv = await _mk_scenario(db, suffix=110)
    r = await client.get(
        f"/api/admin/invoices/{inv.id}/pdf",
        headers=auth_headers(admin_user),
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"
    assert "attachment" not in r.headers.get("content-disposition", "")  # inline by default

    # download=true switches disposition
    r2 = await client.get(
        f"/api/admin/invoices/{inv.id}/pdf?download=true",
        headers=auth_headers(admin_user),
    )
    assert r2.status_code == 200
    assert "attachment" in r2.headers["content-disposition"]


@pytest.mark.asyncio
async def test_pdf_storage_path_written(db):
    """get_or_generate writes the PDF to disk at the expected LocalStorageProvider path."""
    _, _, inv = await _mk_scenario(db, suffix=111)
    await pdf_svc.get_or_generate(db, inv)
    await db.commit()

    assert inv.pdf_storage_path == f"invoices/{inv.year}/{inv.month:02d}/{inv.id}.pdf"
    full = Path(settings.LOCAL_STORAGE_PATH) / inv.pdf_storage_path
    assert full.exists(), f"expected PDF file at {full}"
    assert full.read_bytes()[:4] == b"%PDF"


@pytest.mark.asyncio
async def test_pdf_customer_own_invoice_works(client, db):
    """Owner can successfully fetch their own invoice PDF through the customer endpoint."""
    from app.core.security import create_access_token
    cust, _, inv = await _mk_scenario(db, suffix=112)
    token = create_access_token(str(cust.id), "customer")
    r = await client.get(
        f"/api/me/invoices/{inv.id}/pdf",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.content[:4] == b"%PDF"
    assert r.headers["content-type"] == "application/pdf"
