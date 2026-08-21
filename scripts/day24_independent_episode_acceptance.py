from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from statistics import median
from typing import Any

from aidy.analogue_retrieval import DEFAULT_CANDIDATE_LIMIT
from aidy.analogue_retrieval_v2 import (
    ANALOGUE_RETRIEVAL_VERSION_V2,
    EMBARGO_MINUTES,
    SIMILARITY_FEATURE_VERSION_V2,
    retrieve_analogues_v2,
    similarity_manifest_v2,
)
from aidy.day23_research import canonical_json, digest, freeze_query_manifest
from aidy.evidence_grading_v2 import build_evidence_report_v2, evidence_grade_manifest_v2
from aidy.historical_cases import reconstruct_historical_case_from_storage_row if False else None
from aidy.analogue_retrieval import reconstruct_case_from_storage_row

DAY24_BASE_SHA = "9f0803040e49d58fe082a7de863d8647f7470b84"
DAY23_EXPERIMENT_ID = "day23-j1-j16-baseline-20260821-v1"
DAY23_MANIFEST_DIGEST = "119d8c2a1a11cba44d8195fff81be640f7b9c084d0d7b8c28a61dedfa64e5ac5"
DAY23_CANDIDATE_SNAPSHOT_DIGEST = "bd3c81b54ec05b2150e6e6ecbdffbc3c1e4f943c6a23c9a8ee4977c1dc1c3a88"
DAY23_MEDIAN_INDEPENDENCE = Decimal("0.666667")
DAY23_MEDIAN_EPISODES = Decimal("2")
DAY23_NCC_RATE = Decimal("0.244000")
QUERY_COUNT = 1000
MAX_RESULTS = 200
MIN_SIMILARITY = "0.720000"
MIN_COMPONENT_COVERAGE = "0.650000"
EXPERIMENT_ID = "day24-independent-episode-retrieval-20260822-v1"
RESULT_TABLE = "research_day24_retrieval_results"
SUMMARY_TABLE = "research_day24_summary"
DEFAULT_DATASET = "aidy_analytics_test"
DEFAULT_LOCATION = "EU"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Day 24 frozen independent-episode acceptance.")
    parser.add_argument("--project", default=os.environ.get("AIDY_GCP_PROJECT_ID"))
    parser.add_argument("--dataset", default=os.environ.get("AIDY_BIGQUERY_DATASET", DEFAULT_DATASET))
    parser.add_argument("--location", default=os.environ.get("AIDY_BIGQUERY_LOCATION", DEFAULT_LOCATION))
    parser.add_argument("--output-dir", default="day24_artifacts")
    return parser


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Day 24 timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        decoded = json.loads(value)
        if isinstance(decoded, dict):
            return decoded
    raise TypeError("Expected JSON object.")


def _row(row: Any) -> dict[str, Any]:
    return dict(row.items())


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[object]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for item in rows:
            handle.write(canonical_json(item) + "\n")


def _q(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def _distribution(values: list[Any]) -> dict[str, Any]:
    parsed = sorted(Decimal(str(value)) for value in values if value is not None)
    if not parsed:
        return {"n": 0, "min": None, "p10": None, "p25": None, "median": None, "p75": None, "p90": None, "max": None}

    def quantile(fraction: Decimal) -> Decimal:
        if len(parsed) == 1:
            return parsed[0]
        position = fraction * Decimal(len(parsed) - 1)
        lower = int(position)
        upper = min(lower + 1, len(parsed) - 1)
        weight = position - Decimal(lower)
        return parsed[lower] + (parsed[upper] - parsed[lower]) * weight

    return {
        "n": len(parsed),
        "min": _q(parsed[0]),
        "p10": _q(quantile(Decimal("0.10"))),
        "p25": _q(quantile(Decimal("0.25"))),
        "median": _q(quantile(Decimal("0.50"))),
        "p75": _q(quantile(Decimal("0.75"))),
        "p90": _q(quantile(Decimal("0.90"))),
        "max": _q(parsed[-1]),
    }


def _load_day23_manifest(client: Any, *, project: str, dataset: str) -> list[dict[str, Any]]:
    table = f"{project}.{dataset}.research_day23_query_manifest"
    sql = f"""
        SELECT query_index, query_id, query_as_of_utc, query_payload, source_input_digest
        FROM `{table}`
        WHERE experiment_id = @experiment_id AND manifest_digest = @manifest_digest
        ORDER BY query_index
    """
    from google.cloud import bigquery

    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("experiment_id", "STRING", DAY23_EXPERIMENT_ID),
            bigquery.ScalarQueryParameter("manifest_digest", "STRING", DAY23_MANIFEST_DIGEST),
        ]
    )
    rows = [_row(item) for item in client.query(sql, job_config=config).result()]
    if len(rows) != QUERY_COUNT or [int(item["query_index"]) for item in rows] != list(range(1, QUERY_COUNT + 1)):
        raise SystemExit("Day 24 requires the exact complete Day 23 1,000-query manifest.")
    queries = [_json(item["query_payload"]) for item in rows]
    if len({str(item.get("query_id") or "") for item in queries}) != QUERY_COUNT:
        raise SystemExit("Day 24 frozen query identities are not unique.")
    if freeze_query_manifest(queries)["manifest_digest"] != DAY23_MANIFEST_DIGEST:
        raise SystemExit("Day 24 query payloads do not reproduce the frozen Day 23 manifest digest.")
    for query in queries:
        if int(query["max_results"]) != MAX_RESULTS:
            raise SystemExit("Day 24 refuses max_results drift from the frozen Day 23 comparison.")
        if query["min_similarity_score"] != MIN_SIMILARITY:
            raise SystemExit("Day 24 refuses similarity-threshold tuning.")
        if query["min_component_coverage"] != MIN_COMPONENT_COVERAGE:
            raise SystemExit("Day 24 refuses component-coverage threshold tuning.")
    return queries


