from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from aidy.analogue_retrieval import DEFAULT_CANDIDATE_LIMIT, reconstruct_case_from_storage_row
from aidy.analogue_retrieval_v2 import (
    ANALOGUE_RETRIEVAL_VERSION_V2,
    EMBARGO_MINUTES,
    SIMILARITY_FEATURE_VERSION_V2,
    retrieve_analogues_v2,
    similarity_manifest_v2,
)
from aidy.day23_research import canonical_json, digest, freeze_query_manifest
from aidy.evidence_grading_v2 import build_evidence_report_v2, evidence_grade_manifest_v2

BASE_SHA = "9f0803040e49d58fe082a7de863d8647f7470b84"
DAY23_EXPERIMENT = "day23-j1-j16-baseline-20260821-v1"
MANIFEST_DIGEST = "119d8c2a1a11cba44d8195fff81be640f7b9c084d0d7b8c28a61dedfa64e5ac5"
CANDIDATE_DIGEST = "bd3c81b54ec05b2150e6e6ecbdffbc3c1e4f943c6a23c9a8ee4977c1dc1c3a88"
EXPERIMENT = "day24-independent-episode-retrieval-20260822-v1"
QUERY_COUNT = 1000
MAX_RESULTS = 200
MIN_SIMILARITY = "0.720000"
MIN_COVERAGE = "0.650000"
RESULT_TABLE = "research_day24_retrieval_results"
SUMMARY_TABLE = "research_day24_summary"
DEFAULT_DATASET = "aidy_analytics_test"
DEFAULT_LOCATION = "EU"


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Day 24 independent-episode acceptance")
    parser.add_argument("--project", default=os.environ.get("AIDY_GCP_PROJECT_ID"))
    parser.add_argument("--dataset", default=os.environ.get("AIDY_BIGQUERY_DATASET", DEFAULT_DATASET))
    parser.add_argument("--location", default=os.environ.get("AIDY_BIGQUERY_LOCATION", DEFAULT_LOCATION))
    parser.add_argument("--output-dir", default="day24_artifacts")
    return parser.parse_args()


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Day 24 timestamps must be timezone-aware")
    return parsed.astimezone(UTC)


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    decoded = json.loads(value) if isinstance(value, str) else None
    if not isinstance(decoded, dict):
        raise TypeError("Expected JSON object")
    return decoded


def _row(value: Any) -> dict[str, Any]:
    return dict(value.items())


def _q(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def _distribution(values: list[Any]) -> dict[str, Any]:
    data = sorted(Decimal(str(value)) for value in values if value is not None)
    if not data:
        return {key: None if key != "n" else 0 for key in ("n", "min", "p10", "p25", "median", "p75", "p90", "max")}

    def quantile(p: Decimal) -> Decimal:
        if len(data) == 1:
            return data[0]
        pos = p * Decimal(len(data) - 1)
        lo = int(pos)
        hi = min(lo + 1, len(data) - 1)
        return data[lo] + (data[hi] - data[lo]) * (pos - Decimal(lo))

    return {
        "n": len(data),
        "min": _q(data[0]),
        "p10": _q(quantile(Decimal("0.10"))),
        "p25": _q(quantile(Decimal("0.25"))),
        "median": _q(quantile(Decimal("0.50"))),
        "p75": _q(quantile(Decimal("0.75"))),
        "p90": _q(quantile(Decimal("0.90"))),
        "max": _q(data[-1]),
    }


def _query_config(bigquery: Any, pairs: list[tuple[str, str, Any]]) -> Any:
    return bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter(name, kind, value) for name, kind, value in pairs]
    )


def _load_queries(client: Any, bigquery: Any, project: str, dataset: str) -> list[dict[str, Any]]:
    table = f"{project}.{dataset}.research_day23_query_manifest"
    config = _query_config(
        bigquery,
        [("experiment", "STRING", DAY23_EXPERIMENT), ("manifest", "STRING", MANIFEST_DIGEST)],
    )
    rows = list(
        client.query(
            f"""SELECT query_index, query_payload FROM `{table}`
                WHERE experiment_id=@experiment AND manifest_digest=@manifest
                ORDER BY query_index""",
            job_config=config,
        ).result()
    )
    if len(rows) != QUERY_COUNT:
        raise SystemExit(f"Expected {QUERY_COUNT} frozen queries, found {len(rows)}")
    queries = [_object(item["query_payload"]) for item in rows]
    if freeze_query_manifest(queries)["manifest_digest"] != MANIFEST_DIGEST:
        raise SystemExit("Frozen Day 23 manifest digest does not reproduce")
    for query in queries:
        if int(query["max_results"]) != MAX_RESULTS:
            raise SystemExit("Frozen max_results drifted")
        if query["min_similarity_score"] != MIN_SIMILARITY:
            raise SystemExit("Similarity threshold drifted")
        if query["min_component_coverage"] != MIN_COVERAGE:
            raise SystemExit("Component coverage threshold drifted")
    return queries


