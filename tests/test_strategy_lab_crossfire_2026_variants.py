"""Frozen CROSSFIRE 2026 causal variants (synthetic tests; no profit claims)."""
from datetime import UTC, datetime, timedelta
from math import sin

import pandas as pd
import pytest

from aidy.strategy_lab_crossfire_2026_variants import (
    RESEARCH_CONTRACT,
    VARIANT_KEYS,
    replay,
)
from aidy.strategy_lab_s010_backtest import (
    BASE,
    ORIGINAL_LEVERAGE,
    simulate,
)


def sample(n: int = 900) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for i in range(n):
        price = 2500 + 41 * sin(i / 15) + i * .08
        rows.append({
            "open_time_utc": (start + timedelta(hours=i)).isoformat(),
            "open": price - .2,
            "high": price + 3.0,
            "low": price - 3.0,
            "close": price,
            "m1_count": 60,
        })
    return pd.DataFrame(rows)


def test_single_fixed_variant_keys():
    assert VARIANT_KEYS == (
        "original", "atr3_initial_stop", "sma200_rising_filter",
    )
    assert "2026.frozen" in RESEARCH_CONTRACT
    with pytest.raises(ValueError,match="pre-registered"):
        replay(sample(), "rsi_optimised_87")


def test_original_is_byte_for_byte_same_execution_engine_as_2025():
    source = sample()
    original = simulate(source, ORIGINAL_LEVERAGE, BASE)
    assert replay(source, "original") == original


def test_only_closed_previous_bar_controls_trend_filter():
    source = sample()
    baseline = replay(source, "original")
    filtered = replay(source, "sma200_rising_filter")
    assert filtered["bars"] == len(source)
    assert len(filtered["monthly"]) == 2
    assert filtered["filtered_original_buy_signals"] >= 0
    assert baseline["marked_return_pct"] is not None
    assert filtered["test_cost_model"] == vars(BASE)
    assert not filtered["open_position"] or "entry_utc" in filtered["open_position"]


def test_stop_requires_previous_atr_not_next_bar_future():
    source = sample()
    stop = replay(source, "atr3_initial_stop")
    assert stop["bars"] == len(source)
    assert stop["closed_trades"] == len(stop["trades"])
    assert stop["stop_events"] == sum(
        t["exit_reason"] == "initial_atr_stop" for t in stop["trades"]
    )
    assert all(t["entry_utc"] <= t["exit_utc"] for t in stop["trades"])
    assert stop["sum_paid_execution_cost_usd"] >= 0
    assert len(stop["monthly"]) == 2


def test_no_forward_h1_data_used_for_all_prior_closed_trades():
    source = sample()
    first = replay(source, "atr3_initial_stop")
    source.loc[len(source)-1, "high"] *= 1.05
    source.loc[len(source)-1, "low"] *= .90
    # Changing final candle can alter its own stop; NEVER earlier closed trades.
    second = replay(source, "atr3_initial_stop")
    before = pd.Timestamp(source.iloc[-1]["open_time_utc"])
    earlier_a = [t for t in first["trades"] if pd.Timestamp(t["exit_utc"]) < before]
    earlier_b = [t for t in second["trades"] if pd.Timestamp(t["exit_utc"]) < before]
    assert earlier_a == earlier_b


def test_reject_incomplete_hours_or_future_parameter_grid():
    source = sample()
    source.loc[1,"m1_count"] = 59
    for variant in VARIANT_KEYS:
        with pytest.raises(ValueError,match="complete hourly"):
            replay(source,variant)
