from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from aidy.bigquery_exporter import EXPORT_MANIFEST
from aidy.cross_market_bigquery import CROSS_MARKET_TABLE, ArchivedCrossMarketEvidence

try:
    from scripts.day4_export_r2_to_bigquery import (
        _cleanup_stage,
        _client_from_env,
        _count_identities,
        _ensure_fact_table,
        _ensure_stage_table,
        _load_stage,
        _merge,
        _require_google,
    )
except ModuleNotFoundError:
    from day4_export_r2_to_bigquery import (  # type: ignore[no-redef]
        _cleanup_stage,
        _client_from_env,
        _count_identities,
        _ensure_fact_table,
        _ensure_stage_table,
        _load_stage,
        _merge,
        _require_google,
    )


def ensure_cross_market_warehouse(
    client,
    *,
    project: str,
    dataset: str,
) -> None:
    bigquery, _, not_found = _require_google()
    for spec in (CROSS_MARKET_TABLE, EXPORT_MANIFEST):
        _ensure_fact_table(
            client,
            bigquery,
            not_found,
            project=project,
            dataset=dataset,
            spec=spec,
        )
        _ensure_stage_table(
            client,
            bigquery,
            not_found,
            project=project,
            dataset=dataset,
            spec=spec,
        )


def export_cross_market_raw(
    client,
    *,
    project: str,
    dataset: str,
    raw: str | bytes,
) -> dict[str, object]:
    bigquery, _, _ = _require_google()
    evidence = ArchivedCrossMarketEvidence.from_json(raw)
    run_id = str(uuid4())
    ensure_cross_market_warehouse(client, project=project, dataset=dataset)
    try:
        fact_load = _load_stage(
            client,
            bigquery,
            project=project,
            dataset=dataset,
            spec=CROSS_MARKET_TABLE,
            run_id=run_id,
            rows=[evidence.analytical_row()],
        )
        fact_merge = _merge(
            client,
            bigquery,
            project=project,
            dataset=dataset,
            spec=CROSS_MARKET_TABLE,
            run_id=run_id,
        )
        manifest = evidence.manifest_row(
            exported_at=datetime.now(UTC),
            run_id=run_id,
            load_job_id=f"{fact_load.job_id}:{fact_merge.job_id}",
        )
        manifest_load = _load_stage(
            client,
            bigquery,
            project=project,
            dataset=dataset,
            spec=EXPORT_MANIFEST,
            run_id=run_id,
            rows=[manifest],
        )
        _merge(
            client,
            bigquery,
            project=project,
            dataset=dataset,
            spec=EXPORT_MANIFEST,
            run_id=run_id,
        )

        fact_rows, fact_identities = _count_identities(
            client,
            bigquery,
            project=project,
            dataset=dataset,
            table=CROSS_MARKET_TABLE.name,
            identities=[evidence.load_identity],
        )
        manifest_rows, manifest_identities = _count_identities(
            client,
            bigquery,
            project=project,
            dataset=dataset,
            table=EXPORT_MANIFEST.name,
            identities=[evidence.load_identity],
        )
        if (fact_rows, fact_identities, manifest_rows, manifest_identities) != (1, 1, 1, 1):
            raise RuntimeError("Cross-market BigQuery idempotency reconciliation failed.")
        return {
            "ok": True,
            "load_identity": evidence.load_identity,
            "series_id": evidence.payload["series_id"],
            "observation_date": evidence.payload["observation_date"],
            "fact_rows": fact_rows,
            "fact_identities": fact_identities,
            "manifest_rows": manifest_rows,
            "manifest_identities": manifest_identities,
            "load_job_id": fact_load.job_id,
            "manifest_load_job_id": manifest_load.job_id,
        }
    finally:
        for spec in (CROSS_MARKET_TABLE, EXPORT_MANIFEST):
            _cleanup_stage(
                client,
                bigquery,
                project=project,
                dataset=dataset,
                spec=spec,
                run_id=run_id,
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Export one AIDY cross-market R2 object.")
    parser.add_argument("file", type=Path)
    parser.add_argument("--project", default=os.environ.get("AIDY_GCP_PROJECT_ID", ""))
    parser.add_argument(
        "--dataset", default=os.environ.get("AIDY_BIGQUERY_DATASET", "aidy_analytics_test")
    )
    parser.add_argument("--location", default=os.environ.get("AIDY_BIGQUERY_LOCATION", "EU"))
    args = parser.parse_args()
    project = args.project.strip()
    if not project:
        raw_secret = os.environ.get("AIDY_GCP_SERVICE_ACCOUNT_JSON", "").strip()
        if not raw_secret:
            raise RuntimeError("Missing Google project/credential.")
        project = str(json.loads(raw_secret).get("project_id") or "").strip()
    if not project:
        raise RuntimeError("Could not resolve Google project ID.")
    client = _client_from_env(project, args.location)
    result = export_cross_market_raw(
        client,
        project=project,
        dataset=args.dataset,
        raw=args.file.read_text(encoding="utf-8"),
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"DAY9_EXPORT_ERROR={type(exc).__name__}:{exc}", file=sys.stderr)
        raise
