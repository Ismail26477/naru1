"""Admin reports endpoints (Phase 2B.7).

- GET /admin/reports/revenue               — revenue report (JSON)
- GET /admin/reports/revenue/export        — CSV stream of series + by-product
- GET /admin/reports/churn                 — churn report
- GET /admin/reports/churn/export          — CSV stream of churned list
- GET /admin/reports/daily-delivery        — delivery ops report
- GET /admin/reports/daily-delivery/export — CSV stream of series
- GET /admin/reports/bottle-outstanding    — point-in-time outstanding bottles
- GET /admin/reports/bottle-outstanding/export — CSV stream
- GET /admin/billing/register/export       — server-side CSV for the billing register (migrated from client-side)

All endpoints: admin-only.
"""
from __future__ import annotations
from datetime import date
from typing import Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.middleware.auth import require_admin
from app.models.billing import Invoice
from app.models.user import User
from app.services import reports_service as rs
from app.services.csv_export_service import stream_csv


router = APIRouter(
    prefix="/admin",
    tags=["admin-reports"],
    dependencies=[Depends(require_admin)],
)


# --------- response schemas ---------

class RevenueSeriesOut(BaseModel):
    period: str
    revenue_paise: int
    collected_paise: int
    invoice_count: int


class RevenueByProductOut(BaseModel):
    product_id: uuid.UUID
    product_name: str
    product_sku: str
    revenue_paise: int
    quantity_total: int


class RevenueOut(BaseModel):
    from_date: date
    to_date: date
    group_by: str
    total_revenue_paise: int
    total_collected_paise: int
    total_outstanding_paise: int
    avg_invoice_paise: int
    invoice_count: int
    series: list[RevenueSeriesOut]
    by_product: list[RevenueByProductOut]


class ChurnedCustomerOut(BaseModel):
    customer_id: uuid.UUID
    name: str | None
    phone: str
    last_delivery_date: date | None
    days_inactive: int
    cancelled_at: str | None


class ChurnOut(BaseModel):
    year: int
    month: int
    active_start: int
    active_end: int
    new_customers: int
    churned_customers: int
    net_change: int
    churned_list: list[ChurnedCustomerOut]


class DailyDeliveryPointOut(BaseModel):
    date: date
    scheduled: int
    delivered: int
    skipped: int
    failed: int
    pending: int


class DeliveryByRouteOut(BaseModel):
    route_id: uuid.UUID | None
    route_name: str
    delivered: int
    skipped: int
    failed: int
    total: int


class DeliveryByBoyOut(BaseModel):
    delivery_boy_id: uuid.UUID | None
    name: str
    phone: str
    delivered: int
    skipped: int
    failed: int
    total: int


class DailyDeliveryOut(BaseModel):
    from_date: date
    to_date: date
    total_scheduled: int
    total_delivered: int
    total_skipped: int
    total_failed: int
    completion_rate_pct: float
    series: list[DailyDeliveryPointOut]
    by_route: list[DeliveryByRouteOut]
    by_delivery_boy: list[DeliveryByBoyOut]


class BottleOutstandingCustomerOut(BaseModel):
    customer_id: uuid.UUID
    name: str | None
    phone: str
    area: str | None
    route_name: str | None
    bottles_out: int
    last_return_date: date | None
    days_since_return: int
    ever_returned: bool


class BottleOutstandingOut(BaseModel):
    total_bottles_out: int
    customers_with_outstanding: int
    customers_above_5: int
    oldest_days: int
    customers: list[BottleOutstandingCustomerOut]


# --------- revenue ---------

