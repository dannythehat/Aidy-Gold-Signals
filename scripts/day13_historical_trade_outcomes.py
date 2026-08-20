from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from aidy.trade_outcomes import build_trade_outcome_bundle, trade_outcome_distribution

RISK_BPS = Decimal(25)
HORIZON_MINUTES = 240


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _row_dict(row: Any) -> dict[str, object]:
    return {
        "research_identity": row["research_identity"],
        "provenance_class": row["provenance_class"],
        "pit_eligible": row["pit_eligible"],
        "symbol": row["symbol"],
        "timeframe": row["timeframe"],
        "open_time_utc": _utc_text(row["open_time_utc"]),
        "open": row["open"],
        "high": row["high"],
        "low": row["low"],
        "close": row["close"],
        "source": row["source"],
        "source_file_sha256": row["source_file_sha256"],
        "source_payload_sha256": row["source_payload_sha256"],
    }


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Historical outcome timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _decimal_text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _levels(entry: Decimal, *, direction: str) -> tuple[str, tuple[str, str]]:
    risk = entry * RISK_BPS / Decimal(10000)
    if direction == "long":
        stop = entry - risk
        targets = (entry + risk, entry + risk * Decimal(2))
    else:
        stop = entry + risk
        targets = (entry - risk, entry - risk * Decimal(2))
    return _decimal_text(stop), tuple(_decimal_text(value) for value in targets)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a bounded Day 13 historical trade-outcome distribution."
    )
    parser.add_argument("--project", default=os.environ.get("AIDY_GCP_PROJECT_ID"))
    parser.add_argument(
        "--dataset", default=os.environ.get("AIDY_BIGQUERY_DATASET", "aidy_analytics_test")
    )
    parser.add_argument("--location", default=os.environ.get("AIDY_BIGQUERY_LOCATION", "EU"))
    parser.add_argument("--start", default="2025-01-06T00:00:00+00:00")
    parser.add_argument("--end", default="2025-01-13T00:00:00+00:00")
    parser.add_argument("--max-anchors", type=int, default=120)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not args.project:
        raise SystemExit("AIDY_GCP_PROJECT_ID or --project is required.")
    if args.max_anchors <= 0:
        raise SystemExit("--max-anchors must be positive.")

    start = _parse_utc(args.start)
    end = _parse_utc(args.end)
    if end <= start:
        raise SystemExit("--end must be after --start.")
    query_end = end + timedelta(minutes=HORIZON_MINUTES)

    from google.cloud import bigquery
    from google.oauth2 import service_account

    raw_credentials = os.environ.get("AIDY_GCP_SERVICE_ACCOUNT_JSON")
    if not raw_credentials:
        raise SystemExit("AIDY_GCP_SERVICE_ACCOUNT_JSON is required.")
    info = json.loads(raw_credentials)
    credentials = service_account.Credentials.from_service_account_info(info)
    client = bigquery.Client(project=args.project, credentials=credentials, location=args.location)

    table = f"{args.project}.{args.dataset}.research_candles"
    query = f"""
        SELECT research_identity, provenance_class, pit_eligible, symbol, timeframe,
               open_time_utc, open, high, low, close, source,
               source_file_sha256, source_payload_sha256
        FROM `{table}`
        WHERE source = 'histdata'
          AND symbol = 'XAUUSD'
          AND timeframe = 'M1'
          AND open_time_utc >= @start
          AND open_time_utc <= @query_end
        ORDER BY open_time_utc
    """
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start", "TIMESTAMP", start),
            bigquery.ScalarQueryParameter("query_end", "TIMESTAMP", query_end),
        ]
    )
    result = list(client.query(query, job_config=config).result())
    if not result:
        raise SystemExit("No accepted HistData M1 research rows found in the bounded window.")

    rows = [_row_dict(row) for row in result]
    parsed_times = [_parse_utc(str(row["open_time_utc"])) for row in rows]
    anchors: list[tuple[int, datetime]] = []
    for index, stamp in enumerate(parsed_times):
        if stamp < start or stamp >= end:
            continue
        if stamp.minute == 0:
            anchors.append((index, stamp))
        if len(anchors) >= args.max_anchors:
            break
    if not anchors:
        raise SystemExit("No hourly anchor candidates found in the bounded research window.")

    outcomes: list[dict[str, object]] = []
    for index, anchor_time in anchors:
        entry = Decimal(str(rows[index]["close"]))
        horizon_end = anchor_time + timedelta(minutes=HORIZON_MINUTES)
        future_rows = [
            row
            for row, stamp in zip(rows[index + 1 :], parsed_times[index + 1 :], strict=True)
            if stamp <= horizon_end
        ]
        for direction in ("long", "short"):
            stop, targets = _levels(entry, direction=direction)
            bundle = build_trade_outcome_bundle(
                anchor_time=anchor_time,
                direction=direction,
                entry=_decimal_text(entry),
                stop_loss=stop,
                targets=targets,
                research_rows=future_rows,
                horizons_minutes=(HORIZON_MINUTES,),
            )
            outcomes.append(bundle["outcomes"][0])

    distribution = trade_outcome_distribution(outcomes)
    complete = int(distribution["coverage_counts"].get("complete", 0))
    if complete == 0:
        raise SystemExit("Historical probe produced no complete trade outcomes.")

    print(
        json.dumps(
            {
                "ok": True,
                "evaluation_only": True,
                "pit_eligible": False,
                "realized_pnl_included": False,
                "source_table": "research_candles",
                "source_window_start": start.isoformat(),
                "anchor_window_end": end.isoformat(),
                "query_end_with_lookahead": query_end.isoformat(),
                "source_rows": len(rows),
                "anchors_built": len(anchors),
                "outcomes_built": len(outcomes),
                "complete_outcomes": complete,
                "probe_template": {
                    "directions": ["long", "short"],
                    "risk_bps": _decimal_text(RISK_BPS),
                    "targets_r": ["1", "2"],
                    "horizon_minutes": HORIZON_MINUTES,
                    "strategy_claim": False,
                },
                "distribution": distribution,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
