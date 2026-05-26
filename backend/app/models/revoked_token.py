"""Revoked JWT blacklist (for logout + admin force-logout).

Uses a tiny in-process TTL cache on top of the DB table to avoid per-request DB
hits. Single-worker deploy today; when we scale out, swap cache for Redis
(interface is isolated, no call-site changes needed).
"""
from __future__ import annotations
import time
from datetime import datetime, timedelta, timezone
import uuid
from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.core.time_utils import now_utc


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
