"""First owner-requested independent AIDY Gold Edge experiment: S046 only.

Pre-registered two historical UTC weekdays, no parameter search, no broker
connection, no trade execution or source-code parity claims. These dates
predate the Oct-2026 indicator publication, so no OOS claim is possible.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from aidy.strategy_lab_history_reader import Window, read_bigquery_window
from aidy.strategy_lab_s046_signal_proxy import (
    RULE_VERSION,
    scan_completed_session_sweeps,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/strategy_lab/s046_signal_research"
DAYS = ("2025-01-07", "2025-01-08")  # frozen BEFORE observing BigQuery signal outcomes


def main() -> int:
    from google.cloud import bigquery
    from google.oauth2 import service_account

    OUT.mkdir(parents=True, exist_ok=True)
    observations: list[dict] = []
    source_receipts: list[dict] = []
    result: dict = {
        "schema": "aidy.gold_edge.s046.signal_research.v1",
        "status": "BLOCKED_NOT_ATTEMPTED",
        "strategy_id": "S046",
        "strategy_name": "Session Sweep Boxes: session-level reclaim",
        "selection": "SystemRandom draw #15 from 25 SOURCE REVIEWED rows",
        "original_google_drive_sheet":
            "https://docs.google.com/spreadsheets/d/14EbIPxW5ZeueRX0vz0i6qG7BmlosL04x8-xXl3Hh6N4/edit",
        "public_indicator": "https://www.mql5.com/en/code/77953",
        "method": RULE_VERSION,
        "implementation_type": "PUBLIC_DESCRIPTION_DERIVED_INDEPENDENT_SIGNAL_PROXY",
        "mql5_indicator_code_audited": False,
        "mql5_buffer_parity_proven": False,
        "pre_registered_days_utc": list(DAYS),
        "historical_source": "histdata fixed EST source -> verified UTC M1 BID -> closed M5",
        "qualification_for_strategy_backtest": "BLOCKED_NO_ORIGINAL_EXIT_STOP_OR_POSITION_SIZING",
        "trading_system_pnl_usd": None,
        "wins": None, "losses": None, "win_rate": None,
        "strategy_proven_profitable": False,
        "broker_orders_placed": 0,
        "original_83_strategies_verified_profitable": 0,
        "paper_trades_created": 0,
        "owner_go_no_go": "NO_GO",
    }
    try:
        info = json.loads(os.environ["AIDY_GCP_SERVICE_ACCOUNT_JSON"])
        client = bigquery.Client(
            project=info["project_id"], location="EU",
            credentials=service_account.Credentials.from_service_account_info(info),
        )
        total_candles = 0
        for date in DAYS:
            start = datetime.fromisoformat(f"{date}T00:00:00+00:00")
            end = start + timedelta(hours=21)
            window = Window(start, end, end, 5)
            history, job1 = read_bigquery_window(client, window)
            replay, job2 = read_bigquery_window(client, Window(
                start, end, end, 5, expected_digest=history.input_digest,
            ))
            if history != replay or job1 == job2:
                raise ValueError("Independently sourced identical historical data required")
            signals = scan_completed_session_sweeps(history.bars)
            same_again = scan_completed_session_sweeps(replay.bars)
            if signals != same_again:
                raise ValueError("Signal detector replay disagreement")
            observations.extend([asdict(item) for item in signals])
            total_candles += len(history.bars)
            source_receipts.append({
                "date_utc": date,
                "first_real_query_job": job1,
                "second_real_query_job": job2,
                "source_m1_digest": history.input_digest,
                "source_archive_hashes": list(history.source_archive_hashes),
                "native_m1_bars": history.native_m1_rows,
                "closed_m5_bars": len(history.bars),
                "observed_closed_bar_signals": len(signals),
                "last_observation_utc": end.isoformat(),
                "new_york_post_close_observation_available": False,
            })
        by_side = {s: sum(p["side"] == s for p in observations)
                   for s in ("BULLISH", "BEARISH")}
        by_session = {s: sum(p["session"] == s for p in observations)
                      for s in ("ASIA", "LONDON", "NEW_YORK")}
        checksum_payload = {
            "strategy": "S046", "version": RULE_VERSION,
            "dates": DAYS, "sources": [
                (x["date_utc"], x["source_m1_digest"])
                for x in source_receipts
            ],
            "signal_events": observations,
        }
        result.update({
            "status": "PASS_REAL_HISTORICAL_SIGNAL_PROXY_ONLY",
            "real_closed_m5_bars_observed": total_candles,
            "real_historical_bid_m1_bars": sum(x["native_m1_bars"] for x in source_receipts),
            "observed_signals": len(observations),
            "by_side": by_side,
            "by_session": by_session,
            "real_source_receipts": source_receipts,
            "research_sha256": hashlib.sha256(json.dumps(
                checksum_payload, sort_keys=True, separators=(",", ":"),
            ).encode()).hexdigest(),
            "windows_with_no_post_ny_session_candles": len(DAYS),
            "research_note": (
                "The public description was tested as a signal detector, NOT the "
                "original MQL5 code or a profitable tradeable EA. One sweep per "
                "session level; cancelled on a close beyond the range. No source "
                "parity, no exits, no positions, no net P&L or verified rating."
            ),
        })
        with (OUT/"closed_bar_signal_events.csv").open(
            "w", newline="", encoding="utf-8",
        ) as stream:
            writer = csv.DictWriter(stream, fieldnames=[
                "source_id", "session", "side", "level", "bar_open_utc",
                "confirmed_at_utc", "price_basis",
            ])
            writer.writeheader()
            writer.writerows(observations)
    except Exception as exc:  # noqa: BLE001 - failure must be archived, never fake results
        result.update({
            "status": "BLOCKED_REAL_DATA_OR_RULE_VALIDATION",
            "error_type": type(exc).__name__,
            "error": str(exc)[:350],
        })
    (OUT/"experiment_result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True)+"\n", encoding="utf-8",
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS_REAL_HISTORICAL_SIGNAL_PROXY_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
