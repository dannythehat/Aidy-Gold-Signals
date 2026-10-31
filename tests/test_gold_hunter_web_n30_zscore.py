"""Synthetic-only tests; no observed profit claimed."""
import numpy as np
import pandas as pd
import pytest

from scripts.gold_hunter_web_n30_zscore import features, replay, YEARS, MAX_SPREAD


def make_m1(n=8000):
    time = pd.date_range("2023-01-02T00:00:00Z", periods=n, freq="min")
    close = 1900 + 8*np.sin(np.arange(n)/13) + np.arange(n)*.0004
    return pd.DataFrame({
        "open_time_utc": time,
        "bid_o": close, "bid_h": close+.3, "bid_l": close-.3,
        "bid_c": close+.04,
        "ask_o": close+.25, "ask_h": close+.55, "ask_l": close-.05,
        "ask_c": close+.29, "spread_mean": [.25]*n, "ticks": [1]*n,
    })


def test_source_m1_indicator_prefix_never_reads_future_bars():
    raw = make_m1()
    original = features(raw)
    later = raw.copy()
    later.loc[7900, "bid_c"] += 100
    changed = features(later)
    assert np.allclose(original["z"][500:7899], changed["z"][500:7899],
                       equal_nan=True)
    assert np.allclose(original["h1_sma"][500:7899],
                       changed["h1_sma"][500:7899], equal_nan=True)


def test_trading_mechanics_tracked_and_cash_reconciles():
    row = replay(features(make_m1()), slip=.25, commission=.14)
    assert row["year_start_usd"] == 10000.
    assert row["source_native_parity"] is False
    assert row["intratrade_marked_drawdown_measured"] is False
    assert len(row["trades"]) == row["closed"]
    assert sum(t["pnl_usd"] for t in row["trades"]) == pytest.approx(
        row["realized_net_usd"], abs=.01)


def test_source_assumptions_are_disclosed():
    assert MAX_SPREAD == .50
    assert YEARS == (2023, 2024, 2025)
