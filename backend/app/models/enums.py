"""Domain enums used across models and schemas."""
import enum


class UserRole(str, enum.Enum):
    CUSTOMER = "customer"
    ADMIN = "admin"
    DELIVERY = "delivery"


class ProductUnit(str, enum.Enum):
    LITRE = "litre"
    KG = "kg"
    PIECE = "piece"


class SubscriptionFrequency(str, enum.Enum):
    DAILY = "daily"
    ALTERNATE = "alternate"
    WEEKLY = "weekly"
    CUSTOM = "custom"


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class DeliveryOrderStatus(str, enum.Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    SKIPPED = "skipped"
    FAILED = "failed"


class InvoiceStatus(str, enum.Enum):
    DRAFT = "draft"
    ISSUED = "issued"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    OVERDUE = "overdue"


class PaymentStatus(str, enum.Enum):
    CREATED = "created"
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    REFUNDED = "refunded"


class PaymentMethod(str, enum.Enum):
    WALLET = "wallet"
    RAZORPAY_UPI = "razorpay_upi"
    RAZORPAY_CARD = "razorpay_card"
    CASH = "cash"
    UPI = "upi"
    BANK_TRANSFER = "bank_transfer"
    OTHER = "other"


class NotificationChannel(str, enum.Enum):
    PUSH = "push"
    SMS = "sms"
    WHATSAPP = "whatsapp"


class NotificationStatus(str, enum.Enum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"


class BottleReason(str, enum.Enum):
    DELIVERED = "delivered"
    RETURNED = "returned"
    ADJUSTMENT = "adjustment"
