"""Admin-specific schemas (dashboard stats, audit log)."""
from __future__ import annotations
from datetime import date, datetime
import uuid
from pydantic import BaseModel, Field


class DashboardTrendPoint(BaseModel):
    date: date
    value: int  # count for deliveries / signups; paise for revenue


class DashboardStats(BaseModel):
    # Headline KPIs
    today_deliveries: int
    mtd_revenue_paise: int
    new_customers_mtd: int
    pending_approvals: int
    bottles_outstanding: int
    overdue_invoices: int
    active_subscriptions: int

    # Charts
    deliveries_trend_14d: list[DashboardTrendPoint]
    revenue_trend_30d: list[DashboardTrendPoint]
    signups_trend_30d: list[DashboardTrendPoint]

    generated_at: datetime


class AuditLogOut(BaseModel):
    id: uuid.UUID
    actor_user_id: uuid.UUID | None
    actor_role: str | None
    action: str
    entity_type: str | None
    entity_id: str | None
    before_state: dict | None
    after_state: dict | None
    reason: str | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime

    model_config = {"from_attributes": True}



# ---------- Customer list + detail ----------

class AdminCustomerRow(BaseModel):
    id: uuid.UUID
    phone: str
    name: str | None
    email: str | None
    approved_at: datetime | None
    is_active: bool
    created_at: datetime
    wallet_balance_paise: int
    bottle_balance: int
    active_subs_count: int
    area: str | None
    last_delivery_date: date | None

    model_config = {"from_attributes": True}


class PaginatedCustomers(BaseModel):
    items: list[AdminCustomerRow]
    total: int
    page: int
    page_size: int


class AdminAddressOut(BaseModel):
    id: uuid.UUID
    line1: str
    line2: str | None
    area: str
    city: str
    pincode: str
    is_default: bool

    model_config = {"from_attributes": True}


class AdminCustomerDetail(BaseModel):
    id: uuid.UUID
    phone: str
    name: str | None
    email: str | None
    role: str
    approved_at: datetime | None
    is_active: bool
    wallet_balance_paise: int
    bottle_balance: int
    created_at: datetime
    addresses: list[AdminAddressOut]
    active_subs_count: int
    total_subs_count: int
    invoice_count: int
    open_invoices_paise: int

    model_config = {"from_attributes": True}


# ---------- Adjustment & mutation bodies ----------

class WalletAdjustmentBody(BaseModel):
    amount_paise: int = Field(..., description="positive=credit, negative=debit, non-zero")
    reason: str = Field(..., min_length=10, max_length=500)
    reference_id: str | None = Field(None, max_length=120)
    force: bool = False


class BottleAdjustmentBody(BaseModel):
    change: int = Field(..., description="positive=owe more, negative=return, non-zero")
    reason: str = Field(..., min_length=10, max_length=500)
    force: bool = False


class ReasonBody(BaseModel):
    reason: str = Field(..., min_length=10, max_length=500)


class OptionalReasonBody(BaseModel):
    reason: str | None = Field(None, max_length=500)


# ---------- Paginated children of customer ----------

class WalletTransactionOut(BaseModel):
    id: uuid.UUID
    change_paise: int
    balance_after_paise: int
    reason: str
    reference_id: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class BottleLedgerRow(BaseModel):
    id: uuid.UUID
    change: int
    reason: str
    note: str | None
    delivery_order_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PageOut(BaseModel):
    total: int
    page: int
    page_size: int




# ---------- Routes (2B.3) ----------

class RouteCreateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    area: str | None = Field(None, max_length=200)
    delivery_boy_id: uuid.UUID | None = None


class RouteUpdateBody(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    area: str | None = Field(None, max_length=200)
    delivery_boy_id: uuid.UUID | None = None
    active: bool | None = None


class RouteStopSummary(BaseModel):
    id: uuid.UUID
    sequence: int
    customer_id: uuid.UUID
    customer_name: str | None
    customer_phone: str
    customer_area: str | None
    customer_lat: float | None
    customer_lng: float | None
    bottle_balance: int

    model_config = {"from_attributes": True}


class RouteListRow(BaseModel):
    id: uuid.UUID
    name: str
    area: str | None
    active: bool
    delivery_boy_id: uuid.UUID | None
    delivery_boy_name: str | None
    delivery_boy_phone: str | None
    stops_count: int
    last_delivery_date: date | None

    model_config = {"from_attributes": True}


class PaginatedRoutes(PageOut):
    items: list[RouteListRow]


class RouteDetail(BaseModel):
    id: uuid.UUID
    name: str
    area: str | None
    active: bool
    delivery_boy_id: uuid.UUID | None
    delivery_boy_name: str | None
    delivery_boy_phone: str | None
    stops: list[RouteStopSummary]

    model_config = {"from_attributes": True}


class ReorderStopItem(BaseModel):
    stop_id: uuid.UUID
    sequence: int = Field(..., ge=1)


class ReorderStopsBody2(BaseModel):
    sequence: list[ReorderStopItem] = Field(..., min_length=1)


# ---------- Delivery orders (2B.4) ----------

class DeliveryOrderRow(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    customer_name: str | None
    customer_phone: str
    product_id: uuid.UUID
    product_name: str
    product_requires_bottle: bool
    subscription_id: uuid.UUID | None
    delivery_date: date
    quantity: int
    delivered_quantity: int | None
    bottles_returned: int | None
    unit_price_paise: int
    status: str
    delivery_boy_id: uuid.UUID | None
    delivery_boy_name: str | None
    route_id: uuid.UUID | None
    route_name: str | None
    route_sequence: int | None
    cutoff_locked_at: datetime | None
    delivered_at: datetime | None
    skip_reason: str | None

    model_config = {"from_attributes": True}


class DeliveryOrderKPIs(BaseModel):
    scheduled: int
    delivered: int
    pending: int
    skipped: int
    failed: int


class PaginatedDeliveryOrders(PageOut):
    kpis: DeliveryOrderKPIs
    items: list[DeliveryOrderRow]


class DeliveryOrderDetail(DeliveryOrderRow):
    # Context the operations board wants on the detail screen
    customer_bottle_balance: int
    bottle_entries: list[BottleLedgerRow]
    audit: list[AuditLogOut]


class OverrideBody(BaseModel):
    status: str = Field(..., pattern=r"^(pending|delivered|skipped|failed)$")
    delivered_quantity: int | None = Field(None, ge=0)
    bottles_returned: int | None = Field(None, ge=0)
    reason: str = Field(..., min_length=10, max_length=500)


class BulkSkipBody(BaseModel):
    order_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=200)
    reason: str = Field(..., min_length=10, max_length=500)



class AddStopBody(BaseModel):
    customer_id: uuid.UUID
    position: int | None = Field(None, ge=1)

class PaginatedWallet(PageOut):
    balance_paise: int
    items: list[WalletTransactionOut]


class PaginatedBottles(PageOut):
    balance: int
    items: list[BottleLedgerRow]
