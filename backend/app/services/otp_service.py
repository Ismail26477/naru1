"""OTP issuance + verification, with per-phone and per-IP rate limiting."""
from __future__ import annotations
import secrets
from datetime import timedelta
from fastapi import HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.time_utils import now_utc
from app.models.notification import OtpCode

OTP_TTL_SECONDS = 300
MAX_VERIFY_ATTEMPTS = 5
DEV_FIXED_OTP = "123456"

# Rate limits for /auth/request-otp
MAX_OTP_PER_PHONE_PER_HOUR = 5
MAX_OTP_PER_IP_PER_HOUR = 20


def _generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


async def _count_recent(db: AsyncSession, *, phone: str | None = None, ip: str | None = None) -> int:
    since = now_utc() - timedelta(hours=1)
    stmt = select(func.count(OtpCode.id)).where(OtpCode.created_at >= since)
    if phone is not None:
        stmt = stmt.where(OtpCode.phone == phone)
    if ip is not None:
        stmt = stmt.where(OtpCode.request_ip == ip)
    return int((await db.execute(stmt)).scalar() or 0)


async def create_otp(db: AsyncSession, phone: str, ip: str | None = None) -> tuple[str, int]:
    """Create an OTP record after enforcing rate limits.

    Raises HTTPException(429) if the caller has exceeded:
      - `MAX_OTP_PER_PHONE_PER_HOUR` requests for this phone, OR
      - `MAX_OTP_PER_IP_PER_HOUR` requests for this IP.
    """
    phone_count = await _count_recent(db, phone=phone)
    if phone_count >= MAX_OTP_PER_PHONE_PER_HOUR:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "otp_rate_limit_phone",
                "message": "Too many OTP requests for this phone. Try again later.",
                "limit_per_hour": MAX_OTP_PER_PHONE_PER_HOUR,
            },
        )
    if ip:
        ip_count = await _count_recent(db, ip=ip)
        if ip_count >= MAX_OTP_PER_IP_PER_HOUR:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "otp_rate_limit_ip",
                    "message": "Too many OTP requests from this network. Try again later.",
                    "limit_per_hour": MAX_OTP_PER_IP_PER_HOUR,
                },
            )

    code = _generate_code()
    expires = now_utc() + timedelta(seconds=OTP_TTL_SECONDS)
    row = OtpCode(phone=phone, code=code, expires_at=expires, request_ip=ip)
    db.add(row)
    await db.flush()
    return code, OTP_TTL_SECONDS


async def verify_otp(db: AsyncSession, phone: str, code: str) -> bool:
    # Dev backdoor
    if settings.is_development and code == DEV_FIXED_OTP:
        return True

    now = now_utc()
    stmt = (
        select(OtpCode)
        .where(OtpCode.phone == phone, OtpCode.consumed_at.is_(None), OtpCode.expires_at > now)
        .order_by(OtpCode.created_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    if not rows:
        return False

    latest = rows[0]
    if latest.attempts >= MAX_VERIFY_ATTEMPTS:
        return False

    if latest.code == code:
        latest.consumed_at = now
        return True

    latest.attempts += 1
    return False
