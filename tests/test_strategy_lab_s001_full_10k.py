"""S001 actual account, chronology, cost and signal audit contract."""
import numpy as np
import pandas as pd

from scripts.strategy_lab.s001_full_10k_real_history import (
    MONTHS,
    bias_projection,
    signal_table,
    simulate,
)


def _inputs(signal=1):
    idx=pd.date_range("2025-01-06 10:00",periods=4,freq="15min")
    data=pd.DataFrame({
        "open":[2600.,2600.,2600.,2600.],
        "high":[2601.,2601.,2613.,2601.],
        "low":[2599.,2599.,2599.,2599.],
        "close":[2600.,2600.,2610.,2600.],
        "signal":[0,signal,0,0],
        "atr":[2.,2.,2.,2.],
        "sweep_extreme":[np.nan,2599.,np.nan,np.nan],
        "vwap_proxy":[2600.,2600.,2600.,2600.],
        "bias":[0,1,1,1],
        "uk_date":[pd.Timestamp(t).date() for t in idx],
    },index=idx)
    return data


def test_next_open_trade_is_real_10k_costed():
    packet=simulate(_inputs(),scenario="unit_long_2R")
    assert packet["closed_trades"] == 1
    assert packet["wins"] == 1
    assert packet["net_usd"] > 0
    assert packet["ending_usd"] == round(10000+packet["net_usd"],2)
    entry=packet["trades"][0]
    assert entry["entry_time"]=="2025-01-06 10:30:00Z"
    assert entry["signal_time"]=="2025-01-06 10:30:00Z"
    assert entry["exit_reason"] == "target_2R"
    assert entry["costs"]>0
    assert packet["monthly"][0]["closed_trades"] == 1
    assert sum(x["closed_trades"] for x in packet["monthly"])==1


def test_gaps_cancel_next_open():
    df=_inputs()
    df.index=pd.DatetimeIndex(["2025-01-06 10:00","2025-01-06 10:15",
                               "2025-01-06 12:00","2025-01-06 12:15"])
    x=simulate(df,scenario="gap")
    assert x["closed_trades"]==0
    assert x["net_usd"]==0


def test_stressed_cost_reduces_net():
    df=_inputs()
    base=simulate(df,scenario="base")
    stress=simulate(df,scenario="stress",spread=.60,slippage=.20)
    assert stress["net_usd"]<base["net_usd"]


def test_no_signals_means_no_fake_trades_or_pnl():
    df=_inputs(signal=0)
    r=simulate(df,scenario="none")
    assert r["net_usd"]==0
    assert r["closed_trades"]==0
    assert len(r["monthly"])==len(MONTHS)


def test_confirmed_htf_swing_cannot_be_used_at_pivot():
    df=pd.DataFrame({
        "high":[10.,11.,20.,12.,11.,11.,11.,11.,12.,12.,12.],
        "low":[8.,8.,7.,8.,9.,9.,9.,9.,9.,9.,9.],
    },index=pd.date_range("2025-01-06 08:00",periods=11,freq="1h"))
    times=pd.date_range("2025-01-06 08:15",periods=48,freq="15min")
    projected,_=bias_projection(times,df,lookback=2,confirm=2)
    assert all(projected[times< pd.Timestamp("2025-01-06 13:00")]==0)


def test_signal_table_cannot_fabricate_missing_source_candles():
    idx=pd.date_range("2025-01-06",periods=50,freq="15min",tz="UTC")
    raw=pd.DataFrame({
        "open_time_utc":idx.astype(str),"open":[2600.]*50,
        "high":[2601.]*50,"low":[2599.]*50,"close":[2600.]*50
    })
    raw=raw.drop([11,12]).reset_index(drop=True)
    out=signal_table(raw)
    assert len(out)==48
    assert out["signal"].abs().sum()==0
