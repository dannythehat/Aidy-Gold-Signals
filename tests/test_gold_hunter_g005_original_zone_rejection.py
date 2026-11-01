"""Synthetic G005 quote/lot ledger invariants, no fabricated profit evidence."""
import numpy as np
import pandas as pd
import pytest

from scripts.gold_hunter_g005_original_zone_rejection import (
    broker_lot_overlay,digest,BLOBS,AUTHOR_R,AUTHOR_RISK_PCT,
)

class StopFirstEngine:
    MAX_HOLD_BARS=4
    def _walk(self,m1,side,entry,stop,target,at,limit,slip):
        return at+pd.Timedelta(minutes=15), target, "target"

def fixture(stop=1945):
    at=pd.Timestamp("2025-06-10T11:00:00Z")
    times=pd.date_range(at,periods=8,freq="15min",tz="UTC")
    m15=pd.DataFrame({
      "ask_o":[1950.5]*8,"bid_o":[1950.0]*8,
      "bid_c":[1951.0]*8,"ask_c":[1951.5]*8},index=times)
    m1=pd.DataFrame({"bid_o":[1950.]},index=[at])
    sig=pd.DataFrame([{
      "signal_ts":at-pd.Timedelta(minutes=15),
      "entry_ts":at,"direction":1,"stop":stop,
      "zone_id":4,"setup":"rejection",
    }])
    return sig,m15,m1

def test_original_source_identity_and_selected_fixed_rules():
    assert all(len(sha)==40 for sha in BLOBS.values())
    assert AUTHOR_R==2.0 and AUTHOR_RISK_PCT==.25

def test_cost_and_0_01_lot_invariants():
    sig,m15,m1=fixture()
    engine=StopFirstEngine()
    base=broker_lot_overlay(engine,sig,m15,m1,slippage=.05,
        roundtrip_fee_per_oz=.07,financing_annual=.06)
    stress=broker_lot_overlay(engine,sig,m15,m1,slippage=.25,
        roundtrip_fee_per_oz=.14,financing_annual=.09)
    assert base["closed_trades"]==stress["closed_trades"]==1
    assert base["trades"][0]["lots"]>=.01
    assert abs(round(base["trades"][0]["lots"]*100)-
               base["trades"][0]["lots"]*100)<1e-8
    assert base["trades"][0]["oz"]==base["trades"][0]["lots"]*100
    assert base["trades"][0]["commission_usd"]<stress["trades"][0]["commission_usd"]
    assert base["trades"][0]["cash_equity_after_close"]==pytest.approx(
        10000+base["trades"][0]["net_usd"],abs=.00001)
    assert stress["actual_puprime_symbol_parity"] is False
    assert stress["broker_order_count"]==0
    assert stress["limitations"]

def test_minimum_standard_lot_refuses_unaffordable_signal():
    sig,m15,m1=fixture(stop=1900)
    r=broker_lot_overlay(StopFirstEngine(),sig,m15,m1,slippage=.25,
        roundtrip_fee_per_oz=.14,financing_annual=.09)
    assert r["closed_trades"]==0
    assert r["exclusions"]["min_0_01_standard_lot"]==1

def test_digest_is_deterministic_and_order_insensitive():
    assert digest({"a":1,"b":2})==digest({"b":2,"a":1})
    assert digest({"a":1})!=digest({"a":2})

def test_no_fake_source_trade_without_m15_next_open():
    sig,m15,m1=fixture()
    sig["entry_ts"]=pd.Timestamp("2025-06-11T09:00:00Z")
    r=broker_lot_overlay(StopFirstEngine(),sig,m15,m1,slippage=.25,
        roundtrip_fee_per_oz=.14,financing_annual=.09)
    assert r["closed_trades"]==0
    assert r["exclusions"]["no_next_open"]==1
