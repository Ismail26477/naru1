"""Delivery / route / invoice / bottle schemas."""
from pydantic import BaseModel, Field
from datetime import date, datetime
import uuid
from app.schemas.common import ORMBase


class RouteCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    delivery_boy_id: uuid.UUID | None = None
    area: str | None = None


class RouteOut(ORMBase):
    id: uuid.UUID
    name: str
    delivery_boy_id: uuid.UUID | None
    area: str | None


class RouteStopIn(BaseModel):
    customer_id: uuid.UUID
    sequence: int = Field(..., ge=0)


class RouteStopOut(ORMBase):
    id: uuid.UUID
    route_id: uuid.UUID
    customer_id: uuid.UUID
    sequence: int


class ReorderStopsBody(BaseModel):
    stops: list[RouteStopIn]


class DeliveryOrderOut(ORMBase):
    id: uuid.UUID
    customer_id: uuid.UUID
    subscription_id: uuid.UUID
    product_id: uuid.UUID
    delivery_date: date
    quantity: int
    unit_price_paise: int
    status: str
    delivered_quantity: int | None
    bottles_returned: int | None
    notes: str | None
    skip_reason: str | None
    delivered_at: datetime | None
    delivery_boy_id: uuid.UUID | None
    cutoff_locked_at: datetime | None


class ConfirmDeliveryBody(BaseModel):
    delivered_quantity: int = Field(..., ge=0)
    bottles_returned: int = Field(0, ge=0)
    notes: str | None = Field(None, max_length=500)


class SkipDeliveryBody(BaseModel):
    reason: str = Field(..., min_length=1, max_length=255)


class InvoiceLineOut(ORMBase):
    id: uuid.UUID
    date: date
    product_id: uuid.UUID
    quantity: int
    price_paise: int
    total_paise: int


class InvoiceOut(ORMBase):
    id: uuid.UUID
    customer_id: uuid.UUID
    month: int
    year: int
    subtotal_paise: int
    adjustments_paise: int
    total_paise: int
    status: str
    issued_at: datetime | None
    due_date: date | None
    paid_at: datetime | None
    pdf_url: str | None


class InvoiceDetailOut(InvoiceOut):
    line_items: list[InvoiceLineOut]


class BottleBalanceOut(BaseModel):
    customer_id: uuid.UUID
    balance: int


class WalletOut(BaseModel):
    customer_id: uuid.UUID
    balance_paise: int
    recent_transactions: list[dict]


class DailyDeliveryReportRow(BaseModel):
    product_id: uuid.UUID
    product_name: str
    total_quantity: int
    delivered_quantity: int
    pending: int
    skipped: int


class DailyDeliveryReport(BaseModel):
    date: date
    rows: list[DailyDeliveryReportRow]
    total_orders: int


class BottleOutstandingRow(BaseModel):
    customer_id: uuid.UUID
    customer_name: str | None
    customer_phone: str
    balance: int


class JobRunResult(BaseModel):
    job: str
    affected: int
    details: dict = {}
