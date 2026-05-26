"""APScheduler setup: cron jobs in IST timezone."""
from __future__ import annotations
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.jobs.runners import nightly_cutoff, monthly_billing, morning_reminder, revoked_token_cleanup

log = logging.getLogger("scheduler")
_scheduler: AsyncIOScheduler | None = None


def _wrap(fn):
    async def _runner():
        async with AsyncSessionLocal() as db:
            try:
                result = await fn(db)
                await db.commit()
                log.info(f"job result: {result}")
            except Exception:
                await db.rollback()
                log.exception("job failed")
                raise
    return _runner


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    ist = timezone(settings.TIMEZONE)
    sched = AsyncIOScheduler(timezone=ist)
    sched.add_job(_wrap(nightly_cutoff), CronTrigger(hour=settings.CUTOFF_HOUR_IST, minute=0, timezone=ist),
                  id="nightly_cutoff", replace_existing=True)
    sched.add_job(_wrap(monthly_billing), CronTrigger(day=settings.BILLING_DAY_OF_MONTH, hour=2, minute=0, timezone=ist),
                  id="monthly_billing", replace_existing=True)
    sched.add_job(_wrap(morning_reminder), CronTrigger(hour=7, minute=0, timezone=ist),
                  id="morning_reminder", replace_existing=True)
    sched.add_job(_wrap(revoked_token_cleanup), CronTrigger(hour=3, minute=30, timezone=ist),
                  id="revoked_token_cleanup", replace_existing=True)
    sched.start()
    _scheduler = sched
    log.info("scheduler started")
    return sched


def stop_scheduler():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
