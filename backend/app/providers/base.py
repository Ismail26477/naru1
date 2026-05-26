"""Provider interfaces (abstract). Real + stub implementations live beside this file."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SmsResult:
    success: bool
    message_id: str | None = None
    provider: str = ""
    error: str | None = None


class SMSProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def send_otp(self, phone: str, otp: str) -> SmsResult: ...

    @abstractmethod
    async def send_text(self, phone: str, template: str, context: dict) -> SmsResult: ...


@dataclass
class PushResult:
    success: bool
    provider: str = ""
    error: str | None = None


class PushProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def send(self, user_token: str, title: str, body: str, data: dict | None = None) -> PushResult: ...


@dataclass
class RazorpayOrder:
    order_id: str
    amount_paise: int
    currency: str
    status: str
    key_id: str


class PaymentProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def create_order(self, amount_paise: int, receipt: str, notes: dict | None = None) -> RazorpayOrder: ...

    @abstractmethod
    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool: ...

    @abstractmethod
    def verify_payment_signature(self, order_id: str, payment_id: str, signature: str) -> bool: ...


@dataclass
class GeocodeResult:
    lat: float
    lng: float
    pending: bool = False


class GeocodingProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def geocode(self, address_text: str) -> GeocodeResult: ...


class StorageProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Returns a URL (or local path-based URL) to the stored object."""

    @abstractmethod
    async def get(self, key: str) -> bytes | None:
        """Fetch the object at `key`. Returns None if the object does not exist."""
