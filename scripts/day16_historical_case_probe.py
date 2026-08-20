from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from aidy.bigquery_exporter import FieldSpec
from aidy.historical_cases import (
    RESEARCH_GOLD_CASES,
    analogue_input_view,
    build_retrospective_case,
    historical_case_distribution,
    historical_case_storage_row,
)

CONTEXT_LOOKBACK_DAYS = 45
FUTURE_HORIZON_MINUTES = 240


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Day 16 probe timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


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
        "derivation_version": row["derivation_version"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build and materialize a bounded Day 16 historical Gold case sample."
    )
    parser.add_argument("--project", default=os.environ.get("AIDY_GCP_PROJECT_ID"))
    parser.add_argument(
        "--dataset", default=os.environ.get("AIDY_BIGQUERY_DATASET", "aidy_analytics_test")
    )
    parser.add_argument("--location", default=os.environ.get("AIDY_BIGQUERY_LOCATION", "EU"))
    parser.add_argument("--start", default="2025-01-06T00:00:00+00:00")
    parser.add_argument("--end", default="2025-01-08T00:00:00+00:00")
    parser.add_argument("--max-cases", type=int, default=36)
    return parser


def _schema(bigquery: Any, fields: tuple[FieldSpec, ...]) -> list[Any]:
    return [bigquery.SchemaField(field.name, field.field_type, mode=field.mode) for field in fields]


def _signature(fields: Any) -> tuple[tuple[str, str, str], ...]:
    aliases = {"FLOAT": "FLOAT64", "INTEGER": "INT64", "BOOL": "BOOLEAN"}
    result = []
    for field in fields:
        field_type = aliases.get(str(field.field_type).upper(), str(field.field_type).upper())
        result.append((field.name, field_type, str(field.mode).upper()))
    return tuple(result)


def _ensure_tables(client: Any, bigquery: Any, not_found: type[Exception], table_id: str) -> str:
    expected = _schema(bigquery, RESEARCH_GOLD_CASES.fields)
    try:
        table = client.get_table(table_id)
    except not_found:
        table = bigquery.Table(table_id, schema=expected)
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field=RESEARCH_GOLD_CASES.partition_field,
        )
        table.clustering_fields = list(RESEARCH_GOLD_CASES.clustering_fields)
        table.description = (
            "AIDY canonical historical Gold cases. Input and future evaluation remain separated."
        )
        client.create_table(table)
    else:
        if _signature(table.schema) != _signature(expected):
            raise RuntimeError(f"BigQuery schema drift detected for {table_id}.")
        partition = getattr(table, "time_partitioning", None)
        if getattr(partition, "field", None) != RESEARCH_GOLD_CASES.partition_field:
            raise RuntimeError(f"BigQuery partition drift detected for {table_id}.")
        if tuple(table.clustering_fields or ()) != RESEARCH_GOLD_CASES.clustering_fields:
            raise RuntimeError(f"BigQuery clustering drift detected for {table_id}.")
        if partition is not None and partition.expiration_ms is not None:
            table.time_partitioning = bigquery.TimePartitioning(
                type_=partition.type_, field=partition.field
            )
            client.update_table(table, ["time_partitioning"])

    stage_id = f"{table_id.rsplit('.', 1)[0]}._stage_research_gold_cases_day16"
    stage_fields = [bigquery.SchemaField("_run_id", "STRING", mode="REQUIRED"), *expected]
    try:
        stage = client.get_table(stage_id)
    except not_found:
        stage = bigquery.Table(stage_id, schema=stage_fields)
        stage.description = "Transient AIDY Day 16 historical-case staging."
        client.create_table(stage)
    else:
        if _signature(stage.schema) != _signature(stage_fields):
            raise RuntimeError(f"BigQuery stage schema drift detected for {stage_id}.")
    return stage_id


def _merge_rows(
    client: Any,
    bigquery: Any,
    *,
    table_id: str,
    stage_id: str,
    rows: list[dict[str, Any]],
    run_id: str,
) -> tuple[int, int]:
    staged = [{"_run_id": run_id, **row} for row in rows]
    load_job = client.load_table_from_json(staged, stage_id)
    load_job.result()
    if load_job.errors:
        raise RuntimeError(f"Day 16 BigQuery staging failed: {load_job.errors}")

    conflict_sql = f"""
        SELECT COUNT(*) AS conflicts
        FROM `{stage_id}` S
        JOIN `{table_id}` T USING (case_id)
        WHERE S._run_id = @run_id AND S.case_digest != T.case_digest
    """
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("run_id", "STRING", run_id)]
    )
    conflicts = int(next(client.query(conflict_sql, job_config=config).result())["conflicts"])
    if conflicts:
        raise RuntimeError(
            "Historical-case deterministic drift detected: existing case_id has another digest."
        )

    names = [field.name for field in RESEARCH_GOLD_CASES.fields]
    columns = ", ".join(f"`{name}`" for name in names)
    values = ", ".join(f"S.`{name}`" for name in names)
    merge_sql = f"""
        MERGE `{table_id}` T
        USING (
          SELECT {columns}
          FROM `{stage_id}`
          WHERE _run_id = @run_id
          QUALIFY ROW_NUMBER() OVER (PARTITION BY case_id ORDER BY as_of_utc) = 1
        ) S
        ON T.case_id = S.case_id
        WHEN NOT MATCHED THEN INSERT ({columns}) VALUES ({values})
    """
    client.query(merge_sql, job_config=config).result()

    case_ids = [row["case_id"] for row in rows]
    reconcile_sql = f"""
        SELECT COUNT(*) AS rows, COUNT(DISTINCT case_id) AS identities
        FROM `{table_id}`
        WHERE case_id IN UNNEST(@case_ids)
    """
    reconcile_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("case_ids", "STRING", case_ids)]
    )
    reconciliation = next(client.query(reconcile_sql, job_config=reconcile_config).result())
    client.query(f"DELETE FROM `{stage_id}` WHERE _run_id = @run_id", job_config=config).result()
    return int(reconciliation["rows"]), int(reconciliation["identities"])


