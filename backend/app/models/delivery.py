"""Delivery orders and bottle ledger."""
from datetime import datetime, date
import uuid
from sqlalchemy import Integer, DateTime, Date, ForeignKey, String, Enum as SqlEnum, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import DeliveryOrderStatus, BottleReason
from app.core.time_utils import now_utc


class DeliveryOrder(Base):
    __tablename__ = "delivery_orders"
    __table_args__ = (
        UniqueConstraint("subscription_id", "delivery_date", name="uq_delivery_sub_date"),
        Index("ix_delivery_orders_date_status", "delivery_date", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    subscription_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    delivery_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[DeliveryOrderStatus] = mapped_column(
        SqlEnum(DeliveryOrderStatus, name="delivery_order_status"),
        default=DeliveryOrderStatus.PENDING, nullable=False,
    )
    delivered_quantity: Mapped[int | None] = mapped_column(Integer)
    bottles_returned: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(String(500))
    skip_reason: Mapped[str | None] = mapped_column(String(255))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_boy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    cutoff_locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)


class BottleLedger(Base):
    __tablename__ = "bottle_ledger"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    delivery_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("delivery_orders.id", ondelete="SET NULL"), index=True)
    change: Mapped[int] = mapped_column(Integer, nullable=False)  # +N on delivery, -N on return
    reason: Mapped[BottleReason] = mapped_column(SqlEnum(BottleReason, name="bottle_reason"), nullable=False)
    note: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False, index=True)
