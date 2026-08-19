from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from aidy.bigquery_exporter import FieldSpec, TableSpec
from aidy.historical_backfill import (
    DERIVATION_VERSION,
    HISTDATA_SOURCE,
    RESEARCH_BACKFILL_MANIFEST,
    RESEARCH_CANDLES,
    HistDataPeriod,
    build_research_candles,
    chunk_key,
    download_histdata_period,
    manifest_merge_sql,
    manifest_row,
    merge_sql,
    parse_histdata_m1,
    planned_periods,
    read_histdata_archive,
    request_signature,
    stage_fields,
)

DEFAULT_DATASET = "aidy_analytics_test"
DEFAULT_LOCATION = "EU"
DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAMES = ("M1", "M5", "M15", "H1", "H4", "D1")
DEFAULT_BATCH_SIZE = 25_000


def _require_google() -> tuple[Any, Any, Any]:
    try:
        from google.api_core.exceptions import NotFound
        from google.cloud import bigquery
        from google.oauth2 import service_account
    except ImportError as exc:
        raise RuntimeError(
            "Day 5 BigQuery backfill requires google-cloud-bigquery and google-auth."
        ) from exc
    return bigquery, service_account, NotFound


def _schema(bigquery: Any, fields: tuple[FieldSpec, ...]) -> list[Any]:
    return [bigquery.SchemaField(field.name, field.field_type, mode=field.mode) for field in fields]


def _canonical_type(value: str) -> str:
    aliases = {"FLOAT": "FLOAT64", "INTEGER": "INT64", "BOOL": "BOOLEAN"}
    upper = value.upper()
    return aliases.get(upper, upper)


def _signature(fields: Iterable[Any]) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (field.name, _canonical_type(field.field_type), field.mode.upper()) for field in fields
    )


def _table_id(project: str, dataset: str, name: str) -> str:
    return f"{project}.{dataset}.{name}"


def _ensure_dataset(
    client: Any,
    bigquery: Any,
    *,
    project: str,
    dataset: str,
    location: str,
) -> None:
    dataset_id = f"{project}.{dataset}"
    candidate = bigquery.Dataset(dataset_id)
    candidate.location = location
    candidate.description = "AIDY analytical memory. Retrospective research is PIT-ineligible."
    existing = client.create_dataset(candidate, exists_ok=True)
    if str(existing.location).upper() != location.upper():
        raise RuntimeError(
            f"BigQuery dataset {dataset_id} exists in {existing.location}, expected {location}."
        )


def _ensure_fact_table(
    client: Any,
    bigquery: Any,
    not_found: type[Exception],
    *,
    project: str,
    dataset: str,
    spec: TableSpec,
) -> None:
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
            "AIDY retrospective XAUUSD research history. Never eligible as live PIT evidence."
            if spec.name == RESEARCH_CANDLES.name
            else "AIDY resumable retrospective backfill manifest."
        )
        client.create_table(table)
        return
    if _signature(existing.schema) != _signature(spec.fields):
        raise RuntimeError(f"BigQuery schema drift detected for {table_id}.")
    partition_field = getattr(getattr(existing, "time_partitioning", None), "field", None)
    if partition_field != spec.partition_field:
        raise RuntimeError(f"BigQuery partition drift detected for {table_id}.")
    if tuple(existing.clustering_fields or ()) != spec.clustering_fields:
        raise RuntimeError(f"BigQuery clustering drift detected for {table_id}.")


def _ensure_stage_table(
    client: Any,
    bigquery: Any,
    not_found: type[Exception],
    *,
    project: str,
    dataset: str,
    spec: TableSpec,
) -> None:
    stage_id = _table_id(project, dataset, f"_stage_{spec.name}")
    fields = stage_fields(spec)
    try:
        existing = client.get_table(stage_id)
    except not_found:
        table = bigquery.Table(stage_id, schema=_schema(bigquery, fields))
        table.description = "Transient AIDY Day 5 backfill staging. Not analytical truth."
        client.create_table(table)
        return
    if _signature(existing.schema) != _signature(fields):
        raise RuntimeError(f"BigQuery staging schema drift detected for {stage_id}.")


