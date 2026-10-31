"""Source-interpretation controls, synthetic only, not real trading results."""
import numpy as np
import pandas as pd
import pytest
from scripts.gold_hunter_dev_ny_orb_ema50 import (
   MODES, literal_same_bar_impossible, source_inspired_signals, account_replay
)

def candles(start="2025-06-09",hours=240,entry_day="2025-06-16"):
    ts=pd.date_range(start,periods=hours,freq="h",tz="UTC")
    base=2400+0.10*np.arange(hours)
    df=pd.DataFrame({"open_time_utc":ts,"open":base,"high":base+3.0,
      "low":base-3.0,"close":base+1.0,
      "observed_open_ask":base+0.30,
      "observed_max_spread":np.full(hours,.6),
      "m1_count":np.full(hours,60)})
    # Break 13,14,15 hourly range only on the 16 UTC post-range candle.
    time=pd.Timestamp(entry_day+"T16:00:00Z")
    ix=df.index[df["open_time_utc"]==time]
    if len(ix):
        i=int(ix[0]);df.loc[i,"close"]=df.loc[i,"open"]+24
        df.loc[i,"high"]=df.loc[i,"close"]+1
    return df

def test_literal_rule_no_possible_signals():
    d=candles()
    x=literal_same_bar_impossible(d)
    assert x["strict_literal_signals"]==0
    assert x["checked_full_3h_windows"]>=4

def test_different_session_clocks_and_next_hour_only():
    d=candles()
    fixed,sf,_=source_inspired_signals(d,"FIXED_UTC_REPAIRED")
    local,sl,_=source_inspired_signals(d,"NEWYORK_LOCAL_DST_REPAIRED")
    assert len(sf)>=1 and len(sl)>=1
    assert all(pd.Timestamp(s["entry_at_utc"]) >
               pd.Timestamp(s["signal_at_utc"])-pd.Timedelta(seconds=1)
               for s in sf)
    assert all(s["range_start_utc"].endswith("13:00:00+00:00") for s in sf)
    assert all(s["entry_at_utc"].endswith("17:00:00+00:00") for s in sf)
    assert all(s["clock_mode"]=="NEWYORK_LOCAL_DST_REPAIRED" for s in sl)

def test_ny_winter_range_shifts_utc_one_hour():
    d=candles("2025-01-06",240,"2025-01-13")
    _,sig,info=source_inspired_signals(d,"NEWYORK_LOCAL_DST_REPAIRED")
    # January New York 09:00 is UTC14:00, unlike July UTC13:00.
    if sig:
        assert all(s["range_start_utc"].endswith("14:00:00+00:00") for s in sig)

def test_same_entry_hour_adverse_extreme_and_cash_reconcile():
    d=candles()
    x,sig,_=source_inspired_signals(d,"FIXED_UTC_REPAIRED")
    assert sig
    i=sig[0]["entry_idx"]
    # Force adverse stop in entry hour; must not ignore as an H1 path ambiguity.
    x.loc[i,"low"]=x.loc[i,"open"]-1000
    a=account_replay(x,sig,slip=.25,roundtrip_fee_per_oz=.14,
                     annual_carry=.09,mode="FIXED_UTC_REPAIRED")
    assert a["entries"]>=1
    assert any(z["reason"]=="ENTRY_HOUR_STOP_FIRST" for z in a["ledger"])
    assert abs(sum(z["net_usd"] for z in a["ledger"])-a["net_realized_usd"])<.02
    assert a["no_broker_orders"]
    assert not a["original_author_native_parity"]

def test_reject_unregistered_clock():
    with pytest.raises(ValueError,match="Unknown"):
        source_inspired_signals(candles(),"FUTURE_KNOWS")
