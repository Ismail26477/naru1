"""Empty shells for real integrations. To be wired later; swap via env var only."""
from app.providers.base import (
    SMSProvider, SmsResult, PaymentProvider, RazorpayOrder,
    PushProvider, PushResult, GeocodingProvider, GeocodeResult, StorageProvider,
)


class Msg91SMSProvider(SMSProvider):
    name = "msg91"

    async def send_otp(self, phone: str, otp: str) -> SmsResult:
        raise NotImplementedError("MSG91 integration pending (Phase 2)")

    async def send_text(self, phone: str, template: str, context: dict) -> SmsResult:
        raise NotImplementedError("MSG91 integration pending (Phase 2)")


class RazorpayPaymentProvider(PaymentProvider):
    name = "razorpay"

    async def create_order(self, amount_paise: int, receipt: str, notes: dict | None = None) -> RazorpayOrder:
        raise NotImplementedError("Razorpay integration pending (Phase 2)")

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        raise NotImplementedError("Razorpay integration pending (Phase 2)")

    def verify_payment_signature(self, order_id: str, payment_id: str, signature: str) -> bool:
        raise NotImplementedError("Razorpay integration pending (Phase 2)")


class FcmPushProvider(PushProvider):
    name = "fcm"

    async def send(self, user_token: str, title: str, body: str, data: dict | None = None) -> PushResult:
        raise NotImplementedError("FCM integration pending (Phase 2)")


class GoogleGeocoder(GeocodingProvider):
    name = "google"

    async def geocode(self, address_text: str) -> GeocodeResult:
        raise NotImplementedError("Google Maps integration pending (Phase 2)")


class S3StorageProvider(StorageProvider):
    name = "s3"

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        raise NotImplementedError("S3 integration pending (Phase 2)")

    async def get(self, key: str) -> bytes | None:
        raise NotImplementedError("S3 integration pending (Phase 2)")
