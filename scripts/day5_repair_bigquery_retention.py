from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

DEFAULT_DATASET = "aidy_analytics_test"
DEFAULT_LOCATION = "EU"
DURABLE_TABLES = (
    "market_candles",
    "market_snapshots",
    "market_event_observations",
    "export_manifest",
    "research_candles",
    "research_backfill_manifest",
)


def _require_google() -> tuple[Any, Any, Any]:
    try:
        from google.api_core.exceptions import NotFound
        from google.cloud import bigquery
        from google.oauth2 import service_account
    except ImportError as exc:
        raise RuntimeError(
            "Retention repair requires google-cloud-bigquery and google-auth."
        ) from exc
    return bigquery, service_account, NotFound


def _client_from_env(project: str | None, location: str) -> tuple[Any, str]:
    bigquery, service_account, _ = _require_google()
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


def _partition_expiration(table: Any) -> int | None:
    partitioning = getattr(table, "time_partitioning", None)
    if partitioning is None:
        return None
    return partitioning.expiration_ms


def repair_retention(
    client: Any,
    *,
    project: str,
    dataset: str,
    location: str,
) -> dict[str, object]:
    _, _, not_found = _require_google()
    dataset_id = f"{project}.{dataset}"
    current_dataset = client.get_dataset(dataset_id)
    if str(current_dataset.location).upper() != location.upper():
        raise RuntimeError(
            f"BigQuery dataset {dataset_id} is in {current_dataset.location}, expected {location}."
        )

    dataset_before = {
        "default_table_expiration_ms": current_dataset.default_table_expiration_ms,
        "default_partition_expiration_ms": current_dataset.default_partition_expiration_ms,
    }
    update_fields: list[str] = []
    if current_dataset.default_table_expiration_ms is not None:
        current_dataset.default_table_expiration_ms = None
        update_fields.append("default_table_expiration_ms")
    if current_dataset.default_partition_expiration_ms is not None:
        current_dataset.default_partition_expiration_ms = None
        update_fields.append("default_partition_expiration_ms")
    if update_fields:
        client.update_dataset(current_dataset, update_fields)

    dataset_after = client.get_dataset(dataset_id)
    if dataset_after.default_table_expiration_ms is not None:
        raise RuntimeError("Dataset default table expiration was not removed.")
    if dataset_after.default_partition_expiration_ms is not None:
        raise RuntimeError("Dataset default partition expiration was not removed.")

    table_results: list[dict[str, object]] = []
    for name in DURABLE_TABLES:
        table_id = f"{project}.{dataset}.{name}"
        try:
            table = client.get_table(table_id)
        except not_found:
            table_results.append({"table": name, "status": "not_present"})
            continue

        before_expires = table.expires.isoformat() if table.expires is not None else None
        before_partition_ms = _partition_expiration(table)

        if table.expires is not None:
            table.expires = None
            client.update_table(table, ["expires"])

        if before_partition_ms is not None:
            sql = (
                f"ALTER TABLE `{table_id}` SET OPTIONS "
                "(partition_expiration_days = NULL)"
            )
            job = client.query(sql, location=location)
            job.result()
            if job.errors:
                raise RuntimeError(f"Failed to clear partition expiration for {table_id}: {job.errors}")

        refreshed = client.get_table(table_id)
        after_partition_ms = _partition_expiration(refreshed)
        after_expires = refreshed.expires.isoformat() if refreshed.expires is not None else None
        if after_expires is not None:
            raise RuntimeError(f"Table expiration remains on {table_id}: {after_expires}")
        if after_partition_ms is not None:
            raise RuntimeError(
                f"Partition expiration remains on {table_id}: {after_partition_ms} ms"
            )
        table_results.append(
            {
                "table": name,
                "status": "verified_no_expiration",
                "before_table_expires": before_expires,
                "before_partition_expiration_ms": before_partition_ms,
                "after_table_expires": after_expires,
                "after_partition_expiration_ms": after_partition_ms,
            }
        )

    return {
        "ok": True,
        "project": project,
        "dataset": dataset,
        "location": location,
        "dataset_before": dataset_before,
        "dataset_after": {
            "default_table_expiration_ms": dataset_after.default_table_expiration_ms,
            "default_partition_expiration_ms": dataset_after.default_partition_expiration_ms,
        },
        "tables": table_results,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Remove inherited expiry from AIDY durable BigQuery analytical memory."
    )
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
        client, project = _client_from_env(args.project, args.location)
        result = repair_retention(
            client,
            project=project,
            dataset=args.dataset,
            location=args.location,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"DAY5_RETENTION_REPAIR_ERROR={type(exc).__name__}:{exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
