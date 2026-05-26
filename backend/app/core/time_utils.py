"""Centralized IST/UTC time utilities. All business logic uses these."""
from datetime import datetime, date, time, timedelta, timezone
import pytz

IST = pytz.timezone("Asia/Kolkata")
UTC = timezone.utc


def now_utc() -> datetime:
    return datetime.now(UTC)


def now_ist() -> datetime:
    return datetime.now(IST)


def to_ist(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(IST)


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = IST.localize(dt)
    return dt.astimezone(UTC)


def today_ist() -> date:
    return now_ist().date()


def tomorrow_ist() -> date:
    return today_ist() + timedelta(days=1)


def ist_datetime(d: date, hour: int = 0, minute: int = 0) -> datetime:
    """Construct a tz-aware IST datetime from a date + hour/minute."""
    return IST.localize(datetime.combine(d, time(hour, minute)))


def cutoff_moment_for_delivery_date(delivery_date: date, cutoff_hour_ist: int = 20) -> datetime:
    """The instant BEFORE which modifications to orders for `delivery_date` are allowed.

    Cutoff = the day BEFORE `delivery_date` at 20:00 IST.
    Returns a UTC-aware datetime (for DB comparison).
    """
    cutoff_day = delivery_date - timedelta(days=1)
    return to_utc(ist_datetime(cutoff_day, cutoff_hour_ist, 0))
