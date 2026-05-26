"""Audit log service — a single choke point for writing audit rows.

Usage:
    await audit_service.log_action(
        db,
        actor=current_user,
        action="customer.approve",
        entity_type="customer",
        entity_id=str(customer_id),
        before_state={"approved_at": None},
        after_state={"approved_at": iso_now},
        reason=None,             # optional; required by endpoints that demand it
        request=request,         # fastapi.Request for IP / UA capture (optional)
    )

Rows are only flushed with the enclosing session (we do not commit here);
callers control the transaction boundary.
"""
from __future__ import annotations
from typing import Any
import uuid
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.user import User


async def log_action(
    db: AsyncSession,
    *,
    actor: User | None,
    action: str,
    entity_type: str | None = None,
    entity_id: str | uuid.UUID | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    reason: str | None = None,
    request: Request | None = None,
) -> AuditLog:
    ip: str | None = None
    ua: str | None = None
    if request is not None:
        # respect X-Forwarded-For when present (behind reverse proxy / ingress)
        xff = request.headers.get("x-forwarded-for")
        ip = (xff.split(",")[0].strip() if xff else (request.client.host if request.client else None))
        ua = request.headers.get("user-agent")

    row = AuditLog(
        actor_user_id=actor.id if actor else None,
        actor_role=(actor.role.value if actor and hasattr(actor.role, "value") else (str(actor.role) if actor else None)),
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        before_state=before_state,
        after_state=after_state,
        reason=reason,
        ip_address=ip,
        user_agent=(ua[:255] if ua else None),
    )
    db.add(row)
    await db.flush()
    return row
