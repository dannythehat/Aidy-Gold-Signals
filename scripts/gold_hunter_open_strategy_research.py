"""Source-attested multi-method Gold Hunter benchmark, no live/paper trading.

YEAR=2025 uses AIDY existing authenticated BigQuery 12-month data gate.
YEAR=2026 uses AIDY original 10 R2 tick ZIPs and verified H1 BID/ASK.
Runs full predeclared candidate matrix twice at equal risk/capital.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import pandas as pd

from gold_hunter.open_strategy_lab import Settings, run_family_matrix

ROOT=Path(__file__).resolve().parents[1]
YEAR=int(os.getenv("GOLD_HUNTER_RESEARCH_YEAR","2025"))
DEST=ROOT / f"artifacts/gold_hunter/open_lab_{YEAR}"


def source() -> tuple[pd.DataFrame,dict]:
    if YEAR==2025:
        folder=ROOT/"artifacts/strategy_lab/s010_paid_customer_example"
        cpath=folder/"source_verified_2025_h1_bid.csv"
        receipt=folder/"full_independent_research.json"
        expected="PASS_REAL_12_MONTH_HISTORICAL_RESEARCH"
        months=[f"2025-{m:02d}" for m in range(1,13)]
        key="source_receipts"
        receipt_month_key="calendar_month_utc"
        minrows=5000
    elif YEAR==2026:
        folder=ROOT/"artifacts/strategy_lab/crossfire_2026_holdout_result"
        cpath=folder/"verified_2026_bidask_h1.csv"
        receipt=folder/"crossfire_2026_full_ledger.json"
        expected="PASS_2026_9_MONTH_HISTORICAL_SOURCE_AND_MODEL"
        months=["202512"]+[f"2026{m:02d}" for m in range(1,10)]
        key="source_receipts"
        receipt_month_key="source_month_fixed_est"
        minrows=3500
    else:
        raise ValueError("Only predeclared 2025 and 2026 sources supported")
    if not cpath.is_file() or not receipt.is_file():
        raise ValueError("Authenticated AIDY original market data missing")
    metadata=json.loads(receipt.read_text(encoding="utf-8"))
    receipts=metadata.get(key)
    if (metadata.get("status")!=expected or not isinstance(receipts,list)
            or [r.get(receipt_month_key) for r in receipts]!=months):
        raise ValueError("Original AIDY source receipts fail strict provenance")
    with cpath.open(encoding="utf-8",newline="") as f:
        data=pd.DataFrame(csv.DictReader(f))
    data["m1_count"]=pd.to_numeric(data["m1_count"],errors="raise").astype(int)
    for col in ("open","high","low","close"):
        data[col]=pd.to_numeric(data[col],errors="raise")
    if YEAR==2026:
        for col in ("observed_open_ask","observed_open_spread","observed_max_spread"):
            data[col]=pd.to_numeric(data[col],errors="raise")
        if (not (data["observed_open_ask"]>=data["open"]).all()
                or not (data["observed_max_spread"]>=data["observed_open_spread"]).all()):
            raise ValueError("Real 2026 hourly original ASK/spread evidence invalid")
    periods=pd.to_datetime(data["open_time_utc"],utc=True)
    if (len(data)<minrows or not periods.is_monotonic_increasing
            or periods.duplicated().any()
            or set(periods.dt.strftime("%Y-%m")) !=
              ({f"2025-{m:02d}" for m in range(1,13)} if YEAR==2025
               else {f"2026-{m:02d}" for m in range(1,10)})):
        raise ValueError("Missing real monthly history, duplicate source bars or invalid chronology")
    trace={"input_csv_sha256":hashlib.sha256(cpath.read_bytes()).hexdigest(),
           "source_receipt_sha256":hashlib.sha256(receipt.read_bytes()).hexdigest(),
           "month_receipts":len(receipts),"source_rows":len(data)}
    return data,trace


def run() -> dict:
    df,trace=source()
    base=Settings(observed_quote_mode=(YEAR==2026))
    scenarios={"base":base,
               "stress":replace(base,spread_floor=.80,slippage_per_side=.25,
                                roundtrip_commission_per_oz=.14)}
    DEST.mkdir(parents=True,exist_ok=True)
    all_results={}
    for name,config in scenarios.items():
        matrix=run_family_matrix(df,config)
        all_results[name]={}
        for system,result in matrix.items():
            if result["closed_trades"]!=len(result["trades"]):
                raise ValueError("Closed-trade ledger mismatch")
            all_results[name][system]={
                k:result[k] for k in ("closed_trades","wins","losses","win_rate_pct",
                    "profit_factor","net_marked_usd","realized_net_usd",
                    "max_marked_drawdown_pct","largest_winning_trade_usd",
                    "net_ex_largest_winner_usd","months_above_10_pct",
                    "monthly","sha256")}
            (DEST/f"{name}_{system}.json").write_text(json.dumps(
                result,sort_keys=True,indent=2,allow_nan=False)+"\n",
                encoding="utf-8")
    report={
        "status":"SOURCE_VERIFIED_RESEARCH_COMPLETED",
        "year":YEAR,"trace":trace,
        "method":"Five fixed public-inspired gold methods on one identical engine",
        "research_not_broker_order":True,
        "no_untouched_holdout_claim":True,
        "source_quote_basis":("original observed open ASK, pessimistic same-hour max-spread"
                              if YEAR==2026 else "original BID with illustrative spread"),
        "result":all_results,
    }
    report["sha256"]=hashlib.sha256(json.dumps(report,sort_keys=True,
                                    separators=(",",":"),allow_nan=False).encode()).hexdigest()
    (DEST/"report.json").write_text(json.dumps(report,indent=2,sort_keys=True,
                                               allow_nan=False)+"\n",encoding="utf-8")
    summary={scenario:{name:{k:rec[k] for k in
        ("closed_trades","net_marked_usd","max_marked_drawdown_pct",
         "months_above_10_pct","largest_winning_trade_usd")}
        for name,rec in models.items()} for scenario,models in all_results.items()}
    print("GOLD_HUNTER_OPEN_LAB_VERIFIED",json.dumps(summary,sort_keys=True),flush=True)
    return report


if __name__=="__main__":
    try:
        run()
    except Exception as exc:
        DEST.mkdir(parents=True,exist_ok=True)
        (DEST/"blocked_result.json").write_text(json.dumps({
            "status":"SOURCE_OR_RESEARCH_BLOCKED","error_type":type(exc).__name__,
            "error":str(exc)[:600],"substitute_prices_used":False,
            "broker_orders":0},indent=2)+"\n",encoding="utf-8")
        raise
