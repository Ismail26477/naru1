"""Invoice PDF generation service (Phase 2C).

Design:
- Lazy generation + storage cache. First fetch renders HTML → PDF via weasyprint
  and writes the bytes through the active `StorageProvider`. Subsequent fetches
  read straight from storage.
- Invalidation is a thin `invalidate(invoice_id)` that NULLs both
  `pdf_generated_at` and `pdf_storage_path`. Callers are `billing_admin_service`
  (on regenerate) and `billing_admin_service.flag_post_billing_adjustment` (on
  post-billing override).
- Concurrency: we accept rare duplicate generations (last-write-wins on disk;
  DB row update is idempotent). For our scale (~10s of invoices/day) this is
  far simpler than an advisory lock and still correct.
- RBAC is enforced by the API layer, not here — this service is trusted.

Data fidelity invariant:
- Line items use `InvoiceLineItem.price_paise` (the per-delivery snapshot),
  never `Product.price_paise` (which floats with price changes).
- Totals and adjustments read straight from the `Invoice` row so any drift
  would surface as a mismatch with the `GET /admin/invoices/{id}` payload.
"""
from __future__ import annotations
from datetime import datetime, date, timedelta
from pathlib import Path
import logging

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import now_utc
from app.models.billing import (
    Invoice, InvoiceLineItem, InvoiceAdjustment, InvoiceAdjustmentKind,
)
from app.models.delivery import DeliveryOrder, BottleLedger
from app.models.enums import DeliveryOrderStatus, InvoiceStatus
from app.models.product import Product
from app.models.user import User, Address
from app.providers import get_storage_provider

log = logging.getLogger("invoice_pdf")

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_ENV = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)

_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _paise_to_rupees(p: int) -> str:
    """Format signed paise as a rupee string with 2 decimals (no currency symbol)."""
    sign = "-" if p < 0 else ""
    cents = abs(int(p))
    rupees, paise = divmod(cents, 100)
    return f"{sign}{rupees:,}.{paise:02d}"


def _storage_key(invoice: Invoice) -> str:
    return f"invoices/{invoice.year}/{invoice.month:02d}/{invoice.id}.pdf"


async def _build_context(db: AsyncSession, invoice: Invoice) -> dict:
    """Gather every datum the template needs from the DB."""
    # Customer
    cust = (await db.execute(
        select(User).where(User.id == invoice.customer_id)
    )).scalar_one()

    # Default address (if any)
    addr = (await db.execute(
        select(Address).where(Address.user_id == cust.id).order_by(
            Address.is_default.desc(), Address.created_at.asc()
        ).limit(1)
    )).scalar_one_or_none()
    addr_str = None
    if addr:
        parts = [addr.line1]
        if addr.line2:
            parts.append(addr.line2)
        parts.append(f"{addr.area}, {addr.city} {addr.pincode}")
        addr_str = ", ".join(parts)

    # Line items + product names (one query each to stay simple)
    li_rows = (await db.execute(
        select(InvoiceLineItem, Product)
        .join(Product, Product.id == InvoiceLineItem.product_id)
        .where(InvoiceLineItem.invoice_id == invoice.id)
        .order_by(InvoiceLineItem.date.asc())
    )).all()
    line_items = []
    for li, prod in li_rows:
        line_items.append({
            "date_str": li.date.strftime("%d %b"),
            "product_name": prod.name,
            "product_sku": prod.sku,
            "quantity": li.quantity,
            "price_paise": li.price_paise,
            "price_rupees": _paise_to_rupees(li.price_paise),
            "total_paise": li.total_paise,
            "total_rupees": _paise_to_rupees(li.total_paise),
        })

    # Adjustments
    adj_rows = (await db.execute(
        select(InvoiceAdjustment)
        .where(InvoiceAdjustment.invoice_id == invoice.id)
        .order_by(InvoiceAdjustment.created_at.asc())
    )).scalars().all()
    adjustments = [
        {
            "date_str": a.created_at.strftime("%d %b %Y"),
            "kind_label": a.kind.replace("_", " "),
            "reason": a.reason,
            "amount_paise": a.amount_paise,
            "amount_rupees": _paise_to_rupees(a.amount_paise),
        }
        for a in adj_rows
    ]

    # Delivered / skipped day counts for the billing period
    period_first = date(invoice.year, invoice.month, 1)
    # last day of that month
    if invoice.month == 12:
        next_first = date(invoice.year + 1, 1, 1)
    else:
        next_first = date(invoice.year, invoice.month + 1, 1)
    period_last = next_first - timedelta(days=1)

    delivered_count = (await db.execute(
        select(func.count(DeliveryOrder.id)).where(
            DeliveryOrder.customer_id == invoice.customer_id,
            DeliveryOrder.delivery_date >= period_first,
            DeliveryOrder.delivery_date <= period_last,
            DeliveryOrder.status == DeliveryOrderStatus.DELIVERED,
        )
    )).scalar_one()
    skipped_count = (await db.execute(
        select(func.count(DeliveryOrder.id)).where(
            DeliveryOrder.customer_id == invoice.customer_id,
            DeliveryOrder.delivery_date >= period_first,
            DeliveryOrder.delivery_date <= period_last,
            DeliveryOrder.status == DeliveryOrderStatus.SKIPPED,
        )
    )).scalar_one()

    # Bottle summary: opening (as of period_first - 1), delivered-in-period,
    # returned-in-period, closing (as of invoice date or now).
    opening_bal = (await db.execute(
        select(func.coalesce(func.sum(BottleLedger.change), 0)).where(
            BottleLedger.customer_id == invoice.customer_id,
            func.date(BottleLedger.created_at) < period_first,
        )
    )).scalar_one()
    delivered_bottles = (await db.execute(
        select(func.coalesce(func.sum(BottleLedger.change), 0)).where(
            BottleLedger.customer_id == invoice.customer_id,
            func.date(BottleLedger.created_at) >= period_first,
            func.date(BottleLedger.created_at) <= period_last,
            BottleLedger.change > 0,
        )
    )).scalar_one()
    returned_bottles = (await db.execute(
        select(func.coalesce(func.sum(BottleLedger.change), 0)).where(
            BottleLedger.customer_id == invoice.customer_id,
            func.date(BottleLedger.created_at) >= period_first,
            func.date(BottleLedger.created_at) <= period_last,
            BottleLedger.change < 0,
        )
    )).scalar_one()
    closing_bal = int(opening_bal) + int(delivered_bottles) + int(returned_bottles)

    # Period label + invoice number
    period_label = f"{_MONTH_NAMES[invoice.month - 1]} {invoice.year}"
    invoice_number = f"INV-{invoice.year}-{invoice.month:02d}-{str(invoice.id)[:4].upper()}"

    balance_due = max(0, int(invoice.total_paise) - int(invoice.amount_paid_paise))

    status_val = invoice.status.value if hasattr(invoice.status, "value") else str(invoice.status)

    return {
        "invoice_number": invoice_number,
        "invoice_id_short": str(invoice.id)[:8],
        "period_label": period_label,
        "issued_at_str": invoice.issued_at.strftime("%d %b %Y") if invoice.issued_at else "—",
        "due_date_str": invoice.due_date.strftime("%d %b %Y") if invoice.due_date else "—",
        "regenerated_count": int(invoice.regenerated_count or 0),
        "last_regenerated_at_str": (
            invoice.last_regenerated_at.strftime("%d %b %Y %H:%M")
            if invoice.last_regenerated_at else None
        ),
        "status_class": status_val.lower(),
        "status_label": status_val.replace("_", " ").upper(),

        "customer_id_short": str(cust.id)[:8],
        "customer_name": cust.name,
        "customer_phone": cust.phone,
        "delivery_address": addr_str,

        "delivered_days": int(delivered_count),
        "skipped_days": int(skipped_count),

        "line_items": line_items,
        "adjustments": adjustments,

        "subtotal_rupees": _paise_to_rupees(invoice.subtotal_paise),
        "adjustments_paise": int(invoice.adjustments_paise or 0),
        "adjustments_rupees": _paise_to_rupees(invoice.adjustments_paise),
        "total_rupees": _paise_to_rupees(invoice.total_paise),
        "amount_paid_paise": int(invoice.amount_paid_paise or 0),
        "amount_paid_rupees": _paise_to_rupees(invoice.amount_paid_paise),
        "balance_due_paise": int(balance_due),
        "balance_due_rupees": _paise_to_rupees(balance_due),

        "bottle": {
            "opening_date": (period_first - timedelta(days=1)).strftime("%d %b %Y"),
            "opening": int(opening_bal),
            "delivered": int(delivered_bottles),
            "returned": abs(int(returned_bottles)),
            "closing": int(closing_bal),
        },
    }


