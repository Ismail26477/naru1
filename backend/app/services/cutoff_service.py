"""THE single source of truth for cutoff logic. DO NOT reimplement elsewhere."""
from __future__ import annotations
from datetime import date, datetime, timedelta
from fastapi import HTTPException

from app.core.time_utils import now_utc, to_ist, cutoff_moment_for_delivery_date
from app.core.config import settings


def cutoff_for(delivery_date: date) -> datetime:
    """The UTC instant at which orders for delivery_date become immutable."""
    return cutoff_moment_for_delivery_date(delivery_date, settings.CUTOFF_HOUR_IST)


def is_modifiable(delivery_date: date, at: datetime | None = None) -> bool:
    """True iff `at` (default: now) is strictly BEFORE the cutoff for delivery_date."""
    moment = at or now_utc()
    if moment.tzinfo is None:
        raise ValueError("is_modifiable requires tz-aware datetime")
    return moment < cutoff_for(delivery_date)


def assert_modifiable(delivery_date: date, at: datetime | None = None) -> None:
    """Raise HTTP 409 if delivery_date is past cutoff."""
    if not is_modifiable(delivery_date, at):
        cutoff_ist = to_ist(cutoff_for(delivery_date))
        raise HTTPException(
            status_code=409,
            detail={
                "code": "cutoff_passed",
                "message": f"Cutoff for {delivery_date.isoformat()} was {cutoff_ist.strftime('%Y-%m-%d %H:%M %Z')}. Changes no longer permitted.",
                "delivery_date": delivery_date.isoformat(),
                "cutoff_ist": cutoff_ist.isoformat(),
            },
        )


def earliest_modifiable_date(at: datetime | None = None) -> date:
    """Earliest delivery_date whose cutoff has not yet passed.

    At 19:59 IST on day D: earliest modifiable = D+1 (tomorrow).
    At 20:00 IST on day D: earliest modifiable = D+2 (day after tomorrow).
    """
    moment = at or now_utc()
    ist = to_ist(moment)
    # Tomorrow's cutoff = today 20:00 IST. If we're past that, tomorrow is locked.
    today = ist.date()
    tomorrow = today + timedelta(days=1)
    if is_modifiable(tomorrow, moment):
        return tomorrow
    return tomorrow + timedelta(days=1)
