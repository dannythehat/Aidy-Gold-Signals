from __future__ import annotations

from datetime import UTC, datetime

from aidy.market_recorder import (
    _closed_candle,
    _london_utc_offset_hours,
    _new_york_utc_offset_hours,
    _session_code,
)


def test_closed_candle_accepts_only_fully_closed_bar() -> None:
    captured = datetime(2026, 8, 16, 12, 5, tzinfo=UTC)
    payload = {
        "symbol": "XAUUSD",
        "timeframe": "5m",
        "time": "2026-08-16T12:00:00Z",
        "open": 4350,
        "high": 4355,
        "low": 4348,
        "close": 4353,
    }
    assert _closed_candle(payload, expected_timeframe="5m", captured_at=captured) is not None


def test_current_unclosed_bar_is_rejected() -> None:
    captured = datetime(2026, 8, 16, 12, 4, 59, tzinfo=UTC)
    payload = {
        "symbol": "XAUUSD",
        "timeframe": "5m",
        "time": "2026-08-16T12:00:00Z",
        "open": 4350,
        "high": 4355,
        "low": 4348,
        "close": 4353,
    }
    assert _closed_candle(payload, expected_timeframe="5m", captured_at=captured) is None


def test_naive_candle_timestamp_is_rejected() -> None:
    captured = datetime(2026, 8, 16, 12, 5, tzinfo=UTC)
    payload = {
        "symbol": "XAUUSD",
        "timeframe": "5m",
        "time": "2026-08-16T12:00:00",
        "open": 4350,
        "high": 4355,
        "low": 4348,
        "close": 4353,
    }
    assert _closed_candle(payload, expected_timeframe="5m", captured_at=captured) is None


def test_session_label_is_dst_aware() -> None:
    assert _session_code(datetime(2026, 8, 17, 14, 0, tzinfo=UTC)) == "london_new_york_overlap"


def test_london_dst_boundaries_are_explicit_and_tzdata_free() -> None:
    assert _london_utc_offset_hours(datetime(2026, 3, 29, 0, 59, tzinfo=UTC)) == 0
    assert _london_utc_offset_hours(datetime(2026, 3, 29, 1, 0, tzinfo=UTC)) == 1
    assert _london_utc_offset_hours(datetime(2026, 10, 25, 0, 59, tzinfo=UTC)) == 1
    assert _london_utc_offset_hours(datetime(2026, 10, 25, 1, 0, tzinfo=UTC)) == 0


def test_new_york_dst_boundaries_are_explicit_and_tzdata_free() -> None:
    assert _new_york_utc_offset_hours(datetime(2026, 3, 8, 6, 59, tzinfo=UTC)) == -5
    assert _new_york_utc_offset_hours(datetime(2026, 3, 8, 7, 0, tzinfo=UTC)) == -4
    assert _new_york_utc_offset_hours(datetime(2026, 11, 1, 5, 59, tzinfo=UTC)) == -4
    assert _new_york_utc_offset_hours(datetime(2026, 11, 1, 6, 0, tzinfo=UTC)) == -5


def test_winter_session_clock_remains_correct_without_zoneinfo() -> None:
    assert _session_code(datetime(2026, 1, 12, 14, 0, tzinfo=UTC)) == "london_new_york_overlap"
