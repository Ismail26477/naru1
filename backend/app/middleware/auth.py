"""Auth + RBAC dependencies, with JTI revocation check."""
from __future__ import annotations
import uuid
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User
from app.models.enums import UserRole
from app.services import token_service

bearer_scheme = HTTPBearer(auto_error=True)


async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = creds.credentials
    try:
        payload = decode_token(token)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="not an access token")

    jti = payload.get("jti")
    if jti and await token_service.is_revoked(db, jti):
        raise HTTPException(status_code=401, detail="token revoked")

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="token missing subject")
    try:
        user_id = uuid.UUID(sub)
    except ValueError:
        raise HTTPException(status_code=401, detail="invalid subject")

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="user not found or disabled")
    return user


def require_roles(*allowed: UserRole):
    async def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient role")
        return user
    return _dep


async def require_customer(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.CUSTOMER:
        raise HTTPException(status_code=403, detail="customer role required")
    if user.approved_at is None:
        raise HTTPException(status_code=403, detail="account not yet approved by admin")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="admin role required")
    return user


async def require_delivery(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.DELIVERY:
        raise HTTPException(status_code=403, detail="delivery role required")
    return user
