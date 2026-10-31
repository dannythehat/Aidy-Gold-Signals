"""Historical Jan-Sep 2026 G001 follow-up from immutable existing CROSSFIRE source.

Reuses GitHub Actions run 38851611865's previously verified original HistData
2026 spot BID/ASK tick-derived hourly records, not fresh R2/archive requests.
The 2026 artifact source had original ticks reconciled to monthly H1 source
receipts in the finished crossfire holdout CI. Recheck those receipts and
CSV arithmetic, derive only observed D1 with >=900 original M1 observations.
2026 is a LATER RETROSPECTIVE period, not magically untouched OOS; it was
already used for unrelated Gold strategy research.
Distinct D1-from-H1 vs 2023-25 D1-from-M1 aggregation disclosed.
No actual PU Prime broker parity, financing or tick-order execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scripts.gold_hunter_external_vol_regime_daily import (
    source_daily, run_year, METHODS, digest,
)

def verify_h1(source:Path):
    csv=source/"verified_2026_bidask_h1.csv"
    ledger=source/"crossfire_2026_full_ledger.json"
    if not csv.is_file() or not ledger.is_file():
        raise ValueError("Missing frozen 2026 original source research artifacts")
    proof=json.loads(ledger.read_text())
    receipts=proof["source_receipts"]
    if (proof["status"]!="PASS_2026_9_MONTH_HISTORICAL_SOURCE_AND_MODEL"
            or proof["period_utc"]!="2026-01-01 to 2026-09-30"
            or len(receipts)!=10
            or proof["broker_specific_vantage_ask_or_swaps_proven"] is not False
            or proof["source"]!="original HistData immutable XAUUSD BID/ASK tick source R2"):
        raise ValueError("Source artifact identity mismatch")
    periods=["202512"]+[f"2026{i:02d}" for i in range(1,10)]
    for receipt,period in zip(receipts,periods):
        if (receipt["source_month_fixed_est"]!=period or
                receipt["raw_source_modified"] is not False or
                len(receipt["input_zip_sha256"])!=64 or
                len(receipt["derived_h1_sha256"])!=64 or
                receipt["source_tick_rows"]<1000):
            raise ValueError("Tampered or missing original 2026 monthly source receipt")
    # The full ledger hash is constructed by the original source-verifying
    # crossfire script before publishing this artifact.
    control={"receipts":receipts,"base":proof["base"],"stress":proof["stress"]}
    check=hashlib.sha256(json.dumps(control,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    if check!=proof["full_evidence_sha256"]:
        raise ValueError("2026 original source verification hash mismatch")
    h=pd.read_csv(csv)
    h["open_time_utc"]=pd.to_datetime(h["open_time_utc"],utc=True,errors="raise")
    numerical=("open","high","low","close","observed_open_ask",
               "observed_open_spread","observed_max_spread","m1_count")
    for key in numerical:
        h[key]=pd.to_numeric(h[key],errors="raise")
    h=h.sort_values("open_time_utc")
    if (len(h)<3000 or h["open_time_utc"].duplicated().any() or
        not (h["open_time_utc"].dt.year==2026).all() or
        set(h["open_time_utc"].dt.month)!={1,2,3,4,5,6,7,8,9} or
        (h["observed_open_ask"]<h["open"]).any() or
        (h["m1_count"]<30).any() or
        (h["high"]<h["low"]).any()):
        raise ValueError("Invalid original monthly-derived 2026 H1 source")
    # Crossfire output contains full H1 source rows. Original source has M1
    # count; prohibit treating partial 30-min H1 as a full observed hour.
    h=h.loc[h["m1_count"]==60].copy()
    h["day"]=h["open_time_utc"].dt.normalize()
    d=h.groupby("day",sort=True).agg(
        first_utc=("open_time_utc","first"),
        bid_o=("open","first"),ask_o=("observed_open_ask","first"),
        high=("high","max"),low=("low","min"),
        close=("close","last"),
        m1_count=("m1_count","sum"))
    d=d.loc[(d.index.weekday<5)&(d["m1_count"]>=900)].copy()
    if len(d)<140 or set(d.index.month)!={1,2,3,4,5,6,7,8,9}:
        raise ValueError("Missing full 2026 original quote months")
    return d, {"historical_run_id":38851611865,
               "source_artifact":"CROSSFIRE-S010-2026-REAL-HOLDOUT-3-VERSIONS",
               "original_tick_source":True,"qualified_2026_daily_days":len(d),
               "source_h1_sha256":hashlib.sha256(csv.read_bytes()).hexdigest(),
               "original_2026_evidence_sha256":check,
               "not_2026_unseen_OOS":True}

def feature_extension(earlier, year2026):
    whole=pd.concat([earlier[["first_utc","bid_o","ask_o","high","low",
                              "close","m1_count"]],year2026]).sort_index()
    if whole.index.has_duplicates:raise ValueError("Cross-year overlap")
    prior=whole["close"].shift(1)
    tr=pd.concat([whole["high"]-whole["low"],
        (whole["high"]-prior).abs(),(whole["low"]-prior).abs()],axis=1).max(axis=1).to_numpy()
    atr=np.full(len(whole),np.nan)
    atr[13]=float(np.mean(tr[:14]))
    for i in range(14,len(whole)):
        atr[i]=(13*atr[i-1]+tr[i])/14
    whole["atr14"]=atr
    whole["sma200"]=whole["close"].rolling(200,min_periods=200).mean()
    whole["momentum"]=(whole["close"]-whole["close"].shift(20))/whole["atr14"]
    whole["setup"]=(whole["momentum"]>.5)&(whole["close"]>whole["sma200"])&(
        whole["atr14"]>whole["atr14"].shift(5)*.95)
    whole["risk_tier"]=np.where(whole["momentum"]>=1.8,.02,
        np.where(whole["momentum"]>=1.2,.015,.01))
    return whole

def research(quotes:Path,source:Path,out:Path):
    original,base_receipts=source_daily(quotes)
    this_year,new_proof=verify_h1(source)
    combined=feature_extension(original,this_year)
    report={"schema":"aidy.g001_goldspot_2026_jan_sep_v1",
        "original_data_2023_25":base_receipts,
        "2026_original_H1_tick_source":new_proof,
        "2026_different_timeframe_derivation_disclosed":True,
        "longer_retrospective_not_untouched_out_of_sample":True,
        "source_rights_not_licensed":True,
        "no_orders":True,"scenarios":{}}
    for cost,slip,fee,fund in (("base",.05,.07,.06),("stress",.25,.14,.09)):
        report["scenarios"][cost]={}
        for mode in METHODS:
            item=run_year(combined,2026,mode,slip,fee,fund)
            folder=out/cost
            folder.mkdir(parents=True,exist_ok=True)
            (folder/f"{mode}.json").write_text(
                json.dumps(item,sort_keys=True,indent=2,allow_nan=False)+"\n")
            report["scenarios"][cost][mode]={
                k:item[k] for k in ("marked_usd","realized_usd","closed",
                                    "entries","max_daily_marked_dd_pct",
                                    "pf","open_censored","sha256")}
    report["sha256"]=digest(report)
    (out/"2026_report.json").write_text(json.dumps(
        report,indent=2,sort_keys=True,allow_nan=False)+"\n")
    print("AIDY_G001_HISTORICAL_JANSEP_2026",json.dumps(
        report["scenarios"]["stress"],sort_keys=True),flush=True)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--quotes",required=True,type=Path)
    p.add_argument("--source-2026",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    a=p.parse_args()
    try:research(a.quotes,a.source_2026,a.out)
    except Exception as e:
        a.out.mkdir(parents=True,exist_ok=True)
        (a.out/"BLOCKED.json").write_text(json.dumps({
            "status":"NO_RESULT","error_type":type(e).__name__,
            "no_fabricated_prices":True},indent=2)+"\n")
        raise
