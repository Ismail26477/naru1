"""Stub implementations — used in dev / Phase 1. Contract-identical to real providers."""
from __future__ import annotations
import logging
import secrets
import os
import hashlib
import hmac
from pathlib import Path
from app.providers.base import (
    SMSProvider, SmsResult,
    PushProvider, PushResult,
    PaymentProvider, RazorpayOrder,
    GeocodingProvider, GeocodeResult,
    StorageProvider,
)
from app.core.config import settings

log = logging.getLogger("providers.stub")


class StubSMSProvider(SMSProvider):
    name = "stub"

    async def send_otp(self, phone: str, otp: str) -> SmsResult:
        log.info(f"[STUB-SMS] OTP to {phone}: {otp}", extra={"phone": phone, "otp": otp})
        return SmsResult(success=True, message_id=f"stub-{secrets.token_hex(6)}", provider=self.name)

    async def send_text(self, phone: str, template: str, context: dict) -> SmsResult:
        log.info(f"[STUB-SMS] {template} to {phone}: {context}")
        return SmsResult(success=True, message_id=f"stub-{secrets.token_hex(6)}", provider=self.name)


class StubPushProvider(PushProvider):
    name = "stub"

    async def send(self, user_token: str, title: str, body: str, data: dict | None = None) -> PushResult:
        log.info(f"[STUB-PUSH] token={user_token} title={title} body={body} data={data}")
        return PushResult(success=True, provider=self.name)


class StubPaymentProvider(PaymentProvider):
    name = "stub"

    async def create_order(self, amount_paise: int, receipt: str, notes: dict | None = None) -> RazorpayOrder:
        order_id = f"stub_order_{secrets.token_hex(8)}"
        log.info(f"[STUB-PAY] create_order amount={amount_paise} receipt={receipt} id={order_id}")
        return RazorpayOrder(
            order_id=order_id, amount_paise=amount_paise, currency="INR",
            status="created", key_id="rzp_test_stub",
        )

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        # In dev/stub: accept any non-empty signature. Real provider will HMAC-verify.
        return bool(signature)

    def verify_payment_signature(self, order_id: str, payment_id: str, signature: str) -> bool:
        return bool(signature)


class StubGeocoder(GeocodingProvider):
    name = "stub"
    NAGPUR_LAT = 21.1458
    NAGPUR_LNG = 79.0882

    async def geocode(self, address_text: str) -> GeocodeResult:
        return GeocodeResult(lat=self.NAGPUR_LAT, lng=self.NAGPUR_LNG, pending=True)


class LocalStorageProvider(StorageProvider):
    name = "local"

    def __init__(self, base_path: str = settings.LOCAL_STORAGE_PATH, base_url: str = settings.LOCAL_STORAGE_BASE_URL):
        self.base_path = Path(base_path)
        self.base_url = base_url.rstrip("/")
        self.base_path.mkdir(parents=True, exist_ok=True)

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        full = self.base_path / key
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(data)
        return f"{self.base_url}/{key}"

    async def get(self, key: str) -> bytes | None:
        full = self.base_path / key
        if not full.exists():
            return None
        return full.read_bytes()
