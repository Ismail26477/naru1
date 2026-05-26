"""Product schemas."""
from pydantic import BaseModel, Field
import uuid
from datetime import datetime
from app.schemas.common import ORMBase


class ProductOut(ORMBase):
    id: uuid.UUID
    name: str
    sku: str
    unit: str
    price_paise: int
    requires_bottle: bool
    image_url: str | None
    active: bool


class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    sku: str = Field(..., min_length=1, max_length=40)
    unit: str = Field(..., pattern=r"^(litre|kg|piece)$")
    price_paise: int = Field(..., ge=0)
    requires_bottle: bool = False
    image_url: str | None = None
    active: bool = True