def _load_baseline(client: Any, bigquery: Any, project: str, dataset: str) -> dict[str, Any]:
    table = f"{project}.{dataset}.research_day23_summary"
    config = _query_config(
        bigquery,
        [("experiment", "STRING", DAY23_EXPERIMENT), ("manifest", "STRING", MANIFEST_DIGEST)],
    )
    rows = list(
        client.query(
            f"""SELECT summary_payload FROM `{table}`
                WHERE experiment_id=@experiment AND manifest_digest=@manifest""",
            job_config=config,
        ).result()
    )
    if len(rows) != 1:
        raise SystemExit("Accepted Day 23 baseline summary is missing or duplicated")
    baseline = _object(rows[0]["summary_payload"])
    if str(baseline["j1"]["median_effective_n_over_raw_n"]) != "0.666667":
        raise SystemExit("Day 23 median independence baseline drifted")
    if str(baseline["j1"]["no_comparable_case_rate"]) != "0.244000":
        raise SystemExit("Day 23 NO_COMPARABLE_CASE baseline drifted")
    return baseline


def _load_candidates(client: Any, project: str, dataset: str) -> list[dict[str, Any]]:
    table = f"{project}.{dataset}.research_gold_cases"
    sql = f"""SELECT case_digest, case_version, case_id, symbol, as_of_utc,
                     provenance_class, input_digest, feature_definition_version,
                     regime_definition_version, setup_taxonomy_version,
                     setup_detector_version, data_quality_grade,
                     future_available_after_utc, input_boundary, future_evaluation
              FROM `{table}` WHERE symbol='XAUUSD' ORDER BY as_of_utc, case_id"""
    rows = [_row(item) for item in client.query(sql).result()]
    snapshot = [
        {
            "case_id": str(item["case_id"]),
            "case_digest": str(item["case_digest"]),
            "input_digest": str(item["input_digest"]),
            "as_of_utc": _utc(item["as_of_utc"]).isoformat(),
            "future_available_after_utc": (
                None if item.get("future_available_after_utc") is None else _utc(item["future_available_after_utc"]).isoformat()
            ),
            "provenance_class": str(item["provenance_class"]),
            "data_quality_grade": str(item["data_quality_grade"]),
        }
        for item in rows
    ]
    if digest(snapshot) != CANDIDATE_DIGEST:
        raise SystemExit("Candidate case store changed since the Day 23 frozen baseline")
    return [{"row": item, "case": reconstruct_case_from_storage_row(item)} for item in rows]


