"""Unchanged S010 2021 independent down-year historical research collector.

Receives exactly 13 separately sourced raw archive month receipts (Dec2020
covers the first UTC hours of Jan2021), each immutable original ZIP SHA
and independently normalised BID + observed ASK opening quote. No 2025
parameter adjustments. The published baseline 2025 remains unchanged.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from aidy.strategy_lab_s010_backtest import (
    BASE, ORIGINAL_LEVERAGE, STARTING_USD, STRESS, simulate,
)

EXPECTED = tuple([202012] + [202100 + n for n in range(1, 13)])
START = datetime(2021,1,1,tzinfo=UTC)
END = datetime(2022,1,1,tzinfo=UTC)
METHOD = "S010_2021_ORIGINAL_MA12_34_RSI14_UNCHANGED_TICK_BID_v1"


def collect(folder: Path, output: Path) -> dict:
    output.mkdir(parents=True,exist_ok=True)
    matched = sorted(folder.glob("crossfire-2021-*/receipt.json"))
    if len(matched) != 13:
        raise ValueError(f"Expected 13 exact original source month receipts; got {len(matched)}")
    receipts = []
    rows = []
    for n, receipt_file in enumerate(matched):
        receipt = json.loads(receipt_file.read_text())
        period = str(EXPECTED[n])
        if (receipt_file.parent.name != "crossfire-2021-"+period
                or receipt["source_month_fixed_est"] != period
                or receipt["raw_source_modified"] is not False
                or receipt["broker_ask_executable"] is not False
                or receipt["normalisation"] != "aidy.crossfire.2021.tick_utc_h1_bidask_v1"
                or len(receipt["input_zip_sha256"]) != 64
                or receipt["source_tick_rows"] < 1000):
            raise ValueError("Untrusted, missing or mislabeled source archive receipt")
        with (receipt_file.parent/"hourly.csv").open(newline="",encoding="utf-8") as stream:
            candles=list(csv.DictReader(stream))
        for row in candles:
            row["m1_count"] = int(row["m1_count"])
            for key in ("open","high","low","close","observed_open_ask",
                        "observed_open_spread","observed_max_spread"):
                row[key]=float(row[key])
            if not (row["observed_open_ask"] >= row["open"]
                    and row["observed_open_spread"] >= 0
                    and row["observed_max_spread"] >= 0):
                raise ValueError("Source bid/ask geometry broken")
        if hashlib.sha256(json.dumps(candles,sort_keys=True,separators=(",",":")).encode()).hexdigest() != receipt["derived_h1_sha256"]:
            raise ValueError("Original month derived-hour snapshot SHA did not match")
        receipts.append(receipt)
        rows.extend(candles)
    filtered = [x for x in rows if START <= datetime.fromisoformat(x["open_time_utc"]) < END]
    if len(filtered) < 3500:
        raise ValueError("Too few complete 2021 real source candles (coverage blocker)")
    x=pd.DataFrame(filtered).sort_values("open_time_utc").reset_index(drop=True)
    dts=pd.to_datetime(x["open_time_utc"],utc=True)
    if dts.duplicated().any() or not dts.is_monotonic_increasing:
        raise ValueError("Overlapping source-month seams or duplicate UTC hours")
    if dts.dt.year.nunique()!=1 or dts.dt.year.iloc[0]!=2021:
        raise ValueError("Wrong evaluation year")
    if sum(1 for m in range(1,13) if int((dts.dt.month==m).sum()) >= 150) != 12:
        raise ValueError("Not all twelve 2021 calendar months have real historical coverage")
    for month, sub in x.groupby(dts.dt.strftime("%Y-%m"),sort=True):
        if len(sub)<150:
            raise ValueError("Insufficient true source data in "+month)
    # Strict original source system & cost assumptions, NOT amended.
    original = simulate(x,ORIGINAL_LEVERAGE,BASE)
    stress = simulate(x,ORIGINAL_LEVERAGE,STRESS)
    unlevered = simulate(x,1.0,BASE)
    scenarios={"published_3p28x_base":original,
               "published_3p28x_stress":stress,
               "unlevered_1x_base":unlevered}
    if any(v["bars"]!=len(x) or len(v["monthly"])!=12 for v in scenarios.values()):
        raise ValueError("Irreconcilable year, trade ledger or monthly accounting")
    spreads=x["observed_open_spread"]
    payload={
        "status":"PASS_REAL_2021_UNCHANGED_ORIGINAL_BID_HISTORICAL_RESEARCH",
        "strategy_id":"S010",
        "working_brand":"CROSSFIRE",
        "market_regime":"2021 GOLD NEGATIVE / BROAD TRADING RANGE",
        "source":"12+1 original HistData Generic ASCII BID/ASK tick ZIPs, R2 immutable",
        "period":"2021-01-01 inclusive to 2022-01-01 exclusive UTC",
        "method":METHOD,
        "original_rule_changes":0,
        "original_reference":"AluminumShark/Tick-Backtest MA12/34 RSI14 long only 3.28x",
        "starting_usd":STARTING_USD,
        "real_original_tick_rows":sum(v["source_tick_rows"] for v in receipts),
        "real_complete_h1":len(x),
        "real_source_receipts":receipts,
        "histdata_observed_ask_at_h1_open":True,
        "histdata_ask_used_as_executable_broker_ask":False,
        "execution_model":"IDENTICAL SYNTHETIC COST ASSUMPTIONS AS 2025 BASE",
        "historical_broker_swaps_included":False,
        "margin_call_and_broker_stopout_included":False,
        "source_h1_open_spread_summary":{
            "observations":len(spreads),
            "min_usd_per_oz":round(float(spreads.min()),4),
            "median_usd_per_oz":round(float(spreads.median()),4),
            "p95_usd_per_oz":round(float(spreads.quantile(.95)),4),
            "max_usd_per_oz":round(float(spreads.max()),4),
            "original_2025_base_assumed_spread_usd_per_oz":BASE.spread_usd_per_oz,
        },
        "broker_orders":0,"paper_account_started":False,
        "is_broker_net_profit_verified":False,
        "scenarios":scenarios,
    }
    payload["evidence_sha256"]=hashlib.sha256(json.dumps(
        {"period":payload["period"],"receipts":receipts,"scenarios":scenarios},
        sort_keys=True,separators=(",",":")).encode()).hexdigest()
    (output/"crossfire_2021_original_results.json").write_text(json.dumps(
        payload,indent=2,sort_keys=True)+"\n")
    with (output/"crossfire_2021_true_bidask_h1.csv").open("w",newline="",encoding="utf-8") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(filtered[0]))
        writer.writeheader()
        writer.writerows(filtered)
    # Store only the 12 real genuine year rows, not imaginary 'live' paper results.
    with (output/"crossfire_2021_original_monthly.csv").open("w",newline="",encoding="utf-8") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(original["monthly"][0]))
        writer.writeheader()
        writer.writerows(original["monthly"])
    summary={
        "status":payload["status"],"year":2021,
        "source_archives":len(receipts),
        "source_ticks":payload["real_original_tick_rows"],
        "complete_h1":len(x),"original_changes":0,
        "profitable_model":original["net_marked_pnl_usd"]>0,
        "return_pct":original["marked_return_pct"],
        "net_usd":original["net_marked_pnl_usd"],
        "max_drawdown_pct":original["max_marked_drawdown_pct"],
        "closed_trades":original["closed_trades"],
        "wins":original["wins"],"losses":original["losses"],
        "profit_factor":original["profit_factor"],
        "stressed_ending_usd":stress["ending_marked_equity_usd"],
        "actual_source_spread":payload["source_h1_open_spread_summary"],
        "evidence_sha256":payload["evidence_sha256"],
        "paper_approved":False,
    }
    (output/"crossfire_2021_readable_summary.json").write_text(json.dumps(
        summary,indent=2,sort_keys=True)+"\n")
    return summary


def main()->int:
    folder=Path(sys.argv[1]) if len(sys.argv)>1 else Path("artifacts/strategy_lab/crossfire_2021_source")
    out=Path("artifacts/strategy_lab/crossfire_2021_full_result")
    out.mkdir(parents=True,exist_ok=True)
    try:
        summary=collect(folder,out)
        print("CROSSFIRE_2021_GENUINE_RESULT",json.dumps(summary,sort_keys=True),flush=True)
        return 0
    except Exception as exc:
        blocked={
            "status":"BLOCKED_REAL_2021_SOURCE_OR_RULES",
            "error_type":type(exc).__name__,"error":str(exc)[:400],
            "source_months_required":13,"paper_approved":False,
        }
        (out/"blocked_research.json").write_text(json.dumps(blocked,indent=2)+"\n")
        print("CROSSFIRE_2021_BLOCKED",json.dumps(blocked,sort_keys=True),flush=True)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
