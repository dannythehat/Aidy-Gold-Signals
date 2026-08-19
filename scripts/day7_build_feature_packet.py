from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any

from aidy.feature_engine import build_feature_packet

DEFAULT_DATASET = "aidy_analytics_test"
DEFAULT_LOCATION = "EU"
DEFAULT_SYMBOL = "XAUUSD"
PIT_CANDLE_SOURCE = "gold_api"
MAX_ROWS_PER_TIMEFRAME = 2048


def _require_google() -> tuple[Any, Any]:
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account
    except ImportError as exc:
        raise RuntimeError(
            "Day 7 BigQuery feature packets require google-cloud-bigquery and google-auth."
        ) from exc
    return bigquery, service_account


def _client_from_env(project: str | None, location: str) -> tuple[Any, str]:
    bigquery, service_account = _require_google()
    raw = (os.environ.get("AIDY_GCP_SERVICE_ACCOUNT_JSON") or "").strip()
    if not raw:
        raise RuntimeError("Missing AIDY_GCP_SERVICE_ACCOUNT_JSON.")
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("AIDY_GCP_SERVICE_ACCOUNT_JSON is not valid JSON.") from exc
    credentials = service_account.Credentials.from_service_account_info(info)
    resolved_project = (project or "").strip() or str(info.get("project_id") or "").strip()
    if not resolved_project:
        raise RuntimeError("Google service-account JSON does not contain project_id.")
    return (
        bigquery.Client(project=resolved_project, credentials=credentials, location=location),
        resolved_project,
    )


def _rows(client: Any, bigquery: Any, *, sql: str, parameters: list[Any]) -> list[dict[str, Any]]:
    config = bigquery.QueryJobConfig(query_parameters=parameters)
    job = client.query(sql, job_config=config, location=client.location)
    rows = [dict(row.items()) for row in job.result()]
    if job.errors:
        raise RuntimeError(f"Day 7 BigQuery query failed: {job.errors}")
    return rows


def _snapshot_as_of(
    client: Any,
    bigquery: Any,
    *,
    project: str,
    dataset: str,
    as_of: datetime,
    symbol: str,
) -> dict[str, Any] | None:
    sql = f"""
SELECT *
FROM `{project}.{dataset}.market_snapshots`
WHERE symbol = @symbol AND captured_at <= @as_of
ORDER BY captured_at DESC, load_identity DESC
LIMIT 1
""".strip()
    rows = _rows(
        client,
        bigquery,
        sql=sql,
        parameters=[
            bigquery.ScalarQueryParameter("symbol", "STRING", symbol),
            bigquery.ScalarQueryParameter("as_of", "TIMESTAMP", as_of),
        ],
    )
    return rows[0] if rows else None


def _pit_candles(
    client: Any,
    bigquery: Any,
    *,
    project: str,
    dataset: str,
    as_of: datetime,
    symbol: str,
) -> list[dict[str, Any]]:
    sql = f"""
WITH eligible AS (
  SELECT *, ROW_NUMBER() OVER (
    PARTITION BY source, symbol, timeframe, open_time_utc
    ORDER BY first_observed_at DESC, revision_index DESC, load_identity DESC
  ) AS revision_rank
  FROM `{project}.{dataset}.market_candles`
  WHERE symbol = @symbol
    AND source = @source
    AND open_time_utc <= @as_of
    AND first_observed_at <= @as_of
), canonical AS (
  SELECT * EXCEPT(revision_rank), ROW_NUMBER() OVER (
    PARTITION BY timeframe
    ORDER BY open_time_utc DESC, first_observed_at DESC, revision_index DESC, load_identity DESC
  ) AS timeframe_rank
  FROM eligible
  WHERE revision_rank = 1
)
SELECT * EXCEPT(timeframe_rank)
FROM canonical
WHERE timeframe_rank <= @row_limit
ORDER BY timeframe, open_time_utc
""".strip()
    return _rows(
        client,
        bigquery,
        sql=sql,
        parameters=[
            bigquery.ScalarQueryParameter("symbol", "STRING", symbol),
            bigquery.ScalarQueryParameter("source", "STRING", PIT_CANDLE_SOURCE),
            bigquery.ScalarQueryParameter("as_of", "TIMESTAMP", as_of),
            bigquery.ScalarQueryParameter("row_limit", "INT64", MAX_ROWS_PER_TIMEFRAME),
        ],
    )