def ensure_warehouse(client: Any, *, project: str, dataset: str, location: str) -> None:
    bigquery, _, not_found = _require_google()
    _ensure_dataset(client, bigquery, project=project, dataset=dataset, location=location)
    for spec in (RESEARCH_CANDLES, RESEARCH_BACKFILL_MANIFEST):
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


def _load_rows(
    client: Any,
    bigquery: Any,
    *,
    project: str,
    dataset: str,
    spec: TableSpec,
    run_id: str,
    rows: Iterable[dict[str, object]],
    batch_size: int,
) -> tuple[list[str], int]:
    if batch_size < 1:
        raise ValueError("BigQuery load batch size must be positive.")
    stage_id = _table_id(project, dataset, f"_stage_{spec.name}")
    config = bigquery.LoadJobConfig(
        schema=_schema(bigquery, stage_fields(spec)),
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        ignore_unknown_values=False,
        max_bad_records=0,
    )
    job_ids: list[str] = []
    total = 0
    batch: list[dict[str, object]] = []
    for row in rows:
        batch.append({"_backfill_run_id": run_id, **row})
        if len(batch) < batch_size:
            continue
        job = client.load_table_from_json(
            batch,
            stage_id,
            job_config=config,
            location=client.location,
        )
        job.result()
        if job.errors:
            raise RuntimeError(f"BigQuery staging load failed: {job.errors}")
        job_ids.append(job.job_id)
        total += len(batch)
        batch = []
    if batch:
        job = client.load_table_from_json(
            batch,
            stage_id,
            job_config=config,
            location=client.location,
        )
        job.result()
        if job.errors:
            raise RuntimeError(f"BigQuery staging load failed: {job.errors}")
        job_ids.append(job.job_id)
        total += len(batch)
    return job_ids, total


def _query(client: Any, bigquery: Any, sql: str, *, parameters: list[Any]) -> Any:
    config = bigquery.QueryJobConfig(query_parameters=parameters)
    job = client.query(sql, job_config=config, location=client.location)
    job.result()
    if job.errors:
        raise RuntimeError(f"BigQuery query failed: {job.errors}")
    return job


def _merge_candles(
    client: Any,
    bigquery: Any,
    *,
    project: str,
    dataset: str,
    run_id: str,
) -> Any:
    return _query(
        client,
        bigquery,
        merge_sql(project=project, dataset=dataset),
        parameters=[bigquery.ScalarQueryParameter("run_id", "STRING", run_id)],
    )


def _merge_manifest(
    client: Any,
    bigquery: Any,
    *,
    project: str,
    dataset: str,
    run_id: str,
) -> Any:
    return _query(
        client,
        bigquery,
        manifest_merge_sql(project=project, dataset=dataset),
        parameters=[bigquery.ScalarQueryParameter("run_id", "STRING", run_id)],
    )


def _cleanup_stage(
    client: Any,
    bigquery: Any,
    *,
    project: str,
    dataset: str,
    spec: TableSpec,
    run_id: str,
) -> None:
    sql = (
        f"DELETE FROM `{project}.{dataset}._stage_{spec.name}` "
        "WHERE _backfill_run_id = @run_id"
    )
    _query(
        client,
        bigquery,
        sql,
        parameters=[bigquery.ScalarQueryParameter("run_id", "STRING", run_id)],
    )


