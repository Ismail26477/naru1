"""Invoices, line items, payments, wallet."""
from datetime import datetime, date
import uuid
from sqlalchemy import Integer, DateTime, Date, ForeignKey, String, Enum as SqlEnum, UniqueConstraint, Boolean, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import InvoiceStatus, PaymentStatus, PaymentMethod
from app.core.time_utils import now_utc


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (UniqueConstraint("customer_id", "year", "month", name="uq_invoice_customer_period"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    subtotal_paise: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    adjustments_paise: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_paise: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    amount_paid_paise: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(
        SqlEnum(InvoiceStatus, name="invoice_status"),
        default=InvoiceStatus.DRAFT, nullable=False, index=True,
    )
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_date: Mapped[date | None] = mapped_column(Date)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pdf_url: Mapped[str | None] = mapped_column(String(500))
    pdf_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pdf_storage_path: Mapped[str | None] = mapped_column(String(500))
    regenerated_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    has_post_billing_adjustments: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_regenerated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_regenerated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    line_items: Mapped[list["InvoiceLineItem"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceLineItem.date"
    )
    adjustments: Mapped[list["InvoiceAdjustment"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceAdjustment.created_at"
    )


class InvoiceLineItem(Base):
    __tablename__ = "invoice_line_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    total_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    delivery_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("delivery_orders.id", ondelete="SET NULL"))

    invoice: Mapped[Invoice] = relationship(back_populates="line_items")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="SET NULL"), index=True)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[PaymentMethod] = mapped_column(SqlEnum(PaymentMethod, name="payment_method"), nullable=False)
    razorpay_order_id: Mapped[str | None] = mapped_column(String(120), index=True)
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(120), index=True)
    razorpay_signature: Mapped[str | None] = mapped_column(String(255))
    reference: Mapped[str | None] = mapped_column(String(255))  # generic external ref (UTR, bank txn id, cheque #)
    status: Mapped[PaymentStatus] = mapped_column(
        SqlEnum(PaymentStatus, name="payment_status"),
        default=PaymentStatus.CREATED, nullable=False,
    )
    raw_response: Mapped[str | None] = mapped_column(String(4000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    change_paise: Mapped[int] = mapped_column(Integer, nullable=False)  # positive=credit, negative=debit
    reason: Mapped[str] = mapped_column(String(120), nullable=False)
    reference_id: Mapped[str | None] = mapped_column(String(120))
    balance_after_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False, index=True)


class InvoiceAdjustmentKind(str):
    WALLET_CREDIT = "wallet_credit"
    MANUAL_CREDIT = "manual_credit"
    MANUAL_DEBIT = "manual_debit"
    OVERRIDE_ADJUSTMENT = "override_adjustment"


class InvoiceAdjustment(Base):
    """Signed ledger of adjustments to an invoice (wallet application, manual corrections, override re-bills).

    Positive `amount_paise` = debit (increases amount due).
    Negative `amount_paise` = credit (reduces amount due).
    """
    __tablename__ = "invoice_adjustments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)  # signed
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    reference_id: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False, index=True)

    invoice: Mapped[Invoice] = relationship(back_populates="adjustments")

