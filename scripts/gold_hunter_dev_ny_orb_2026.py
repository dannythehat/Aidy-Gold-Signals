"""2026 continuation: original previously authenticated Gold tick-derived H1 spot.

Uses CROSSFIRE immutable source run 38851611865 artifact original 2026
historical Jan-Sep H1 and verifies receipt/source ledger sha256 with existing
G001 verify_h1. No new market data or vendor fees. The author's described
3h NY ORB same-bar claim impossible; repaired fixed UTC and local NY clocks
only. No Dec2025 source warmup in this re-use: first 50 complete Jan H1
observations are warmup, excluded from signals. Retrospective, NOT OOS.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import pandas as pd

from scripts.gold_hunter_g001_2026_original_h1 import verify_h1
from scripts.gold_hunter_dev_ny_orb_ema50 import (
    MODES,literal_same_bar_impossible,source_inspired_signals,
    account_replay,checksum,SOURCE_URL
)

def read_original_2026(root:Path):
    _,proof=verify_h1(root)
    csv=root/"verified_2026_bidask_h1.csv"
    f=pd.read_csv(csv)
    f["open_time_utc"]=pd.to_datetime(f["open_time_utc"],utc=True,errors="raise")
    for key in ("open","high","low","close","observed_open_ask",
                "observed_max_spread","m1_count"):
        f[key]=pd.to_numeric(f[key],errors="raise")
    f=f.loc[(f["m1_count"]==60)
            & (f["open_time_utc"]>=pd.Timestamp("2026-01-01",tz="UTC"))
            & (f["open_time_utc"]<pd.Timestamp("2026-10-01",tz="UTC"))].copy()
    f=f.sort_values("open_time_utc").reset_index(drop=True)
    if (len(f)<3000 or f["open_time_utc"].duplicated().any()
         or set(f["open_time_utc"].dt.month)!=set(range(1,10))
         or (f["observed_open_ask"]<f["open"]).any()):
        raise ValueError("Original source 2026 time, quote or coverage invalid")
    return f,proof


def research(root:Path,out:Path):
    f,proof=read_original_2026(root)
    literal=literal_same_bar_impossible(f)
    report={"schema":"aidy.dev_ny_orb_2026_original_h1.v1",
      "original_article":SOURCE_URL,"year":"2026-Jan-Sep",
      "source_verified_2026":proof,
      "hours_original_60_60_m1":len(f),
      "article_rules_originally_contradictory":True,
      "2025_december_warmup_not_in_source_csv":True,
      "original_author_code_not_published":True,
      "not_untouched_out_of_sample":True,
      "not_original_gc_futures":True,
      "paper_live_orders":0,"literal":literal,"repairs":{}}
    for mode in MODES:
        df,signals,coverage=source_inspired_signals(f,mode)
        folder=out/mode
        folder.mkdir(parents=True,exist_ok=True)
        (folder/"signals.json").write_text(json.dumps(
            signals,indent=2,sort_keys=True,allow_nan=False)+"\n")
        cases={}
        for label,slip,fee,finance in (("base",.05,.07,.06),
                                        ("stress",.25,.14,.09)):
            r=account_replay(df,signals,slip=slip,
                roundtrip_fee_per_oz=fee,annual_carry=finance,mode=mode)
            (folder/f"{label}_ledger.json").write_text(json.dumps(
                r,indent=2,sort_keys=True,allow_nan=False)+"\n")
            cases[label]={k:v for k,v in r.items() if k!="ledger"}
        report["repairs"][mode]={"coverage":coverage,"costs":cases}
    report["sha256"]=checksum(report)
    out.mkdir(parents=True,exist_ok=True)
    (out/"report.json").write_text(json.dumps(
        report,sort_keys=True,indent=2,allow_nan=False)+"\n")
    print("AIDY_DEV_ORB_2026",json.dumps({
        "literal":literal,
        "stress":{mode:rep["costs"]["stress"] for mode,rep in report["repairs"].items()}
    },sort_keys=True),flush=True)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    try:research(a.source,a.out)
    except Exception as e:
        a.out.mkdir(parents=True,exist_ok=True)
        (a.out/"BLOCKED.json").write_text(json.dumps({
            "not_tested":True,"error_type":type(e).__name__,
            "no_fake_market_data":True},indent=2)+"\n")
        raise
