from __future__ import annotations

import argparse
import bisect
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from aidy.analogue_retrieval import (
    DEFAULT_MIN_COMPONENT_COVERAGE,
    DEFAULT_MIN_SIMILARITY,
    build_analogue_query,
    candidate_query_parameters,
    candidate_query_sql,
    reconstruct_case_from_storage_row,
    retrieve_analogues,
)
from aidy.day23_research import (
    BASELINE_SHA,
    CANDIDATE_LIMIT,
    CONTEXT_LOOKBACK_DAYS,
    MAX_RESULTS,
    MIN_COMPONENT_COVERAGE,
    MIN_SIMILARITY,
    QUERY_COUNT,
    QUERY_START_UTC,
    canonical_json,
    digest,
    episode_independence_diagnostics,
    freeze_query_manifest,
    preregistration,
    realized_dispersion,
    summarize_j1,
    summarize_j16,
)
from aidy.evidence_grading import build_evidence_report
from aidy.historical_backfill import RETROSPECTIVE_PROVENANCE
from aidy.historical_cases import build_retrospective_case_input

DEFAULT_DATASET = "aidy_analytics_test"
DEFAULT_LOCATION = "EU"
EXPERIMENT_ID = "day23-j1-j16-baseline-20260821-v1"
MANIFEST_TABLE = "research_day23_query_manifest"
J1_TABLE = "research_day23_j1_results"
J16_TABLE = "research_day23_j16_results"
SUMMARY_TABLE = "research_day23_summary"


@dataclass(frozen=True, slots=True)
class CandidateRecord:
    row: dict[str, Any]
    case: dict[str, Any]


def _parse_utc(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Day 23 timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _utc_text(value: datetime | str) -> str:
    return _parse_utc(value).isoformat()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run frozen Day 23 Architecture V2 J1 + descriptive-baseline J16."
    )
    parser.add_argument("--project", default=os.environ.get("AIDY_GCP_PROJECT_ID"))
    parser.add_argument("--dataset", default=os.environ.get("AIDY_BIGQUERY_DATASET", DEFAULT_DATASET))
    parser.add_argument("--location", default=os.environ.get("AIDY_BIGQUERY_LOCATION", DEFAULT_LOCATION))
    parser.add_argument("--query-count", type=int, default=QUERY_COUNT)
    parser.add_argument("--query-start", default=QUERY_START_UTC)
    parser.add_argument("--candidate-limit", type=int, default=CANDIDATE_LIMIT)
    parser.add_argument("--max-results", type=int, default=MAX_RESULTS)
    parser.add_argument("--output-dir", default="day23_artifacts")
    return parser


def _require_frozen_parameters(args: argparse.Namespace) -> None:
    if args.query_count != QUERY_COUNT:
        raise SystemExit(f"Day 23 query count is frozen at exactly {QUERY_COUNT}.")
    if _utc_text(args.query_start) != _utc_text(QUERY_START_UTC):
        raise SystemExit(f"Day 23 query start is frozen at {QUERY_START_UTC}.")
    if args.candidate_limit != CANDIDATE_LIMIT:
        raise SystemExit(f"Day 23 candidate limit is frozen at {CANDIDATE_LIMIT}.")
    if args.max_results != MAX_RESULTS:
        raise SystemExit(f"Day 23 max_results is frozen at {MAX_RESULTS}.")
    if DEFAULT_MIN_SIMILARITY != MIN_SIMILARITY:
        raise SystemExit("Day 17 min-similarity baseline changed; Day 23 must not tune retrieval.")
    if DEFAULT_MIN_COMPONENT_COVERAGE != MIN_COMPONENT_COVERAGE:
        raise SystemExit("Day 17 component-coverage baseline changed; Day 23 must not tune retrieval.")


def _row_mapping(row: Any) -> dict[str, Any]:
    return dict(row.items())


def _research_row(row: Any) -> dict[str, Any]:
    value = _row_mapping(row)
    value["open_time_utc"] = _utc_text(value["open_time_utc"])
    return value


