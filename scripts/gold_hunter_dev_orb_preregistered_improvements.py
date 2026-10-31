"""Prespecified Gold NY ORB EMA50 5R improvement FALSIFICATION suite.

Frozen source-inspired independent 3h ORB source interpretation from
scripts.gold_hunter_dev_ny_orb_ema50 (not the original unprovided author
bot). Original published code lacks enough detail for native replication.
All source quotes are original independently verified AIDY XAUUSD spot
BID/ASK M1 -> 60/60 true H1, 2022 true source R2 tick ZIPs, 2023–25
encrypted original source snapshot caches, 2026Jan–Sep true verified original
tick H1 from frozen CROSSFIRE CI receipts. No data October 2026.

IMPROVEMENT CANDIDATES FROZEN BEFORE running this suite (no grid search):
  BASE_2PCT          2% current independent original control, no filter
  RISK_HALF_PCT      0.5% same signals, drawdown management ONLY
  BREAK_BUFFER_025   require close >=0.25 ATR beyond actual range breakout
  RANGE_WIDTH_15    require 3 H1 range width >= 1.5 ATR
  EMA_STRENGTH_10   require signed close-vs-EMA50 separation >= 1.0 ATR
  BUFFER_WIDTH_LOW  predeclared combination of buffer, range and 0.5% risk

All filters computed at completed SIGNAL H1 close, not after entry.
No filter is an original author rule. Six variants × two declared clocks
constitute MULTIPLE historical research trials, not six independent edges.
Test 2022, 2023, 2024, 2025, Jan–Sep2026 and CONTINUOUS Jan2025–Sep2026.
All are RESEARCH retro, not pristine OOS, no live orders or 2026 Oct prices.

Profit and drawdown are after estimated original BID/ASK + $0.25/oz each
side slippage + $0.14 roundtrip commission/oz + 9% yearly pro-rata
funding; **none is historical PU Prime certified**. H1 stop-first gap
model approximate because tick intra-H1 sequencing is not captured.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import pandas as pd

from scripts.gold_hunter_dev_ny_orb_2022 import load_months
from scripts.gold_hunter_dev_ny_orb_2026 import read_original_2026
from scripts.gold_hunter_2023_2024_causal_research import source_year
from scripts.gold_hunter_dev_ny_orb_ema50 import (
   MODES,source_inspired_signals,account_replay,checksum,
   literal_same_bar_impossible, SOURCE_URL
)

VARIANTS=(
  "BASE_2PCT","RISK_HALF_PCT","BREAK_BUFFER_025",
  "RANGE_WIDTH_15","EMA_STRENGTH_10","BUFFER_WIDTH_LOW",
)
YEAR_LABELS=("2022","2023","2024","2025","2026_jan_sep",
             "2025_to_2026_sep_continuous")
STRESS={"slip":.25,"roundtrip_fee_per_oz":.14,"annual_carry":.09}


def candidate_filter(signals:list[dict],variant:str):
    if variant not in VARIANTS:
        raise ValueError("Unknown preregistered Gold ORB improvement")
    if variant in ("BASE_2PCT","RISK_HALF_PCT"):
        return signals
    survivors=[]
    for s in signals:
        atr=float(s["atr14_bid"])
        if atr<=0:raise ValueError("Completed source indicator invalid")
        side=int(s["direction"])
        entry_boundary=(float(s["range_high_bid"]) if side==1
                        else float(s["range_low_bid"]))
        breakout_R=side*(float(s["signal_closed_bid"])-entry_boundary)/atr
        width_R=(float(s["range_high_bid"])-float(s["range_low_bid"]))/atr
        trend_R=side*(float(s["signal_closed_bid"])-float(s["ema50_bid"]))/atr
        if variant in ("BREAK_BUFFER_025","BUFFER_WIDTH_LOW") and breakout_R<.25:
            continue
        if variant in ("RANGE_WIDTH_15","BUFFER_WIDTH_LOW") and width_R<1.5:
            continue
        if variant=="EMA_STRENGTH_10" and trend_R<1.0:
            continue
        survivors.append(s)
    return survivors


def test_suite(data:pd.DataFrame,period:str,out:Path):
    if period not in YEAR_LABELS:raise ValueError("Unknown declared period")
    if len(data)<3000 or (data["m1_count"]!=60).any():
        raise ValueError("Market source incomplete")
    literal=literal_same_bar_impossible(data)
    results={}
    for clock in MODES:
        enriched,signals,coverage=source_inspired_signals(data,clock)
        variants={}
        for candidate in VARIANTS:
            admitted=candidate_filter(signals,candidate)
            risk=.005 if candidate in ("RISK_HALF_PCT","BUFFER_WIDTH_LOW") else .02
            result=account_replay(enriched,admitted,mode=clock,
                risk_fraction=risk,**STRESS)
            location=out/period/clock
            location.mkdir(parents=True,exist_ok=True)
            (location/f"{candidate}.json").write_text(
                json.dumps({"source_signal_count":len(signals),
                   "post_filter_signals":len(admitted),"variant":candidate,
                   "outcome":result},indent=2,sort_keys=True,allow_nan=False)+"\n")
            variants[candidate]={
              k:v for k,v in result.items() if k!="ledger"}
            variants[candidate]["unfiltered_signals"]=len(signals)
            variants[candidate]["admitted_signals"]=len(admitted)
        results[clock]={"original_signal_coverage":coverage,"variants":variants}
    return {"period":period,"literal_author_impossibility":literal,
            "clocks":results}


def research(source_2022:Path,source_old:Path,source_2026:Path,out:Path):
    datasets={}
    yy22,old22=load_months(source_2022)
    datasets["2022"]=yy22
    manifests={"2022":old22}
    for yr in (2023,2024,2025):
        df,source=source_year(source_old,yr)
        datasets[str(yr)]=df
        manifests[str(yr)]=source
    new,year26=read_original_2026(source_2026)
    datasets["2026_jan_sep"]=new
    manifests["2026_jan_sep"]=year26
    together=pd.concat([datasets["2025"],new],ignore_index=True).sort_values(
        "open_time_utc").reset_index(drop=True)
    if together["open_time_utc"].duplicated().any():
        raise ValueError("Original 2025-26 overlapping H1 quote timestamps")
    datasets["2025_to_2026_sep_continuous"]=together
    manifests["2025_to_2026_sep_continuous"]={
        "uses_original_years":["2025","2026_jan_sep"],
        "underlying_year_SHA":[manifests["2025"]["hourly_data_sha256"],
                               manifests["2026_jan_sep"]["source_h1_sha256"]]}
    report={"schema":"aidy.dev_ny_orb_hypothesis_controls_2022_2026.v1",
      "original_source_article":SOURCE_URL,
      "source_rule_unavailable_native_parity":True,
      "all_periods_retro_not_pristine_OOS":True,
      "methods_preregistered":list(VARIANTS),
      "session_modes":list(MODES),"multiple_trials_12_filter_clock_variants":True,
      "not_broker_live":True,"no_2026_oct_original_histdata_available":True,
      "stress_assumptions_not_actual_PU_Prime":STRESS,
      "data_source_manifests":manifests,"periods":{}}
    for period in YEAR_LABELS:
        x=test_suite(datasets[period],period,out)
        report["periods"][period]=x
        print("AIDY_NY_ORB_PREDECLARED_IMPROVEMENTS",json.dumps({
          "period":period,"results":{
             clock:{v:{"P_L":stats["net_marked_usd"],
                       "H1_DD":stats["max_h1_marked_drawdown_pct"],
                       "fills":stats["closed"]}
               for v,stats in block["variants"].items()}
             for clock,block in x["clocks"].items()}},
             sort_keys=True),flush=True)
    report["sha256"]=checksum(report)
    out.mkdir(parents=True,exist_ok=True)
    (out/"summary.json").write_text(json.dumps(report,indent=2,
      sort_keys=True,allow_nan=False)+"\n")
    return report


if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("--source-2022",type=Path,required=True)
    a.add_argument("--source-old",type=Path,required=True)
    a.add_argument("--source-2026",type=Path,required=True)
    a.add_argument("--out",type=Path,required=True)
    p=a.parse_args()
    try:research(p.source_2022,p.source_old,p.source_2026,p.out)
    except Exception as e:
        p.out.mkdir(parents=True,exist_ok=True)
        (p.out/"BLOCKED.json").write_text(json.dumps({
         "not_tested":True,"failure_type":type(e).__name__,
         "no_fake_prices":True},indent=2)+"\n")
        raise
