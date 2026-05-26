"""User & address schemas."""
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from datetime import datetime
import uuid
from app.schemas.common import ORMBase
from app.models.enums import UserRole


class UserOut(ORMBase):
    id: uuid.UUID
    phone: str
    name: str | None
    email: str | None
    role: str
    approved_at: datetime | None
    is_active: bool
    wallet_balance_paise: int
    created_at: datetime


class UpdateMeBody(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    email: EmailStr | None = None


class AdminUserListItem(ORMBase):
    id: uuid.UUID
    phone: str
    name: str | None
    email: str | None
    role: str
    approved_at: datetime | None
    is_active: bool
    created_at: datetime


class AddressCreate(BaseModel):
    line1: str = Field(..., min_length=1, max_length=255)
    line2: str | None = Field(None, max_length=255)
    area: str = Field(..., min_length=1, max_length=120)
    city: str = "Nagpur"
    pincode: str = Field(..., min_length=6, max_length=10)
    is_default: bool = False


class AddressOut(ORMBase):
    id: uuid.UUID
    line1: str
    line2: str | None
    area: str
    city: str
    pincode: str
    lat: float | None
    lng: float | None
    is_default: bool
    geocoding_pending: bool
