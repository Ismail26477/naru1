"""Admin reports service (Phase 2B.7) — read-only aggregations.

Single source of truth for:
- Revenue: SUM(invoice.total_paise) issued in [from..to], plus by-product breakdown.
- Churn: customers active at month-start who aren't active at month-end.
- Daily delivery: counts by delivery_orders.status per day, with optional route / delivery-boy filters.
- Bottle outstanding: point-in-time balance via SUM(bottle_ledger.change) per customer.

All money stays in paise. Dates are in IST (date-only) per domain convention.
"""
from __future__ import annotations
import calendar
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select, func, and_, case, literal
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import today_ist, now_utc
from app.models.billing import Invoice, InvoiceLineItem, Payment
from app.models.delivery import DeliveryOrder, BottleLedger
from app.models.enums import (
    DeliveryOrderStatus,
    InvoiceStatus,
    PaymentStatus,
    SubscriptionStatus,
    UserRole,
)
from app.models.product import Product
from app.models.route import Route, RouteStop
from app.models.subscription import Subscription
from app.models.user import User


# --------- revenue ---------

@dataclass
class RevenueSeriesPoint:
    period: str  # ISO date (day) / 'YYYY-WW' (week) / 'YYYY-MM' (month)
    revenue_paise: int
    collected_paise: int
    invoice_count: int


@dataclass
class RevenueByProduct:
    product_id: uuid.UUID
    product_name: str
    product_sku: str
    revenue_paise: int
    quantity_total: int


@dataclass
class RevenueReport:
    from_date: date
    to_date: date
    group_by: str
    total_revenue_paise: int
    total_collected_paise: int
    total_outstanding_paise: int
    avg_invoice_paise: int
    invoice_count: int
    series: list[RevenueSeriesPoint]
    by_product: list[RevenueByProduct]


def _date_range_days(a: date, b: date) -> list[date]:
    return [a + timedelta(days=i) for i in range((b - a).days + 1)]


def _period_key(d: date, group_by: str) -> str:
    if group_by == "day":
        return d.isoformat()
    if group_by == "week":
        iso_year, iso_week, _ = d.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if group_by == "month":
        return f"{d.year}-{d.month:02d}"
    raise ValueError(f"unknown group_by {group_by}")


