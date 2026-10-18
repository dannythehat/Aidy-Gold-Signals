"""S003 original source-default rule and no-lookahead first-screen protections."""
import pandas as pd
from scripts.strategy_lab.s003_breakout_follow_two_period import (
 DEFAULTS, README_PRESET, _exit_leg, _signal, _sizing,
 compute_indicators, PERIODS,
)

def bar(**overrides):
    x={"open":2500.,"close":2510.,"high":2513.,"low":2501.,
       "ema":2500.,"bbupper":2507.,"bblower":2480.,
       "atr":5.,"volume":110.,"volma":100.,"ny_hour":12}
    x.update(overrides)
    return pd.Series(x)

def test_readme_preset_not_confused_with_executable_pine_defaults():
    assert DEFAULTS["session_start_hour"]==12
    assert DEFAULTS["session_end_hour"]==18
    assert DEFAULTS["cooldown_bars"]==6
    assert README_PRESET["session_start_hour"]==0
    assert README_PRESET["session_end_hour"]==15
    assert README_PRESET["cooldown_bars"]==3
    assert DEFAULTS["partial_trigger_rr"]==1.6
    assert DEFAULTS["rr_full_target"]==2.0
    assert DEFAULTS["max_open_trades"]==1

def test_completed_close_bollinger_and_volume_filter_are_required():
    assert _signal(bar(),DEFAULTS)==1
    assert _signal(bar(volume=100),DEFAULTS)==0
    assert _signal(bar(close=2505),DEFAULTS)==0
    assert _signal(bar(ny_hour=11),DEFAULTS)==0
    assert _signal(bar(ny_hour=18),DEFAULTS)==0
    assert _signal(bar(close=2470.,ema=2480.,bblower=2475.,bbupper=2500.),DEFAULTS)==-1

def test_risk_sizing_is_one_percent_current_equity_and_0p01_lot_step():
    assert _sizing(10000.,10.,2500.)==.1
    assert _sizing(10000.,100.,2500.)==.01
    assert _sizing(10000.,200.,2500.)==0
    assert _sizing(0.,10.,2500.)==0

def test_bid_ask_cost_per_trade_leg_and_slippage_are_explicit():
    p={"entry_quote":2600.,"side":1}
    x=_exit_leg(p,.1,2610.,"FULL_TARGET_2R",pd.Timestamp("2025-03-21 11:00"),1.)
    assert x["price_pnl_usd"]==100.
    assert x["slippage_usd"]==2.
    assert abs(x["commission_usd"]-.7)<1e-9
    assert abs(x["net_pnl_usd"]-97.3)<1e-8

def test_real_source_tick_count_to_signal_only_when_qualified():
    idx=pd.date_range("2024-12-01",periods=300,freq="15min")
    d=pd.DataFrame({
       "open":[2400.]*300,"close":[2400.]*300,"high":[2401.]*300,
       "low":[2399.]*300,"volume":[100]*300,
    },index=idx)
    c=compute_indicators(d)
    assert pd.isna(c["ema"].iloc[198])
    assert abs(c["ema"].iloc[200]-2400.)<1e-9
    assert c["volma"].iloc[-1]==100.
    assert c["atr"].iloc[-1]>0

def test_independent_2025_and_2026_account_period_contract():
    assert PERIODS["2025"]==("2025-01-01","2026-01-01",12)
    assert PERIODS["2026"]==("2026-01-01","2026-10-01",9)
