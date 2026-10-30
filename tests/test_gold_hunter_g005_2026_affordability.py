"""Falsify affordability modelling without source data or market trading."""
import pandas as pd
import pytest
from scripts.gold_hunter_g005_2026_affordability import (
    BALANCES, account_replay, CONTRACT_OZ, MINLOT,
)

class OriginalStub:
    MAX_HOLD_BARS=5
    def _walk(self,m1,side,entry,stop,target,at,limit,slip):
        return at+pd.Timedelta(minutes=15),target,"target"

def fixture():
    at=pd.Timestamp("2026-03-17T12:00:00Z")
    idx=pd.date_range(at,periods=10,freq="15min",tz="UTC")
    m15=pd.DataFrame({"ask_o":[3000.4]*10,"bid_o":[3000.0]*10,
                      "bid_c":[3000.0]*10,"ask_c":[3000.4]*10},index=idx)
    m1=pd.DataFrame({"bid_o":[3000]},index=[at])
    sig=pd.DataFrame([{"signal_ts":at-pd.Timedelta(minutes=15),
                       "entry_ts":at,"direction":1,"stop":2950.0}])
    return sig,m15,m1

def test_preserves_same_source_settings_and_different_balances():
    sig,m15,m1=fixture()
    r10=account_replay(OriginalStub(),sig,m15,m1,10000.)
    r25=account_replay(OriginalStub(),sig,m15,m1,25000.)
    r50=account_replay(OriginalStub(),sig,m15,m1,50000.)
    assert r10["closed_trades"]==0
    assert r10["rejected"]["cannot_place_0_01_standard_lot"]==1
    assert r25["closed_trades"]==r50["closed_trades"]==1
    assert r25["ledger"][0]["lots"]==.01
    assert r50["ledger"][0]["lots"]==.02
    assert r25["source_unchanged_risk_pct"]==r50["source_unchanged_risk_pct"]==.25
    assert r25["actual_broker_and_cent_contract_parity_proven"] is False

def test_cash_ledger_and_margin_respect_full_standard_100oz():
    sig,m15,m1=fixture()
    for start in BALANCES:
        r=account_replay(OriginalStub(),sig,m15,m1,start)
        assert r["no_broker_orders"]
        assert r["starting_usd"]==start
        assert abs(sum(t["net_usd"] for t in r["ledger"])-r["realized_usd"])<.02
        for t in r["ledger"]:
            assert t["ounces"]==t["lots"]*CONTRACT_OZ
            assert t["lots"]>=MINLOT
            assert t["assumed_initial_margin_usd"]<=start

def test_unknown_balance_refused_prevents_hidden_parameter_grid():
    sig,m15,m1=fixture()
    with pytest.raises(ValueError,match="Unregistered"):
        account_replay(OriginalStub(),sig,m15,m1,15000.)