def _render_pdf_bytes(context: dict) -> bytes:
    """Render the Jinja template and convert to PDF bytes via weasyprint."""
    from weasyprint import HTML  # local import keeps cold-start fast
    tmpl = _ENV.get_template("invoice_pdf.html")
    html = tmpl.render(**context)
    return HTML(string=html).write_pdf()


async def generate_invoice_pdf(db: AsyncSession, invoice_id) -> bytes:
    """Render the PDF from scratch and return its bytes (does not cache)."""
    inv = (await db.execute(
        select(Invoice).where(Invoice.id == invoice_id)
    )).scalar_one()
    ctx = await _build_context(db, inv)
    return _render_pdf_bytes(ctx)


async def get_or_generate(db: AsyncSession, invoice: Invoice) -> bytes:
    """Return cached PDF bytes if present, else generate + cache + return.

    Writes `pdf_storage_path` and `pdf_generated_at` on cache miss. If the
    cached file has been deleted out-of-band, falls back to regenerating.
    """
    storage = get_storage_provider()
    if invoice.pdf_storage_path and invoice.pdf_generated_at:
        cached = await storage.get(invoice.pdf_storage_path)
        if cached:
            return cached
        log.warning(
            f"invoice_pdf: cached path {invoice.pdf_storage_path} missing on disk; regenerating"
        )

    ctx = await _build_context(db, invoice)
    pdf_bytes = _render_pdf_bytes(ctx)

    key = _storage_key(invoice)
    await storage.put(key, pdf_bytes, content_type="application/pdf")

    invoice.pdf_storage_path = key
    invoice.pdf_generated_at = now_utc()
    # pdf_url kept for backward-compat — point it at the same key
    invoice.pdf_url = key
    await db.flush()
    return pdf_bytes


async def invalidate(db: AsyncSession, invoice_id) -> None:
    """Clear the PDF cache columns so the next fetch regenerates.

    Does NOT delete the file from storage (cheap leak; avoids a whole class
    of race conditions with concurrent readers). The file will be overwritten
    on the next generate call since the storage key is stable per invoice.
    """
    inv = (await db.execute(
        select(Invoice).where(Invoice.id == invoice_id)
    )).scalar_one_or_none()
    if inv is None:
        return
    inv.pdf_storage_path = None
    inv.pdf_generated_at = None
    await db.flush()