def _load_day23_summary(client: Any, *, project: str, dataset: str) -> dict[str, Any]:
    table = f"{project}.{dataset}.research_day23_summary"
    sql = f"""
        SELECT summary_payload
        FROM `{table}`
        WHERE experiment_id = @experiment_id AND manifest_digest = @manifest_digest
    """
    from google.cloud import bigquery

    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("experiment_id", "STRING", DAY23_EXPERIMENT_ID),
            bigquery.ScalarQueryParameter("manifest_digest", "STRING", DAY23_MANIFEST_DIGEST),
        ]
    )
    rows = list(client.query(sql, job_config=config).result())
    if len(rows) != 1:
        raise SystemExit("Day 24 requires the single accepted Day 23 summary.")
    summary = _json(rows[0]["summary_payload"])
    if Decimal(str(summary["j1"]["median_effective_n_over_raw_n"])) != DAY23_MEDIAN_INDEPENDENCE:
        raise SystemExit("Day 23 baseline independence metric drifted.")
    if Decimal(str(summary["j1"]["distinct_independent_episodes_distribution"]["median"])) != DAY23_MEDIAN_EPISODES:
        raise SystemExit("Day 23 baseline median episode count drifted.")
    if Decimal(str(summary["j1"]["no_comparable_case_rate"])) != DAY23_NCC_RATE:
        raise SystemExit("Day 23 baseline NO_COMPARABLE_CASE rate drifted.")
    return summary


def _load_candidates(client: Any, *, project: str, dataset: str) -> list[dict[str, Any]]:
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
    rows = [_row(item) for item in client.query(sql).result()]
    if not rows:
        raise SystemExit("Day 24 requires the accepted historical Gold case store.")
    snapshot = [
        {
            "case_id": str(item["case_id"]),
            "case_digest": str(item["case_digest"]),
            "input_digest": str(item["input_digest"]),
            "as_of_utc": _utc(item["as_of_utc"]).isoformat(),
            "future_available_after_utc": (
                None
                if item.get("future_available_after_utc") is None
                else _utc(item["future_available_after_utc"]).isoformat()
            ),
            "provenance_class": str(item["provenance_class"]),
            "data_quality_grade": str(item["data_quality_grade"]),
        }
        for item in rows
    ]
    if digest(snapshot) != DAY23_CANDIDATE_SNAPSHOT_DIGEST:
        raise SystemExit(
            "Historical candidate store changed since Day 23; Day 24 refuses an unregistered comparison."
        )
    return [{"row": item, "case": reconstruct_case_from_storage_row(item)} for item in rows]


