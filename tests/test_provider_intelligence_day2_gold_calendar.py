from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from aidy.twelve_data_market import (
    gold_session_is_open,
    expected_market_minute_opens,
    completeness,
    SESSION_CALENDAR_VERSION,
)

NY = ZoneInfo("America/New_York")


def ny(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=NY)


def utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def test_sunday_open_is_exactly_1800_new_york() -> None:
    assert gold_session_is_open(ny(2026, 9, 6, 17, 59)) is False
    assert gold_session_is_open(ny(2026, 9, 6, 18, 0)) is True
    assert gold_session_is_open(ny(2026, 9, 6, 18, 1)) is True


def test_friday_close_is_exactly_1700_new_york() -> None:
    assert gold_session_is_open(ny(2026, 9, 11, 16, 59)) is True
    assert gold_session_is_open(ny(2026, 9, 11, 17, 0)) is False
    assert gold_session_is_open(ny(2026, 9, 11, 18, 0)) is False


def test_daily_maintenance_break_is_1700_to_1800_new_york() -> None:
    for day in (7, 8, 9, 10):  # Mon-Thu
        assert gold_session_is_open(ny(2026, 9, day, 16, 59)) is True
        assert gold_session_is_open(ny(2026, 9, day, 17, 0)) is False
        assert gold_session_is_open(ny(2026, 9, day, 17, 59)) is False
        assert gold_session_is_open(ny(2026, 9, day, 18, 0)) is True


def test_normal_weekday_window_remains_open_outside_maintenance() -> None:
    assert gold_session_is_open(ny(2026, 9, 8, 1, 0)) is True
    assert gold_session_is_open(ny(2026, 9, 8, 12, 0)) is True
    assert gold_session_is_open(ny(2026, 9, 8, 16, 59)) is True
    assert gold_session_is_open(ny(2026, 9, 8, 18, 0)) is True
    assert gold_session_is_open(ny(2026, 9, 8, 23, 59)) is True


def test_spring_dst_transition_preserves_new_york_wall_clock_rules() -> None:
    # US DST starts 2026-03-08. Sunday 18:00 NY is 22:00 UTC after transition.
    assert ny(2026, 3, 8, 18, 0).astimezone(UTC) == utc(2026, 3, 8, 22, 0)
    assert gold_session_is_open(utc(2026, 3, 8, 21, 59)) is False
    assert gold_session_is_open(utc(2026, 3, 8, 22, 0)) is True

    # Monday maintenance 17:00-18:00 NY is 21:00-22:00 UTC while EDT applies.
    assert gold_session_is_open(utc(2026, 3, 9, 20, 59)) is True
    assert gold_session_is_open(utc(2026, 3, 9, 21, 0)) is False
    assert gold_session_is_open(utc(2026, 3, 9, 21, 59)) is False
    assert gold_session_is_open(utc(2026, 3, 9, 22, 0)) is True


def test_autumn_dst_transition_preserves_new_york_wall_clock_rules() -> None:
    # US DST ends 2026-11-01. Sunday 18:00 NY is 23:00 UTC after transition.
    assert ny(2026, 11, 1, 18, 0).astimezone(UTC) == utc(2026, 11, 1, 23, 0)
    assert gold_session_is_open(utc(2026, 11, 1, 22, 59)) is False
    assert gold_session_is_open(utc(2026, 11, 1, 23, 0)) is True

    # Monday maintenance 17:00-18:00 NY is 22:00-23:00 UTC while EST applies.
    assert gold_session_is_open(utc(2026, 11, 2, 21, 59)) is True
    assert gold_session_is_open(utc(2026, 11, 2, 22, 0)) is False
    assert gold_session_is_open(utc(2026, 11, 2, 22, 59)) is False
    assert gold_session_is_open(utc(2026, 11, 2, 23, 0)) is True


def test_closed_minutes_are_expected_absent_not_missing() -> None:
    # Tue 16:58-18:02 NY spans open -> maintenance -> reopen.
    start = ny(2026, 9, 8, 16, 58).astimezone(UTC)
    end = ny(2026, 9, 8, 18, 2).astimezone(UTC)
    expected = expected_market_minute_opens(start, end)
    expected_local = {minute.astimezone(NY).strftime("%H:%M") for minute in expected}

    assert "16:58" in expected_local
    assert "16:59" in expected_local
    assert "17:00" not in expected_local
    assert "17:30" not in expected_local
    assert "17:59" not in expected_local
    assert "18:00" in expected_local
    assert "18:01" in expected_local
    assert len(expected) == 4


def test_missing_minute_inside_open_session_is_a_true_gap() -> None:
    start = ny(2026, 9, 8, 12, 0).astimezone(UTC)
    end = ny(2026, 9, 8, 12, 5).astimezone(UTC)
    expected = expected_market_minute_opens(start, end)
    assert len(expected) == 5

    bars = [
        {"open_time_utc": minute.isoformat()}
        for minute in expected
        if minute != expected[2]
    ]
    state = completeness(bars, start_utc=start, end_utc=end, timeframe="1m")

    assert state["expected_market_minutes"] == 5
    assert state["observed_market_minutes"] == 4
    assert state["coverage_ratio"] == "0.800000"
    assert state["admissible"] is False
    assert state["session_calendar_version"] == SESSION_CALENDAR_VERSION


def test_full_open_session_sample_is_admissible() -> None:
    start = ny(2026, 9, 8, 12, 0).astimezone(UTC)
    end = start + timedelta(minutes=5)
    expected = expected_market_minute_opens(start, end)
    bars = [{"open_time_utc": minute.isoformat()} for minute in expected]
    state = completeness(bars, start_utc=start, end_utc=end, timeframe="1m")
    assert state["expected_market_minutes"] == 5
    assert state["observed_market_minutes"] == 5
    assert state["coverage_ratio"] == "1.000000"
    assert state["admissible"] is True
