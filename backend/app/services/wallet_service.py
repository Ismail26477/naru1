"""Wallet service — atomic adjustments with row-level locking.

SAFETY GUARANTEES:
- SELECT ... FOR UPDATE on the user row → no concurrent adjustments
- WalletTransaction + User.wallet_balance + audit_log written in the
  same session; caller owns commit/rollback (via get_db dependency).
- Post-op integrity check: SUM(change_paise) must equal new balance.
  If the check fails the caller's transaction is rolled back.
- Negative balances are rejected unless `force=True` AND reason is
  non-empty (minimum length enforced at API layer).
"""
from __future__ import annotations
import uuid
from fastapi import HTTPException, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.billing import WalletTransaction
from app.services import audit_service


class WalletIntegrityError(RuntimeError):
    """Raised if SUM(wallet_transactions) != user.wallet_balance after write."""


async def wallet_balance(db: AsyncSession, customer_id: uuid.UUID) -> int:
    """Current cached balance (fast)."""
    stmt = select(User.wallet_balance_paise).where(User.id == customer_id)
    v = (await db.execute(stmt)).scalar_one_or_none()
    return int(v or 0)


async def _sum_transactions(db: AsyncSession, customer_id: uuid.UUID) -> int:
    stmt = select(func.coalesce(func.sum(WalletTransaction.change_paise), 0)).where(
        WalletTransaction.customer_id == customer_id
    )
    return int((await db.execute(stmt)).scalar() or 0)


async def adjust(
    db: AsyncSession,
    *,
    customer_id: uuid.UUID,
    change_paise: int,
    reason: str,
    actor: User,
    force: bool = False,
    reference_id: str | None = None,
    request: Request | None = None,
) -> WalletTransaction:
    """Atomic wallet adjustment.

    Raises HTTPException 404 if customer not found,
    400 if resulting balance negative and not forced,
    WalletIntegrityError if post-op ledger sum drifts.
    """
    if change_paise == 0:
        raise HTTPException(status_code=400, detail="change_paise must be non-zero")

    # Lock customer row to serialise concurrent adjustments
    stmt = select(User).where(User.id == customer_id).with_for_update()
    user = (await db.execute(stmt)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="customer not found")

    before_balance = int(user.wallet_balance_paise or 0)
    after_balance = before_balance + change_paise

    if after_balance < 0 and not force:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "would_go_negative",
                "message": (
                    f"Adjustment would take wallet to {after_balance} paise. "
                    "Retry with force=true to override."
                ),
                "current_balance_paise": before_balance,
                "requested_change_paise": change_paise,
            },
        )

    # Apply
    user.wallet_balance_paise = after_balance
    tx = WalletTransaction(
        customer_id=customer_id,
        change_paise=change_paise,
        reason=reason[:120],  # column width
        reference_id=reference_id,
        balance_after_paise=after_balance,
    )
    db.add(tx)
    await db.flush()

    # Audit (non-optional; any failure aborts the enclosing transaction)
    await audit_service.log_action(
        db,
        actor=actor,
        action="wallet.adjust",
        entity_type="wallet",
        entity_id=str(customer_id),
        before_state={"balance_paise": before_balance},
        after_state={
            "balance_paise": after_balance,
            "change_paise": change_paise,
            "transaction_id": str(tx.id),
            "force": bool(force),
        },
        reason=reason,
        request=request,
    )

    # Integrity check
    ledger_sum = await _sum_transactions(db, customer_id)
    if ledger_sum != after_balance:
        # This must never happen; raising will roll back the get_db() context.
        raise WalletIntegrityError(
            f"ledger drift: sum(transactions)={ledger_sum} != user.balance={after_balance}"
        )

    return tx
