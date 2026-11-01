"""Independent, originally sourced 2022 Gold ORB EMA50 5R research.

READ ONLY existing exact 202201..202212 HistData source tick ZIPs from
Cloudflare R2, preserving original raw quote file SHA and separately audited
derived 60/60 M1-complete BID/ASK H1. No original author bot code published.

The 202201 source ZIP is in fixed GMT-5, so the earliest Jan 1 UTC hours
may technically be in 202112. No fabricated start-year EMA warmup: the
first 50 real complete H1 bars in this 2022 study build it causally.
The 2022 retrospective is not pristine untouched OOS because historical
market facts and the 2023–26 findings were already discussed.

Exact pre-registered independent clocks and risk/exit rules reused UNCHANGED
from scripts.gold_hunter_dev_ny_orb_ema50.py. Not PU Prime historical fills.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path

import pandas as pd

from scripts.gold_hunter_dev_ny_orb_ema50 import (
    SOURCE_URL, MODES, checksum,literal_same_bar_impossible,
    source_inspired_signals, account_replay,
)

MONTHS=tuple(f"2022{i:02d}" for i in range(1,13))
START=pd.Timestamp("2022-01-01",tz="UTC")
END=pd.Timestamp("2023-01-01",tz="UTC")


def load_months(root:Path):
    source=[]
    receipts=[]
    for month in MONTHS:
        folder=root/f"ny-orb-source-{month}"
        p=folder/"receipt.json"
        csvpath=folder/"hourly.csv"
        if not p.is_file() or not csvpath.is_file():
            raise ValueError(f"Original 2022 market month missing: {month}")
        receipt=json.loads(p.read_text(encoding="utf-8"))
        if (receipt["source_month_fixed_est"]!=month
                or len(receipt["input_zip_sha256"])!=64
                or receipt["raw_source_modified"] is not False
                or receipt["broker_ask_executable"] is not False
                or receipt["complete_utc_h1"]<200
                or "m1_count" in receipt):
            raise ValueError("Invalid 2022 source month provenance")
        with csvpath.open(newline="",encoding="utf-8") as h:
            rows=list(csv.DictReader(h))
        for row in rows:
            row["m1_count"]=int(row["m1_count"])
            for k in ("open","high","low","close","observed_open_ask",
                      "observed_open_spread","observed_max_spread"):
                row[k]=float(row[k])
        digest=hashlib.sha256(json.dumps(
            rows,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        if digest!=receipt["derived_h1_sha256"]:
            raise ValueError(f"2022 H1 source verified hash mismatch: {month}")
        receipts.append(receipt)
        source.extend(rows)
    x=pd.DataFrame(source)
    x["open_time_utc"]=pd.to_datetime(x["open_time_utc"],utc=True,errors="raise")
    x=x.loc[(x.open_time_utc>=START)&(x.open_time_utc<END)].copy()
    x=x.sort_values("open_time_utc").reset_index(drop=True)
    if (x.open_time_utc.duplicated().any() or not x.open_time_utc.is_monotonic_increasing
            or x.empty or len(x)<4000
            or set(x.open_time_utc.dt.month)!=set(range(1,13))
            or (x.m1_count!=60).any()
            or (x.observed_open_ask<x.open).any()):
        raise ValueError("Insufficient or invalid authentic full year 2022 observed H1")
    return x,{"periods":list(MONTHS),"receipts":receipts,
        "complete_h1_count":len(x),
        "sha256_H1_sorted_original":hashlib.sha256(
            x.to_csv(index=False).encode()).hexdigest(),
        "dec2021_utc_warmup_missing":True,
        "original_spot_bidask_not_broker_parity":True}


def research(root:Path,out:Path):
    f,proof=load_months(root)
    literal=literal_same_bar_impossible(f)
    results={}
    out.mkdir(parents=True,exist_ok=True)
    for mode in MODES:
        enriched,sig,coverage=source_inspired_signals(f,mode)
        folder=out/mode
        folder.mkdir(parents=True,exist_ok=True)
        (folder/"signals.json").write_text(json.dumps(sig,indent=2,sort_keys=True)+"\n")
        cases={}
        for label,slip,fee,carry in (("base",.05,.07,.06),
                                      ("stress",.25,.14,.09)):
            data=account_replay(enriched,sig,slip=slip,
                    roundtrip_fee_per_oz=fee,annual_carry=carry,mode=mode)
            (folder/f"{label}_ledger.json").write_text(json.dumps(
                data,sort_keys=True,indent=2,allow_nan=False)+"\n")
            cases[label]={k:v for k,v in data.items() if k!="ledger"}
        results[mode]={"coverage":coverage,"cases":cases}
    report={"schema":"aidy.dev_ny_orb_2022_orig_verified_h1.v1",
        "year":"2022","historical_data":proof,
        "article_original_url":SOURCE_URL,
        "article_literal_rule":literal,
        "unpublished_author_code_exact_parity":False,
        "earliest_2022_EMA_requires_first_50_H1":True,
        "not_sealed_out_of_sample":True,"no_trading_orders":True,
        "results":results}
    report["sha256"]=checksum(report)
    (out/"report.json").write_text(json.dumps(
        report,indent=2,sort_keys=True,allow_nan=False)+"\n")
    print("AIDY_DEV_NY_ORB_2022",json.dumps({
        "source_complete_H1":len(f),
        "literal":literal,
        "stress":{mode:{k:v for k,v in item["cases"]["stress"].items()
            if k in ("signal_count","entries","closed","net_marked_usd",
                     "max_h1_marked_drawdown_pct","profit_factor","open_censored")}
            for mode,item in results.items()}},sort_keys=True),flush=True)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--sources",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    a=p.parse_args()
    try:research(a.sources,a.out)
    except Exception as e:
        a.out.mkdir(parents=True,exist_ok=True)
        (a.out/"BLOCKED.json").write_text(json.dumps({
          "not_tested":True,"error_type":type(e).__name__,
          "no_market_price_synthesis":True},indent=2)+"\n")
        raise
