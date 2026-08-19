from datetime import UTC, datetime

import pytest

from aidy.market_sessions import (
    london_utc_offset_hours,
    new_york_utc_offset_hours,
    session_code_at,
)


def test_london_dst_boundary_changes_offset_at_0100_utc() -> None:
    before = datetime(2026, 3, 29, 0, 59, 59, tzinfo=UTC)
    after = datetime(2026, 3, 29, 1, 0, tzinfo=UTC)
    assert london_utc_offset_hours(before) == 0
    assert london_utc_offset_hours(after) == 1


def test_new_york_dst_boundary_changes_offset_at_0700_utc() -> None:
    before = datetime(2026, 3, 8, 6, 59, 59, tzinfo=UTC)
    after = datetime(2026, 3, 8, 7, 0, tzinfo=UTC)
    assert new_york_utc_offset_hours(before) == -5
    assert new_york_utc_offset_hours(after) == -4


def test_summer_overlap_begins_earlier_in_utc_than_winter() -> None:
    summer = datetime(2026, 7, 1, 12, 30, tzinfo=UTC)
    winter = datetime(2026, 1, 15, 12, 30, tzinfo=UTC)
    assert session_code_at(summer) == "london_new_york_overlap"
    assert session_code_at(winter) == "london"


def test_weekend_is_explicit() -> None:
    saturday = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    assert session_code_at(saturday) == "weekend"


def test_session_clock_rejects_naive_datetime() -> None:
    naive = datetime.fromisoformat("2026-08-19T12:00:00")
    with pytest.raises(ValueError, match="timezone-aware"):
        session_code_at(naive)
