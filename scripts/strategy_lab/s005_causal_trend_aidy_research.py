"""S005 AIDY genuine-source H1/H4 causal condition diagnosis, frozen original replay.

Only two preregistered structural hypotheses: A) >=0.30 last-24-completed-H1
path efficiency, and B) previous six fully closed H4 bars' momentum agrees
with proposed trade. Both are applied to the ORIGINAL publisher signals at a
finished bar before the next-open entry, never filtered after outcomes.
No optimal threshold search, no real broker connection, no trading or promotion.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.strategy_lab.s005_publisher_engine_two_preset_parity import (
    BLOBS, PUB_COMMIT, original_modules,
)

MONTHS = {
    "2023_2024": ["202212"] + [f"{y}{m:02d}" for y in (2023, 2024) for m in range(1,13)],
    "2025_2026": ["202412"] + [f"2025{m:02d}" for m in range(1,13)] + [f"2026{m:02d}" for m in range(1,10)],
}
PERIODS = {
    "2023": ("2023_2024", "2023-01-01", "2024-01-01", 103, 320.60),
    "2024": ("2023_2024", "2024-01-01", "2025-01-01", 123, 693.33),
    "2025": ("2025_2026", "2025-01-01", "2026-01-01", 121, 1668.12),
    "2026_JAN_SEP": ("2025_2026", "2026-01-01", "2026-10-01", 80, 2360.70),
}
COSTS = (0.45,0.90)
VARIANTS = ("ORIGINAL", "A_H1_PATH_EFFICIENCY_0P30", "B_H4_SIX_BAR_MOMENTUM_AGREES")
SCHEMA = "aidy.s005.causal_trend_quality_2023_to_sep2026.v1"


def digest(a):
    return hashlib.sha256(json.dumps(a,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def market_group(root: Path, months: list[str]):
    chunks, proofs = [], []
    for month in months:
        # A strict original-source dataset naming scheme, never generic fallback.
        if months[0]=="202212":
            d=root/("s005-2023-24-source-"+month)
        else:
            d=root/("s001-source-"+month)
        r=json.loads((d/"receipt.json").read_text(encoding="utf-8"))
        required={"fixed_est_month":month,"source_clock":"EST_FIXED_UTC_MINUS_05",
                  "original_zip_modified":False,"actual_broker_fill_verified":False}
        if any(r.get(k)!=v for k,v in required.items()):
            raise ValueError("Original source receipt failure: "+month)
        if any(len(str(r.get(k,"")))!=64 for k in ("derived_m15_sha256","original_zip_sha256")):
            raise ValueError("Unqualified historic source hash: "+month)
        with (d/"m15.csv").open(newline="",encoding="utf-8") as f:
            rows=list(csv.DictReader(f))
        clean=[]
        for x in rows:
            clean.append({"open_time_utc":x["open_time_utc"],
              **{k:float(x[k]) for k in ("open","high","low","close","observed_open_ask", "observed_open_spread","observed_max_spread")},
              **{k:int(x[k]) for k in ("m1_count","volume")}})
        if len(clean)<750 or len(clean)!=int(r["complete_m15"]) or digest(clean)!=r["derived_m15_sha256"]:
            raise ValueError("Monthly original bar source mismatch: "+month)
        frame=pd.DataFrame(clean)
        idx=pd.to_datetime(frame.pop("open_time_utc"),utc=True)
        if (idx-pd.Timedelta(hours=5)).dt.strftime("%Y%m").ne(month).any() or idx.duplicated().any() or not idx.is_monotonic_increasing:
            raise ValueError("Original fixed EST UTC bar time mismatch: "+month)
        if ((frame.m1_count!=15).any() or (frame.volume<15).any() or
            (frame.observed_open_ask<frame.open).any() or
            (frame.low>frame.high).any() or (frame.open<frame.low).any() or
            (frame.open>frame.high).any() or (frame.close<frame.low).any() or
            (frame.close>frame.high).any() or
            ((frame.observed_open_ask-frame.open-frame.observed_open_spread).abs()>.00001).any()):
            raise ValueError("Invalid original source quote/candle: "+month)
        frame.index=idx.dt.tz_localize(None)
        chunks.append(frame)
        proofs.append({"month":month,"source_zip_sha256":r["original_zip_sha256"],
                      "derived_m15_sha256":r["derived_m15_sha256"],"rows":len(clean),
                      "original_source_time_inversions":r["source_tick_inversions"]})
    m15=pd.concat(chunks)
    if m15.index.duplicated().any() or not m15.index.is_monotonic_increasing:
        raise ValueError("Cross-month source overlap/order mismatch")
    h1=m15.resample("60min").agg(open=("open","first"),high=("high","max"),
            low=("low","min"),close=("close","last"),actual_m15=("open","count"))
    h1=h1[h1.actual_m15==4].copy()
    h4=m15.resample("240min").agg(open=("open","first"),high=("high","max"),
            low=("low","min"),close=("close","last"),actual_m15=("open","count"))
    h4=h4[h4.actual_m15==16].copy()
    if len(h1)<7500 or len(h4)<1500:
        raise ValueError("Insufficient authenticated complete H1/H4")
    return h1,h4,proofs,digest({"h1_sha256":hashlib.sha256(h1.to_csv().encode()).hexdigest(),
                                "h4_sha256":hashlib.sha256(h4.to_csv().encode()).hexdigest(),
                                "source_receipts":proofs})


def causal_context(h1, h4):
    """Entry at H1 next open: feature for signal candle i uses <= i-close."""
    close=h1.close.astype(float)
    absolute_movement=close.diff().abs().rolling(24,min_periods=24).sum()
    path=(close.diff(24).abs()/absolute_movement.replace(0,np.nan)).to_numpy()
    h1_finish=(h1.index+pd.Timedelta(hours=1)).as_unit("ns").asi8
    h4_finish=(h4.index+pd.Timedelta(hours=4)).as_unit("ns").asi8
    prior=np.searchsorted(h4_finish,h1_finish,side="right")-1
    confirm=np.full(len(h1),np.nan)
    h4close=h4.close.to_numpy(float)
    for i,j in enumerate(prior):
        if j>=6 and 0<=h1_finish[i]-h4_finish[j]<=12*3600*1_000_000_000:
            confirm[i]=h4close[j]-h4close[j-6]
            if h4_finish[j]>h1_finish[i]:
                raise ValueError("H4 future leak")
    if np.any(np.isfinite(path) & ((path<0) | (path>1+1e-9))):
        raise ValueError("Path efficiency outside [0,1]")
    return path,confirm


def signals_for_variant(base,path,momentum,variant):
    long0,short0,longexit,shortexit=base
    if variant=="ORIGINAL":
        return tuple(np.array(x,copy=True) for x in base)
    if variant=="A_H1_PATH_EFFICIENCY_0P30":
        valid=np.isfinite(path)&(path>=0.30)
        return (long0 & valid,short0 & valid, np.array(longexit,copy=True),np.array(shortexit,copy=True))
    if variant=="B_H4_SIX_BAR_MOMENTUM_AGREES":
        return (long0 & np.isfinite(momentum)&(momentum>0),
                short0 & np.isfinite(momentum)&(momentum<0),
                np.array(longexit,copy=True),np.array(shortexit,copy=True))
    raise ValueError("Unknown or unregistered variant")


def summarise(engine,arr,atr,base,lo,hi,cost,year,context,variant):
    o,h,l,c,times=arr
    params=engine.EngineParams(sl_atr=2.5,tp_atr=0.,trail_atr=0.,allow_reverse=True,
        risk_pct=1.,start_equity=10000.)
    spec=engine.SymbolSpec("XAUUSD",cost=cost,max_leverage=20.)
    res=engine.simulate(o,h,l,c,times,atr,*base,spec,params,lo,hi)
    realized=float(sum(t.pnl for t in res.trades))
    if len(res.trades)<1 or not np.isfinite(realized) or abs(realized-100*res.net_return)>.20:
        raise ValueError("Original publisher native cash/P&L divergence "+year+variant)
    trade_rows=[]
    for t in res.trades:
        sig=t.entry_i-1
        if sig<0 or sig>=len(times):
            raise ValueError("Trade lacks causal pre-entry state")
        entry=int(times[t.entry_i])
        if not (pd.Timestamp("2023-01-01",tz="UTC").timestamp()<=entry<=pd.Timestamp("2026-10-01",tz="UTC").timestamp()):
            raise ValueError("Incorrect trade epoch (Pandas unit bug)")
        hold_h=(int(times[t.exit_i])-entry)/3600
        trade_rows.append({
            "trade_side":"LONG" if t.dir>0 else "SHORT",
            "entry_utc":str(pd.Timestamp(entry,unit="s",tz="UTC")),
            "exit_utc":str(pd.Timestamp(int(times[t.exit_i]),unit="s",tz="UTC")),
            "entry_h1_signal_time":str(pd.Timestamp(int(times[sig]),unit="s",tz="UTC")),
            "entry_causal_path_efficiency_24h1":float(context[0][sig]) if np.isfinite(context[0][sig]) else None,
            "entry_causal_last_six_complete_h4_momentum_usd":float(context[1][sig]) if np.isfinite(context[1][sig]) else None,
            "entry_path_gate_pass":bool(np.isfinite(context[0][sig]) and context[0][sig]>=.3),
            "entry_h4_gate_pass":bool(np.isfinite(context[1][sig]) and context[1][sig]*t.dir>0),
            "model_pnl_usd":round(float(t.pnl),6),"model_float_ounces":round(float(t.units),7),
            "exit_reason":t.reason,"holding_hours":round(float(hold_h),2),
            "is_model_win":bool(t.pnl>0)})
    return {"net_profit_usd":round(realized,2),"ending_usd":round(10000+realized,2),
            "max_marked_drawdown_pct":round(-float(res.max_dd),4),
            "profit_factor":round(float(res.profit_factor),4) if np.isfinite(res.profit_factor) else None,
            "win_rate_pct":round(float(res.win_rate),3),
            "completed_trades":len(res.trades),
            "long_model_net_usd":round(sum(t.pnl for t in res.trades if t.dir>0),2),
            "short_model_net_usd":round(sum(t.pnl for t in res.trades if t.dir<0),2),
            "stops_including_gaps":sum(t.reason in ("sl","sl_gap") for t in res.trades),
            "largest_three_winners_usd":round(sum(sorted((float(t.pnl) for t in res.trades),reverse=True)[:3]),2),
            "trade_ledger":trade_rows}


def diagnose_original(trades):
    bucket=defaultdict(list)
    for t in trades:
        side=t["trade_side"]
        bucket[(side,"path_gate_pass" if t["entry_path_gate_pass"] else "path_gate_fail")].append(t["model_pnl_usd"])
        bucket[(side,"h4_gate_pass" if t["entry_h4_gate_pass"] else "h4_gate_fail")].append(t["model_pnl_usd"])
        bucket[(side,"stop" if t["exit_reason"] in ("sl","sl_gap") else "other_exit")].append(t["model_pnl_usd"])
    return {"|".join(k):{"trades":len(a),"original_fixed_trade_cohort_net_usd":round(sum(a),2),
                        "winners":sum(z>0 for z in a)} for k,a in sorted(bucket.items())}


def run(root_old,publisher,out):
    engine,strategies=original_modules(publisher)
    buckets={}
    for group in MONTHS:
        root=root_old/(group)
        h1,h4,receipts,source_hash=market_group(root,MONTHS[group])
        o,h,l,c=[h1[k].to_numpy(float) for k in ("open","high","low","close")]
        times=h1.index.tz_localize("UTC").as_unit("ns").asi8//1_000_000_000
        if times[-1]-times[0]<365*24*3600:
            raise ValueError("Incorrect H1 UTC seconds scale")
        hours=h1.index.tz_localize("UTC").hour.to_numpy()
        atr=engine.atr(h,l,c,14)
        long0,short0,longexit,shortexit=strategies.donchian(o,h,l,c,hours,entry_n=24,exit_n=12,ema_filter=200)
        context=causal_context(h1,h4)
        buckets[group]={"h1_count":len(h1),"h4_count":len(h4),"source_proof_sha256":source_hash,
                        "all_source_receipts":receipts,"engine_arrays":(o,h,l,c,times),
                        "atr":atr,"original_signals":(long0,short0,longexit,shortexit),"context":context}
    output={};out.mkdir(parents=True,exist_ok=True)
    for yr,(group,start,end,expected_trades,expected_model_profit) in PERIODS.items():
        raw=buckets[group]
        arr=raw["engine_arrays"]
        times=arr[-1]
        lo=int(np.searchsorted(times,int(pd.Timestamp(start,tz="UTC").timestamp())))
        hi=int(np.searchsorted(times,int(pd.Timestamp(end,tz="UTC").timestamp())))
        if not 3900 <= hi-lo <= 6400:
            raise ValueError("Missing substantial full year of H1: "+yr)
        output[yr]={}
        for cost in COSTS:
            ckey=f"{cost:.2f}"
            variants={}
            for name in VARIANTS:
                sigs=signals_for_variant(raw["original_signals"],*raw["context"],name)
                variants[name]=summarise(engine,arr,raw["atr"],sigs,lo,hi,cost,yr,raw["context"],name)
            original=variants["ORIGINAL"]
            if cost==.45 and (original["completed_trades"] !=expected_trades or
                                abs(original["net_profit_usd"]-expected_model_profit)>.02):
                raise ValueError(f"CANONICAL_ORIGINAL_PARITY_FAIL {yr} expected {expected_trades} {expected_model_profit}, got {original['completed_trades']} {original['net_profit_usd']}")
            # EXIT arrays are shared by all experiments, actual trade population will be rerun.
            original_ledger=original["trade_ledger"]
            rec={"models":variants,"original_causal_entry_diagnostics":diagnose_original(original_ledger),
                 "comparison_to_original":{key:{"delta_model_net_usd":round(z["net_profit_usd"]-original["net_profit_usd"],2),
                    "delta_max_marked_dd_pp":round(z["max_marked_drawdown_pct"]-original["max_marked_drawdown_pct"],4),
                    "change_closed_trades":z["completed_trades"]-original["completed_trades"],
                    "largest_three_winners_usd":z["largest_three_winners_usd"]}
                    for key,z in variants.items() if key!="ORIGINAL"}}
            output[yr][ckey]=rec
            print("S005_AIDY_CAUSAL_GATE_RESULTS",json.dumps({"period":yr,"publisher_cost":cost,
             "variants":{name:{k:v[k] for k in ("net_profit_usd","max_marked_drawdown_pct","completed_trades","profit_factor","stops_including_gaps")} for name,v in variants.items()}},sort_keys=True),flush=True)
    packet={"schema":SCHEMA,"original_author_source_commit":PUB_COMMIT,
        "original_author_source_blobs":BLOBS,
        "all_months_pinned_original_price_bidask_receipts":True,
        "study_periods":{"2023":"calendar year","2024":"calendar year","2025":"calendar year","2026_JAN_SEP":"nine months through 2026-09-30"},
        "prespecified_rules":[
            "Original: exact author Donchian24/12 EMA200 H1 ATR14 x2.5 1% entry risk, no profit target.",
            "A: permit original BUY or SELL only if absolute close[i]-close[i-24] / sum 24 absolute H1 movements >= 0.30 on the completed H1 signal candle.",
            "B: permit original BUY only if last fully completed H4 close > sixth earlier fully completed H4 close; permit SELL only if less; no future H4 data."],
        "hypotheses_not_tuned_on_actual_outcomes":True,
        "all_years_already_research_reviewed_therefore_not_blind_oos":True,
        "trade_execution_engine":"original_publisher_python_model_reexecuted_with_original_bid_H1_entry_exit",
        "same_exit_stop_leverage_and_risk_rules_except_registered_entry_gates":True,
        "source_original_bidask_price_available_but_ask_broker_execution_not_simulated":True,
        "actual_bidask_at_trade_fill_used":False,
        "native_MT5_account_trade_ledger_verified":False,"actual_swaps_and_margin_not_qualified":True,
        "cash_recompound_on_accepted_trades":True,"false_discard_only_backtest":False,
        "model_cost_roundtrip_usd_per_oz":list(COSTS),
        "original_strategy_modified_in_repo_or_broker":False,"real_paper_or_live_orders_placed":False,
        "years":output,
        "source_groups":{key:{k:v for k,v in d.items() if k in ("h1_count","h4_count","source_proof_sha256","all_source_receipts")} for key,d in buckets.items()}}
    packet["sha256"]=digest(packet)
    (out/"S005_AIDY_CAUSAL_REGIME_2023_2026.json").write_text(json.dumps(packet,indent=2,sort_keys=True,allow_nan=False)+"\n",encoding="utf-8")
    rows=[]
    for yr,v in output.items():
        for cost,w in v.items():
            a=w["models"]["ORIGINAL"]
            for name,z in w["models"].items():
                rows.append({"period":yr,"cost_per_oz_roundtrip_model":cost,"variant":name,
                  "trades":z["completed_trades"],"model_net_usd":z["net_profit_usd"],
                  "delta_vs_original_net_usd":round(z["net_profit_usd"]-a["net_profit_usd"],2),
                  "model_max_marked_dd_pct":z["max_marked_drawdown_pct"],
                  "dd_improvement_pp":round(z["max_marked_drawdown_pct"]-a["max_marked_drawdown_pct"],4),
                  "profit_factor":z["profit_factor"],"largest_three_winners_usd":z["largest_three_winners_usd"]})
    with (out/"S005_FOUR_PERIOD_MODEL_COMPARISON.csv").open("w",newline="",encoding="utf-8") as file:
        writer=csv.DictWriter(file,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print("S005_AIDY_RESEARCH_COMPLETED",packet["sha256"],flush=True)
    return packet


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--source-root",required=True,type=Path)
    ap.add_argument("--publisher-root",required=True,type=Path)
    ap.add_argument("--out",required=True,type=Path)
    x=ap.parse_args()
    run(x.source_root,x.publisher_root,x.out)

if __name__=="__main__": main()