from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any

from aidy.pit_reconstruction import normalize_as_of, query_contract, reconstruction_bundle

DEFAULT_DATASET = "aidy_analytics_test"
DEFAULT_LOCATION = "EU"
DEFAULT_SYMBOL = "XAUUSD"


def _require_google() -> tuple[Any, Any]:
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account
    except ImportError as exc:
        raise RuntimeError(
            "Day 6 BigQuery reconstruction requires google-cloud-bigquery and google-auth."
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
        bigquery.Client(
            project=resolved_project,
            credentials=credentials,
            location=location,
        ),
        resolved_project,
    )


def _query_rows(
    client: Any,
    bigquery: Any,
    *,
    sql: str,
    as_of: datetime,
    symbol: str,
    needs_symbol: bool,
) -> list[dict[str, Any]]:
    parameters = [bigquery.ScalarQueryParameter("as_of", "TIMESTAMP", as_of)]
    if needs_symbol:
        parameters.append(bigquery.ScalarQueryParameter("symbol", "STRING", symbol))
    config = bigquery.QueryJobConfig(query_parameters=parameters)
    job = client.query(sql, job_config=config, location=client.location)
    rows = [dict(row.items()) for row in job.result()]
    if job.errors:
        raise RuntimeError(f"Day 6 reconstruction query failed: {job.errors}")
    return rows


def reconstruct_from_bigquery(
    client: Any,
    *,
    project: str,
    dataset: str,
    as_of: datetime | str,
    symbol: str,
) -> dict[str, Any]:
    if not symbol.strip():
        raise ValueError("symbol is required.")
    bigquery, _ = _require_google()
    cutoff = normalize_as_of(as_of)
    queries = query_contract(project=project, dataset=dataset)

    candles = _query_rows(
        client,
        bigquery,
        sql=queries["candles"].sql,
        as_of=cutoff,
        symbol=symbol,
        needs_symbol=True,
    )
    events = _query_rows(
        client,
        bigquery,
        sql=queries["events"].sql,
        as_of=cutoff,
        symbol=symbol,
        needs_symbol=False,
    )
    snapshots = _query_rows(
        client,
        bigquery,
        sql=queries["snapshot"].sql,
        as_of=cutoff,
        symbol=symbol,
        needs_symbol=True,
    )

    bundle = reconstruction_bundle(
        as_of=cutoff,
        symbol=symbol,
        candle_rows=candles,
        event_rows=events,
        snapshot_rows=snapshots,
        query_ids={name: query.query_id for name, query in queries.items()},
    )
    bundle["warehouse"] = {"project": project, "dataset": dataset}
    return bundle


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconstruct exactly what PIT-eligible AIDY evidence was knowable as of T."
    )
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--project")
    parser.add_argument(
        "--dataset",
        default=os.environ.get("AIDY_BIGQUERY_DATASET", DEFAULT_DATASET),
    )
    parser.add_argument(
        "--location",
        default=os.environ.get("AIDY_BIGQUERY_LOCATION", DEFAULT_LOCATION),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        cutoff = normalize_as_of(args.as_of)
        client, project = _client_from_env(args.project, args.location)
        result = reconstruct_from_bigquery(
            client,
            project=project,
            dataset=args.dataset,
            as_of=cutoff,
            symbol=args.symbol,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"DAY6_RECONSTRUCTION_ERROR={type(exc).__name__}:{exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
