"""Centralized 8 PM IST cutoff: modifying at 19:59 works, at 20:01 fails."""
import pytest
from datetime import date, datetime, timedelta
import pytz

from app.services.cutoff_service import is_modifiable, assert_modifiable, cutoff_for
from fastapi import HTTPException

IST = pytz.timezone("Asia/Kolkata")


def _ist_to_utc(y, m, d, h, mi):
    return IST.localize(datetime(y, m, d, h, mi)).astimezone(pytz.UTC)


def test_cutoff_moment_is_previous_day_2000_ist():
    delivery_day = date(2026, 3, 15)
    cutoff = cutoff_for(delivery_day)
    ist_view = cutoff.astimezone(IST)
    assert ist_view.date() == date(2026, 3, 14)
    assert ist_view.hour == 20 and ist_view.minute == 0


def test_modifiable_at_1959_ist_works():
    delivery_day = date(2026, 3, 15)
    at = _ist_to_utc(2026, 3, 14, 19, 59)
    assert is_modifiable(delivery_day, at) is True


def test_not_modifiable_at_2001_ist_fails():
    delivery_day = date(2026, 3, 15)
    at = _ist_to_utc(2026, 3, 14, 20, 1)
    assert is_modifiable(delivery_day, at) is False


def test_not_modifiable_at_exactly_2000_ist():
    delivery_day = date(2026, 3, 15)
    at = _ist_to_utc(2026, 3, 14, 20, 0)
    # At 20:00 exactly, cutoff is reached — not strictly before cutoff, so immutable.
    assert is_modifiable(delivery_day, at) is False


def test_assert_modifiable_raises_after_cutoff():
    delivery_day = date(2026, 3, 15)
    at = _ist_to_utc(2026, 3, 14, 20, 1)
    with pytest.raises(HTTPException) as exc:
        assert_modifiable(delivery_day, at)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "cutoff_passed"


def test_assert_modifiable_ok_before_cutoff():
    delivery_day = date(2026, 3, 15)
    at = _ist_to_utc(2026, 3, 14, 19, 59)
    # Should not raise
    assert_modifiable(delivery_day, at)


def test_modifying_day_after_tomorrow_always_ok():
    # If it's 10 AM IST on day 14, day 16 (day after tomorrow) is obviously ok
    at = _ist_to_utc(2026, 3, 14, 10, 0)
    assert is_modifiable(date(2026, 3, 16), at) is True