def _query_parameters(bigquery: Any, params: dict[str, Any]) -> list[Any]:
    return [
        bigquery.ScalarQueryParameter("symbol", "STRING", params["symbol"]),
        bigquery.ScalarQueryParameter(
            "query_as_of", "TIMESTAMP", _parse_utc(str(params["query_as_of"]))
        ),
        bigquery.ArrayQueryParameter(
            "allowed_provenance", "STRING", params["allowed_provenance"]
        ),
        bigquery.ScalarQueryParameter(
            "feature_definition_version", "STRING", params["feature_definition_version"]
        ),
        bigquery.ScalarQueryParameter(
            "regime_definition_version", "STRING", params["regime_definition_version"]
        ),
        bigquery.ScalarQueryParameter(
            "setup_taxonomy_version", "STRING", params["setup_taxonomy_version"]
        ),
        bigquery.ScalarQueryParameter(
            "setup_detector_version", "STRING", params["setup_detector_version"]
        ),
        bigquery.ScalarQueryParameter("candidate_limit", "INT64", params["candidate_limit"]),
    ]


def _anchor_times(client: Any, bigquery: Any, *, project: str, dataset: str) -> list[datetime]:
    table = f"{project}.{dataset}.research_candles"
    sql = f"""
        SELECT DISTINCT TIMESTAMP_ADD(open_time_utc, INTERVAL 1 MINUTE) AS query_as_of_utc
        FROM `{table}`
        WHERE source = 'histdata'
          AND symbol = 'XAUUSD'
          AND timeframe = 'M1'
          AND TIMESTAMP_ADD(open_time_utc, INTERVAL 1 MINUTE) >= @query_start
          AND EXTRACT(MINUTE FROM TIMESTAMP_ADD(open_time_utc, INTERVAL 1 MINUTE)) = 0
          AND EXTRACT(SECOND FROM TIMESTAMP_ADD(open_time_utc, INTERVAL 1 MINUTE)) = 0
        ORDER BY query_as_of_utc
        LIMIT @query_count
    """
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("query_start", "TIMESTAMP", _parse_utc(QUERY_START_UTC)),
            bigquery.ScalarQueryParameter("query_count", "INT64", QUERY_COUNT),
        ]
    )
    rows = list(client.query(sql, job_config=config).result())
    anchors = [_parse_utc(row["query_as_of_utc"]) for row in rows]
    if len(anchors) != QUERY_COUNT:
        raise SystemExit(
            f"Frozen Day 23 anchor rule produced {len(anchors)} queries, expected {QUERY_COUNT}; "
            "do not replace or cherry-pick queries."
        )
    if len(set(anchors)) != QUERY_COUNT:
        raise SystemExit("Frozen Day 23 query anchors are not unique.")
    return anchors


def _research_rows(
    client: Any,
    bigquery: Any,
    *,
    project: str,
    dataset: str,
    anchors: list[datetime],
) -> tuple[list[dict[str, Any]], list[datetime]]:
    start = min(anchors) - timedelta(days=CONTEXT_LOOKBACK_DAYS)
    end = max(anchors)
    table = f"{project}.{dataset}.research_candles"
    sql = f"""
        SELECT research_identity, provenance_class, pit_eligible, symbol, timeframe,
               open_time_utc, open, high, low, close, source,
               source_file_sha256, source_payload_sha256, derivation_version
        FROM `{table}`
        WHERE source = 'histdata'
          AND symbol = 'XAUUSD'
          AND open_time_utc >= @start
          AND open_time_utc < @end
        ORDER BY open_time_utc, timeframe, research_identity
    """
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start", "TIMESTAMP", start),
            bigquery.ScalarQueryParameter("end", "TIMESTAMP", end),
        ]
    )
    rows = [_research_row(row) for row in client.query(sql, job_config=config).result()]
    if not rows:
        raise SystemExit("Day 23 found no HistData research rows for frozen query reconstruction.")
    stamps = [_parse_utc(row["open_time_utc"]) for row in rows]
    return rows, stamps


