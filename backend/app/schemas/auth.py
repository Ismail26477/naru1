"""Auth schemas."""
from pydantic import BaseModel, Field, field_validator
import re


class RequestOtpBody(BaseModel):
    phone: str = Field(..., min_length=10, max_length=20)

    @field_validator("phone")
    @classmethod
    def normalize(cls, v: str) -> str:
        v = v.strip().replace(" ", "")
        if not re.match(r"^\+?\d{10,15}$", v):
            raise ValueError("invalid phone format")
        if not v.startswith("+"):
            # Default to India if no country code
            if len(v) == 10:
                v = "+91" + v
            else:
                v = "+" + v
        return v


class RequestOtpResponse(BaseModel):
    message: str
    otp: str | None = None  # only non-null in dev mode
    expires_in_seconds: int


class VerifyOtpBody(BaseModel):
    phone: str
    otp: str = Field(..., min_length=4, max_length=8)

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, v: str) -> str:
        v = v.strip().replace(" ", "")
        if not v.startswith("+"):
            if len(v) == 10:
                v = "+91" + v
            else:
                v = "+" + v
        return v


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str
    user_id: str
    name: str | None
    approved: bool


class RefreshBody(BaseModel):
    refresh_token: str