async def revenue_report(
    db: AsyncSession,
    *,
    from_date: date,
    to_date: date,
    group_by: str = "day",
    view_mode: str = "issued_date",
) -> RevenueReport:
    if group_by not in ("day", "week", "month"):
        raise ValueError(f"group_by must be day|week|month, got {group_by}")
    if view_mode not in ("issued_date", "bill_period"):
        raise ValueError(f"view_mode must be issued_date|bill_period, got {view_mode}")
    if from_date > to_date:
        raise ValueError("from_date must be ≤ to_date")

    # Two modes for date filtering:
    #   issued_date  — invoices whose issued_at::date falls in [from..to].
    #                  Series/by-product filter on issued_at::date.
    #   bill_period  — invoices whose billed month (year, month) falls in [from..to]
    #                  (inclusive at month granularity). Series is always monthly in
    #                  this mode (group_by is forced to 'month').
    if view_mode == "bill_period":
        group_by = "month"
        bill_date = func.make_date(Invoice.year, Invoice.month, 1)
        date_pred = and_(
            bill_date >= date(from_date.year, from_date.month, 1),
            bill_date <= date(to_date.year, to_date.month, 1),
        )
        inv_stmt = (
            select(
                Invoice.id, Invoice.total_paise, Invoice.amount_paid_paise,
                Invoice.status, Invoice.issued_at, Invoice.year, Invoice.month,
            ).where(date_pred)
        )
    else:
        date_pred = and_(
            Invoice.issued_at.is_not(None),
            func.date(Invoice.issued_at) >= from_date,
            func.date(Invoice.issued_at) <= to_date,
        )
        inv_stmt = (
            select(
                Invoice.id, Invoice.total_paise, Invoice.amount_paid_paise,
                Invoice.status, Invoice.issued_at, Invoice.year, Invoice.month,
            ).where(date_pred)
        )

    invs = (await db.execute(inv_stmt)).all()

    total_revenue = sum(int(r.total_paise or 0) for r in invs)
    total_collected = sum(int(r.amount_paid_paise or 0) for r in invs)
    total_outstanding = sum(max(0, int(r.total_paise or 0) - int(r.amount_paid_paise or 0)) for r in invs)
    count = len(invs)
    avg = (total_revenue // count) if count else 0

    # Series
    buckets: dict[str, dict[str, int]] = {}
    for r in invs:
        if view_mode == "bill_period":
            k = f"{r.year}-{r.month:02d}"
        else:
            d = r.issued_at.date()
            k = _period_key(d, group_by)
        b = buckets.setdefault(k, {"revenue": 0, "collected": 0, "count": 0})
        b["revenue"] += int(r.total_paise or 0)
        b["collected"] += int(r.amount_paid_paise or 0)
        b["count"] += 1

    # For "day" group_by (issued_date mode only), emit zero-rows so charts don't have gaps.
    if group_by == "day" and view_mode == "issued_date":
        for d in _date_range_days(from_date, to_date):
            buckets.setdefault(d.isoformat(), {"revenue": 0, "collected": 0, "count": 0})
    # For bill_period mode, zero-fill missing months in range so monthly chart is continuous.
    if view_mode == "bill_period":
        y, m = from_date.year, from_date.month
        while (y, m) <= (to_date.year, to_date.month):
            buckets.setdefault(f"{y}-{m:02d}", {"revenue": 0, "collected": 0, "count": 0})
            m += 1
            if m > 12:
                y, m = y + 1, 1

    series = [
        RevenueSeriesPoint(
            period=k,
            revenue_paise=b["revenue"],
            collected_paise=b["collected"],
            invoice_count=b["count"],
        )
        for k, b in sorted(buckets.items())
    ]

    # By product (from line items whose parent invoice is in range under the selected mode)
    by_prod_rows = (await db.execute(
        select(
            Product.id, Product.name, Product.sku,
            func.coalesce(func.sum(InvoiceLineItem.total_paise), 0).label("rev"),
            func.coalesce(func.sum(InvoiceLineItem.quantity), 0).label("qty"),
        )
        .join(InvoiceLineItem, InvoiceLineItem.product_id == Product.id)
        .join(Invoice, Invoice.id == InvoiceLineItem.invoice_id)
        .where(date_pred)
        .group_by(Product.id, Product.name, Product.sku)
        .order_by(func.sum(InvoiceLineItem.total_paise).desc())
    )).all()
    by_product = [
        RevenueByProduct(
            product_id=r.id, product_name=r.name, product_sku=r.sku,
            revenue_paise=int(r.rev), quantity_total=int(r.qty),
        )
        for r in by_prod_rows
    ]

    return RevenueReport(
        from_date=from_date, to_date=to_date, group_by=group_by,
        total_revenue_paise=total_revenue,
        total_collected_paise=total_collected,
        total_outstanding_paise=total_outstanding,
        avg_invoice_paise=avg,
        invoice_count=count,
        series=series,
        by_product=by_product,
    )


# --------- churn ---------

@dataclass
class ChurnedCustomer:
    customer_id: uuid.UUID
    name: str | None
    phone: str
    last_delivery_date: date | None
    days_inactive: int
    cancelled_at: datetime | None


@dataclass
class ChurnReport:
    year: int
    month: int
    active_start: int
    active_end: int
    new_customers: int
    churned_customers: int
    net_change: int
    churned_list: list[ChurnedCustomer]


async def _customers_with_active_sub_on(db: AsyncSession, as_of: date) -> set[uuid.UUID]:
    """Return customer_ids with at least one subscription whose coverage window includes `as_of`.

    A subscription covers `as_of` iff `start_date ≤ as_of` AND (`end_date` is null OR `end_date > as_of`).
    Current `status` is deliberately NOT checked — a subscription that is now CANCELLED
    but whose `end_date` is after `as_of` *was* active on `as_of` (historical accuracy).
    Paused subs still count as active for churn (they're expected to resume). This matches
    the user's spec: churn requires disappearing completely from the active set.
    """
    stmt = select(Subscription.customer_id).distinct().where(
        Subscription.start_date <= as_of,
        (Subscription.end_date.is_(None)) | (Subscription.end_date > as_of),
    )
    return set((await db.execute(stmt)).scalars().all())


async def churn_report(db: AsyncSession, *, year: int, month: int) -> ChurnReport:
    if not (1 <= month <= 12):
        raise ValueError(f"month must be 1..12, got {month}")
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    day_before_first = first - timedelta(days=1)

    # Active at start of month = active on the day before month start (so someone who
    # becomes active on day 1 counts as NEW not carry-over).
    active_start_set = await _customers_with_active_sub_on(db, day_before_first)
    active_end_set = await _customers_with_active_sub_on(db, last)

    churned_ids = active_start_set - active_end_set
    new_ids = active_end_set - active_start_set

    # Enrich churned list
    churned: list[ChurnedCustomer] = []
    if churned_ids:
        users = (await db.execute(
            select(User).where(User.id.in_(churned_ids))
        )).scalars().all()
        # Last delivery per customer
        last_deliv = (await db.execute(
            select(
                DeliveryOrder.customer_id,
                func.max(DeliveryOrder.delivery_date).label("last_date"),
            )
            .where(
                DeliveryOrder.customer_id.in_(churned_ids),
                DeliveryOrder.status == DeliveryOrderStatus.DELIVERED,
            )
            .group_by(DeliveryOrder.customer_id)
        )).all()
        last_deliv_map = {r.customer_id: r.last_date for r in last_deliv}
        # Last-cancel timestamp: take the most recent subscription.updated_at for the customer
        # that has status=CANCELLED (proxy for "cancelled_at" since we don't store it separately).
        cancels = (await db.execute(
            select(
                Subscription.customer_id,
                func.max(Subscription.updated_at).label("cx_at"),
            )
            .where(
                Subscription.customer_id.in_(churned_ids),
                Subscription.status == SubscriptionStatus.CANCELLED,
            )
            .group_by(Subscription.customer_id)
        )).all()
        cancel_map = {r.customer_id: r.cx_at for r in cancels}

        today = today_ist()
        for u in users:
            last_d = last_deliv_map.get(u.id)
            days_inactive = (today - last_d).days if last_d else -1
            churned.append(ChurnedCustomer(
                customer_id=u.id, name=u.name, phone=u.phone,
                last_delivery_date=last_d, days_inactive=days_inactive,
                cancelled_at=cancel_map.get(u.id),
            ))
        churned.sort(key=lambda c: (c.cancelled_at or datetime.min), reverse=True)

    return ChurnReport(
        year=year, month=month,
        active_start=len(active_start_set),
        active_end=len(active_end_set),
        new_customers=len(new_ids),
        churned_customers=len(churned_ids),
        net_change=len(active_end_set) - len(active_start_set),
        churned_list=churned,
    )


# --------- daily delivery ---------

@dataclass
class DailyDeliveryPoint:
    date: date
    scheduled: int
    delivered: int
    skipped: int
    failed: int
    pending: int


@dataclass
class DeliveryByRoute:
    route_id: uuid.UUID | None
    route_name: str
    delivered: int
    skipped: int
    failed: int
    total: int


@dataclass
class DeliveryByBoy:
    delivery_boy_id: uuid.UUID | None
    name: str
    phone: str
    delivered: int
    skipped: int
    failed: int
    total: int


@dataclass
class DailyDeliveryReport:
    from_date: date
    to_date: date
    total_scheduled: int
    total_delivered: int
    total_skipped: int
    total_failed: int
    completion_rate_pct: float
    series: list[DailyDeliveryPoint]
    by_route: list[DeliveryByRoute]
    by_delivery_boy: list[DeliveryByBoy]


async def daily_delivery_report(
    db: AsyncSession,
    *,
    from_date: date,
    to_date: date,
    route_id: uuid.UUID | None = None,
    delivery_boy_id: uuid.UUID | None = None,
) -> DailyDeliveryReport:
    if from_date > to_date:
        raise ValueError("from_date must be ≤ to_date")

    base_where = [
        DeliveryOrder.delivery_date >= from_date,
        DeliveryOrder.delivery_date <= to_date,
    ]
    if delivery_boy_id:
        base_where.append(DeliveryOrder.delivery_boy_id == delivery_boy_id)

    if route_id:
        # Filter to customers in this route
        cust_ids_subq = select(RouteStop.customer_id).where(RouteStop.route_id == route_id)
        base_where.append(DeliveryOrder.customer_id.in_(cust_ids_subq))

    # Per-day counts by status
    rows = (await db.execute(
        select(
            DeliveryOrder.delivery_date,
            DeliveryOrder.status,
            func.count().label("n"),
        )
        .where(and_(*base_where))
        .group_by(DeliveryOrder.delivery_date, DeliveryOrder.status)
    )).all()

    by_day: dict[date, dict[str, int]] = {}
    totals = {"delivered": 0, "skipped": 0, "failed": 0, "pending": 0}
    for r in rows:
        d = r.delivery_date
        st = r.status.value if hasattr(r.status, "value") else str(r.status)
        n = int(r.n)
        b = by_day.setdefault(d, {"delivered": 0, "skipped": 0, "failed": 0, "pending": 0})
        if st in b:
            b[st] += n
            totals[st] = totals.get(st, 0) + n

    # Zero-fill dates
    for d in _date_range_days(from_date, to_date):
        by_day.setdefault(d, {"delivered": 0, "skipped": 0, "failed": 0, "pending": 0})

    series = [
        DailyDeliveryPoint(
            date=d,
            scheduled=sum(v.values()),
            delivered=v["delivered"], skipped=v["skipped"],
            failed=v["failed"], pending=v["pending"],
        )
        for d, v in sorted(by_day.items())
    ]
    total_scheduled = totals["delivered"] + totals["skipped"] + totals["failed"] + totals["pending"]
    completion_rate = (totals["delivered"] / total_scheduled * 100) if total_scheduled else 0.0

    # By route
    # Join delivery_orders.customer → route_stops → routes
    by_route_rows = (await db.execute(
        select(
            Route.id, Route.name,
            DeliveryOrder.status,
            func.count().label("n"),
        )
        .outerjoin(RouteStop, RouteStop.customer_id == DeliveryOrder.customer_id)
        .outerjoin(Route, Route.id == RouteStop.route_id)
        .where(and_(*base_where))
        .group_by(Route.id, Route.name, DeliveryOrder.status)
    )).all()
    br_map: dict[uuid.UUID | None, dict[str, Any]] = {}
    for r in by_route_rows:
        key = r.id
        st = r.status.value if hasattr(r.status, "value") else str(r.status)
        entry = br_map.setdefault(key, {
            "route_id": r.id, "route_name": r.name or "(unassigned)",
            "delivered": 0, "skipped": 0, "failed": 0, "total": 0,
        })
        if st in entry:
            entry[st] += int(r.n)
            entry["total"] += int(r.n)
    by_route = sorted(
        [
            DeliveryByRoute(
                route_id=v["route_id"], route_name=v["route_name"],
                delivered=v["delivered"], skipped=v["skipped"],
                failed=v["failed"], total=v["total"],
            )
            for v in br_map.values()
        ],
        key=lambda r: r.total, reverse=True,
    )

    # By delivery boy
    by_boy_rows = (await db.execute(
        select(
            User.id, User.name, User.phone,
            DeliveryOrder.status,
            func.count().label("n"),
        )
        .outerjoin(User, User.id == DeliveryOrder.delivery_boy_id)
        .where(and_(*base_where))
        .group_by(User.id, User.name, User.phone, DeliveryOrder.status)
    )).all()
    bb_map: dict[uuid.UUID | None, dict[str, Any]] = {}
    for r in by_boy_rows:
        key = r.id
        st = r.status.value if hasattr(r.status, "value") else str(r.status)
        entry = bb_map.setdefault(key, {
            "delivery_boy_id": r.id, "name": r.name or "(unassigned)",
            "phone": r.phone or "",
            "delivered": 0, "skipped": 0, "failed": 0, "total": 0,
        })
        if st in entry:
            entry[st] += int(r.n)
            entry["total"] += int(r.n)
    by_delivery_boy = sorted(
        [
            DeliveryByBoy(
                delivery_boy_id=v["delivery_boy_id"], name=v["name"], phone=v["phone"],
                delivered=v["delivered"], skipped=v["skipped"],
                failed=v["failed"], total=v["total"],
            )
            for v in bb_map.values()
        ],
        key=lambda b: b.total, reverse=True,
    )

    return DailyDeliveryReport(
        from_date=from_date, to_date=to_date,
        total_scheduled=total_scheduled,
        total_delivered=totals["delivered"],
        total_skipped=totals["skipped"],
        total_failed=totals["failed"],
        completion_rate_pct=round(completion_rate, 2),
        series=series,
        by_route=by_route,
        by_delivery_boy=by_delivery_boy,
    )


# --------- bottle outstanding ---------

@dataclass
class BottleOutstandingCustomer:
    customer_id: uuid.UUID
    name: str | None
    phone: str
    area: str | None
    route_name: str | None
    bottles_out: int
    last_return_date: date | None
    days_since_return: int
    ever_returned: bool


@dataclass
class BottleOutstandingReport:
    total_bottles_out: int
    customers_with_outstanding: int
    customers_above_5: int
    oldest_days: int
    customers: list[BottleOutstandingCustomer]


async def bottle_outstanding_report(db: AsyncSession) -> BottleOutstandingReport:
    """Point-in-time: customers with SUM(bottle_ledger.change) > 0."""
    today = today_ist()

    # SUM per customer with positive balance
    bal_rows = (await db.execute(
        select(
            BottleLedger.customer_id,
            func.coalesce(func.sum(BottleLedger.change), 0).label("bal"),
        )
        .group_by(BottleLedger.customer_id)
        .having(func.coalesce(func.sum(BottleLedger.change), 0) > 0)
    )).all()
    if not bal_rows:
        return BottleOutstandingReport(
            total_bottles_out=0, customers_with_outstanding=0,
            customers_above_5=0, oldest_days=0, customers=[],
        )

    cust_ids = [r.customer_id for r in bal_rows]
    bal_map = {r.customer_id: int(r.bal) for r in bal_rows}

    users = (await db.execute(
        select(User).where(User.id.in_(cust_ids))
    )).scalars().all()
    users_map = {u.id: u for u in users}

    # First delivery per customer (for "ever returned = false" days-since calculation)
    first_delivery_rows = (await db.execute(
        select(
            BottleLedger.customer_id,
            func.min(BottleLedger.created_at).label("first"),
        )
        .where(BottleLedger.customer_id.in_(cust_ids), BottleLedger.change > 0)
        .group_by(BottleLedger.customer_id)
    )).all()
    first_map = {r.customer_id: r.first for r in first_delivery_rows}

    # Last return per customer (most recent change<0)
    last_return_rows = (await db.execute(
        select(
            BottleLedger.customer_id,
            func.max(BottleLedger.created_at).label("last_ret"),
        )
        .where(BottleLedger.customer_id.in_(cust_ids), BottleLedger.change < 0)
        .group_by(BottleLedger.customer_id)
    )).all()
    last_ret_map = {r.customer_id: r.last_ret for r in last_return_rows}

    # Route per customer
    route_rows = (await db.execute(
        select(RouteStop.customer_id, Route.name)
        .join(Route, Route.id == RouteStop.route_id)
        .where(RouteStop.customer_id.in_(cust_ids))
    )).all()
    route_map = {r.customer_id: r.name for r in route_rows}

    # Default address area per customer
    from app.models.user import Address
    addr_rows = (await db.execute(
        select(Address.user_id, Address.area)
        .where(Address.user_id.in_(cust_ids), Address.is_default.is_(True))
    )).all()
    area_map = {r.user_id: r.area for r in addr_rows}

    customers: list[BottleOutstandingCustomer] = []
    total = 0
    count_above_5 = 0
    oldest_days = 0
    for cid, bal in bal_map.items():
        u = users_map.get(cid)
        if not u:
            continue
        last_ret = last_ret_map.get(cid)
        if last_ret:
            days_since = (today - last_ret.date()).days
            ever = True
        elif cid in first_map:
            days_since = (today - first_map[cid].date()).days
            ever = False
        else:
            days_since = 0
            ever = False

        customers.append(BottleOutstandingCustomer(
            customer_id=cid, name=u.name, phone=u.phone,
            area=area_map.get(cid),
            route_name=route_map.get(cid),
            bottles_out=bal,
            last_return_date=last_ret.date() if last_ret else None,
            days_since_return=days_since,
            ever_returned=ever,
        ))
        total += bal
        if bal > 5:
            count_above_5 += 1
        if days_since > oldest_days:
            oldest_days = days_since

    # Sort: highest bottles first, then oldest days
    customers.sort(key=lambda c: (c.bottles_out, c.days_since_return), reverse=True)

    return BottleOutstandingReport(
        total_bottles_out=total,
        customers_with_outstanding=len(customers),
        customers_above_5=count_above_5,
        oldest_days=oldest_days,
        customers=customers,
    )
