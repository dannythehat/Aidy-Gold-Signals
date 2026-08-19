from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from aidy.bigquery_exporter import (
    EXPORT_MANIFEST,
    TABLE_SPECS,
    ArchivedEvidence,
    FieldSpec,
    TableSpec,
    analytical_row,
    manifest_row,
    merge_sql,
    staging_fields,
)


def _require_google() -> tuple[Any, Any, Any]:
    try:
        from google.api_core.exceptions import NotFound
        from google.cloud import bigquery
        from google.oauth2 import service_account
    except ImportError as exc:
        raise RuntimeError(
            "Day 4 live export requires google-cloud-bigquery and google-auth."
        ) from exc
    return bigquery, service_account, NotFound


def _schema(bigquery: Any, fields: tuple[FieldSpec, ...]) -> list[Any]:
    return [
        bigquery.SchemaField(field.name, field.field_type, mode=field.mode)
        for field in fields
    ]


def _canonical_type(value: str) -> str:
    aliases = {"FLOAT": "FLOAT64", "INTEGER": "INT64"}
    upper = value.upper()
    return aliases.get(upper, upper)


def _schema_signature(table: Any) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (field.name, _canonical_type(field.field_type), field.mode.upper())
        for field in table.schema
    )


def _expected_signature(fields: tuple[FieldSpec, ...]) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (field.name, _canonical_type(field.field_type), field.mode.upper())
        for field in fields
    )


def _table_id(project: str, dataset: str, name: str) -> str:
    return f"{project}.{dataset}.{name}"


def _ensure_dataset(client: Any, bigquery: Any, *, project: str, dataset: str, location: str) -> Any:
    dataset_id = f"{project}.{dataset}"
    candidate = bigquery.Dataset(dataset_id)
    candidate.location = location
    candidate.description = "AIDY analytical memory. R2 remains authoritative raw evidence."
    existing = client.create_dataset(candidate, exists_ok=True)
    if str(existing.location).upper() != location.upper():
        raise RuntimeError(
            f"BigQuery dataset {dataset_id} exists in {existing.location}, expected {location}."
        )
    return existing


def _ensure_fact_table(
    client: Any,
    bigquery: Any,
    not_found: type[Exception],
    *,
    project: str,
    dataset: str,
    spec: TableSpec,
) -> Any:
    table_id = _table_id(project, dataset, spec.name)
    try:
        existing = client.get_table(table_id)
    except not_found:
        table = bigquery.Table(table_id, schema=_schema(bigquery, spec.fields))
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field=spec.partition_field,
        )
        table.clustering_fields = list(spec.clustering_fields)
        table.description = (
            "AIDY point-in-time analytical fact. Immutable source identity is "
            "archive_key + payload_digest."
        )
        return client.create_table(table)
    if _schema_signature(existing) != _expected_signature(spec.fields):
        raise RuntimeError(f"BigQuery schema drift detected for {table_id}.")
    partition_field = getattr(getattr(existing, "time_partitioning", None), "field", None)
    if partition_field != spec.partition_field:
        raise RuntimeError(f"BigQuery partition drift detected for {table_id}.")
    if tuple(existing.clustering_fields or ()) != spec.clustering_fields:
        raise RuntimeError(f"BigQuery clustering drift detected for {table_id}.")
    return existing


def _ensure_stage_table(
    client: Any,
    bigquery: Any,
    not_found: type[Exception],
    *,
    project: str,
    dataset: str,
    spec: TableSpec,
) -> Any:
    stage_name = f"_stage_{spec.name}"
    table_id = _table_id(project, dataset, stage_name)
    fields = staging_fields(spec)
    try:
        existing = client.get_table(table_id)
    except not_found:
        table = bigquery.Table(table_id, schema=_schema(bigquery, fields))
        table.description = "Transient AIDY export staging. Not analytical truth."
        return client.create_table(table)
    if _schema_signature(existing) != _expected_signature(fields):
        raise RuntimeError(f"BigQuery staging schema drift detected for {table_id}.")
    return existing


