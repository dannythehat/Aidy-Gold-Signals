from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

DEFAULT_DATASET = "aidy_analytics_test"
DEFAULT_LOCATION = "EU"
_ALLOWED_DATASET = "aidy_analytics_test"


def _require_google() -> tuple[Any, Any]:
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account
    except ImportError as exc:
        raise RuntimeError(
            "Day 5 failed-state reset requires google-cloud-bigquery and google-auth."
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


def _single_count(client: Any, sql: str, *, location: str) -> int:
    rows = list(client.query(sql, location=location).result())
    if len(rows) != 1:
        raise RuntimeError("Expected exactly one count row.")
    return int(rows[0][0])


def reset_failed_state(
    client: Any,
    *,
    project: str,
    dataset: str,
    location: str,
) -> dict[str, object]:
    if dataset != _ALLOWED_DATASET:
        raise RuntimeError(
            f"Refusing Day 5 reset outside {_ALLOWED_DATASET}; got {dataset}."
        )

    prefix = f"`{project}.{dataset}"
    successful_manifests = _single_count(
        client,
        f"SELECT COUNT(*) FROM {prefix}.research_backfill_manifest` "
        "WHERE status = 'success'",
        location=location,
    )
    if successful_manifests != 0:
        raise RuntimeError(
            "Refusing to reset Day 5 research state because successful manifests exist."
        )

    before_rows = _single_count(
        client,
        f"SELECT COUNT(*) FROM {prefix}.research_candles`",
        location=location,
    )
    before_identities = _single_count(
        client,
        f"SELECT COUNT(DISTINCT research_identity) FROM {prefix}.research_candles`",
        location=location,
    )
    stage_candles = _single_count(
        client,
        f"SELECT COUNT(*) FROM {prefix}._stage_research_candles`",
        location=location,
    )
    stage_manifests = _single_count(
        client,
        f"SELECT COUNT(*) FROM {prefix}._stage_research_backfill_manifest`",
        location=location,
    )

    for table in (
        "_stage_research_candles",
        "_stage_research_backfill_manifest",
        "research_candles",
        "research_backfill_manifest",
    ):
        job = client.query(
            f"TRUNCATE TABLE `{project}.{dataset}.{table}`",
            location=location,
        )
        job.result()
        if job.errors:
            raise RuntimeError(f"Failed to truncate {table}: {job.errors}")

    after = {
        "research_candles": _single_count(
            client,
            f"SELECT COUNT(*) FROM {prefix}.research_candles`",
            location=location,
        ),
        "research_backfill_manifest": _single_count(
            client,
            f"SELECT COUNT(*) FROM {prefix}.research_backfill_manifest`",
            location=location,
        ),
        "stage_research_candles": _single_count(
            client,
            f"SELECT COUNT(*) FROM {prefix}._stage_research_candles`",
            location=location,
        ),
        "stage_research_backfill_manifest": _single_count(
            client,
            f"SELECT COUNT(*) FROM {prefix}._stage_research_backfill_manifest`",
            location=location,
        ),
    }
    if any(after.values()):
        raise RuntimeError(f"Day 5 reset did not leave all research tables empty: {after}")

    return {
        "ok": True,
        "project": project,
        "dataset": dataset,
        "before": {
            "research_rows": before_rows,
            "research_identities": before_identities,
            "successful_manifests": successful_manifests,
            "stage_research_candles": stage_candles,
            "stage_research_backfill_manifest": stage_manifests,
        },
        "after": after,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reset only failed Day 5 research state in the AIDY test dataset."
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
        result = reset_failed_state(
            client,
            project=project,
            dataset=args.dataset,
            location=args.location,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"DAY5_RESET_ERROR={type(exc).__name__}:{exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
