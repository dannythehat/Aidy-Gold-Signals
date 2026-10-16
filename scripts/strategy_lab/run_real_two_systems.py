"""Run two mechanical AIDY systems on 2025 verified real XAUUSD H1 BID.

Requires the successful SAME-run S010 full-2025 BigQuery source experiment.
No source acquisition is silently mocked, no MT5 orders are submitted.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pandas as pd

from aidy.strategy_lab_system_processor import DONCHIAN, S010, process_systems

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "artifacts/strategy_lab/s010_paid_customer_example"
OUT = ROOT / "artifacts/strategy_lab/two_system_processing"


def run() -> dict:
    report_file = SOURCE / "full_independent_research.json"
    candles_file = SOURCE / "source_verified_2025_h1_bid.csv"
    if not report_file.is_file() or not candles_file.is_file():
        raise ValueError("Real upstream BigQuery source run is REQUIRED")
    upstream = json.loads(report_file.read_text(encoding="utf-8"))
    if (upstream.get("status") != "PASS_REAL_12_MONTH_HISTORICAL_RESEARCH"
            or len(upstream.get("source_receipts", ())) != 12
            or upstream.get("paper_and_live_broker_orders") != 0):
        raise ValueError("Invalid upstream historical source and execution receipts")
    months = [r["calendar_month_utc"] for r in upstream["source_receipts"]]
    if months != [f"2025-{month:02d}" for month in range(1, 13)]:
        raise ValueError("Missing or reordered real 2025 archive months")
    for receipt in upstream["source_receipts"]:
        if (not receipt.get("query_job_id")
                or receipt.get("invalid_original_rows", 0) != 0
                or receipt.get("complete_h1", 0) < 200
                or len(receipt.get("monthly_source_sha256", "")) != 64):
            raise ValueError("Missing original warehouse provenance")
    raw = candles_file.read_bytes()
    identity = hashlib.sha256(raw).hexdigest()
    with candles_file.open(newline="", encoding="utf-8") as stream:
        candles = list(csv.DictReader(stream))
    if len(candles) != sum(r["complete_h1"] for r in upstream["source_receipts"]):
        raise ValueError("Actual source hourly candle count changed")
    if len(candles) < 3500:
        raise ValueError("Actual 2025 H1 coverage insufficient")
    # The earlier original runner wrote floats; reconstitute its exact schema.
    for record in candles:
        record["m1_count"] = int(record["m1_count"])
        for field in ("open", "high", "low", "close"):
            record[field] = float(record[field])
    frame = pd.DataFrame(candles)
    results = process_systems(frame, source_identity=identity)
    original = upstream["scenarios"]
    if (results["models"][S010]["base"] != original["published_3p28x_base"]
            or results["models"][S010]["stress"] != original["published_3p28x_stress"]):
        raise ValueError("Original published S010 account, trades or costs drifted")
    if results["models"][DONCHIAN]["source_category"] != "LABORATORY_DEFINED_NOT_CATALOGUE":
        raise ValueError("Unverified catalogue system identity substituted")
    OUT.mkdir(parents=True, exist_ok=True)
    packet = {
        "status": "PASS_REAL_MARKET_SOURCE_TWO_MECHANICAL_RESEARCH_RUNS",
        "source_receipt_count": len(months),
        "actual_bigquery_job_ids": [r["query_job_id"] for r in upstream["source_receipts"]],
        "actual_xauusd_h1_bid_csv_sha256": identity,
        "upstream_s010_research_sha256": upstream["research_sha256"],
        "legacy_original_model_parity": True,
        "system_processor": results,
        "catalogue_systems_claimed_tested": [S010],
        "additional_lab_defined_system": DONCHIAN,
        "original_83_system_profitability_batch_complete": False,
        "real_customer_or_broker_orders": 0,
    }
    packet["result_sha256"] = hashlib.sha256(json.dumps(
        packet, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()
    (OUT / "two_system_historical_research.json").write_text(
        json.dumps(packet, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    for system, result in results["models"].items():
        for scenario in ("base", "stress"):
            trades = result[scenario]["trades"]
            dest = OUT / f"{system}_{scenario}_trades.csv"
            with dest.open("w", encoding="utf-8", newline="") as stream:
                if trades:
                    writer = csv.DictWriter(stream, fieldnames=list(trades[0]))
                    writer.writeheader()
                    writer.writerows(trades)
                else:
                    stream.write("no_closed_trades\n")
    print("AIDY_MULTI_SYSTEM_REAL_HISTORICAL_PASS", json.dumps({
        "systems": len(results["models"]), "h1_bars": len(candles),
        "market_source_sha": identity,
        "s010_original_parity": True,
        "modelled_outcomes": {
            k: {
                "trades": v["base"]["closed_trades"],
                "modelled_net_usd": v["base"]["net_marked_pnl_usd"],
                "marked_drawdown_percent": v["base"]["max_marked_drawdown_pct"],
            } for k, v in results["models"].items()
        },
    }, sort_keys=True), flush=True)
    return packet


if __name__ == "__main__":
    run()
