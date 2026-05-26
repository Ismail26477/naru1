"""Subscription and schedule override models."""
from datetime import datetime, date
import uuid
from sqlalchemy import String, Integer, Boolean, DateTime, Date, ForeignKey, Enum as SqlEnum, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import SubscriptionFrequency, SubscriptionStatus
from app.core.time_utils import now_utc


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    frequency: Mapped[SubscriptionFrequency] = mapped_column(SqlEnum(SubscriptionFrequency, name="subscription_frequency"), nullable=False)
    # Weekday selection for weekly / custom frequencies. Stored as CSV of ints
    # where 0=Mon..6=Sun (e.g. "0,2,4" = Mon/Wed/Fri). NULL for daily / alternate.
    custom_days: Mapped[str | None] = mapped_column(String(20))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[SubscriptionStatus] = mapped_column(
        SqlEnum(SubscriptionStatus, name="subscription_status"),
        default=SubscriptionStatus.ACTIVE,
        nullable=False,
    )
    pause_from: Mapped[date | None] = mapped_column(Date)
    pause_until: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)

    customer: Mapped["User"] = relationship(back_populates="subscriptions", foreign_keys=[customer_id])
    product: Mapped["Product"] = relationship()
    overrides: Mapped[list["SubscriptionScheduleOverride"]] = relationship(
        back_populates="subscription", cascade="all, delete-orphan"
    )


class SubscriptionScheduleOverride(Base):
    __tablename__ = "subscription_schedule_overrides"
    __table_args__ = (UniqueConstraint("subscription_id", "date", name="uq_subscription_override_date"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subscription_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    quantity_override: Mapped[int | None] = mapped_column(Integer)
    skip: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    subscription: Mapped[Subscription] = relationship(back_populates="overrides")
