"""Schedule expansion for subscriptions.

Given a subscription and a date range, yield the (date, quantity) pairs
that SHOULD have delivery orders generated (respecting overrides, pauses, frequency).
"""
from __future__ import annotations
from datetime import date, timedelta
from typing import Iterator
from app.models.subscription import Subscription, SubscriptionScheduleOverride
from app.models.enums import SubscriptionFrequency, SubscriptionStatus


def _parse_custom_days(s: str | None) -> set[int]:
    if not s:
        return set()
    return {int(x.strip()) for x in s.split(",") if x.strip().isdigit()}


def is_scheduled(sub: Subscription, d: date) -> bool:
    """Is this subscription supposed to deliver on date d (ignoring overrides/pauses)?"""
    if d < sub.start_date:
        return False
    if sub.end_date and d > sub.end_date:
        return False
    if sub.frequency == SubscriptionFrequency.DAILY:
        return True
    if sub.frequency == SubscriptionFrequency.ALTERNATE:
        return (d - sub.start_date).days % 2 == 0
    if sub.frequency == SubscriptionFrequency.WEEKLY:
        # custom_days like "0" means every Monday
        return d.weekday() in _parse_custom_days(sub.custom_days)
    if sub.frequency == SubscriptionFrequency.CUSTOM:
        return d.weekday() in _parse_custom_days(sub.custom_days)
    return False


def is_paused_on(sub: Subscription, d: date) -> bool:
    if sub.status == SubscriptionStatus.PAUSED:
        return True
    if sub.pause_from and sub.pause_until and sub.pause_from <= d <= sub.pause_until:
        return True
    return False


def expand(
    sub: Subscription,
    start: date,
    end: date,
    overrides: list[SubscriptionScheduleOverride] | None = None,
) -> Iterator[tuple[date, int]]:
    """Yield (date, quantity) for each day `sub` would deliver in [start, end].

    - Skipped days yielded only if overrides contain skip=true → caller drops them.
    - quantity_override applies.
    """
    if sub.status == SubscriptionStatus.CANCELLED:
        return
    ov_map = {o.date: o for o in (overrides or []) if start <= o.date <= end}

    d = start
    while d <= end:
        if sub.status != SubscriptionStatus.PAUSED and not is_paused_on(sub, d):
            ov = ov_map.get(d)
            scheduled = is_scheduled(sub, d)
            if ov and ov.skip:
                pass  # explicit skip
            elif ov and ov.quantity_override is not None:
                # Override can FORCE a delivery on a day that wasn't scheduled
                if ov.quantity_override > 0:
                    yield d, ov.quantity_override
            elif scheduled:
                yield d, sub.quantity
        d += timedelta(days=1)