def _research_candles(
    client: Any,
    bigquery: Any,
    *,
    project: str,
    dataset: str,
    as_of: datetime,
    symbol: str,
) -> list[dict[str, Any]]:
    sql = f"""
WITH ranked AS (
  SELECT *, ROW_NUMBER() OVER (
    PARTITION BY timeframe
    ORDER BY open_time_utc DESC, research_identity DESC
  ) AS timeframe_rank
  FROM `{project}.{dataset}.research_candles`
  WHERE symbol = @symbol
    AND open_time_utc <= @as_of
    AND provenance_class = 'retrospective_history'
    AND pit_eligible = FALSE
)
SELECT * EXCEPT(timeframe_rank)
FROM ranked
WHERE timeframe_rank <= @row_limit
ORDER BY timeframe, open_time_utc
""".strip()
    return _rows(
        client,
        bigquery,
        sql=sql,
        parameters=[
            bigquery.ScalarQueryParameter("symbol", "STRING", symbol),
            bigquery.ScalarQueryParameter("as_of", "TIMESTAMP", as_of),
            bigquery.ScalarQueryParameter("row_limit", "INT64", MAX_ROWS_PER_TIMEFRAME),
        ],
    )


def build_from_bigquery(
    client: Any,
    *,
    project: str,
    dataset: str,
    as_of: datetime,
    symbol: str,
    mode: str,
) -> dict[str, Any]:
    bigquery, _ = _require_google()
    if mode == "pit":
        snapshot = _snapshot_as_of(
            client,
            bigquery,
            project=project,
            dataset=dataset,
            as_of=as_of,
            symbol=symbol,
        )
        candles = _pit_candles(
            client,
            bigquery,
            project=project,
            dataset=dataset,
            as_of=as_of,
            symbol=symbol,
        )
    elif mode == "retrospective":
        snapshot = None
        candles = _research_candles(
            client,
            bigquery,
            project=project,
            dataset=dataset,
            as_of=as_of,
            symbol=symbol,
        )
    else:
        raise ValueError("mode must be pit or retrospective")

    packet = build_feature_packet(
        as_of=as_of,
        symbol=symbol,
        candle_rows=candles,
        mode=mode,
        snapshot=snapshot,
    )
    packet["warehouse"] = {"project": project, "dataset": dataset}
    packet["warehouse_input_rows"] = len(candles)
    if mode == "pit":
        packet["pit_candle_source"] = PIT_CANDLE_SOURCE
    return packet


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a deterministic AIDY Gold feature packet.")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--mode", choices=("pit", "retrospective"), required=True)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--project")
    parser.add_argument("--dataset", default=os.environ.get("AIDY_BIGQUERY_DATASET", DEFAULT_DATASET))
    parser.add_argument("--location", default=os.environ.get("AIDY_BIGQUERY_LOCATION", DEFAULT_LOCATION))
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        as_of = datetime.fromisoformat(args.as_of)
        if as_of.tzinfo is None:
            raise ValueError("--as-of must be timezone-aware")
        client, project = _client_from_env(args.project, args.location)
        packet = build_from_bigquery(
            client,
            project=project,
            dataset=args.dataset,
            as_of=as_of,
            symbol=args.symbol,
            mode=args.mode,
        )
        print(json.dumps(packet, sort_keys=True, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(f"DAY7_FEATURE_ERROR={type(exc).__name__}:{exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
