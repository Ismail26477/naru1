"""Application configuration via pydantic-settings."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="/app/backend/.env", env_file_encoding="utf-8", extra="ignore"
    )

    APP_NAME: str = "Posuhtik"
    APP_ENV: str = "development"
    DEBUG: bool = True

    DATABASE_URL: str
    DATABASE_URL_SYNC: str
    TEST_DATABASE_URL: str | None = None

    REDIS_URL: str = "redis://localhost:6379/0"

    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    SMS_PROVIDER: str = "stub"
    PAYMENT_PROVIDER: str = "stub"
    PUSH_PROVIDER: str = "stub"
    GEOCODER_PROVIDER: str = "stub"
    STORAGE_PROVIDER: str = "local"

    MSG91_AUTH_KEY: str = ""
    MSG91_TEMPLATE_ID: str = ""
    MSG91_SENDER_ID: str = "POSUTK"

    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""

    FCM_SERVER_KEY: str = ""
    FCM_SERVICE_ACCOUNT_JSON: str = ""

    GOOGLE_MAPS_API_KEY: str = ""

    S3_BUCKET: str = ""
    S3_REGION: str = "ap-south-1"
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""
    S3_ENDPOINT: str = ""

    LOCAL_STORAGE_PATH: str = "/app/backend/storage"
    LOCAL_STORAGE_BASE_URL: str = "/static"

    TIMEZONE: str = "Asia/Kolkata"
    CUTOFF_HOUR_IST: int = 20
    BILLING_DAY_OF_MONTH: int = 1
    OVERRIDE_MAX_DAYS_BACK: int = 7

    CORS_ORIGINS: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_development(self) -> bool:
        return self.APP_ENV.lower() == "development"

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
