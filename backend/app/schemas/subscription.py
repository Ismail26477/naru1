"""Subscription schemas."""
from pydantic import BaseModel, Field, ConfigDict, model_validator
from datetime import date, datetime
import uuid
from app.schemas.common import ORMBase


class SubscriptionCreate(BaseModel):
    product_id: uuid.UUID
    quantity: int = Field(..., ge=1, le=50)
    frequency: str = Field(..., pattern=r"^(daily|alternate|weekly|custom)$")
    custom_days: str | None = None  # e.g. "0,2,4"
    start_date: date
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_custom_days(self):
        if self.frequency in ("weekly", "custom") and not self.custom_days:
            raise ValueError("custom_days required for weekly/custom frequency")
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on/after start_date")
        return self


class SubscriptionUpdate(BaseModel):
    quantity: int | None = Field(None, ge=1, le=50)
    frequency: str | None = Field(None, pattern=r"^(daily|alternate|weekly|custom)$")
    custom_days: str | None = None
    end_date: date | None = None
    status: str | None = Field(None, pattern=r"^(active|paused|cancelled)$")
    pause_from: date | None = None
    pause_until: date | None = None


class SubscriptionOut(ORMBase):
    id: uuid.UUID
    customer_id: uuid.UUID
    product_id: uuid.UUID
    quantity: int
    frequency: str
    custom_days: str | None
    start_date: date
    end_date: date | None
    status: str
    pause_from: date | None
    pause_until: date | None
    created_at: datetime


class ScheduleOverrideCreate(BaseModel):
    date: date
    skip: bool = False
    quantity_override: int | None = Field(None, ge=0, le=50)
    reason: str | None = Field(None, max_length=255)

    @model_validator(mode="after")
    def one_of(self):
        if not self.skip and self.quantity_override is None:
            raise ValueError("provide skip=true or quantity_override")
        return self


class ScheduleOverrideOut(ORMBase):
    id: uuid.UUID
    subscription_id: uuid.UUID
    date: date
    quantity_override: int | None
    skip: bool
    reason: str | None
