"""Token revocation (logout + admin force-logout)."""
from __future__ import annotations
import time
import uuid
from datetime import datetime, timezone
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from cachetools import TTLCache

from app.models.revoked_token import RevokedToken
from app.core.time_utils import now_utc

# In-process cache. Cleared naturally after TTL so stale deletions don't linger.
_CACHE: TTLCache[str, float] = TTLCache(maxsize=10_000, ttl=60 * 60)


async def is_revoked(db: AsyncSession, jti: str) -> bool:
    if jti in _CACHE:
        return True
    row = (await db.execute(select(RevokedToken.jti).where(RevokedToken.jti == jti))).scalar_one_or_none()
    if row:
        _CACHE[jti] = time.time()
        return True
    return False


async def revoke(db: AsyncSession, jti: str, expires_at: datetime, user_id: uuid.UUID | None = None) -> None:
    exists = (await db.execute(select(RevokedToken.jti).where(RevokedToken.jti == jti))).scalar_one_or_none()
    if exists:
        _CACHE[jti] = time.time()
        return
    db.add(RevokedToken(jti=jti, user_id=user_id, expires_at=expires_at))
    await db.flush()
    _CACHE[jti] = time.time()


async def revoke_all_for_user(db: AsyncSession, user_id: uuid.UUID, horizon: datetime) -> int:
    """Mass-revoke: a sentinel row with a synthetic jti='user:<uid>:<ts>'.
    Every token carries a `sub=user_id` claim, so we enforce via a user-level
    'tokens_invalid_before' stamp on top of the JTI blacklist — simpler:
    this helper returns count of existing JTIs revoked (none for pre-issued tokens
    we don't know). In practice we also bump the user's token version — for v1
    we rely on short 60min access tokens + explicit logout. Documented in TECH_DEBT.
    """
    # For v1: we cannot enumerate all outstanding JTIs for a user — they're not stored.
    # So admin "revoke all" deactivates the user and sets a boolean that get_current_user
    # re-checks via User.is_active. See api/v1/admin.py::revoke_user_tokens.
    return 0


async def cleanup_expired(db: AsyncSession) -> int:
    stmt = delete(RevokedToken).where(RevokedToken.expires_at < now_utc())
    res = await db.execute(stmt)
    return res.rowcount or 0
