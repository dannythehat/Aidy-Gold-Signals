"""Pure synthetic rule causality and cash-ledger tests, never market profit."""
import numpy as np
import pandas as pd
import pytest
from scripts.gold_hunter_external_vol_regime_daily import METHODS, PIN, run_year

def fixture():
    n=800
    idx=pd.bdate_range("2023-01-02",periods=n,tz="UTC")
    i=np.arange(n,dtype=float)
    close=1850+1.2*i+15*np.sin(i/12)
    op=close-.4
    high=np.maximum(close,op)+3
    low=np.minimum(close,op)-3
    d=pd.DataFrame({"first_utc":idx,"bid_o":op,"ask_o":op+.4,
        "high":high,"low":low,"close":close,"m1_count":[1350]*n},index=idx)
    prev=d["close"].shift()
    tr=pd.concat([d["high"]-d["low"],(d["high"]-prev).abs(),
                  (d["low"]-prev).abs()],axis=1).max(axis=1)
    d["atr14"]=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    d["sma200"]=d["close"].rolling(200,min_periods=200).mean()
    d["momentum"]=(d["close"]-d["close"].shift(20))/d["atr14"]
    d["setup"]=(d["momentum"]>.5)&(d["close"]>d["sma200"])&(
        d["atr14"]>d["atr14"].shift(5)*.95)
    d["risk_tier"]=np.where(d["momentum"]>=1.8,.02,
        np.where(d["momentum"]>=1.2,.015,.01))
    return d

def test_genuine_new_source_has_exact_pinned_rules():
    assert len(PIN)==40
    assert set(METHODS)=={"PINE_CLOSE_NEXT_OPEN","PROTECTIVE_INTRADAY_STOP"}
    d=fixture()
    assert not d["setup"].iloc[:199].any()
    assert d["setup"].iloc[250:].any()

def test_closed_trades_reconcile_and_lots_are_0p01():
    d=fixture()
    for mode in METHODS:
        x=run_year(d,2024,mode,.25,.14,.09)
        assert x["entries"]>0
        assert x["closed"]>0
        assert abs(sum(t["net_usd"] for t in x["trades"])-x["realized_usd"]) < .01
        assert all(t["lots"] >= .01 and round(t["lots"]*100)%1==0 for t in x["trades"])
        assert not x["native_pine_parity"]
        assert x["no_broker_trades"]
        assert len(x["daily_equity"])==len(d.loc[d.index.year==2024])

def test_cost_scenarios_are_finite_and_historical():
    d=fixture()
    for mode in METHODS:
        for year in (2023,2024,2025):
            r=run_year(d,year,mode,.05,.07,.06)
            assert np.isfinite(r["marked_usd"])
            assert r["max_daily_marked_dd_pct"]<=0
            assert r["closed"]<=r["entries"]
            assert r["initial_usd"]==10000.

def test_unknown_unregistered_fails():
    with pytest.raises(ValueError,match="Unknown"):
        run_year(fixture(),2023,"FAKE",.05,.07,.06)
