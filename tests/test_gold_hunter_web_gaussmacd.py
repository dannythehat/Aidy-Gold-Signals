"""Synthetic mechanical tests for a newly discovered source, not performance proof."""
import numpy as np
import pandas as pd
import pytest

from scripts.gold_hunter_web_gaussmacd_research import (
    GAUSS_PERIOD, YEARS, gauss4, indicators, signal_at, simulate, true_wilder,
)


def synthetic_market(n=1000):
    times = pd.date_range("2023-01-02T00:00:00Z", periods=n, freq="h")
    prices = 1900 + np.cumsum(np.sin(np.arange(n)/29)*.4 + .1)
    return pd.DataFrame({
        "open": prices, "high": prices+1, "low": prices-1,
        "close": prices+.1, "ask_o": prices+.4, "ask_h": prices+1.4,
        "ask_l": prices-.6, "ask_c": prices+.5, "m1_count": [60]*n
    }, index=times)


def test_gaussian_source_pole_alpha_constant_and_causal_prefix():
    c = pd.Series([2000 + i*.2 + np.sin(i/15) for i in range(800)])
    x = gauss4(c)
    assert len(x) == len(c)
    changed = c.copy()
    changed.iloc[-1] += 15000
    other = gauss4(changed)
    assert np.array_equal(x.iloc[:-1].to_numpy(), other.iloc[:-1].to_numpy())
    assert GAUSS_PERIOD == 100


def test_wilder_seed_and_risk_ledger_reconciles():
    z = pd.Series([2.0]*40)
    out = true_wilder(z, 14)
    assert pd.isna(out.iloc[12])
    assert out.iloc[13] == pytest.approx(2.0)
    assert out.iloc[-1] == pytest.approx(2.0)
    ind = indicators(synthetic_market())
    result = simulate(ind, slippage=.25, commission=.14)
    assert result["starting_usd"] == 1000.0
    assert result["no_actual_mt5_order"] is True
    assert result["closed"] == len(result["trades"])
    assert result["realized_net_usd"] == pytest.approx(
        sum(x["pnl_usd"] for x in result["trades"]), abs=.01)
    assert result["max_marked_drawdown_pct"] <= 0
    assert len(result["monthly"]) == 12


def test_future_candle_changes_cannot_rewrite_prior_signals():
    base = synthetic_market(900)
    alt = base.copy()
    alt.iloc[-1, alt.columns.get_loc("close")] += 1000
    a, b = indicators(base), indicators(alt)
    assert [signal_at(a, i) for i in range(350, 899)] == [
        signal_at(b, i) for i in range(350, 899)]
    assert YEARS == (2023, 2024, 2025)
