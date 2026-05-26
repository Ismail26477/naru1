"""Product model."""
from datetime import datetime
import uuid
from sqlalchemy import String, Boolean, Integer, DateTime, Enum as SqlEnum, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import ProductUnit
from app.core.time_utils import now_utc


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    sku: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    unit: Mapped[ProductUnit] = mapped_column(SqlEnum(ProductUnit, name="product_unit"), nullable=False)
    # Money: integer paise (not float).
    price_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    requires_bottle: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(String(2000))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