def _candidate_pool(query: dict[str, Any], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    query_time = _utc(query["as_of_utc"])
    allowed = set(query["allowed_candidate_provenance"])
    versions = query["feature_versions"]
    result = []
    for record in records:
        item = record["row"]
        if _utc(item["as_of_utc"]) >= query_time:
            continue
        available = item.get("future_available_after_utc")
        if available is None or _utc(available) > query_time:
            continue
        if item.get("provenance_class") not in allowed or item.get("data_quality_grade") == "insufficient":
            continue
        if item.get("feature_definition_version") != versions["feature_definition_version"]:
            continue
        if item.get("regime_definition_version") != versions["regime_definition_version"]:
            continue
        if item.get("setup_taxonomy_version") != versions["setup_taxonomy_version"]:
            continue
        if item.get("setup_detector_version") != versions["setup_detector_version"]:
            continue
        result.append(record)
    result.sort(key=lambda record: str(record["row"]["case_id"]))
    result.sort(key=lambda record: _utc(record["row"]["as_of_utc"]), reverse=True)
    return result[:DEFAULT_CANDIDATE_LIMIT]


def _ensure_table(client: Any, bigquery: Any, not_found: type[Exception], table_id: str, schema: list[Any]) -> None:
    try:
        existing = client.get_table(table_id)
    except not_found:
        client.create_table(bigquery.Table(table_id, schema=schema))
        return
    actual = [(field.name, field.field_type, field.mode) for field in existing.schema]
    expected = [(field.name, field.field_type, field.mode) for field in schema]
    if actual != expected:
        raise RuntimeError(f"Day 24 BigQuery schema drift: {table_id}")


def _persist_result_rows(client: Any, bigquery: Any, not_found: type[Exception], table_id: str, rows: list[dict[str, Any]]) -> None:
    schema = [
        bigquery.SchemaField("experiment_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("manifest_digest", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("base_sha", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("query_index", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("query_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("payload_digest", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("result_payload", "JSON", mode="REQUIRED"),
        bigquery.SchemaField("recorded_at_utc", "TIMESTAMP", mode="REQUIRED"),
    ]
    _ensure_table(client, bigquery, not_found, table_id, schema)
    sql = f"SELECT query_id, payload_digest FROM `{table_id}` WHERE experiment_id = @experiment_id"
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("experiment_id", "STRING", EXPERIMENT_ID)]
    )
    existing = {str(item["query_id"]): str(item["payload_digest"]) for item in client.query(sql, job_config=config).result()}
    expected = {str(item["query_id"]): str(item["payload_digest"]) for item in rows}
    conflicts = [key for key in expected if key in existing and existing[key] != expected[key]]
    if conflicts:
        raise RuntimeError("Immutable Day 24 result conflict detected.")
    missing = [item for item in rows if str(item["query_id"]) not in existing]
    for start in range(0, len(missing), 100):
        errors = client.insert_rows_json(table_id, missing[start : start + 100])
        if errors:
            raise RuntimeError(f"Day 24 result persistence failed: {errors}")
    count_sql = f"SELECT COUNT(*) n, COUNT(DISTINCT query_id) ids FROM `{table_id}` WHERE experiment_id = @experiment_id"
    check = next(client.query(count_sql, job_config=config).result())
    if int(check["n"]) != QUERY_COUNT or int(check["ids"]) != QUERY_COUNT:
        raise RuntimeError("Day 24 result reconciliation failed.")


def _persist_summary(client: Any, bigquery: Any, not_found: type[Exception], table_id: str, summary: dict[str, Any], recorded_at: str) -> None:
    schema = [
        bigquery.SchemaField("experiment_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("manifest_digest", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("base_sha", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("payload_digest", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("summary_payload", "JSON", mode="REQUIRED"),
        bigquery.SchemaField("recorded_at_utc", "TIMESTAMP", mode="REQUIRED"),
    ]
    _ensure_table(client, bigquery, not_found, table_id, schema)
    sql = f"SELECT payload_digest FROM `{table_id}` WHERE experiment_id = @experiment_id AND manifest_digest = @manifest_digest"
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("experiment_id", "STRING", EXPERIMENT_ID),
            bigquery.ScalarQueryParameter("manifest_digest", "STRING", DAY23_MANIFEST_DIGEST),
        ]
    )
    existing = [str(item["payload_digest"]) for item in client.query(sql, job_config=config).result()]
    payload_digest = str(summary["summary_digest"])
    if existing and existing != [payload_digest]:
        raise RuntimeError("Immutable Day 24 summary conflict detected.")
    if not existing:
        errors = client.insert_rows_json(
            table_id,
            [
                {
                    "experiment_id": EXPERIMENT_ID,
                    "manifest_digest": DAY23_MANIFEST_DIGEST,
                    "base_sha": DAY24_BASE_SHA,
                    "payload_digest": payload_digest,
                    "summary_payload": summary,
                    "recorded_at_utc": recorded_at,
                }
            ],
        )
        if errors:
            raise RuntimeError(f"Day 24 summary persistence failed: {errors}")


