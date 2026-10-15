"""S046 source-description proxy: synthetic unit scenarios are NOT gold results."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.strategy_lab_history_reader import ClosedBar
from aidy.strategy_lab_s046_signal_proxy import (
    RULE_VERSION,
    scan_completed_session_sweeps,
)

START = datetime(2025, 1, 7, tzinfo=UTC)


def bar(minute, *, high="101", low="99", close="100"):
    at = START + timedelta(minutes=minute)
    return ClosedBar(
        at, at + timedelta(minutes=5), Decimal(100),
        Decimal(high), Decimal(low), Decimal(close),
    )


def sequence():
    return [bar(m) for m in range(0, 21 * 60, 5)]


def test_actual_completed_session_then_non_repainting_high_and_low_sweeps():
    arr = sequence()
    arr[8 * 12] = bar(8 * 60, high="102", close="100")
    arr[8 * 12 + 1] = bar(8 * 60 + 5, high="102", close="100")
    arr[8 * 12 + 2] = bar(8 * 60 + 10, low="98", close="100")
    got = scan_completed_session_sweeps(arr)
    assert RULE_VERSION.startswith("S046")
    assert [(s.session, s.side) for s in got] == [
        ("ASIA", "BEARISH"), ("ASIA", "BULLISH"),
    ]
    assert got[0].confirmed_at_utc == (START + timedelta(hours=8, minutes=5)).isoformat()
    assert len(got) == 2  # second wick beyond same high ignored


def test_close_beyond_session_high_cancels_level_without_false_sweep():
    arr = sequence()
    arr[96] = bar(480, high="103", close="102")
    arr[97] = bar(485, high="103", close="100")
    found = scan_completed_session_sweeps(arr)
    assert not any(s.session == "ASIA" and s.side == "BEARISH" for s in found)


def test_no_sweep_is_marked_during_incomplete_session():
    arr = sequence()
    arr[95] = bar(475, high="105", close="100")
    assert not any(
        s.session == "ASIA" for s in scan_completed_session_sweeps(arr)
    )


def test_only_bid_utc_closed_continuous_bars_accepted():
    arr = sequence()
    invalids = [
        arr[:-1] + [ClosedBar(
            arr[-1].open_time_utc,
            arr[-1].available_at_utc, arr[-1].open,
            arr[-1].high, arr[-1].low, arr[-1].close, "ask",
        )],
        arr[:30] + arr[31:],
        arr[:9] + [ClosedBar(
            arr[9].open_time_utc,
            arr[9].available_at_utc + timedelta(minutes=5),
            arr[9].open, arr[9].high, arr[9].low, arr[9].close,
        )] + arr[10:],
        [],
    ]
    for candidate in invalids:
        with pytest.raises(ValueError):
            scan_completed_session_sweeps(candidate)


def test_new_york_level_cannot_claim_signals_without_after_close_bars():
    arr = sequence()
    arr[-1] = bar(1255, high="600", low="10", close="100")
    assert not any(s.session == "NEW_YORK" for s in scan_completed_session_sweeps(arr))
