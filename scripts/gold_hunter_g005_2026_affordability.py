"""G005 2026 account-size AFFORDABILITY — frozen original 001B signals.

This is a historical continuation using immutable prior CI artifacts only:
* Original 001B timestamped signals from CI #41047905827 and exactly matching
  10 original 2026 R2 tick-derived BID/ASK M1 monthly receipts.
* Original publisher engine's M1 stop-first/target-first intraminute walk.
* Exact same predeclared 2R stop, 0.25% initial equity risk and fee/carry,
  no change to the source strategy itself.

SCENARIOS: distinct *hypothetical* standard-symbol XAUUSD accounts $10k,
$25k, $50k, $100k; ordinary 100oz/standard-lot, 0.01 lot step, 20:1
leverage. NO actual PU Prime account/broker/cent symbol evidence.
Not source-native risk execution (independent lot, spread, fees, 9% carry).
Never claim these 2026 accounts as a pure OOS or live/forward pilot.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd

from scripts.gold_hunter_g005_original_zone_rejection import (
    original_modules,digest,AUTHOR_R,AUTHOR_RISK_PCT
)
from scripts.gold_hunter_g005_2026_original_tick_replay import (
    verified_2026_m1, BEGIN, END
)

BALANCES=(10000.,25000.,50000.,100000.)
CONTRACT_OZ=100.
MINLOT=.01
LOTSTEP=.01
ASSUMED_LEVERAGE=20.
STRESS_SLIP=.25
STRESS_FEE=.14
STRESS_ANNUAL_CARRY=.09

def account_replay(engine,signals,m15,m1,start):
    if start not in BALANCES:
        raise ValueError("Unregistered independent starting balance")
    cash=start
    last_exit=None
    ledger=[]
    rejected={"no_next_15m_open":0,"overlapping":0,"stop_inverted":0,
              "cannot_place_0_01_standard_lot":0,"margin_exceeded":0}
    for s in signals.itertuples(index=False):
        ts=s.entry_ts
        if ts not in m15.index:
            rejected["no_next_15m_open"]+=1
            continue
        if last_exit is not None and ts<=last_exit:
            rejected["overlapping"]+=1
            continue
        row=m15.loc[ts]
        side=int(s.direction)
        entry=(float(row.ask_o) if side>0 else float(row.bid_o))+side*STRESS_SLIP
        stop=float(s.stop)
        risk=side*(entry-stop)
        if not math.isfinite(risk) or risk<=0:
            rejected["stop_inverted"]+=1
            continue
        available_cash_risk=cash*(AUTHOR_RISK_PCT/100)
        ounces_unrounded=available_cash_risk/risk
        step_ounces=CONTRACT_OZ*LOTSTEP
        steps=math.floor(ounces_unrounded/step_ounces+1e-10)
        if steps<1:
            rejected["cannot_place_0_01_standard_lot"]+=1
            continue
        lots=round(LOTSTEP*steps,2)
        oz=CONTRACT_OZ*lots
        margin=entry*oz/ASSUMED_LEVERAGE
        if margin>cash:
            rejected["margin_exceeded"]+=1
            continue
        target=entry+side*AUTHOR_R*risk
        idx=m15.index.get_loc(ts)
        limit=m15.index[min(idx+engine.MAX_HOLD_BARS,len(m15)-1)]
        result=engine._walk(m1,side,entry,stop,target,ts,limit,STRESS_SLIP)
        if result is None:
            exit_ts=limit
            exit_price=float(m15.loc[limit].bid_c if side>0 else m15.loc[limit].ask_c)
            reason="timeout"
        else:
            exit_ts,exit_price,reason=result
        elapsed_hours=max(0.,(exit_ts-ts).total_seconds()/3600)
        fee=STRESS_FEE*oz
        carry=entry*oz*STRESS_ANNUAL_CARRY*elapsed_hours/(24*365)
        gross=(exit_price-entry)*side*oz
        net=gross-fee-carry
        cash+=net
        last_exit=exit_ts
        ledger.append({
          "signal_utc":s.signal_ts.isoformat(),"entry_utc":ts.isoformat(),
          "exit_utc":exit_ts.isoformat(),"side":side,
          "stop":stop,"target":round(target,5),"reason":reason,
          "raw_requested_ounces":round(ounces_unrounded,6),
          "lots":lots,"ounces":oz,"cash_risk_budget":round(available_cash_risk,5),
          "assumed_initial_margin_usd":round(margin,5),
          "commission_usd":round(fee,6),
          "hypothetical_funding_usd":round(carry,6),
          "gross_usd":round(gross,6),"net_usd":round(net,6),
          "cash_after_close":round(cash,6)
        })
    if abs(cash-start-sum(t["net_usd"] for t in ledger))>.02:
        raise ValueError("Account cash vs individual real source trade ledger mismatch")
    gain=sum(max(0.,t["net_usd"]) for t in ledger)
    loss=-sum(min(0.,t["net_usd"]) for t in ledger)
    points=np.array([start]+[t["cash_after_close"] for t in ledger])
    maxdd=float(np.min((points/np.maximum.accumulate(points)-1)*100))
    return {
        "starting_usd":start,"source_unchanged_R":AUTHOR_R,
        "source_unchanged_risk_pct":AUTHOR_RISK_PCT,
        "true_source_signal_count":len(signals),
        "closed_trades":len(ledger),
        "realized_usd":round(cash-start,2),
        "net_return_pct":round(100*(cash/start-1),4),
        "profit_factor":round(gain/loss,3) if loss else None,
        "closed_trade_drawdown_pct":round(maxdd,4),
        "rejected":rejected,"min_lot":MINLOT,
        "standard_contract_oz_per_lot":CONTRACT_OZ,
        "assumed_leverage":ASSUMED_LEVERAGE,
        "actual_broker_and_cent_contract_parity_proven":False,
        "overnight_financing_actual_schedule_proven":False,
        "source_original_risk_sizing_executable":len(ledger)>0,
        "no_intratrade_equity_drawdown_proof":True,
        "no_broker_orders":True,
        "ledger":ledger
    }

def research(source_root:Path,prior_evidence:Path,original_author:Path,out:Path):
    dataset,strategy,engine=original_modules(original_author)
    minute,receipt=verified_2026_m1(source_root)
    proof_path=prior_evidence/"report.json"
    signals_path=prior_evidence/"source_001B_2026_signals.csv"
    if not proof_path.is_file() or not signals_path.is_file():
        raise ValueError("Original G005 2026 source signal/evidence artifacts missing")
    old=json.loads(proof_path.read_text())
    if (old["schema"]!="aidy.g005.2026_original_tick_source_001B.v1"
          or old["source_original_unmodified"] is not True
          or old["source_2026_original_tick_receipts"]["months"]!=10):
        raise ValueError("Not the certified original 001B 2026 source execution")
    sig=pd.read_csv(signals_path)
    sig["signal_ts"]=pd.to_datetime(sig["signal_ts"],utc=True)
    sig["entry_ts"]=pd.to_datetime(sig["entry_ts"],utc=True)
    sig=sig.sort_values("signal_ts")
    if (len(sig)!=old["g005_signals_in_2026"]
          or (sig["signal_ts"]<BEGIN).any()
          or (sig["entry_ts"]>=END).any()
          or sig["signal_ts"].duplicated().all()
          or not set(sig["direction"]).issubset({-1,1})):
        raise ValueError("Original 2026 001B signals tampered")
    m15=dataset.resample(minute,"15min")
    m15.index.name="ts"
    summary={"schema":"aidy.g005.2026_standard_lot_affordability_v1",
             "original_2026_verified_source_sha":old["sha256"],
             "real_2026_quote_receipt_hash":digest(receipt),
             "not_modified_source_signals":True,
             "not_source_native_MT5":True,"not_untouched_oos":True,
             "three_year_2023_25_original_results_preserved":True,
             "balances_tested":list(BALANCES),"results":{}}
    out.mkdir(parents=True,exist_ok=True)
    for amount in BALANCES:
        x=account_replay(engine,sig,m15,minute,amount)
        (out/f"account_{int(amount)}_ledger.json").write_text(
            json.dumps(x,sort_keys=True,indent=2,allow_nan=False)+"\n")
        summary["results"][str(int(amount))]={k:v for k,v in x.items() if k!="ledger"}
    if (summary["results"]["10000"]["closed_trades"]!=
        old["broker_cost_scenarios"]["stress"]["closed_trades"] or
        abs(summary["results"]["10000"]["realized_usd"]-
            old["broker_cost_scenarios"]["stress"]["net_usd"])>.02):
        raise ValueError("Frozen 2026 $10k independent baseline mismatch")
    summary["sha256"]=digest(summary)
    (out/"report.json").write_text(json.dumps(
        summary,sort_keys=True,indent=2,allow_nan=False)+"\n")
    print("G005_2026_ACCOUNT_AFFORDABILITY",json.dumps(
        summary["results"],sort_keys=True),flush=True)
    return summary

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--quotes",required=True,type=Path)
    p.add_argument("--prior-evidence",required=True,type=Path)
    p.add_argument("--author",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    a=p.parse_args()
    try:research(a.quotes,a.prior_evidence,a.author,a.out)
    except Exception as ex:
        a.out.mkdir(parents=True,exist_ok=True)
        (a.out/"BLOCKED.json").write_text(json.dumps({
           "not_tested":True,"error":type(ex).__name__},indent=2)+"\n")
        raise