def _checkpoint_exists(
    client: Any,
    bigquery: Any,
    *,
    project: str,
    dataset: str,
    chunk: str,
    request_sig: str,
) -> bool:
    sql = f"""
SELECT COUNT(*) AS n
FROM `{project}.{dataset}.{RESEARCH_BACKFILL_MANIFEST.name}`
WHERE chunk_key = @chunk_key
  AND request_signature = @request_signature
  AND derivation_version = @derivation_version
  AND provenance_class = 'retrospective_history'
  AND pit_eligible = FALSE
  AND status = 'success'
""".strip()
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("chunk_key", "STRING", chunk),
            bigquery.ScalarQueryParameter("request_signature", "STRING", request_sig),
            bigquery.ScalarQueryParameter(
                "derivation_version",
                "STRING",
                DERIVATION_VERSION,
            ),
        ]
    )
    rows = list(client.query(sql, job_config=config, location=client.location).result())
    return bool(rows and int(rows[0]["n"]) > 0)


def _reconcile_candles(
    client: Any,
    bigquery: Any,
    *,
    project: str,
    dataset: str,
    chunk: str,
    payload_digest: str,
    expected: dict[str, int],
) -> dict[str, dict[str, int]]:
    sql = f"""
SELECT timeframe, COUNT(*) AS rows, COUNT(DISTINCT research_identity) AS identities,
       COUNTIF(pit_eligible) AS pit_eligible_rows,
       COUNT(DISTINCT provenance_class) AS provenance_classes
FROM `{project}.{dataset}.{RESEARCH_CANDLES.name}`
WHERE chunk_key = @chunk_key AND source_payload_sha256 = @payload_digest
GROUP BY timeframe
""".strip()
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("chunk_key", "STRING", chunk),
            bigquery.ScalarQueryParameter("payload_digest", "STRING", payload_digest),
        ]
    )
    rows = list(client.query(sql, job_config=config, location=client.location).result())
    actual = {
        str(row["timeframe"]): {
            "rows": int(row["rows"]),
            "identities": int(row["identities"]),
            "pit_eligible_rows": int(row["pit_eligible_rows"]),
            "provenance_classes": int(row["provenance_classes"]),
        }
        for row in rows
    }
    for timeframe, count in expected.items():
        observed = actual.get(timeframe)
        if observed is None:
            raise RuntimeError(f"Missing BigQuery research timeframe after load: {timeframe}")
        if observed["rows"] != count or observed["identities"] != count:
            raise RuntimeError(
                f"Research reconciliation mismatch for {timeframe}: expected {count}, "
                f"got rows={observed['rows']} identities={observed['identities']}."
            )
        if observed["pit_eligible_rows"] != 0 or observed["provenance_classes"] != 1:
            raise RuntimeError(f"Research provenance invariant failed for {timeframe}.")
    return actual


def _reconcile_manifest(
    client: Any,
    bigquery: Any,
    *,
    project: str,
    dataset: str,
    backfill_id: str,
) -> int:
    sql = f"""
SELECT COUNT(*) AS rows, COUNTIF(pit_eligible) AS pit_eligible_rows
FROM `{project}.{dataset}.{RESEARCH_BACKFILL_MANIFEST.name}`
WHERE backfill_identity = @backfill_identity
""".strip()
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("backfill_identity", "STRING", backfill_id)
        ]
    )
    rows = list(client.query(sql, job_config=config, location=client.location).result())
    if len(rows) != 1:
        raise RuntimeError("Manifest reconciliation returned an unexpected result.")
    count = int(rows[0]["rows"])
    if count != 1 or int(rows[0]["pit_eligible_rows"]) != 0:
        raise RuntimeError("Manifest idempotency/provenance reconciliation failed.")
    return count


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


def _iter_candle_rows(candles: dict[str, list[Any]]) -> Iterable[dict[str, object]]:
    for values in candles.values():
        for candle in values:
            yield candle.to_row()


