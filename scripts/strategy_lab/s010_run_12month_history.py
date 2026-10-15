"""S010 real historical twelve-month test on original BigQuery XAUUSD M1 BID.

No data export of secret credentials. Source dataset is retrospective HistData BID;
actual bid/ask tick source of publisher is unavailable. Costs are modelled.
"""
from __future__ import annotations
import csv
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from aidy.strategy_lab_s010_backtest import (
    BASE,
    ORIGINAL_LEVERAGE,
    STARTING_USD,
    STRESS,
    simulate,
)
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/strategy_lab/s010_paid_customer_example"
TABLE = "aidy-signals.aidy_analytics_test.research_candles"
CAP = 1_500_000_000


def retrieve_month(client, first: datetime, end: datetime) -> tuple[list[dict], dict]:
    from google.cloud import bigquery
    # One group per complete 60-minute UTC block; source fixed EST clock is
    # also whole-hour aligned. Exclude and explicitly count incomplete blocks.
    sql = f"""
      SELECT TIMESTAMP_SECONDS(DIV(UNIX_SECONDS(open_time_utc),3600)*3600)
          AS open_time_utc,
        ARRAY_AGG(open ORDER BY open_time_utc ASC LIMIT 1)[OFFSET(0)] AS open,
        MAX(high) AS high, MIN(low) AS low,
        ARRAY_AGG(close ORDER BY open_time_utc DESC LIMIT 1)[OFFSET(0)] AS close,
        COUNT(*) AS m1_count, COUNT(DISTINCT open_time_utc) AS unique_m1,
        COUNTIF(NOT(
          source='histdata' AND symbol='XAUUSD' AND timeframe='M1'
          AND price_basis='bid' AND source_dataset='generic_ascii_m1'
          AND source_timezone='EST_FIXED_UTC_MINUS_05'
          AND derivation_version='aidy_histdata_source_aligned_v1'
          AND provenance_class='retrospective_history'
          AND pit_eligible=FALSE AND derived_from_timeframe IS NULL
          AND input_rows=1
          AND source_open_time=FORMAT_TIMESTAMP('%Y%m%d %H%M%S',
             TIMESTAMP_SUB(open_time_utc, INTERVAL 5 HOUR),'UTC')
          AND LENGTH(source_file_sha256)=64
          AND LENGTH(source_payload_sha256)=64
          AND research_identity IS NOT NULL
        )) AS invalid_original_rows,
        ARRAY_AGG(DISTINCT source_file_sha256 IGNORE NULLS) AS archive_shas
      FROM {chr(96)}{TABLE}{chr(96)}
      WHERE symbol='XAUUSD' AND timeframe='M1'
        AND open_time_utc>=@start AND open_time_utc<@end
      GROUP BY 1 ORDER BY 1
    """
    params = [
        bigquery.ScalarQueryParameter("start", "TIMESTAMP", first),
        bigquery.ScalarQueryParameter("end", "TIMESTAMP", end),
    ]
    dry=client.query(sql,job_config=bigquery.QueryJobConfig(
        query_parameters=params,dry_run=True,use_query_cache=False))
    estimated=int(dry.total_bytes_processed or 0)
    if estimated>CAP:
        raise ValueError("Monthly BigQuery source scan exceeds frozen safety cap")
    job=client.query(sql,job_config=bigquery.QueryJobConfig(
        query_parameters=params,use_query_cache=False,
        maximum_bytes_billed=CAP))
    rows=list(job.result(timeout=240))
    if not rows:
        raise ValueError("Native HistData M1 data absent; no synthetic repair")
    items=[]
    bad=0
    partial=0
    archives=set()
    observed=0
    for obj in rows:
        r=dict(obj)
        observed+=int(r["m1_count"])
        bad+=int(r["invalid_original_rows"])
        archives.update(r["archive_shas"] or [])
        if r["m1_count"]!=60 or r["unique_m1"]!=60:
            partial+=1
            continue
        items.append({
            "open_time_utc":r["open_time_utc"].isoformat(),
            "open":float(r["open"]),"high":float(r["high"]),
            "low":float(r["low"]),"close":float(r["close"]),"m1_count":60,
        })
    if bad:
        raise ValueError(f"{bad} M1 records violate frozen source validation")
    if any(len(a)!=64 or any(c not in "0123456789abcdef" for c in a)
           for a in archives):
        raise ValueError("Invalid source archive fingerprint")
    if len(items)<200:
        raise ValueError("Fewer than 200 fully sourced hourly candles this month")
    sha=hashlib.sha256(json.dumps(items,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    receipt={
        "calendar_month_utc":first.strftime("%Y-%m"),
        "query_job_id":job.job_id,
        "query_estimated_bytes_scanned":estimated,
        "observed_native_m1_rows":observed,
        "complete_h1":len(items),
        "partial_hour_excluded":partial,
        "source_archive_sha256":sorted(archives),
        "monthly_source_sha256":sha,
    }
    return items,receipt


def main()->int:
    from google.cloud import bigquery
    from google.oauth2 import service_account
    OUT.mkdir(parents=True,exist_ok=True)
    blockers={
        "strategy_id":"S010","status":"BLOCKED_SOURCE_OR_EXECUTION",
        "source_url":"https://github.com/AluminumShark/Tick-Backtest",
        "original_external_tick_bid_ask_not_accessible":True,
        "real_paper_live_trades":0,
        "source_stops_protecting_trade":"NONE IN ORIGINAL SOURCE",
        "owner_launch_status":"NO_GO",
    }
    try:
        info=json.loads(os.environ["AIDY_GCP_SERVICE_ACCOUNT_JSON"])
        client=bigquery.Client(
            project=info["project_id"],location="EU",
            credentials=service_account.Credentials.from_service_account_info(info))
        candles=[]
        receipts=[]
        for m in range(1,13):
            start=datetime(2025,m,1,tzinfo=UTC)
            finish=datetime(2026,1,1,tzinfo=UTC) if m==12 else datetime(2025,m+1,1,tzinfo=UTC)
            rows,receipt=retrieve_month(client,start,finish)
            candles.extend(rows)
            receipts.append(receipt)
            print("S010_SOURCE_MONTH",json.dumps({
                k:receipt[k] for k in ("calendar_month_utc","observed_native_m1_rows",
                                        "complete_h1","partial_hour_excluded","query_job_id")
            },sort_keys=True),flush=True)
        if len(candles)<3500 or sum(x["observed_native_m1_rows"] for x in receipts)<210000:
            raise ValueError("Insufficient genuinely sourced months")
        frame=pd.DataFrame(candles)
        times=pd.to_datetime(frame["open_time_utc"],utc=True)
        if times.duplicated().any() or not times.is_monotonic_increasing:
            raise ValueError("Source month seams duplicated or not chronological")
        base=simulate(frame,ORIGINAL_LEVERAGE,BASE)
        stress=simulate(frame,ORIGINAL_LEVERAGE,STRESS)
        low=simulate(frame,1.,BASE)
        scenarios={"published_3p28x_base":base,
                   "published_3p28x_stress":stress,
                   "unlevered_1x_base":low}
        if any(len(s["monthly"])!=12 or s["bars"]!=len(candles)
               or s["closed_trades"]!=len(s["trades"]) for s in scenarios.values()):
            raise ValueError("Missing months or irreconcilable complete trade ledger")
        result={
            "status":"PASS_REAL_12_MONTH_HISTORICAL_RESEARCH",
            "strategy_id":"S010",
            "source":"AluminumShark/Tick-Backtest, main.py and src/strategy.py",
            "reference_account_usd":STARTING_USD,
            "market":"XAUUSD", "period":"2025-01-01 to 2025-12-31 UTC",
            "signal_timeframe":"H1 native M1 derived, real retrospective BID",
            "published_author_parameters_not_optimised_again":True,
            "original_publisher_bid_ask_ticks_available":False,
            "bid_ask_spread_and_slippage_observed":False,
            "costs_illustrative_and_not_verified_broker_quotes":True,
            "exact_original_tick_engine_parity":False,
            "independently_qualified_profitable":False,
            "sealed_oos":False,
            "risk_warning":"3.28x and NO PROTECTIVE STOP; financing, margin calls excluded",
            "trade_execution":"NEXT H1 OPEN AFTER COMPLETED H1 CLOSE SIGNAL",
            "paper_and_live_broker_orders":0,
            "days_38_to_40_original_approved":False,
            "source_receipts":receipts,
            "scenarios":scenarios,
        }
        result["research_sha256"]=hashlib.sha256(json.dumps(
            {"source_receipts":receipts,"scenarios":scenarios},
            sort_keys=True,separators=(",",":")).encode()).hexdigest()
        with (OUT/"source_verified_2025_h1_bid.csv").open("w",newline="",encoding="utf-8") as stream:
            writer=csv.DictWriter(stream,fieldnames=list(candles[0]))
            writer.writeheader()
            writer.writerows(candles)
        (OUT/"full_independent_research.json").write_text(
            json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8")
        (OUT/"source_provenance.json").write_text(
            json.dumps(receipts,sort_keys=True,indent=2)+"\n",encoding="utf-8")
        print("S010_ACTUAL_YEAR_RESEARCH",json.dumps({
            "status":result["status"],
            "months":len(receipts),
            "m1_rows":sum(r["observed_native_m1_rows"] for r in receipts),
            "valid_h1_bars":len(candles),
            "research_sha256":result["research_sha256"],
            "result":{key:base[key] for key in (
                "closed_trades","wins","losses","win_rate_pct",
                "profit_factor","ending_marked_equity_usd",
                "net_marked_pnl_usd","marked_return_pct",
                "max_marked_drawdown_pct","gold_buy_hold_1x_pct",
                "sum_paid_execution_cost_usd","open_position")},
            "monthly":base["monthly"],
            "stress_ending_usd":stress["ending_marked_equity_usd"],
            "unlevered_ending_usd":low["ending_marked_equity_usd"],
        },sort_keys=True),flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001 - mandatory archived blocker, no fake PASS
        blockers["error_type"]=type(exc).__name__
        blockers["error"]=str(exc)[:380]
        (OUT/"blocked_result.json").write_text(
            json.dumps(blockers,sort_keys=True,indent=2)+"\n",encoding="utf-8")
        print("S010_BLOCKED",json.dumps(blockers,sort_keys=True),flush=True)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
