"""Frozen deterministic unit controls for source-attested PO3 27-grid research."""
from pathlib import Path

import pandas as pd
import pytest

from scripts.gold_hunter_po3_27_original_source_screen import (
    CARRY, GRID, LICENSE_BLOB, ORIGINAL_BLOB, cooldown_active, first_exit, load_year,
    m5_bars, rejects, state_fights,
)


def test_source_identity_and_no_broker_instructions():
    assert len(ORIGINAL_BLOB) == 40
    assert len(LICENSE_BLOB) == 40
    assert GRID == 27.0 and CARRY == 0.09


def test_rejection_shape_frozen_27_grid():
    short = {"bid_o": 26.6, "bid_h": 27.6, "bid_l": 26.0, "bid_c": 26.2}
    long = {"bid_o": 27.4, "bid_h": 27.9, "bid_l": 26.4, "bid_c": 27.8}
    assert rejects(short, 1.0, -1, 27.0)
    assert rejects(long, 1.0, 1, 27.0)
    assert not rejects(short, 1.0, 1, 27.0)
    assert not rejects(long, 1.0, -1, 27.0)


def test_rejects_wrong_candle_body_or_overshoot():
    b = {"bid_o": 27.2, "bid_h": 27.5, "bid_l": 26.0, "bid_c": 26.2}
    assert not rejects(b, 1.0, -1, 27.0)
    b["bid_h"] = 29.0
    assert not rejects(b, 1.0, -1, 27.0)


def test_recent_27_level_flip_is_directional():
    rows = pd.DataFrame([
        {"bid_c": 28.0}, {"bid_c": 26.0}, {"bid_c": 26.1},
    ])
    assert state_fights(rows, 27.0, .4, 1.0, 1)
    assert not state_fights(rows, 27.0, .4, 1.0, -1)


def test_stop_first_on_ambiguous_minute_both_directions():
    m = pd.DataFrame([{
        "bid_o": 27.0, "bid_h": 30.0, "bid_l": 24.0, "bid_c": 27.0,
        "ask_o": 27.3, "ask_h": 30.3, "ask_l": 24.3, "ask_c": 27.3,
    }])
    assert first_exit(m, 1, 25.0, 29.0) == (0, "STOP_FIRST_M1", 24.75)
    assert first_exit(m, -1, 29.0, 25.0) == (0, "STOP_FIRST_M1", 29.25)


def test_incomplete_m5_not_admitted():
    t = pd.date_range("2024-01-01T00:00:00Z", periods=4, freq="min")
    x = pd.DataFrame({
        "open_time_utc": t,
        "bid_o": [27.0]*4, "bid_h": [28.0]*4,
        "bid_l": [26.0]*4, "bid_c": [27.0]*4,
        "ask_o": [27.3]*4, "ask_h": [28.3]*4,
        "ask_l": [26.3]*4, "ask_c": [27.3]*4,
    })
    assert m5_bars(x).empty


def test_no_2026_m1_or_fabricated_source():
    with pytest.raises(ValueError, match="Only 2023/24/25"):
        load_year(Path("/missing"), 2026)


def test_original_three_bar_same_level_cooldown():
    at = pd.Timestamp("2024-03-01T12:00:00Z")
    assert cooldown_active(27.0, 1, at, 27.0, 1,
                           at + pd.Timedelta(minutes=10))
    assert not cooldown_active(27.0, 1, at, 27.0, 1,
                               at + pd.Timedelta(minutes=15))
    assert not cooldown_active(27.0, 1, at, 54.0, 1,
                               at + pd.Timedelta(minutes=5))
    assert not cooldown_active(27.0, 1, at, 27.0, -1,
                               at + pd.Timedelta(minutes=5))