def process_period(
    client: Any,
    *,
    project: str,
    dataset: str,
    period: HistDataPeriod,
    timeframes: tuple[str, ...],
    cache_dir: Path,
    batch_size: int,
    force_process: bool,
) -> dict[str, object]:
    bigquery, _, _ = _require_google()
    request_sig = request_signature(timeframes)
    chunk = chunk_key(symbol=DEFAULT_SYMBOL, period=period)
    if not force_process and _checkpoint_exists(
        client,
        bigquery,
        project=project,
        dataset=dataset,
        chunk=chunk,
        request_sig=request_sig,
    ):
        return {
            "period": period.key,
            "status": "checkpoint_skipped",
            "chunk_key": chunk,
            "request_signature": request_sig,
        }

    run_id = str(uuid4())
    ingested_at = datetime.now(UTC)
    archive_path = download_histdata_period(period, cache_dir=cache_dir)
    archive = read_histdata_archive(archive_path, period)
    bars, stats = parse_histdata_m1(archive.payload_text)
    candles = build_research_candles(
        bars,
        timeframes=timeframes,
        symbol=DEFAULT_SYMBOL,
        archive=archive,
        ingested_at=ingested_at,
        backfill_run_id=run_id,
    )
    expected = {timeframe: len(candles[timeframe]) for timeframe in timeframes}
    manifest = manifest_row(
        archive=archive,
        symbol=DEFAULT_SYMBOL,
        timeframes=timeframes,
        stats=stats,
        candles=candles,
        ingested_at=ingested_at,
        run_id=run_id,
    )

    candle_load_jobs: list[str] = []
    manifest_load_jobs: list[str] = []
    candle_merge_job: str | None = None
    manifest_merge_job: str | None = None
    query_bytes = 0
    try:
        candle_load_jobs, loaded = _load_rows(
            client,
            bigquery,
            project=project,
            dataset=dataset,
            spec=RESEARCH_CANDLES,
            run_id=run_id,
            rows=_iter_candle_rows(candles),
            batch_size=batch_size,
        )
        if loaded != sum(expected.values()):
            raise RuntimeError(
                f"Staging count mismatch: expected {sum(expected.values())}, loaded {loaded}."
            )
        merge_job = _merge_candles(
            client,
            bigquery,
            project=project,
            dataset=dataset,
            run_id=run_id,
        )
        candle_merge_job = merge_job.job_id
        query_bytes += int(merge_job.total_bytes_processed or 0)
        reconciliation = _reconcile_candles(
            client,
            bigquery,
            project=project,
            dataset=dataset,
            chunk=chunk,
            payload_digest=archive.payload_sha256,
            expected=expected,
        )
        manifest_load_jobs, manifest_loaded = _load_rows(
            client,
            bigquery,
            project=project,
            dataset=dataset,
            spec=RESEARCH_BACKFILL_MANIFEST,
            run_id=run_id,
            rows=[manifest],
            batch_size=1,
        )
        if manifest_loaded != 1:
            raise RuntimeError("Backfill manifest staging did not load exactly one row.")
        manifest_job = _merge_manifest(
            client,
            bigquery,
            project=project,
            dataset=dataset,
            run_id=run_id,
        )
        manifest_merge_job = manifest_job.job_id
        query_bytes += int(manifest_job.total_bytes_processed or 0)
        manifest_count = _reconcile_manifest(
            client,
            bigquery,
            project=project,
            dataset=dataset,
            backfill_id=str(manifest["backfill_identity"]),
        )
    finally:
        _cleanup_stage(
            client,
            bigquery,
            project=project,
            dataset=dataset,
            spec=RESEARCH_CANDLES,
            run_id=run_id,
        )
        _cleanup_stage(
            client,
            bigquery,
            project=project,
            dataset=dataset,
            spec=RESEARCH_BACKFILL_MANIFEST,
            run_id=run_id,
        )

    return {
        "period": period.key,
        "status": "loaded",
        "run_id": run_id,
        "chunk_key": chunk,
        "backfill_identity": manifest["backfill_identity"],
        "request_signature": request_sig,
        "source_file": archive.zip_name,
        "source_file_sha256": archive.zip_sha256,
        "source_payload_sha256": archive.payload_sha256,
        "first_open_time_utc": manifest["first_open_time_utc"],
        "last_open_time_utc": manifest["last_open_time_utc"],
        "m1_rows": stats.rows,
        "duplicate_rows": stats.duplicate_rows,
        "gap_count": stats.gap_count,
        "max_gap_seconds": stats.max_gap_seconds,
        "timeframe_counts": expected,
        "reconciliation": reconciliation,
        "manifest_rows": manifest_count,
        "candle_load_job_ids": candle_load_jobs,
        "manifest_load_job_ids": manifest_load_jobs,
        "candle_merge_job_id": candle_merge_job,
        "manifest_merge_job_id": manifest_merge_job,
        "query_bytes_processed": query_bytes,
    }


