"""Billing: generate invoices for a given (month, year) from delivered orders."""
from __future__ import annotations
from datetime import date, datetime, timedelta
import uuid
import calendar

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.delivery import DeliveryOrder
from app.models.billing import Invoice, InvoiceLineItem
from app.models.product import Product
from app.models.user import User
from app.models.enums import InvoiceStatus, DeliveryOrderStatus, UserRole
from app.core.time_utils import now_utc


def _month_range(year: int, month: int) -> tuple[date, date]:
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    return first, last


async def compute_invoice_for_customer(
    db: AsyncSession, customer_id: uuid.UUID, year: int, month: int
) -> tuple[int, list[InvoiceLineItem]]:
    """Return (subtotal_paise, line_items) for delivered orders in that period."""
    first, last = _month_range(year, month)
    stmt = (
        select(DeliveryOrder, Product)
        .join(Product, Product.id == DeliveryOrder.product_id)
        .where(
            DeliveryOrder.customer_id == customer_id,
            DeliveryOrder.delivery_date >= first,
            DeliveryOrder.delivery_date <= last,
            DeliveryOrder.status == DeliveryOrderStatus.DELIVERED,
        )
        .order_by(DeliveryOrder.delivery_date.asc())
    )
    rows = (await db.execute(stmt)).all()
    line_items: list[InvoiceLineItem] = []
    subtotal = 0
    for order, _product in rows:
        qty = order.delivered_quantity if order.delivered_quantity is not None else order.quantity
        unit_price = order.unit_price_paise
        line_total = qty * unit_price
        subtotal += line_total
        line_items.append(
            InvoiceLineItem(
                date=order.delivery_date,
                product_id=order.product_id,
                quantity=qty,
                price_paise=unit_price,
                total_paise=line_total,
                delivery_order_id=order.id,
            )
        )
    return subtotal, line_items


async def generate_invoices_for_period(
    db: AsyncSession, year: int, month: int
) -> list[Invoice]:
    """DEPRECATED (Phase 2B.8): use `billing_admin_service.generate_invoices` instead.

    This legacy path does NOT use the advisory lock, does NOT write a `billing.generate`
    audit row, and does NOT honour per-customer atomicity or the post-billing-adjustment
    hook. Preserved temporarily for code paths that still import it; planned removal
    in Phase 3 cleanup (tracked in `docs/TECH_DEBT.md`).
    """
    import warnings
    warnings.warn(
        "billing_service.generate_invoices_for_period is deprecated since Phase 2B.8 "
        "— use billing_admin_service.generate_invoices (with a system actor) instead. "
        "Planned removal in Phase 3.",
        DeprecationWarning,
        stacklevel=2,
    )
    """Create invoices for every customer who had activity in that month.
    Idempotent: if an invoice already exists for (customer, month, year), skip.
    """
    customers = (
        await db.execute(select(User).where(User.role == UserRole.CUSTOMER))
    ).scalars().all()
    created: list[Invoice] = []
    # Pre-fetch existing invoices
    existing_stmt = select(Invoice.customer_id).where(Invoice.month == month, Invoice.year == year)
    existing_ids: set[uuid.UUID] = set((await db.execute(existing_stmt)).scalars().all())

    for cust in customers:
        if cust.id in existing_ids:
            continue
        subtotal, items = await compute_invoice_for_customer(db, cust.id, year, month)
        if subtotal == 0 and not items:
            continue  # no activity, no invoice
        # due date = 10th of next month
        due_y, due_m = (year, month + 1) if month < 12 else (year + 1, 1)
        due_date = date(due_y, due_m, 10)
        invoice = Invoice(
            customer_id=cust.id,
            year=year,
            month=month,
            subtotal_paise=subtotal,
            adjustments_paise=0,
            total_paise=subtotal,
            status=InvoiceStatus.ISSUED,
            issued_at=now_utc(),
            due_date=due_date,
        )
        db.add(invoice)
        await db.flush()
        for it in items:
            it.invoice_id = invoice.id
            db.add(it)
        created.append(invoice)
    await db.flush()
    return created