def _frozen_queries(
    *,
    research_rows: list[dict[str, Any]],
    row_stamps: list[datetime],
    anchors: list[datetime],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    queries: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    lookback = timedelta(days=CONTEXT_LOOKBACK_DAYS)
    for index, as_of in enumerate(anchors, start=1):
        left = bisect.bisect_left(row_stamps, as_of - lookback)
        right = bisect.bisect_left(row_stamps, as_of)
        input_boundary = build_retrospective_case_input(
            as_of=as_of,
            research_rows=research_rows[left:right],
        )
        query = build_analogue_query(
            input_boundary=input_boundary,
            allowed_provenance=(RETROSPECTIVE_PROVENANCE,),
            source_case_id=None,
            max_results=MAX_RESULTS,
        )
        if query["min_similarity_score"] != f"{MIN_SIMILARITY:.6f}":
            raise SystemExit("Frozen Day 17 similarity threshold drifted during Day 23 query build.")
        if query["min_component_coverage"] != f"{MIN_COMPONENT_COVERAGE:.6f}":
            raise SystemExit("Frozen Day 17 coverage threshold drifted during Day 23 query build.")
        queries.append(query)
        sources.append(
            {
                "query_index": index,
                "source_input_digest": input_boundary["input_digest"],
                "source_provenance": input_boundary["provenance"],
                "query_data_quality": input_boundary["data_quality"],
            }
        )
    return queries, sources


def _candidate_records(
    client: Any,
    *,
    project: str,
    dataset: str,
) -> list[CandidateRecord]:
    table = f"{project}.{dataset}.research_gold_cases"
    sql = f"""
        SELECT case_digest, case_version, case_id, symbol, as_of_utc,
               provenance_class, input_digest, feature_definition_version,
               regime_definition_version, setup_taxonomy_version,
               setup_detector_version, data_quality_grade,
               future_available_after_utc, input_boundary, future_evaluation
        FROM `{table}`
        WHERE symbol = 'XAUUSD'
        ORDER BY as_of_utc, case_id
    """
    records: list[CandidateRecord] = []
    for row in client.query(sql).result():
        mapping = _row_mapping(row)
        records.append(
            CandidateRecord(row=mapping, case=reconstruct_case_from_storage_row(mapping))
        )
    if not records:
        raise SystemExit("Day 23 requires the existing Day 16 research_gold_cases store.")
    return records


def _candidate_pool(
    query: dict[str, Any], records: list[CandidateRecord]
) -> list[CandidateRecord]:
    query_as_of = _parse_utc(query["as_of_utc"])
    allowed = set(query["allowed_candidate_provenance"])
    versions = query["feature_versions"]
    filtered = []
    for record in records:
        row = record.row
        as_of = _parse_utc(row["as_of_utc"])
        available_after = row.get("future_available_after_utc")
        if as_of >= query_as_of:
            continue
        if available_after is None or _parse_utc(available_after) > query_as_of:
            continue
        if row.get("provenance_class") not in allowed:
            continue
        if row.get("data_quality_grade") == "insufficient":
            continue
        if row.get("feature_definition_version") != versions["feature_definition_version"]:
            continue
        if row.get("regime_definition_version") != versions["regime_definition_version"]:
            continue
        if row.get("setup_taxonomy_version") != versions["setup_taxonomy_version"]:
            continue
        if row.get("setup_detector_version") != versions["setup_detector_version"]:
            continue
        filtered.append(record)
    filtered.sort(key=lambda item: str(item.row["case_id"]))
    filtered.sort(key=lambda item: _parse_utc(item.row["as_of_utc"]), reverse=True)
    return filtered[:CANDIDATE_LIMIT]


def _prove_candidate_sql_parity(
    client: Any,
    bigquery: Any,
    *,
    project: str,
    dataset: str,
    queries: list[dict[str, Any]],
    records: list[CandidateRecord],
) -> dict[str, Any]:
    sql = candidate_query_sql(project=project, dataset=dataset)
    checked = []
    for index in (0, len(queries) - 1):
        query = queries[index]
        params = candidate_query_parameters(query, candidate_limit=CANDIDATE_LIMIT)
        config = bigquery.QueryJobConfig(query_parameters=_query_parameters(bigquery, params))
        actual_ids = [str(row["case_id"]) for row in client.query(sql, job_config=config).result()]
        expected_ids = [str(record.row["case_id"]) for record in _candidate_pool(query, records)]
        if actual_ids != expected_ids:
            raise SystemExit(
                f"Day 23 in-memory candidate selection diverged from frozen Day 17 SQL at query {index + 1}."
            )
        checked.append(
            {
                "query_index": index + 1,
                "query_id": query["query_id"],
                "candidate_n": len(actual_ids),
                "candidate_identity_digest": digest(actual_ids),
            }
        )
    return {"candidate_sql_parity": True, "checks": checked}


def _manifest_schema(bigquery: Any) -> list[Any]:
    return [
        bigquery.SchemaField("experiment_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("manifest_digest", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("baseline_sha", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("query_index", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("query_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("query_as_of_utc", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("source_input_digest", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("payload_digest", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("query_payload", "JSON", mode="REQUIRED"),
        bigquery.SchemaField("source_metadata", "JSON", mode="REQUIRED"),
        bigquery.SchemaField("recorded_at_utc", "TIMESTAMP", mode="REQUIRED"),
    ]


def _result_schema(bigquery: Any) -> list[Any]:
    return [
        bigquery.SchemaField("experiment_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("manifest_digest", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("baseline_sha", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("query_index", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("query_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("query_as_of_utc", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("payload_digest", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("result_payload", "JSON", mode="REQUIRED"),
        bigquery.SchemaField("recorded_at_utc", "TIMESTAMP", mode="REQUIRED"),
    ]


def _summary_schema(bigquery: Any) -> list[Any]:
    return [
        bigquery.SchemaField("experiment_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("manifest_digest", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("baseline_sha", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("payload_digest", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("summary_payload", "JSON", mode="REQUIRED"),
        bigquery.SchemaField("recorded_at_utc", "TIMESTAMP", mode="REQUIRED"),
    ]


def _ensure_table(
    client: Any,
    bigquery: Any,
    not_found: type[Exception],
    table_id: str,
    schema: list[Any],
) -> None:
    try:
        existing = client.get_table(table_id)
    except not_found:
        table = bigquery.Table(table_id, schema=schema)
        table.description = "AIDY Day 23 Architecture V2 frozen research evidence."
        client.create_table(table)
        return
    actual = [(field.name, field.field_type, field.mode) for field in existing.schema]
    expected = [(field.name, field.field_type, field.mode) for field in schema]
    if actual != expected:
        raise RuntimeError(f"Day 23 BigQuery schema drift detected for {table_id}.")


def _persist_rows(
    client: Any,
    bigquery: Any,
    not_found: type[Exception],
    *,
    table_id: str,
    schema: list[Any],
    rows: list[dict[str, Any]],
    key_columns: tuple[str, ...],
) -> int:
    _ensure_table(client, bigquery, not_found, table_id, schema)
    stage_id = f"{table_id.rsplit('.', 1)[0]}._stage_{table_id.rsplit('.', 1)[1]}"
    stage_schema = [bigquery.SchemaField("_run_token", "STRING", mode="REQUIRED"), *schema]
    _ensure_table(client, bigquery, not_found, stage_id, stage_schema)
    run_token = uuid4().hex
    client.query(f"TRUNCATE TABLE `{stage_id}`").result()
    staged = [{"_run_token": run_token, **row} for row in rows]
    load = client.load_table_from_json(staged, stage_id)
    load.result()
    if load.errors:
        raise RuntimeError(f"Day 23 staging failed for {table_id}: {load.errors}")

    on_clause = " AND ".join(f"T.`{name}` = S.`{name}`" for name in key_columns)
    conflict_sql = f"""
        SELECT COUNT(*) AS n
        FROM `{stage_id}` S
        JOIN `{table_id}` T ON {on_clause}
        WHERE S._run_token = @run_token
          AND S.payload_digest != T.payload_digest
    """
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("run_token", "STRING", run_token)]
    )
    conflicts = int(next(client.query(conflict_sql, job_config=config).result())["n"])
    if conflicts:
        raise RuntimeError(
            f"Immutable Day 23 evidence conflict in {table_id}: existing key has different payload."
        )

    names = [field.name for field in schema]
    columns = ", ".join(f"`{name}`" for name in names)
    values = ", ".join(f"S.`{name}`" for name in names)
    merge_sql = f"""
        MERGE `{table_id}` T
        USING (SELECT {columns} FROM `{stage_id}` WHERE _run_token = @run_token) S
        ON {on_clause}
        WHEN NOT MATCHED THEN INSERT ({columns}) VALUES ({values})
    """
    client.query(merge_sql, job_config=config).result()

    where = " AND ".join(f"`{name}` = @key_{index}" for index, name in enumerate(key_columns))
    first = rows[0]
    params = []
    for index, name in enumerate(key_columns):
        value = first[name]
        field = next(field for field in schema if field.name == name)
        params.append(bigquery.ScalarQueryParameter(f"key_{index}", field.field_type, value))
    if "query_id" in key_columns:
        reconcile_sql = f"""
            SELECT COUNT(*) AS n, COUNT(DISTINCT query_id) AS ids
            FROM `{table_id}`
            WHERE experiment_id = @experiment_id AND manifest_digest = @manifest_digest
        """
        reconcile_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("experiment_id", "STRING", first["experiment_id"]),
                bigquery.ScalarQueryParameter("manifest_digest", "STRING", first["manifest_digest"]),
            ]
        )
        reconciliation = next(client.query(reconcile_sql, job_config=reconcile_config).result())
        count = int(reconciliation["n"])
        identities = int(reconciliation["ids"])
        if count != len(rows) or identities != len(rows):
            raise RuntimeError(f"Day 23 persisted evidence reconciliation failed for {table_id}.")
    else:
        reconciliation = next(
            client.query(
                f"SELECT COUNT(*) AS n FROM `{table_id}` WHERE {where}",
                job_config=bigquery.QueryJobConfig(query_parameters=params),
            ).result()
        )
        count = int(reconciliation["n"])
        if count != 1:
            raise RuntimeError(f"Day 23 summary reconciliation failed for {table_id}.")
    client.query(f"TRUNCATE TABLE `{stage_id}`").result()
    return count


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[object]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")


def main() -> int:
    args = _parser().parse_args()
    _require_frozen_parameters(args)
    if not args.project:
        raise SystemExit("AIDY_GCP_PROJECT_ID or --project is required.")

    from google.api_core.exceptions import NotFound
    from google.cloud import bigquery
    from google.oauth2 import service_account

    raw_credentials = os.environ.get("AIDY_GCP_SERVICE_ACCOUNT_JSON")
    if not raw_credentials:
        raise SystemExit("AIDY_GCP_SERVICE_ACCOUNT_JSON is required.")
    info = json.loads(raw_credentials)
    credentials = service_account.Credentials.from_service_account_info(info)
    client = bigquery.Client(project=args.project, credentials=credentials, location=args.location)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    recorded_at = datetime.now(UTC).isoformat()

    anchors = _anchor_times(client, bigquery, project=args.project, dataset=args.dataset)
    research_rows, row_stamps = _research_rows(
        client,
        bigquery,
        project=args.project,
        dataset=args.dataset,
        anchors=anchors,
    )
    queries, query_sources = _frozen_queries(
        research_rows=research_rows,
        row_stamps=row_stamps,
        anchors=anchors,
    )
    manifest = freeze_query_manifest(queries)
    manifest_digest = manifest["manifest_digest"]
    manifest_artifact_rows = []
    manifest_bq_rows = []
    for index, (query, source) in enumerate(zip(queries, query_sources, strict=True), start=1):
        payload = {
            "query_index": index,
            "query": query,
            "source_input_digest": source["source_input_digest"],
            "source_provenance": source["source_provenance"],
            "query_data_quality": source["query_data_quality"],
        }
        payload_digest = digest(payload)
        manifest_artifact_rows.append(payload)
        manifest_bq_rows.append(
            {
                "experiment_id": EXPERIMENT_ID,
                "manifest_digest": manifest_digest,
                "baseline_sha": BASELINE_SHA,
                "query_index": index,
                "query_id": query["query_id"],
                "query_as_of_utc": query["as_of_utc"],
                "source_input_digest": source["source_input_digest"],
                "payload_digest": payload_digest,
                "query_payload": query,
                "source_metadata": {
                    "source_provenance": source["source_provenance"],
                    "query_data_quality": source["query_data_quality"],
                },
                "recorded_at_utc": recorded_at,
            }
        )
    _write_json(output_dir / "preregistration.json", preregistration())
    _write_json(
        output_dir / "manifest_header.json",
        {
            "experiment_id": EXPERIMENT_ID,
            "manifest_version": manifest["manifest_version"],
            "manifest_digest": manifest_digest,
            "query_count": len(queries),
            "preregistration": manifest["preregistration"],
        },
    )
    _write_jsonl(output_dir / "query_manifest.jsonl", manifest_artifact_rows)
    manifest_table = f"{args.project}.{args.dataset}.{MANIFEST_TABLE}"
    _persist_rows(
        client,
        bigquery,
        NotFound,
        table_id=manifest_table,
        schema=_manifest_schema(bigquery),
        rows=manifest_bq_rows,
        key_columns=("experiment_id", "query_id"),
    )

    records = _candidate_records(client, project=args.project, dataset=args.dataset)
    candidate_snapshot = [
        {
            "case_id": str(record.row["case_id"]),
            "case_digest": str(record.row["case_digest"]),
            "input_digest": str(record.row["input_digest"]),
            "as_of_utc": _utc_text(record.row["as_of_utc"]),
            "future_available_after_utc": (
                None
                if record.row.get("future_available_after_utc") is None
                else _utc_text(record.row["future_available_after_utc"])
            ),
            "provenance_class": str(record.row["provenance_class"]),
            "data_quality_grade": str(record.row["data_quality_grade"]),
        }
        for record in records
    ]
    candidate_snapshot_digest = digest(candidate_snapshot)
    _write_json(
        output_dir / "candidate_store_snapshot.json",
        {
            "source_table": "research_gold_cases",
            "row_count": len(candidate_snapshot),
            "snapshot_digest": candidate_snapshot_digest,
            "rows": candidate_snapshot,
        },
    )
    parity = _prove_candidate_sql_parity(
        client,
        bigquery,
        project=args.project,
        dataset=args.dataset,
        queries=queries,
        records=records,
    )

    j1_artifacts: list[dict[str, Any]] = []
    j16_artifacts: list[dict[str, Any]] = []
    j1_bq_rows: list[dict[str, Any]] = []
    j16_bq_rows: list[dict[str, Any]] = []
    case_lookup = {str(record.row["case_id"]): record for record in records}

    for index, query in enumerate(queries, start=1):
        pool_records = _candidate_pool(query, records)
        pool_cases = [record.case for record in pool_records]
        retrieval = retrieve_analogues(query=query, candidate_cases=pool_cases)
        if retrieval["outcomes_used_for_selection"] is not False:
            raise SystemExit("Day 23 detected outcome contamination in Day 17 selection.")
        independence = episode_independence_diagnostics(retrieval["matches"])
        raw_n = int(retrieval["returned_match_count"])
        if raw_n != int(independence["selected_raw_n"]):
            raise SystemExit("Day 23 independence accounting changed the Day 17 selected raw count.")

        selected_identities = []
        for match in retrieval["matches"]:
            record = case_lookup[str(match["case_id"])]
            selected_identities.append(
                {
                    "rank": int(match["rank"]),
                    "case_id": str(match["case_id"]),
                    "case_digest": str(record.row["case_digest"]),
                    "input_digest": str(match["input_digest"]),
                    "as_of_utc": str(match["as_of_utc"]),
                    "similarity_score": match["similarity"]["similarity_score"],
                    "component_coverage": match["similarity"]["component_coverage"],
                }
            )
        pool_identity = [
            {
                "case_id": str(record.row["case_id"]),
                "case_digest": str(record.row["case_digest"]),
            }
            for record in pool_records
        ]
        no_comparable = retrieval["evidence_state"] == "no_sufficient_similarity" and raw_n == 0
        j1_payload = {
            "query_index": index,
            "query_id": query["query_id"],
            "query_as_of_utc": query["as_of_utc"],
            "retrieval_version": retrieval["retrieval_version"],
            "similarity_feature_version": retrieval.get("similarity_feature_version"),
            "retrieval_evidence_state": retrieval["evidence_state"],
            "retrieval_outcome": "NO_COMPARABLE_CASE" if no_comparable else retrieval["evidence_state"],
            "no_comparable_case": no_comparable,
            "candidate_raw_n": len(pool_records),
            "eligible_candidate_n": int(retrieval["eligible_candidate_count"]),
            "sufficient_match_n": int(retrieval["sufficient_match_count"]),
            "raw_n": raw_n,
            "selected_raw_n": raw_n,
            "candidate_pool_digest": digest(pool_identity),
            "selection_digest": retrieval["selection_digest"],
            "retrieval_digest": retrieval["retrieval_digest"],
            "selected_identities": selected_identities,
            **independence,
        }
        j1_payload["result_digest"] = digest(j1_payload)
        j1_artifacts.append(j1_payload)
        j1_bq_rows.append(
            {
                "experiment_id": EXPERIMENT_ID,
                "manifest_digest": manifest_digest,
                "baseline_sha": BASELINE_SHA,
                "query_index": index,
                "query_id": query["query_id"],
                "query_as_of_utc": query["as_of_utc"],
                "payload_digest": j1_payload["result_digest"],
                "result_payload": j1_payload,
                "recorded_at_utc": recorded_at,
            }
        )

        dispersion = realized_dispersion(retrieval["matches"])
        if retrieval["evidence_state"] == "query_insufficient_quality":
            grade_payload = {
                "dataset_grade": "not_graded",
                "dataset_grade_label": "NOT GRADED — QUERY INSUFFICIENT QUALITY",
                "dataset_n": 0,
                "dataset_metrics": {},
                "source_selection_digest": retrieval["selection_digest"],
                "evidence_report_digest": None,
                "outcome_values_used_for_dataset_grade": False,
                "grade_source": "existing_day18_report_not_applicable_to_query_insufficient_quality",
            }
        else:
            report = build_evidence_report(retrieval=retrieval)
            grade_payload = {
                "dataset_grade": report["dataset_grade"]["grade"],
                "dataset_grade_label": report["dataset_grade"]["grade_label"],
                "dataset_n": int(report["dataset_grade"]["n"]),
                "dataset_metrics": report["dataset_grade"]["metrics"],
                "source_selection_digest": report["source_selection_digest"],
                "evidence_report_digest": report["report_digest"],
                "outcome_values_used_for_dataset_grade": report["outcome_values_used_for_dataset_grade"],
                "grade_source": "existing_day18_build_evidence_report",
            }
        j16_payload = {
            "query_index": index,
            "query_id": query["query_id"],
            "query_as_of_utc": query["as_of_utc"],
            **grade_payload,
            "descriptive_baseline_only": True,
            "validation_clearance": False,
            "authoritative_retest_day": 38,
            **dispersion,
        }
        j16_payload["result_digest"] = digest(j16_payload)
        j16_artifacts.append(j16_payload)
        j16_bq_rows.append(
            {
                "experiment_id": EXPERIMENT_ID,
                "manifest_digest": manifest_digest,
                "baseline_sha": BASELINE_SHA,
                "query_index": index,
                "query_id": query["query_id"],
                "query_as_of_utc": query["as_of_utc"],
                "payload_digest": j16_payload["result_digest"],
                "result_payload": j16_payload,
                "recorded_at_utc": recorded_at,
            }
        )

    _write_jsonl(output_dir / "j1_results.jsonl", j1_artifacts)
    _write_jsonl(output_dir / "j16_results.jsonl", j16_artifacts)
    j1_table = f"{args.project}.{args.dataset}.{J1_TABLE}"
    j16_table = f"{args.project}.{args.dataset}.{J16_TABLE}"
    _persist_rows(
        client,
        bigquery,
        NotFound,
        table_id=j1_table,
        schema=_result_schema(bigquery),
        rows=j1_bq_rows,
        key_columns=("experiment_id", "query_id"),
    )
    _persist_rows(
        client,
        bigquery,
        NotFound,
        table_id=j16_table,
        schema=_result_schema(bigquery),
        rows=j16_bq_rows,
        key_columns=("experiment_id", "query_id"),
    )

    j1_summary = summarize_j1(j1_artifacts)
    j16_summary = summarize_j16(j16_artifacts)
    summary = {
        "ok": True,
        "experiment_id": EXPERIMENT_ID,
        "baseline_sha": BASELINE_SHA,
        "manifest_version": manifest["manifest_version"],
        "manifest_digest": manifest_digest,
        "frozen_query_count": len(queries),
        "query_anchor_start_utc": anchors[0].isoformat(),
        "query_anchor_end_utc": anchors[-1].isoformat(),
        "query_manifest_frozen_before_retrieval": True,
        "retrieval_tuned_during_experiment": False,
        "query_removed_or_replaced": False,
        "day17_min_similarity_score": str(MIN_SIMILARITY),
        "day17_min_component_coverage": str(MIN_COMPONENT_COVERAGE),
        "day18_max_results": MAX_RESULTS,
        "candidate_limit": CANDIDATE_LIMIT,
        "candidate_store_row_count": len(candidate_snapshot),
        "candidate_store_snapshot_digest": candidate_snapshot_digest,
        "candidate_sql_parity": parity,
        "outcomes_used_for_analogue_selection": False,
        "j1": j1_summary,
        "j16": j16_summary,
        "stop_work_branch_fired": j1_summary["stop_work_fired"],
        "normal_roadmap_progression_allowed": j1_summary["normal_roadmap_progression_allowed"],
        "bigquery_evidence": {
            "dataset": args.dataset,
            "manifest_table": MANIFEST_TABLE,
            "j1_table": J1_TABLE,
            "j16_table": J16_TABLE,
            "summary_table": SUMMARY_TABLE,
            "manifest_rows": len(manifest_bq_rows),
            "j1_rows": len(j1_bq_rows),
            "j16_rows": len(j16_bq_rows),
        },
        "security": {"secret_values_emitted": False},
    }
    summary["summary_digest"] = digest(summary)
    _write_json(output_dir / "summary.json", summary)
    summary_row = {
        "experiment_id": EXPERIMENT_ID,
        "manifest_digest": manifest_digest,
        "baseline_sha": BASELINE_SHA,
        "payload_digest": summary["summary_digest"],
        "summary_payload": summary,
        "recorded_at_utc": recorded_at,
    }
    summary_table = f"{args.project}.{args.dataset}.{SUMMARY_TABLE}"
    _persist_rows(
        client,
        bigquery,
        NotFound,
        table_id=summary_table,
        schema=_summary_schema(bigquery),
        rows=[summary_row],
        key_columns=("experiment_id", "manifest_digest"),
    )

    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
