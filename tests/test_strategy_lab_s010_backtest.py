"""Source-pinned original MA/RSI full-system regression and fail-closed tests."""
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from aidy.strategy_lab_s010_backtest import (
    BASE, STRESS, Costs, derive_signals, simulate,
)


def history(size=420):
    start=datetime(2025,1,1,tzinfo=UTC)
    # Oscillatory prices exercise several authentic MA 12/34 crossovers.
    prices=[2500+40*__import__("math").sin(i/16)+i*.04 for i in range(size)]
    rows=[]
    for i,p in enumerate(prices):
        rows.append({
            "open_time_utc":(start+timedelta(hours=i)).isoformat(),
            "open":p-1, "high":p+2, "low":p-2, "close":p, "m1_count":60,
        })
    return pd.DataFrame(rows)


def test_original_published_sma_rsi_and_complete_ledger_reproducible():
    h=history()
    data=derive_signals(h)
    assert data["signal"].isin([-1,0,1]).all()
    assert data["signal"].iloc[:34].eq(0).all()
    assert data["sma_fast"].iloc[33]==pytest.approx(
        sum(h["close"].iloc[22:34])/12)
    a=simulate(h,3.28,BASE)
    b=simulate(h,3.28,BASE)
    assert a==b
    assert a["bars"]==len(h)
    assert a["closed_trades"]==len(a["trades"])
    assert a["initial_usd"]==10_000
    assert a["leverage"]==3.28
    assert a["costs"]["spread_usd_per_oz"]==.30
    assert a["risk_flags"][0]=="No strategy stop-loss"
    assert a["monthly"][0]["month"]=="2025-01"
    assert len(a["equity"])==len(h)


def test_entry_is_not_at_signalling_candle_open():
    x=derive_signals(history())
    a=simulate(history(),3.28,BASE)
    for t in a["trades"]:
        entry=pd.Timestamp(t["entry_utc"])
        prior=x.loc[x["open_time_utc"]==entry-timedelta(hours=1)]
        assert len(prior)==1
        assert prior.iloc[0]["signal"]==1
        closing=x.loc[x["open_time_utc"]==pd.Timestamp(t["exit_utc"])-timedelta(hours=1)]
        assert len(closing)==1
        assert closing.iloc[0]["signal"]==-1


def test_stress_and_1x_is_not_invented_broker_truth():
    h=history()
    low=simulate(h,1.,BASE)
    stressed=simulate(h,3.28,STRESS)
    assert low["leverage"]==1.0
    assert stressed["costs"]["spread_usd_per_oz"]==.80
    assert low["closed_trades"]==stressed["closed_trades"]


def test_reject_malformed_source_and_incomplete_hour():
    frame=history()
    frame.loc[10,"m1_count"]=47
    with pytest.raises(ValueError):
        derive_signals(frame)
    frame=history()
    frame.loc[10,"open_time_utc"]=frame.loc[9,"open_time_utc"]
    with pytest.raises(ValueError):
        derive_signals(frame)
    frame=history()
    frame.loc[10,"high"]=frame.loc[10,"low"]-1
    with pytest.raises(ValueError):
        derive_signals(frame)


def test_cost_model_rejects_negative_or_nonfinite_values():
    with pytest.raises(ValueError):
        Costs("bad",-1,0,0).validate()
    with pytest.raises(ValueError):
        Costs("bad",0,float("nan"),0).validate()
    with pytest.raises(ValueError):
        simulate(history(),7,BASE)