def ensure_warehouse(client: Any, *, project: str, dataset: str, location: str) -> dict[str, Any]:
    bigquery, _, not_found = _require_google()
    _ensure_dataset(client, bigquery, project=project, dataset=dataset, location=location)
    created: dict[str, Any] = {}
    for spec in (*TABLE_SPECS.values(), EXPORT_MANIFEST):
        created[spec.name] = _ensure_fact_table(
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
    return created


def _load_stage(
    client: Any,
    bigquery: Any,
    *,
    project: str,
    dataset: str,
    spec: TableSpec,
    run_id: str,
    rows: list[dict[str, Any]],
) -> Any:
    stage_rows = [{"_export_run_id": run_id, **row} for row in rows]
    config = bigquery.LoadJobConfig(
        schema=_schema(bigquery, staging_fields(spec)),
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        ignore_unknown_values=False,
        max_bad_records=0,
    )
    job = client.load_table_from_json(
        stage_rows,
        _table_id(project, dataset, f"_stage_{spec.name}"),
        job_config=config,
        location=client.location,
    )
    job.result()
    if job.errors:
        raise RuntimeError(f"BigQuery staging load failed: {job.errors}")
    return job


def _merge(client: Any, bigquery: Any, *, project: str, dataset: str, spec: TableSpec, run_id: str) -> Any:
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("run_id", "STRING", run_id)]
    )
    job = client.query(
        merge_sql(project=project, dataset=dataset, destination=spec),
        job_config=config,
        location=client.location,
    )
    job.result()
    if job.errors:
        raise RuntimeError(f"BigQuery merge failed for {spec.name}: {job.errors}")
    return job


def _cleanup_stage(client: Any, bigquery: Any, *, project: str, dataset: str, spec: TableSpec, run_id: str) -> None:
    sql = (
        f"DELETE FROM `{project}.{dataset}._stage_{spec.name}` "
        "WHERE _export_run_id = @run_id"
    )
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("run_id", "STRING", run_id)]
    )
    client.query(sql, job_config=config, location=client.location).result()


def _count_identities(
    client: Any,
    bigquery: Any,
    *,
    project: str,
    dataset: str,
    table: str,
    identities: list[str],
) -> tuple[int, int]:
    if not identities:
        return 0, 0
    sql = f"""
SELECT COUNT(*) AS row_count, COUNT(DISTINCT load_identity) AS identity_count
FROM `{project}.{dataset}.{table}`
WHERE load_identity IN UNNEST(@identities)
""".strip()
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("identities", "STRING", identities)]
    )
    rows = list(client.query(sql, job_config=config, location=client.location).result())
    if len(rows) != 1:
        raise RuntimeError("BigQuery reconciliation query returned an unexpected result.")
    return int(rows[0]["row_count"]), int(rows[0]["identity_count"])


def _parse_evidence(paths: list[Path]) -> list[ArchivedEvidence]:
    records: list[ArchivedEvidence] = []
    seen: set[str] = set()
    for path in paths:
        evidence = ArchivedEvidence.from_json(path.read_text(encoding="utf-8"))
        if evidence.load_identity in seen:
            continue
        seen.add(evidence.load_identity)
        records.append(evidence)
    if not records:
        raise RuntimeError("No supported R2 evidence objects were supplied for export.")
    return records