@router.get("/reports/revenue", response_model=RevenueOut)
async def revenue(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    group_by: Literal["day", "week", "month"] = "day",
    view_mode: Literal["issued_date", "bill_period"] = "issued_date",
    db: AsyncSession = Depends(get_db),
):
    try:
        r = await rs.revenue_report(
            db, from_date=from_date, to_date=to_date,
            group_by=group_by, view_mode=view_mode,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return r


@router.get("/reports/revenue/export")
async def revenue_export(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    group_by: Literal["day", "week", "month"] = "day",
    view_mode: Literal["issued_date", "bill_period"] = "issued_date",
    db: AsyncSession = Depends(get_db),
):
    r = await rs.revenue_report(
        db, from_date=from_date, to_date=to_date,
        group_by=group_by, view_mode=view_mode,
    )

    def rows():
        yield ["--- Summary ---"]
        yield ["From", r.from_date.isoformat()]
        yield ["To", r.to_date.isoformat()]
        yield ["Group by", r.group_by]
        yield ["View mode", view_mode]
        yield ["Total revenue (₹)", r.total_revenue_paise / 100]
        yield ["Total collected (₹)", r.total_collected_paise / 100]
        yield ["Total outstanding (₹)", r.total_outstanding_paise / 100]
        yield ["Avg invoice (₹)", r.avg_invoice_paise / 100]
        yield ["Invoice count", r.invoice_count]
        yield []
        yield ["--- Series ---"]
        yield ["period", "revenue_rupees", "collected_rupees", "invoice_count"]
        for s in r.series:
            yield [s.period, s.revenue_paise / 100, s.collected_paise / 100, s.invoice_count]
        yield []
        yield ["--- By product ---"]
        yield ["product_sku", "product_name", "revenue_rupees", "quantity_total"]
        for p in r.by_product:
            yield [p.product_sku, p.product_name, p.revenue_paise / 100, p.quantity_total]

    return stream_csv(
        filename=f"posuhtik_revenue_{from_date.isoformat()}_{to_date.isoformat()}.csv",
        header=["field", "value", "value2", "value3"],
        rows=(r + [""] * (4 - len(r)) for r in rows()),
    )


# --------- churn ---------

@router.get("/reports/churn", response_model=ChurnOut)
async def churn(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    db: AsyncSession = Depends(get_db),
):
    y, m = month.split("-")
    try:
        r = await rs.churn_report(db, year=int(y), month=int(m))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ChurnOut(
        year=r.year, month=r.month,
        active_start=r.active_start, active_end=r.active_end,
        new_customers=r.new_customers, churned_customers=r.churned_customers,
        net_change=r.net_change,
        churned_list=[
            ChurnedCustomerOut(
                customer_id=c.customer_id, name=c.name, phone=c.phone,
                last_delivery_date=c.last_delivery_date,
                days_inactive=c.days_inactive,
                cancelled_at=c.cancelled_at.isoformat() if c.cancelled_at else None,
            )
            for c in r.churned_list
        ],
    )


@router.get("/reports/churn/export")
async def churn_export(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    db: AsyncSession = Depends(get_db),
):
    y, m = month.split("-")
    r = await rs.churn_report(db, year=int(y), month=int(m))
    header = [
        "name", "phone", "last_delivery_date",
        "days_inactive", "cancelled_at",
    ]
    rows = (
        [c.name, c.phone, c.last_delivery_date.isoformat() if c.last_delivery_date else None,
         c.days_inactive, c.cancelled_at.isoformat() if c.cancelled_at else None]
        for c in r.churned_list
    )
    return stream_csv(
        filename=f"posuhtik_churn_{month}.csv",
        header=header,
        rows=rows,
    )


# --------- daily delivery ---------

@router.get("/reports/daily-delivery", response_model=DailyDeliveryOut)
async def daily_delivery(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    route_id: uuid.UUID | None = None,
    delivery_boy_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    try:
        r = await rs.daily_delivery_report(
            db, from_date=from_date, to_date=to_date,
            route_id=route_id, delivery_boy_id=delivery_boy_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return r


@router.get("/reports/daily-delivery/export")
async def daily_delivery_export(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    route_id: uuid.UUID | None = None,
    delivery_boy_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    r = await rs.daily_delivery_report(
        db, from_date=from_date, to_date=to_date,
        route_id=route_id, delivery_boy_id=delivery_boy_id,
    )
    header = ["date", "scheduled", "delivered", "skipped", "failed", "pending"]
    rows = (
        [p.date.isoformat(), p.scheduled, p.delivered, p.skipped, p.failed, p.pending]
        for p in r.series
    )
    return stream_csv(
        filename=f"posuhtik_delivery_{from_date.isoformat()}_{to_date.isoformat()}.csv",
        header=header,
        rows=rows,
    )


# --------- bottle outstanding ---------

@router.get("/reports/bottle-outstanding", response_model=BottleOutstandingOut)
async def bottle_outstanding(db: AsyncSession = Depends(get_db)):
    r = await rs.bottle_outstanding_report(db)
    return r


@router.get("/reports/bottle-outstanding/export")
async def bottle_outstanding_export(db: AsyncSession = Depends(get_db)):
    r = await rs.bottle_outstanding_report(db)
    header = [
        "name", "phone", "area", "route_name",
        "bottles_out", "last_return_date", "days_since_return", "ever_returned",
    ]
    rows = (
        [c.name, c.phone, c.area, c.route_name,
         c.bottles_out,
         c.last_return_date.isoformat() if c.last_return_date else None,
         c.days_since_return,
         "yes" if c.ever_returned else "no"]
        for c in r.customers
    )
    return stream_csv(
        filename="posuhtik_bottles_outstanding.csv",
        header=header,
        rows=rows,
    )


# --------- billing register (server-side migration from 2B.6 client CSV) ---------

@router.get("/billing/register/export")
async def billing_register_export(
    year: int = Query(..., ge=2020, le=2100),
    month: int = Query(..., ge=1, le=12),
    db: AsyncSession = Depends(get_db),
):
    rows_res = (await db.execute(
        select(Invoice, User).join(User, User.id == Invoice.customer_id)
        .where(Invoice.year == year, Invoice.month == month)
        .order_by(User.name.asc())
    )).all()

    header = [
        "invoice_id", "customer_name", "customer_phone",
        "year", "month",
        "subtotal_rupees", "adjustments_rupees", "total_rupees",
        "amount_paid_rupees", "balance_due_rupees",
        "status", "issued_at", "due_date", "paid_at",
    ]

    def rows():
        for inv, u in rows_res:
            yield [
                str(inv.id), u.name, u.phone,
                inv.year, inv.month,
                inv.subtotal_paise / 100,
                inv.adjustments_paise / 100,
                inv.total_paise / 100,
                inv.amount_paid_paise / 100,
                max(0, inv.total_paise - inv.amount_paid_paise) / 100,
                inv.status.value if hasattr(inv.status, "value") else str(inv.status),
                inv.issued_at.isoformat() if inv.issued_at else None,
                inv.due_date.isoformat() if inv.due_date else None,
                inv.paid_at.isoformat() if inv.paid_at else None,
            ]

    return stream_csv(
        filename=f"posuhtik_billing_register_{year}-{month:02d}.csv",
        header=header,
        rows=rows(),
    )
