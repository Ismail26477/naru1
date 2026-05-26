"""Background job bodies (idempotent)."""
from __future__ import annotations
import asyncio
from datetime import date, timedelta
import logging

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import now_ist, tomorrow_ist, now_utc
from app.services.order_service import generate_orders_for_date, lock_orders_for_date
from app.services import billing_admin_service, audit_service
from app.schemas.delivery import JobRunResult
from app.models.enums import UserRole
from app.models.route import Route
from app.models.user import User

log = logging.getLogger("jobs")

# Arbitrary advisory-lock namespace keys so cluster-safe if we scale later
LOCK_NIGHTLY = 7101
LOCK_BILLING = 7102
LOCK_REMINDER = 7103


async def _with_advisory_lock(db: AsyncSession, lock_key: int, fn):
    got = (await db.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_key})).scalar()
    if not got:
        log.warning(f"advisory lock {lock_key} held by another worker; skipping")
        return JobRunResult(job="skipped", affected=0, details={"lock_key": lock_key})
    try:
        return await fn()
    finally:
        await db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": lock_key})


async def get_system_user(db: AsyncSession) -> User:
    """Fetch the singleton automation user (seeded by migration e5c1b7f2a3d8).

    Raises RuntimeError if missing — the migration should have created it.
    """
    u = (await db.execute(
        select(User).where(User.is_system.is_(True))
    )).scalar_one_or_none()
    if u is None:
        raise RuntimeError(
            "System user not found. Run `alembic upgrade head` to seed it "
            "(migration e5c1b7f2a3d8)."
        )
    return u


async def nightly_cutoff(db: AsyncSession) -> JobRunResult:
    """At 20:00 IST: generate any missing orders for tomorrow and stamp cutoff_locked_at.

    Writes an `orders.generated` audit row with actor=system so the nightly
    automation is traceable.
    """
    async def _run():
        target = tomorrow_ist()
        created = await generate_orders_for_date(db, target)
        locked = await lock_orders_for_date(db, target)
        log.info(f"nightly_cutoff: created={len(created)} locked={locked} date={target}")

        # Audit (system actor) for automated order generation
        try:
            system = await get_system_user(db)
            await audit_service.log_action(
                db, actor=system, action="orders.generated",
                entity_type="delivery_batch", entity_id=target.isoformat(),
                after_state={
                    "date": target.isoformat(),
                    "created": len(created),
                    "locked": locked,
                },
                reason="Automated nightly cutoff",
            )
        except Exception as e:  # noqa: BLE001 — audit failure must not block ops job
            log.error(f"nightly_cutoff audit write failed: {e}")

        return JobRunResult(
            job="nightly_cutoff", affected=locked,
            details={"date": target.isoformat(), "created": len(created), "locked": locked},
        )
    return await _with_advisory_lock(db, LOCK_NIGHTLY, _run)


async def monthly_billing(db: AsyncSession) -> JobRunResult:
    """On 1st at 02:00 IST: generate invoices for the previous month.

    Routes through `billing_admin_service.generate_invoices` so it shares:
      - pg_try_advisory_xact_lock (prevents collision with manual regen)
      - audit trail (billing.generate with actor=system)
      - per-customer atomicity (one bad customer doesn't fail the month)
      - post-billing-adjustment flag propagation

    Conflict handling:
      - 409 invoices_already_exist → someone pre-generated manually; log WARN + succeed.
      - 409 billing_generation_locked → sleep 30s, retry once; then log ERROR + succeed
        (next day's cron attempt will pick it up, and manual admin can still run it).
    """
    today = now_ist().date()
    if today.month == 1:
        y, m = today.year - 1, 12
    else:
        y, m = today.year, today.month - 1

    system = await get_system_user(db)

    async def _do_generate() -> billing_admin_service.GenerationResult | None:
        try:
            return await billing_admin_service.generate_invoices(
                db, year=y, month=m,
                actor=system, regenerate=False,
                reason=None,
            )
        except HTTPException as e:
            code = (e.detail or {}).get("code") if isinstance(e.detail, dict) else None
            if code == "invoices_already_exist":
                log.warning(
                    f"monthly_billing: invoices already exist for {y}-{m:02d} "
                    f"(likely manual pre-gen); skipping."
                )
                return None
            if code == "billing_generation_locked":
                raise _LockContention() from e
            raise

    class _LockContention(RuntimeError):
        pass

    try:
        result = await _do_generate()
    except _LockContention:
        log.warning(f"monthly_billing: lock contention for {y}-{m:02d}; retrying in 30s")
        await asyncio.sleep(30)
        try:
            result = await _do_generate()
        except _LockContention:
            log.error(
                f"monthly_billing: lock contention persists for {y}-{m:02d}; "
                f"giving up (next scheduled run or manual admin action will recover)."
            )
            return JobRunResult(
                job="monthly_billing", affected=0,
                details={"year": y, "month": m, "status": "lock_contention_gave_up"},
            )

    if result is None:
        return JobRunResult(
            job="monthly_billing", affected=0,
            details={"year": y, "month": m, "status": "already_exists_skipped"},
        )

    log.info(
        f"monthly_billing: created={result.created_count} "
        f"skipped={result.skipped_customers} failed={len(result.failed)} "
        f"period={y}-{m:02d}"
    )
    return JobRunResult(
        job="monthly_billing", affected=result.created_count,
        details={
            "year": y, "month": m,
            "created": result.created_count,
            "skipped_customers": result.skipped_customers,
            "failed_customers": len(result.failed),
        },
    )


async def morning_reminder(db: AsyncSession) -> JobRunResult:
    """At 07:00 IST: send delivery reminders to delivery boys (stub: log notifications)."""
    from app.models.notification import NotificationsLog
    from app.models.enums import NotificationChannel, NotificationStatus
    from app.core.time_utils import now_utc, today_ist

    async def _run():
        routes = (await db.execute(select(Route).where(Route.delivery_boy_id.is_not(None)))).scalars().all()
        d = today_ist()
        count = 0
        for r in routes:
            nl = NotificationsLog(
                user_id=r.delivery_boy_id,
                channel=NotificationChannel.PUSH,
                template="delivery_reminder",
                recipient=str(r.delivery_boy_id),
                payload=f'{{"route":"{r.name}","date":"{d.isoformat()}"}}',
                status=NotificationStatus.SENT,
                sent_at=now_utc(),
            )
            db.add(nl)
            count += 1
        await db.flush()
        log.info(f"morning_reminder: sent={count} date={d}")
        # Light audit so ops can see the run happened (non-money-path, but helpful for debugging).
        try:
            system = await get_system_user(db)
            await audit_service.log_action(
                db, actor=system, action="reminder.sent",
                entity_type="reminder_batch", entity_id=d.isoformat(),
                after_state={"date": d.isoformat(), "sent": count},
                reason="Automated morning reminder",
            )
        except Exception as e:  # noqa: BLE001
            log.error(f"morning_reminder audit write failed: {e}")
        return JobRunResult(job="morning_reminder", affected=count, details={"date": d.isoformat()})
    return await _with_advisory_lock(db, LOCK_REMINDER, _run)


async def revoked_token_cleanup(db: AsyncSession) -> JobRunResult:
    """Daily sweep to prune expired revoked-token rows. (Read/cleanup — no audit needed.)"""
    from app.services import token_service
    async def _run():
        deleted = await token_service.cleanup_expired(db)
        log.info(f"revoked_token_cleanup: deleted={deleted}")
        return JobRunResult(job="revoked_token_cleanup", affected=deleted, details={})
    return await _with_advisory_lock(db, 7104, _run)