def _pool(query: dict[str, Any], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    query_time = _utc(query["as_of_utc"])
    allowed = set(query["allowed_candidate_provenance"])
    versions = query["feature_versions"]
    selected: list[dict[str, Any]] = []
    for record in records:
        item = record["row"]
        available = item.get("future_available_after_utc")
        if _utc(item["as_of_utc"]) >= query_time or available is None or _utc(available) > query_time:
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
        selected.append(record)
    selected.sort(key=lambda item: str(item["row"]["case_id"]))
    selected.sort(key=lambda item: _utc(item["row"]["as_of_utc"]), reverse=True)
    return selected[:DEFAULT_CANDIDATE_LIMIT]


def _ensure_table(client: Any, bigquery: Any, not_found: type[Exception], table_id: str, schema: list[Any]) -> None:
    try:
        table = client.get_table(table_id)
    except not_found:
        client.create_table(bigquery.Table(table_id, schema=schema))
        return
    actual = [(field.name, field.field_type, field.mode) for field in table.schema]
    expected = [(field.name, field.field_type, field.mode) for field in schema]
    if actual != expected:
        raise RuntimeError(f"BigQuery schema drift for {table_id}")


def _persist_results(client: Any, bigquery: Any, not_found: type[Exception], table_id: str, rows: list[dict[str, Any]]) -> None:
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
    config = _query_config(bigquery, [("experiment", "STRING", EXPERIMENT)])
    existing = {
        str(item["query_id"]): str(item["payload_digest"])
        for item in client.query(
            f"SELECT query_id,payload_digest FROM `{table_id}` WHERE experiment_id=@experiment",
            job_config=config,
        ).result()
    }
    for row in rows:
        key = str(row["query_id"])
        if key in existing and existing[key] != row["payload_digest"]:
            raise RuntimeError("Immutable Day 24 result conflict")
    missing = [row for row in rows if str(row["query_id"]) not in existing]
    for offset in range(0, len(missing), 100):
        errors = client.insert_rows_json(table_id, missing[offset : offset + 100])
        if errors:
            raise RuntimeError(f"Day 24 BigQuery result insert failed: {errors}")
    check = next(
        client.query(
            f"SELECT COUNT(*) n,COUNT(DISTINCT query_id) ids FROM `{table_id}` WHERE experiment_id=@experiment",
            job_config=config,
        ).result()
    )
    if int(check["n"]) != QUERY_COUNT or int(check["ids"]) != QUERY_COUNT:
        raise RuntimeError("Day 24 result reconciliation failed")


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
    config = _query_config(
        bigquery,
        [("experiment", "STRING", EXPERIMENT), ("manifest", "STRING", MANIFEST_DIGEST)],
    )
    existing = [
        str(item["payload_digest"])
        for item in client.query(
            f"""SELECT payload_digest FROM `{table_id}`
                WHERE experiment_id=@experiment AND manifest_digest=@manifest""",
            job_config=config,
        ).result()
    ]
    if existing and existing != [summary["summary_digest"]]:
        raise RuntimeError("Immutable Day 24 summary conflict")
    if not existing:
        errors = client.insert_rows_json(
            table_id,
            [{
                "experiment_id": EXPERIMENT,
                "manifest_digest": MANIFEST_DIGEST,
                "base_sha": BASE_SHA,
                "payload_digest": summary["summary_digest"],
                "summary_payload": summary,
                "recorded_at_utc": recorded_at,
            }],
        )
        if errors:
            raise RuntimeError(f"Day 24 BigQuery summary insert failed: {errors}")


def main() -> int:
    args = _args()
    if not args.project:
        raise SystemExit("AIDY_GCP_PROJECT_ID or --project is required")
    from google.api_core.exceptions import NotFound
    from google.cloud import bigquery
    from google.oauth2 import service_account

    secret = os.environ.get("AIDY_GCP_SERVICE_ACCOUNT_JSON")
    if not secret:
        raise SystemExit("AIDY_GCP_SERVICE_ACCOUNT_JSON is required")
    credentials = service_account.Credentials.from_service_account_info(json.loads(secret))
    client = bigquery.Client(project=args.project, credentials=credentials, location=args.location)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    recorded_at = datetime.now(UTC).isoformat()

    queries = _load_queries(client, bigquery, args.project, args.dataset)
    baseline = _load_baseline(client, bigquery, args.project, args.dataset)
    records = _load_candidates(client, args.project, args.dataset)
    results: list[dict[str, Any]] = []
    bq_rows: list[dict[str, Any]] = []
    relaxations: Counter[str] = Counter()
    grades: Counter[str] = Counter()

    for index, query in enumerate(queries, start=1):
        pool = _pool(query, records)
        cases = [item["case"] for item in pool]
        retrieval = retrieve_analogues_v2(query=query, candidate_cases=cases)
        reverse = retrieve_analogues_v2(query=query, candidate_cases=list(reversed(cases)))
        if retrieval["retrieval_digest"] != reverse["retrieval_digest"]:
            raise SystemExit(f"Candidate-order reproducibility failed at query {index}")
        if retrieval["outcome_values_used_for_selection"] is not False:
            raise SystemExit("Outcome value leaked into retrieval selection")
        report = build_evidence_report_v2(retrieval=retrieval)
        if report["outcome_values_used_for_dataset_grade"] is not False:
            raise SystemExit("Outcome value leaked into evidence grading")
        independence = retrieval["independence"]
        if int(independence["grading_effective_n"]) != int(retrieval["returned_match_count"]):
            raise SystemExit("Effective independent N mismatch")
        for relaxation in retrieval["gate_relaxations"]:
            relaxations[str(relaxation["name"])] += 1
        grades[str(report["dataset_grade"]["grade"])] += 1
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
            "selected_case_ids": [item["case_id"] for item in retrieval["matches"]],
            "selected_episode_ids": [item["episode_id"] for item in retrieval["matches"]],
            "selection_digest": retrieval["selection_digest"],
            "retrieval_digest": retrieval["retrieval_digest"],
            "dataset_grade": report["dataset_grade"]["grade"],
            "dataset_grade_digest": report["dataset_grade"]["grade_digest"],
            "evidence_report_digest": report["report_digest"],
        }
        compact["result_digest"] = digest(compact)
        results.append(compact)
        bq_rows.append({
            "experiment_id": EXPERIMENT,
            "manifest_digest": MANIFEST_DIGEST,
            "base_sha": BASE_SHA,
            "query_index": index,
            "query_id": query["query_id"],
            "payload_digest": compact["result_digest"],
            "result_payload": compact,
            "recorded_at_utc": recorded_at,
        })

    ncc = sum(item["evidence_state"] == "no_comparable_case" for item in results)
    ncc_rate = Decimal(ncc) / Decimal(QUERY_COUNT)
    coverage = (
        "coverage_limited" if ncc_rate > Decimal("0.75")
        else "low_coverage_accepted" if ncc_rate > Decimal("0.50")
        else "not_coverage_limited"
    )
    comparable = [item for item in results if int(item["pre_dedup_raw_n"]) > 0]
    summary = {
        "ok": True,
        "experiment_id": EXPERIMENT,
        "base_sha": BASE_SHA,
        "frozen_manifest_digest": MANIFEST_DIGEST,
        "frozen_query_count": QUERY_COUNT,
        "query_removed_or_replaced": False,
        "thresholds_retained": {
            "min_similarity_score": MIN_SIMILARITY,
            "min_component_coverage": MIN_COVERAGE,
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
        "candidate_store_snapshot_digest": CANDIDATE_DIGEST,
        "candidate_raw_n_distribution": _distribution([item["candidate_raw_n"] for item in results]),
        "pre_dedup_raw_n_distribution": _distribution([item["pre_dedup_raw_n"] for item in results]),
        "pre_dedup_effective_n_over_raw_n_distribution": _distribution(
            [item["pre_dedup_effective_n_over_raw_n"] for item in comparable]
        ),
        "distinct_independent_episodes_distribution": _distribution(
            [item["distinct_independent_episodes"] for item in comparable]
        ),
        "grading_effective_n_distribution": _distribution([item["grading_effective_n"] for item in results]),
        "no_comparable_case_count": ncc,
        "no_comparable_case_rate": _q(ncc_rate),
        "coverage_classification": coverage,
        "gate_relaxation_query_counts": dict(sorted(relaxations.items())),
        "dataset_grade_counts": dict(sorted(grades.items())),
        "retrieval_reproducible_under_candidate_reordering": True,
        "day23_baseline": {
            "median_effective_n_over_raw_n": baseline["j1"]["median_effective_n_over_raw_n"],
            "median_distinct_independent_episodes": baseline["j1"]["distinct_independent_episodes_distribution"]["median"],
            "no_comparable_case_rate": baseline["j1"]["no_comparable_case_rate"],
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

    with (output / "retrieval_results.jsonl").open("w", encoding="utf-8") as handle:
        for item in results:
            handle.write(canonical_json(item) + "\n")
    (output / "summary.json").write_text(
        json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    (output / "frozen_manifest_reference.json").write_text(
        json.dumps({
            "day23_experiment_id": DAY23_EXPERIMENT,
            "manifest_digest": MANIFEST_DIGEST,
            "candidate_store_snapshot_digest": CANDIDATE_DIGEST,
            "query_count": QUERY_COUNT,
        }, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    _persist_results(
        client,
        bigquery,
        NotFound,
        f"{args.project}.{args.dataset}.{RESULT_TABLE}",
        bq_rows,
    )
    _persist_summary(
        client,
        bigquery,
        NotFound,
        f"{args.project}.{args.dataset}.{SUMMARY_TABLE}",
        summary,
        recorded_at,
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
