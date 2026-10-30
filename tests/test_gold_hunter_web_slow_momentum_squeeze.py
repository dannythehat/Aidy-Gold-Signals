"""Synthetic causality/accounting fixtures only. Original 2023-25 data verified by CI."""
import numpy as np
import pandas as pd
import pytest

from scripts.gold_hunter_web_slow_momentum_squeeze import (
    FAMILIES,indicators,replay,
)


def fixture(n=3000):
    ts=pd.date_range("2023-01-02",periods=n,freq="h",tz="UTC")
    i=np.arange(n,dtype=float)
    close=1900+60*np.sin(i/90)+.12*i+4*np.sin(i/3)
    base=close-0.7
    return pd.DataFrame({
        "open_time_utc":ts,"open":base,
        "high":np.maximum(base,close)+1.2,
        "low":np.minimum(base,close)-1.2,"close":close,
        "observed_open_ask":base+.32,
        "observed_max_spread":np.full(n,.55),
        "m1_count":np.full(n,60),
    })


def test_all_forecasts_are_causal_after_future_mutation():
    original=fixture()
    alternative=original.copy()
    cut=2500
    alternative.loc[cut:,"close"]+=200
    alternative.loc[cut:,"open"]+=200
    alternative.loc[cut:,"high"]+=200
    alternative.loc[cut:,"low"]+=200
    alternative.loc[cut:,"observed_open_ask"]+=200
    left,_=indicators(original)
    right,_=indicators(alternative)
    # Includes full closed bar 2499 but excludes any later changed rows.
    for k in ("signal_tsmom","signal_squeeze","ATR14","ATR20"):
        np.testing.assert_allclose(
            left[k].iloc[:cut].to_numpy(),
            right[k].iloc[:cut].to_numpy(),
            equal_nan=True)


def test_source_rule_port_shapes_and_no_training_future():
    x,coverage=indicators(fixture())
    assert set(FAMILIES)=={"TSMOM_MULTI_HORIZON","BB_KC_SQUEEZE_RELEASE"}
    assert set(x["signal_squeeze"].unique()) <= {-1,0,1}
    assert set(x["signal_tsmom"].unique()) <= {-1,0,1}
    assert x["signal_tsmom"].iloc[:1440].eq(0).all()
    assert coverage["momentum_complete_bars"]>=1400


def test_exact_net_trade_ledger_and_stress_execution():
    x,_=indicators(fixture())
    for family in FAMILIES:
        base=replay(x,family,slippage=.05,commission=.07,financing_rate=.06)
        stress=replay(x,family,slippage=.25,commission=.14,financing_rate=.09)
        assert stress["closed_trades"]==len(stress["trade_ledger"])
        assert sum(t["net_usd"] for t in stress["trade_ledger"]) == pytest.approx(
            stress["realized_usd"], abs=.01)
        assert stress["initial_usd"]==10_000.
        assert stress["no_source_native_parity"] is True
        assert stress["protective_stop_locks_same_forecast_until_reset"] is True
        assert stress["marked_net_usd"] <= base["marked_net_usd"]+.01


def test_cannot_register_unknown_family():
    x,_=indicators(fixture())
    with pytest.raises(ValueError,match="Unregistered"):
        replay(x,"MAKE_MONEY",slippage=0,commission=0,financing_rate=0)
