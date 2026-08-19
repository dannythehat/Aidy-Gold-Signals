from __future__ import annotations

from datetime import UTC, datetime, timedelta


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("AIDY session timestamps must be timezone-aware.")
    return value.astimezone(UTC)


def _first_sunday(year: int, month: int) -> datetime:
    first = datetime(year, month, 1, tzinfo=UTC)
    return first + timedelta(days=(6 - first.weekday()) % 7)


def _last_sunday(year: int, month: int) -> datetime:
    if month == 12:
        first_next_month = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        first_next_month = datetime(year, month + 1, 1, tzinfo=UTC)
    last = first_next_month - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - 6) % 7)


def london_utc_offset_hours(value: datetime) -> int:
    """Modern UK DST rule, expressed only in UTC for runtime portability."""

    now = _utc(value)
    start = _last_sunday(now.year, 3).replace(hour=1)
    end = _last_sunday(now.year, 10).replace(hour=1)
    return 1 if start <= now < end else 0


def new_york_utc_offset_hours(value: datetime) -> int:
    """Modern US DST rule (2007+), expressed only in UTC."""

    now = _utc(value)
    second_march_sunday = _first_sunday(now.year, 3) + timedelta(days=7)
    first_november_sunday = _first_sunday(now.year, 11)
    start = second_march_sunday.replace(hour=7)
    end = first_november_sunday.replace(hour=6)
    return -4 if start <= now < end else -5


def session_code_at(value: datetime) -> str:
    """Return AIDY's deterministic Gold session label for an absolute UTC instant."""

    now = _utc(value)
    if now.weekday() >= 5:
        return "weekend"

    london = now + timedelta(hours=london_utc_offset_hours(now))
    new_york = now + timedelta(hours=new_york_utc_offset_hours(now))
    tokyo = now + timedelta(hours=9)

    london_open = london.weekday() < 5 and 8 <= london.hour < 17
    new_york_open = new_york.weekday() < 5 and 8 <= new_york.hour < 17
    tokyo_open = tokyo.weekday() < 5 and 9 <= tokyo.hour < 18

    if london_open and new_york_open:
        return "london_new_york_overlap"
    if london_open:
        return "london"
    if new_york_open:
        return "new_york"
    if tokyo_open:
        return "asia"
    return "off_hours"