def main() -> int:
    args = _parser().parse_args()
    if not args.project:
        raise SystemExit("AIDY_GCP_PROJECT_ID or --project is required.")
    if args.max_cases <= 0:
        raise SystemExit("--max-cases must be positive.")
    start = _parse_utc(args.start)
    end = _parse_utc(args.end)
    if end <= start:
        raise SystemExit("--end must be after --start.")
    context_start = start - timedelta(days=CONTEXT_LOOKBACK_DAYS)
    query_end = end + timedelta(minutes=FUTURE_HORIZON_MINUTES)

    from google.api_core.exceptions import NotFound
    from google.cloud import bigquery
    from google.oauth2 import service_account

    raw_credentials = os.environ.get("AIDY_GCP_SERVICE_ACCOUNT_JSON")
    if not raw_credentials:
        raise SystemExit("AIDY_GCP_SERVICE_ACCOUNT_JSON is required.")
    info = json.loads(raw_credentials)
    credentials = service_account.Credentials.from_service_account_info(info)
    client = bigquery.Client(project=args.project, credentials=credentials, location=args.location)

    source_table = f"{args.project}.{args.dataset}.research_candles"
    query = f"""
        SELECT research_identity, provenance_class, pit_eligible, symbol, timeframe,
               open_time_utc, open, high, low, close, source,
               source_file_sha256, source_payload_sha256, derivation_version
        FROM `{source_table}`
        WHERE source = 'histdata'
          AND symbol = 'XAUUSD'
          AND open_time_utc >= @context_start
          AND open_time_utc <= @query_end
        ORDER BY open_time_utc, timeframe
    """
    query_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("context_start", "TIMESTAMP", context_start),
            bigquery.ScalarQueryParameter("query_end", "TIMESTAMP", query_end),
        ]
    )
    source_result = list(client.query(query, job_config=query_config).result())
    if not source_result:
        raise SystemExit("No accepted HistData research rows found for the Day 16 probe.")
    rows = [_row_dict(row) for row in source_result]

    anchors = []
    for row in rows:
        if row["timeframe"] != "M1":
            continue
        stamp = _parse_utc(str(row["open_time_utc"]))
        case_as_of = stamp + timedelta(minutes=1)
        if start <= case_as_of < end and case_as_of.minute == 0:
            anchors.append(case_as_of)
        if len(anchors) >= args.max_cases:
            break
    if not anchors:
        raise SystemExit("Day 16 probe found no closed hourly M1 case anchors.")

    cases = [build_retrospective_case(as_of=anchor, research_rows=rows) for anchor in anchors]
    views = [analogue_input_view(case) for case in cases]
    if any(view.get("future_evaluation_included") is not False for view in views):
        raise SystemExit("Day 16 analogue projection leaked future evaluation state.")

    storage_rows = [historical_case_storage_row(case) for case in cases]
    table_id = f"{args.project}.{args.dataset}.{RESEARCH_GOLD_CASES.name}"
    stage_id = _ensure_tables(client, bigquery, NotFound, table_id)
    run_id = f"day16-{uuid4().hex}"
    reconciled_rows, reconciled_identities = _merge_rows(
        client,
        bigquery,
        table_id=table_id,
        stage_id=stage_id,
        rows=storage_rows,
        run_id=run_id,
    )
    if reconciled_rows != len(cases) or reconciled_identities != len(cases):
        raise SystemExit("Day 16 BigQuery case reconciliation did not match built identities.")

    distribution = historical_case_distribution(cases)
    complete_move_cases = sum(
        all(label["coverage_state"] == "complete" for label in case["future_evaluation"]["move_bundle"]["labels"])
        for case in cases
    )
    result = {
        "ok": True,
        "case_version": cases[0]["case_version"],
        "input_version": cases[0]["input_boundary"]["input_version"],
        "provenance_class": "retrospective_history",
        "source_table": "research_candles",
        "destination_table": RESEARCH_GOLD_CASES.name,
        "source_window_start": context_start.isoformat(),
        "case_window_start": start.isoformat(),
        "case_window_end": end.isoformat(),
        "query_end_with_future_horizon": query_end.isoformat(),
        "source_rows": len(rows),
        "cases_built": len(cases),
        "cases_reconciled": reconciled_rows,
        "complete_move_cases": complete_move_cases,
        "analogue_views_built": len(views),
        "future_evaluation_in_analogue_views": False,
        "retrospective_live_decision_claim": False,
        "day14_counterfactuals_attached": 0,
        "distribution": distribution,
        "sample_case": {
            "case_id": cases[0]["case_id"],
            "as_of_utc": cases[0]["as_of_utc"],
            "data_quality_grade": cases[0]["input_boundary"]["data_quality"]["grade"],
            "regime": cases[0]["input_boundary"]["regime"]["labels"],
            "detector_state": cases[0]["input_boundary"]["setup"]["detector_state"],
            "candidate_setup_ids": cases[0]["input_boundary"]["setup"]["candidate_setup_ids"],
            "analogue_view_digest": views[0]["view_digest"],
        },
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