def main() -> int:
    args = _parser().parse_args()
    if not args.project:
        raise SystemExit("AIDY_GCP_PROJECT_ID or --project is required.")

    from google.api_core.exceptions import NotFound
    from google.cloud import bigquery
    from google.oauth2 import service_account

    raw_credentials = os.environ.get("AIDY_GCP_SERVICE_ACCOUNT_JSON")
    if not raw_credentials:
        raise SystemExit("AIDY_GCP_SERVICE_ACCOUNT_JSON is required.")
    credentials = service_account.Credentials.from_service_account_info(json.loads(raw_credentials))
    client = bigquery.Client(project=args.project, credentials=credentials, location=args.location)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    recorded_at = datetime.now(UTC).isoformat()

    queries = _load_day23_manifest(client, project=args.project, dataset=args.dataset)
    baseline = _load_day23_summary(client, project=args.project, dataset=args.dataset)
    records = _load_candidates(client, project=args.project, dataset=args.dataset)
    results: list[dict[str, Any]] = []
    persisted: list[dict[str, Any]] = []
    relaxation_counts: Counter[str] = Counter()
    grade_counts: Counter[str] = Counter()

    for index, query in enumerate(queries, start=1):
        pool = _candidate_pool(query, records)
        cases = [item["case"] for item in pool]
        retrieval = retrieve_analogues_v2(query=query, candidate_cases=cases)
        reversed_result = retrieve_analogues_v2(query=query, candidate_cases=list(reversed(cases)))
        if retrieval["retrieval_digest"] != reversed_result["retrieval_digest"]:
            raise SystemExit(f"Day 24 retrieval is not reproducible at frozen query {index}.")
        if retrieval["outcome_values_used_for_selection"] is not False:
            raise SystemExit("Day 24 detected outcome-value leakage into selection.")
        report = build_evidence_report_v2(retrieval=retrieval)
        if report["outcome_values_used_for_dataset_grade"] is not False:
            raise SystemExit("Day 24 detected outcome-value leakage into evidence grading.")
        independence = retrieval["independence"]
        if int(independence["grading_effective_n"]) != int(retrieval["returned_match_count"]):
            raise SystemExit("Day 24 effective-N accounting mismatch.")
        for item in retrieval["gate_relaxations"]:
            relaxation_counts[str(item["name"])] += 1
        grade_counts[str(report["dataset_grade"]["grade"])] += 1
        compact = {
            "query_index": index,
            "query_id": query["query_id"],
            "query_as_of_utc": query["as_of_utc"],
            "candidate_raw_n": len(pool),
            "evidence_state": retrieval["evidence_state"],
            "no_comparable_reason": retrieval["no_comparable_reason"],
            "eligible_candidate_n": retrieval["eligible_candidate_count"],
            "hard_gate_pass_n": retrieval["hard_gate_pass_count"],
            "sufficient_match_n": retrieval["sufficient_match_count"],
            "pre_dedup_raw_n": independence["pre_dedup_raw_n"],
            "pre_dedup_kish_effective_n": independence["pre_dedup_kish_effective_n"],
            "pre_dedup_effective_n_over_raw_n": independence["pre_dedup_effective_n_over_raw_n"],
            "distinct_independent_episodes": independence["distinct_independent_episodes"],
            "grading_effective_n": independence["grading_effective_n"],
            "temporal_span_hours": independence["temporal_span_hours"],
            "distinct_months": independence["distinct_months"],
            "gate_relaxations": retrieval["gate_relaxations"],
            "exclusion_counts": retrieval["exclusion_counts"],
            "selected_episode_ids": [item["episode_id"] for item in retrieval["matches"]],
            "selected_case_ids": [item["case_id"] for item in retrieval["matches"]],
            "selection_digest": retrieval["selection_digest"],
            "retrieval_digest": retrieval["retrieval_digest"],
            "dataset_grade": report["dataset_grade"]["grade"],
            "dataset_grade_digest": report["dataset_grade"]["grade_digest"],
            "evidence_report_digest": report["report_digest"],
        }
        compact["result_digest"] = digest(compact)
        results.append(compact)
        persisted.append(
            {
                "experiment_id": EXPERIMENT_ID,
                "manifest_digest": DAY23_MANIFEST_DIGEST,
                "base_sha": DAY24_BASE_SHA,
                "query_index": index,
                "query_id": query["query_id"],
                "payload_digest": compact["result_digest"],
                "result_payload": compact,
                "recorded_at_utc": recorded_at,
            }
        )

    ncc = [item for item in results if item["evidence_state"] == "no_comparable_case"]
    ncc_rate = Decimal(len(ncc)) / Decimal(QUERY_COUNT)
    coverage_classification = (
        "coverage_limited"
        if ncc_rate > Decimal("0.75")
        else "low_coverage_accepted"
        if ncc_rate > Decimal("0.50")
        else "not_coverage_limited"
    )
    ratios = [item["pre_dedup_effective_n_over_raw_n"] for item in results if item["pre_dedup_effective_n_over_raw_n"] is not None]
    episodes = [item["distinct_independent_episodes"] for item in results if int(item["pre_dedup_raw_n"]) > 0]
    grading_ns = [item["grading_effective_n"] for item in results]
    summary = {
        "ok": True,
        "experiment_id": EXPERIMENT_ID,
        "base_sha": DAY24_BASE_SHA,
        "frozen_manifest_digest": DAY23_MANIFEST_DIGEST,
        "frozen_query_count": QUERY_COUNT,
        "query_removed_or_replaced": False,
        "thresholds_retained": {
            "min_similarity_score": MIN_SIMILARITY,
            "min_component_coverage": MIN_COMPONENT_COVERAGE,
        },
        "retrieval_version": ANALOGUE_RETRIEVAL_VERSION_V2,
        "similarity_feature_version": SIMILARITY_FEATURE_VERSION_V2,
        "similarity_manifest": similarity_manifest_v2(),
        "evidence_grade_manifest": evidence_grade_manifest_v2(),
        "embargo_minutes": EMBARGO_MINUTES,
        "episode_deduplication_enabled": True,
        "grading_uses_effective_independent_n": True,
        "outcome_values_used_for_selection": False,
        "outcome_values_used_for_grading": False,
        "candidate_store_row_count": len(records),
        "candidate_store_snapshot_digest": DAY23_CANDIDATE_SNAPSHOT_DIGEST,
        "candidate_raw_n_distribution": _distribution([item["candidate_raw_n"] for item in results]),
        "pre_dedup_raw_n_distribution": _distribution([item["pre_dedup_raw_n"] for item in results]),
        "pre_dedup_effective_n_over_raw_n_distribution": _distribution(ratios),
        "distinct_independent_episodes_distribution": _distribution(episodes),
        "grading_effective_n_distribution": _distribution(grading_ns),
        "no_comparable_case_count": len(ncc),
        "no_comparable_case_rate": _q(ncc_rate),
        "coverage_classification": coverage_classification,
        "gate_relaxation_query_counts": dict(sorted(relaxation_counts.items())),
        "dataset_grade_counts": dict(sorted(grade_counts.items())),
        "retrieval_reproducible_under_candidate_reordering": True,
        "day23_baseline": {
            "median_effective_n_over_raw_n": str(baseline["j1"]["median_effective_n_over_raw_n"]),
            "median_distinct_independent_episodes": str(baseline["j1"]["distinct_independent_episodes_distribution"]["median"]),
            "no_comparable_case_rate": str(baseline["j1"]["no_comparable_case_rate"]),
        },
        "recovery_branch_invoked": False,
        "recovery_thresholds_used_as_acceptance_gate": False,
        "bigquery_evidence": {
            "result_table": RESULT_TABLE,
            "summary_table": SUMMARY_TABLE,
            "result_rows": QUERY_COUNT,
        },
        "security": {"secret_values_emitted": False},
    }
    summary["summary_digest"] = digest(summary)
    _write_jsonl(output / "retrieval_results.jsonl", results)
    _write_json(output / "summary.json", summary)
    _write_json(
        output / "frozen_manifest_reference.json",
        {
            "day23_experiment_id": DAY23_EXPERIMENT_ID,
            "manifest_digest": DAY23_MANIFEST_DIGEST,
            "candidate_store_snapshot_digest": DAY23_CANDIDATE_SNAPSHOT_DIGEST,
            "query_count": QUERY_COUNT,
        },
    )

    result_table = f"{args.project}.{args.dataset}.{RESULT_TABLE}"
    summary_table = f"{args.project}.{args.dataset}.{SUMMARY_TABLE}"
    _persist_result_rows(client, bigquery, NotFound, result_table, persisted)
    _persist_summary(client, bigquery, NotFound, summary_table, summary, recorded_at)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
