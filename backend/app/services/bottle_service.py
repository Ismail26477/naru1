"""Bottle ledger helper — centralized so balance stays consistent."""
from __future__ import annotations
import uuid
from fastapi import HTTPException, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.delivery import BottleLedger
from app.models.user import User
from app.models.enums import BottleReason
from app.services import audit_service


class BottleIntegrityError(RuntimeError):
    """Raised if SUM(bottle_ledger) drifts after a write."""


async def bottle_balance(db: AsyncSession, customer_id: uuid.UUID) -> int:
    stmt = select(func.coalesce(func.sum(BottleLedger.change), 0)).where(
        BottleLedger.customer_id == customer_id
    )
    return int((await db.execute(stmt)).scalar() or 0)


async def record(
    db: AsyncSession,
    customer_id: uuid.UUID,
    change: int,
    reason: BottleReason,
    delivery_order_id: uuid.UUID | None = None,
    note: str | None = None,
) -> BottleLedger:
    """Internal helper used by the delivery flow (no audit/lock)."""
    entry = BottleLedger(
        customer_id=customer_id,
        change=change,
        reason=reason,
        delivery_order_id=delivery_order_id,
        note=note,
    )
    db.add(entry)
    await db.flush()
    return entry


async def adjust(
    db: AsyncSession,
    *,
    customer_id: uuid.UUID,
    change: int,
    reason: str,
    actor: User,
    force: bool = False,
    request: Request | None = None,
) -> BottleLedger:
    """Atomic bottle adjustment with row-level locking + audit.

    A negative resulting balance is allowed (customer returned more bottles
    than they owe — promo credit, over-return, etc.) but always requires
    `force=True` to avoid accidental data entry.
    """
    if change == 0:
        raise HTTPException(status_code=400, detail="change must be non-zero")

    # Lock the customer row so concurrent bottle adjustments serialise.
    locked = (await db.execute(
        select(User).where(User.id == customer_id).with_for_update()
    )).scalar_one_or_none()
    if not locked:
        raise HTTPException(status_code=404, detail="customer not found")

    before = await bottle_balance(db, customer_id)
    after = before + change

    if after < 0 and not force:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "would_go_negative",
                "message": (
                    f"Adjustment would take bottle balance to {after}. "
                    "Retry with force=true to override."
                ),
                "current_balance": before,
                "requested_change": change,
            },
        )

    entry = BottleLedger(
        customer_id=customer_id,
        change=change,
        reason=BottleReason.ADJUSTMENT,
        delivery_order_id=None,
        note=reason[:255],
    )
    db.add(entry)
    await db.flush()

    await audit_service.log_action(
        db,
        actor=actor,
        action="bottle.adjust",
        entity_type="bottle",
        entity_id=str(customer_id),
        before_state={"balance": before},
        after_state={
            "balance": after,
            "change": change,
            "ledger_id": str(entry.id),
            "force": bool(force),
        },
        reason=reason,
        request=request,
    )

    # Integrity: recompute from ledger
    ledger_sum = await bottle_balance(db, customer_id)
    if ledger_sum != after:
        raise BottleIntegrityError(
            f"bottle ledger drift: sum={ledger_sum} expected={after}"
        )

    return entry

