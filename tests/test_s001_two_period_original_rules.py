"""S001 original published rule formulas, chronology and two-account audit gates."""
from __future__ import annotations
from datetime import UTC, datetime
import numpy as np
import pandas as pd

from scripts.strategy_lab.s001_two_period_original_rules import (
    PERIODS,RULES,build_signals,model_period,project_bias,swing_events,
    wilder_atr_publisher,
)

def test_original_publisher_atr_seed_preserved_not_silently_optimised():
    ix=pd.date_range("2025-01-01",periods=19,freq="15min")
    data=pd.DataFrame({"high":[101.]*19,"low":[99.]*19,"close":[100.]*19},index=ix)
    a=wilder_atr_publisher(data,14)
    assert np.isnan(a[13])
    assert a[14]==28.0
    assert np.isclose(a[15],(28*13+2)/14)

def test_confirmed_swings_only_released_after_HTF_close():
    ix=pd.date_range("2025-01-06 08:00",periods=13,freq="h")
    d=pd.DataFrame({"high":[3.,3.,3.,3.,3.,8.,3.,3.,3.,3.,3.,3.,3.],
                    "low":[2.]*13},index=ix)
    ev=swing_events(d,5,3)
    hi=[x for x in ev if x[1]=="high" and x[2]==8.]
    assert hi and hi[0][0]==pd.Timestamp("2025-01-06 17:00:00")
    times=pd.DatetimeIndex(["2025-01-06 13:00","2025-01-06 16:45"])
    assert all(project_bias(times,ev)==0)

def test_both_periods_exact_same_frozen_input_contract():
    assert RULES["target_r"] is None
    assert RULES["require_vwap_confluence"] is False
    assert RULES["vwap_weight"].startswith("source_HistData_tick_count")
    assert len(PERIODS["2025"]["months"])==12
    assert len(PERIODS["2026"]["months"])==9
    assert PERIODS["2025"]["start"]=="2025-01-01"
    assert PERIODS["2026"]["end"]=="2026-10-01"

def synthetic(signal=1,year="2025"):
    times=pd.date_range(f"{year}-01-06 10:00",periods=5,freq="15min")
    return pd.DataFrame({
        "open":[2600.,2600.,2600.,2600.,2600.],
        "high":[2601.,2601.,2601.,2601.,2602.],
        "low":[2599.,2599.,2599.,2599.,2599.],
        "close":[2600.,2600.,2600.,2600.,2602.],
        "signal":[0,signal,0,0,0],"naive":[0]*5,
        "atr":[2.]*5,
        "vwap":[2601.,2601.,2601.,2601.,2601.],
        "long_wick_reference":[2599.]*5,
        "short_wick_reference":[2601.]*5,
        "observed_open_spread":[.50]*5,
        "uk_date":[x.date() for x in times],
    },index=times)

def test_causal_next_m15_entry_and_costs_on_independent_10k_account():
    r=model_period(synthetic(),"2025","published_default_vwap_exit")
    assert r["closed_trades"]==1
    trade=r["trades"][0]
    assert trade["entry_time"]=="2025-01-06 10:30:00Z"
    assert trade["signal_time"]=="2025-01-06 10:30:00Z"
    assert trade["exit_reason"]=="native_volume_sourced_vwap_cross"
    assert trade["execution_cost"]>0
    assert abs(r["end_usd"]-10000-r["net_usd"])<.02

def test_2026_reset_to_exactly_independent_10k():
    a=model_period(synthetic(year="2025"),"2025","published_default_vwap_exit")
    b=model_period(synthetic(year="2026"),"2026","published_default_vwap_exit")
    assert a["start_usd"]==b["start_usd"]==10000
    assert a["net_usd"]==b["net_usd"]
    assert len(b["monthly"])==9
    assert b["monthly"][0]["closed_trades"]==1

def test_no_sweep_means_no_fabricated_research_pnl():
    r=model_period(synthetic(signal=0),"2025","published_default_vwap_exit")
    assert r["closed_trades"]==0 and r["net_usd"]==0
    assert r["max_marked_drawdown_pct"]==0

def test_no_volume_substitution_when_source_has_none():
    ix=pd.date_range("2025-01-01",periods=60,freq="15min")
    raw=pd.DataFrame({
        "open":2600.,"high":2601.,"low":2599.,"close":2600.,
        "observed_open_spread":.5,
    },index=ix)
    try:
        build_signals(raw)
        raise AssertionError("Should reject history without authentic volume")
    except KeyError:
        pass
