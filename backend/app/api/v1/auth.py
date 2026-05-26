"""Auth routes: request-otp, verify-otp, refresh, logout."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User
from app.models.enums import UserRole
from app.schemas.auth import RequestOtpBody, RequestOtpResponse, VerifyOtpBody, TokenResponse, RefreshBody
from app.schemas.common import Message
from app.services.otp_service import create_otp, verify_otp
from app.services import token_service
from app.providers import get_sms_provider
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.core.config import settings
from app.middleware.auth import get_current_user, bearer_scheme
from fastapi.security import HTTPAuthorizationCredentials

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/request-otp", response_model=RequestOtpResponse)
async def request_otp(body: RequestOtpBody, request: Request, db: AsyncSession = Depends(get_db)):
    # Block OTP generation for system accounts (they can't log in anyway; fail fast).
    existing = (await db.execute(
        select(User).where(User.phone == body.phone)
    )).scalar_one_or_none()
    if existing is not None and existing.is_system:
        raise HTTPException(
            status_code=403,
            detail={"code": "system_account_no_login", "message": "System accounts cannot log in."},
        )

    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else None)
    if ip and "," in ip:
        ip = ip.split(",")[0].strip()
    code, ttl = await create_otp(db, body.phone, ip=ip)
    await get_sms_provider().send_otp(body.phone, code)
    return RequestOtpResponse(
        message="OTP sent",
        otp=code if settings.is_development else None,
        expires_in_seconds=ttl,
    )


@router.post("/verify-otp", response_model=TokenResponse)
async def verify_and_login(body: VerifyOtpBody, db: AsyncSession = Depends(get_db)):
    ok = await verify_otp(db, body.phone, body.otp)
    if not ok:
        raise HTTPException(status_code=400, detail="invalid or expired OTP")

    user = (await db.execute(select(User).where(User.phone == body.phone))).scalar_one_or_none()
    if user is not None and user.is_system:
        # System accounts are for automation only.
        raise HTTPException(
            status_code=403,
            detail={"code": "system_account_no_login", "message": "System accounts cannot log in."},
        )
    if user is None:
        user = User(phone=body.phone, role=UserRole.CUSTOMER, is_active=True)
        db.add(user)
        await db.flush()

    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    access = create_access_token(str(user.id), role_str)
    refresh = create_refresh_token(str(user.id), role_str)
    return TokenResponse(
        access_token=access, refresh_token=refresh, role=role_str,
        user_id=str(user.id), name=user.name, approved=user.approved_at is not None,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_access(body: RefreshBody, db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="not a refresh token")

    jti = payload.get("jti")
    if jti and await token_service.is_revoked(db, jti):
        raise HTTPException(status_code=401, detail="token revoked")

    import uuid as _uuid
    try:
        uid = _uuid.UUID(payload["sub"])
    except Exception:
        raise HTTPException(status_code=401, detail="invalid subject")

    user = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="user disabled")
    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    return TokenResponse(
        access_token=create_access_token(str(user.id), role_str),
        refresh_token=create_refresh_token(str(user.id), role_str),
        role=role_str, user_id=str(user.id), name=user.name,
        approved=user.approved_at is not None,
    )


@router.post("/logout", response_model=Message)
async def logout(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke the current access token (adds its jti to the blacklist)."""
    payload = decode_token(creds.credentials)
    jti = payload.get("jti")
    exp = payload.get("exp")
    if jti and exp:
        exp_dt = datetime.fromtimestamp(int(exp), tz=timezone.utc)
        await token_service.revoke(db, jti, exp_dt, user_id=user.id)
    return Message(message="logged out")