def export_files(
    client: Any,
    *,
    project: str,
    dataset: str,
    paths: list[Path],
) -> dict[str, Any]:
    bigquery, _, _ = _require_google()
    records = _parse_evidence(paths)
    run_id = str(uuid4())
    started = datetime.now(UTC)
    grouped: dict[str, list[ArchivedEvidence]] = defaultdict(list)
    for evidence in records:
        grouped[evidence.record_type].append(evidence)

    merge_job_ids: list[str] = []
    load_job_ids: list[str] = []
    query_bytes = 0
    reconciliation: dict[str, dict[str, int]] = {}
    manifest_records: list[tuple[ArchivedEvidence, str]] = []

    try:
        for record_type, batch in grouped.items():
            spec = TABLE_SPECS[record_type]
            fact_rows = [analytical_row(item) for item in batch]
            load_job = _load_stage(
                client,
                bigquery,
                project=project,
                dataset=dataset,
                spec=spec,
                run_id=run_id,
                rows=fact_rows,
            )
            load_job_ids.append(load_job.job_id)
            merge_job = _merge(
                client,
                bigquery,
                project=project,
                dataset=dataset,
                spec=spec,
                run_id=run_id,
            )
            merge_job_ids.append(merge_job.job_id)
            query_bytes += int(merge_job.total_bytes_processed or 0)
            combined_job_id = f"{load_job.job_id}:{merge_job.job_id}"
            manifest_records.extend((item, combined_job_id) for item in batch)

            identities = [item.load_identity for item in batch]
            row_count, identity_count = _count_identities(
                client,
                bigquery,
                project=project,
                dataset=dataset,
                table=spec.name,
                identities=identities,
            )
            expected = len(identities)
            if row_count != expected or identity_count != expected:
                raise RuntimeError(
                    f"BigQuery fact reconciliation failed for {spec.name}: "
                    f"expected {expected}, rows={row_count}, identities={identity_count}."
                )
            reconciliation[spec.name] = {
                "expected": expected,
                "rows": row_count,
                "identities": identity_count,
            }

        exported_at = datetime.now(UTC)
        manifests = [
            manifest_row(
                evidence,
                exported_at=exported_at,
                run_id=run_id,
                load_job_id=load_job_id,
            )
            for evidence, load_job_id in manifest_records
        ]
        manifest_load = _load_stage(
            client,
            bigquery,
            project=project,
            dataset=dataset,
            spec=EXPORT_MANIFEST,
            run_id=run_id,
            rows=manifests,
        )
        load_job_ids.append(manifest_load.job_id)
        manifest_merge = _merge(
            client,
            bigquery,
            project=project,
            dataset=dataset,
            spec=EXPORT_MANIFEST,
            run_id=run_id,
        )
        merge_job_ids.append(manifest_merge.job_id)
        query_bytes += int(manifest_merge.total_bytes_processed or 0)

        identities = [item.load_identity for item in records]
        manifest_rows, manifest_identities = _count_identities(
            client,
            bigquery,
            project=project,
            dataset=dataset,
            table=EXPORT_MANIFEST.name,
            identities=identities,
        )
        expected = len(identities)
        if manifest_rows != expected or manifest_identities != expected:
            raise RuntimeError(
                "BigQuery manifest reconciliation failed: "
                f"expected {expected}, rows={manifest_rows}, identities={manifest_identities}."
            )
        reconciliation[EXPORT_MANIFEST.name] = {
            "expected": expected,
            "rows": manifest_rows,
            "identities": manifest_identities,
        }
    finally:
        for spec in (*TABLE_SPECS.values(), EXPORT_MANIFEST):
            try:
                _cleanup_stage(
                    client,
                    bigquery,
                    project=project,
                    dataset=dataset,
                    spec=spec,
                    run_id=run_id,
                )
            except Exception:
                pass

    return {
        "ok": True,
        "run_id": run_id,
        "started_at": started.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "project": project,
        "dataset": dataset,
        "source_files": [str(path) for path in paths],
        "records": len(records),
        "load_identities": [item.load_identity for item in records],
        "archive_keys": [item.archive_key for item in records],
        "load_job_ids": load_job_ids,
        "merge_job_ids": merge_job_ids,
        "query_bytes_processed": query_bytes,
        "reconciliation": reconciliation,
    }


def _client_from_env(project: str, location: str) -> Any:
    bigquery, service_account, _ = _require_google()
    raw = os.environ.get("AIDY_GCP_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        raise RuntimeError("Missing AIDY_GCP_SERVICE_ACCOUNT_JSON.")
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("AIDY_GCP_SERVICE_ACCOUNT_JSON is not valid JSON.") from exc
    credentials = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    return bigquery.Client(project=project, credentials=credentials, location=location)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export immutable AIDY R2 evidence into BigQuery.")
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--project", default=os.environ.get("AIDY_GCP_PROJECT_ID", ""))
    parser.add_argument(
        "--dataset", default=os.environ.get("AIDY_BIGQUERY_DATASET", "aidy_analytics_test")
    )
    parser.add_argument("--location", default=os.environ.get("AIDY_BIGQUERY_LOCATION", "EU"))
    parser.add_argument("--ensure-only", action="store_true")
    args = parser.parse_args()

    if not args.project.strip():
        raise RuntimeError("Missing AIDY_GCP_PROJECT_ID.")
    if not args.ensure_only and not args.files:
        raise RuntimeError("At least one R2 evidence file is required unless --ensure-only is used.")
    client = _client_from_env(args.project, args.location)
    tables = ensure_warehouse(
        client,
        project=args.project,
        dataset=args.dataset,
        location=args.location,
    )
    if args.ensure_only:
        print(
            json.dumps(
                {
                    "ok": True,
                    "project": args.project,
                    "dataset": args.dataset,
                    "location": args.location,
                    "tables": sorted(tables),
                },
                sort_keys=True,
            )
        )
        return 0

    result = export_files(
        client,
        project=args.project,
        dataset=args.dataset,
        paths=args.files,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"DAY4_EXPORT_ERROR={type(exc).__name__}:{exc}", file=sys.stderr)
        raise