def run_backfill(
    *,
    client: Any,
    project: str,
    dataset: str,
    location: str,
    periods: tuple[HistDataPeriod, ...],
    timeframes: tuple[str, ...],
    cache_dir: Path,
    batch_size: int,
    force_process: bool,
) -> dict[str, object]:
    ensure_warehouse(client, project=project, dataset=dataset, location=location)
    results = [
        process_period(
            client,
            project=project,
            dataset=dataset,
            period=period,
            timeframes=timeframes,
            cache_dir=cache_dir,
            batch_size=batch_size,
            force_process=force_process,
        )
        for period in periods
    ]
    return {
        "ok": True,
        "project": project,
        "dataset": dataset,
        "location": location,
        "source": HISTDATA_SOURCE,
        "symbol": DEFAULT_SYMBOL,
        "timeframes": list(timeframes),
        "derivation_version": DERIVATION_VERSION,
        "periods": [period.key for period in periods],
        "results": results,
    }


def _parse_timeframes(raw: str) -> tuple[str, ...]:
    values = tuple(
        dict.fromkeys(item.strip().upper() for item in raw.split(",") if item.strip())
    )
    request_signature(values)
    return values


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AIDY Day 5 provenance-safe retrospective XAUUSD HistData backfill."
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
    parser.add_argument("--start-year", type=int)
    parser.add_argument("--end-year", type=int)
    parser.add_argument("--period", action="append", default=[])
    parser.add_argument("--timeframes", default=",".join(DEFAULT_TIMEFRAMES))
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/day5-histdata"))
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--force-process",
        action="store_true",
        help=(
            "Bypass successful manifest checkpoint. BigQuery MERGEs remain "
            "insert-only/idempotent."
        ),
    )
    parser.add_argument("--ensure-only", action="store_true")
    return parser.parse_args()


def _periods_from_args(args: argparse.Namespace) -> tuple[HistDataPeriod, ...]:
    if args.period:
        result: list[HistDataPeriod] = []
        for raw in args.period:
            value = str(raw).strip()
            if len(value) == 4 and value.isdigit():
                result.append(HistDataPeriod(int(value)))
            elif len(value) == 6 and value.isdigit():
                result.append(HistDataPeriod(int(value[:4]), int(value[4:])))
            else:
                raise ValueError(
                    f"Invalid HistData period {value!r}; expected YYYY or YYYYMM."
                )
        return tuple(result)
    if args.start_year is None or args.end_year is None:
        raise ValueError("Supply --period YYYY or both --start-year and --end-year.")
    return planned_periods(
        args.start_year,
        args.end_year,
        current_date=datetime.now(UTC),
    )


def main() -> int:
    args = _parse_args()
    try:
        client, project = _client_from_env(args.project, args.location)
        if args.ensure_only:
            ensure_warehouse(
                client,
                project=project,
                dataset=args.dataset,
                location=args.location,
            )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "project": project,
                        "dataset": args.dataset,
                        "location": args.location,
                        "ensure_only": True,
                    },
                    sort_keys=True,
                )
            )
            return 0
        periods = _periods_from_args(args)
        timeframes = _parse_timeframes(args.timeframes)
        result = run_backfill(
            client=client,
            project=project,
            dataset=args.dataset,
            location=args.location,
            periods=periods,
            timeframes=timeframes,
            cache_dir=args.cache_dir,
            batch_size=args.batch_size,
            force_process=args.force_process,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"DAY5_BACKFILL_ERROR={type(exc).__name__}:{exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
