"""AIDY multi-system research tests, never broker orders."""
import pandas as pd
import pytest

from aidy.strategy_lab_s010_backtest import BASE, simulate
from aidy.strategy_lab_system_processor import (
    DONCHIAN,
    S010,
    donchian_closed_bar_signals,
    process_systems,
)


def sample_bars():
    stamps = pd.date_range("2025-01-02", periods=260, freq="h", tz="UTC")
    prices = [2600 + ((i % 40) * (2 if (i // 40) % 2 == 0 else -2))
              for i in range(260)]
    return pd.DataFrame({
        "open_time_utc": [x.isoformat() for x in stamps],
        "open": prices,
        "high": [p + 1 for p in prices],
        "low": [p - 1 for p in prices],
        "close": prices,
        "m1_count": [60] * 260,
    })


def test_run_both_system_families_and_default_parity():
    frame = sample_bars()
    result = process_systems(frame, source_identity="a" * 64)
    assert result == process_systems(frame, source_identity="a" * 64)
    assert tuple(result["models"]) == (S010, DONCHIAN)
    assert result["models"][S010]["base"] == simulate(frame, 3.28, BASE)
    assert result["models"][DONCHIAN]["base"]["method"] == "LAB_DONCHIAN_20_10_H1_V1"
    assert result["models"][DONCHIAN]["source_category"] == "LABORATORY_DEFINED_NOT_CATALOGUE"
    assert all(x["paper_or_live_orders"] == 0 for x in result["models"].values())


def test_no_future_leakage():
    original = sample_bars()
    before = donchian_closed_bar_signals(original)
    changed = original.copy()
    changed.loc[250, "close"] = 3000
    changed.loc[250, "high"] = 3001
    after = donchian_closed_bar_signals(changed)
    assert before[:250] == after[:250]
    assert before[:20] == (0,) * 20


def test_unsupported_catalogue_systems_not_silently_substituted():
    frame = sample_bars()
    for names in [("S040",), ("S005",), (S010, S010), ()]:
        with pytest.raises(ValueError):
            process_systems(frame, requested=names, source_identity="a" * 64)


def test_fail_on_bad_market_and_untrusted_signals():
    frame = sample_bars()
    bad = frame.copy()
    bad.loc[31, "m1_count"] = 59
    with pytest.raises(ValueError):
        process_systems(bad, source_identity="a" * 64)
    with pytest.raises(ValueError):
        process_systems(frame, source_identity="not-a-hash")
    with pytest.raises(ValueError):
        simulate(frame, 1.0, BASE, verified_signal_override=(1,) * len(frame))
