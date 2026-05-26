"""Provider factory — resolves implementation from config (zero code change to switch)."""
from __future__ import annotations
from functools import lru_cache

from app.core.config import settings
from app.providers.base import SMSProvider, PaymentProvider, PushProvider, GeocodingProvider, StorageProvider
from app.providers.stubs import (
    StubSMSProvider, StubPaymentProvider, StubPushProvider, StubGeocoder, LocalStorageProvider,
)
from app.providers.real import (
    Msg91SMSProvider, RazorpayPaymentProvider, FcmPushProvider, GoogleGeocoder, S3StorageProvider,
)


@lru_cache
def get_sms_provider() -> SMSProvider:
    return Msg91SMSProvider() if settings.SMS_PROVIDER == "msg91" else StubSMSProvider()


@lru_cache
def get_payment_provider() -> PaymentProvider:
    return RazorpayPaymentProvider() if settings.PAYMENT_PROVIDER == "razorpay" else StubPaymentProvider()


@lru_cache
def get_push_provider() -> PushProvider:
    return FcmPushProvider() if settings.PUSH_PROVIDER == "fcm" else StubPushProvider()


@lru_cache
def get_geocoder() -> GeocodingProvider:
    return GoogleGeocoder() if settings.GEOCODER_PROVIDER == "google" else StubGeocoder()


@lru_cache
def get_storage_provider() -> StorageProvider:
    return S3StorageProvider() if settings.STORAGE_PROVIDER == "s3" else LocalStorageProvider()
