from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from aidy.analogue_retrieval import reconstruct_case_from_storage_row
from aidy.analogue_retrieval_v2 import retrieve_analogues_v2, verify_retrieval_digest_v2
from aidy.analogue_retrieval_v3 import enrich_query_with_market_structure
from aidy.day23_research import canonical_json, digest, freeze_query_manifest
from aidy.historical_case_context_v2 import enrich_historical_case_with_market_structure
from aidy.j5_epoch_effect import J5_VERSION, run_j5_epoch_effect, verify_j5_digest
from aidy.market_structure_context import (
    MARKET_STRUCTURE_CONTEXT_VERSION,
    market_structure_epoch_at,
)

BASE_SHA = "9c2d0e33177c40bbc123f380bce68ffe2430f504"
DAY23_EXPERIMENT = "day23-j1-j16-baseline-20260821-v1"
MANIFEST_DIGEST = "119d8c2a1a11cba44d8195fff81be640f7b9c084d0d7b8c28a61dedfa64e5ac5"
CANDIDATE_DIGEST = "bd3c81b54ec05b2150e6e6ecbdffbc3c1e4f943c6a23c9a8ee4977c1dc1c3a88"
EXPERIMENT = "day25-market-structure-20260823-v1"
QUERY_COUNT = 1000
CANDIDATE_COUNT = 36
RESULT_TABLE = "research_day25_retrieval_results"
SUMMARY_TABLE = "research_day25_summary"
DEFAULT_DATASET = "aidy_analytics_test"
DEFAULT_LOCATION = "EU"


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Day 25 market-structure acceptance")
    parser.add_argument("--project", default=os.environ.get("AIDY_GCP_PROJECT_ID"))
    parser.add_argument("--dataset", default=os.environ.get("AIDY_BIGQUERY_DATASET", DEFAULT_DATASET))
    parser.add_argument("--location", default=os.environ.get("AIDY_BIGQUERY_LOCATION", DEFAULT_LOCATION))
    parser.add_argument("--output-dir", default="day25_artifacts")
    return parser.parse_args()


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Day 25 timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    decoded = json.loads(value) if isinstance(value, str) else None
    if not isinstance(decoded, dict):
        raise TypeError("Expected JSON object.")
    return decoded


def _row(value: Any) -> dict[str, Any]:
    return dict(value.items())


def _q(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def _query_config(bigquery: Any, pairs: list[tuple[str, str, Any]]) -> Any:
    return bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(name, kind, value) for name, kind, value in pairs
        ]
    )


def _load_queries(
    client: Any,
    bigquery: Any,
    project: str,
    dataset: str,
) -> list[dict[str, Any]]:
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
        raise SystemExit("Frozen Day 23 query manifest digest does not reproduce.")
    return queries


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
                None
                if item.get("future_available_after_utc") is None
                else _utc(item["future_available_after_utc"]).isoformat()
            ),
            "provenance_class": str(item["provenance_class"]),
            "data_quality_grade": str(item["data_quality_grade"]),
        }
        for item in rows
    ]
    if digest(snapshot) != CANDIDATE_DIGEST:
        raise SystemExit("Candidate case store changed since the frozen Day 23/24 snapshot.")
    if len(rows) != CANDIDATE_COUNT:
        raise SystemExit(f"Expected {CANDIDATE_COUNT} candidate cases, found {len(rows)}")
    return [reconstruct_case_from_storage_row(item) for item in rows]


def _ensure_table(
    client: Any,
    bigquery: Any,
    not_found: type[Exception],
    table_id: str,
    schema: list[Any],
) -> None:
    try:
        table = client.get_table(table_id)
    except not_found:
        client.create_table(bigquery.Table(table_id, schema=schema))
        return
    actual = [(field.name, field.field_type, field.mode) for field in table.schema]
    expected = [(field.name, field.field_type, field.mode) for field in schema]
    if actual != expected:
        raise RuntimeError(f"BigQuery schema drift for {table_id}")


def _persist_rows(
    client: Any,
    bigquery: Any,
    not_found: type[Exception],
    table_id: str,
    rows: list[dict[str, Any]],
) -> None:
    schema = [
        bigquery.SchemaField("experiment_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("manifest_digest", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("base_sha", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("query_index", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("source_query_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("payload_digest", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("result_payload_json", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("recorded_at_utc", "TIMESTAMP", mode="REQUIRED"),
    ]
    _ensure_table(client, bigquery, not_found, table_id, schema)
    config = _query_config(bigquery, [("experiment", "STRING", EXPERIMENT)])
    existing = {
        str(item["source_query_id"]): str(item["payload_digest"])
        for item in client.query(
            f"""SELECT source_query_id,payload_digest FROM `{table_id}`
                WHERE experiment_id=@experiment""",
            job_config=config,
        ).result()
    }
    missing: list[dict[str, Any]] = []
    for row in rows:
        key = str(row["source_query_id"])
        if key in existing and existing[key] != row["payload_digest"]:
            raise RuntimeError("Immutable Day 25 result conflict.")
        if key not in existing:
            missing.append(row)
    if missing:
        job = client.load_table_from_json(
            missing,
            table_id,
            job_config=bigquery.LoadJobConfig(
                schema=schema,
                write_disposition="WRITE_APPEND",
            ),
        )
        job.result()
    check = next(
        client.query(
            f"""SELECT COUNT(*) n,COUNT(DISTINCT source_query_id) ids
                FROM `{table_id}` WHERE experiment_id=@experiment""",
            job_config=config,
        ).result()
    )
    if int(check["n"]) != QUERY_COUNT or int(check["ids"]) != QUERY_COUNT:
        raise RuntimeError("Day 25 retrieval-result reconciliation failed.")


def _persist_summary(
    client: Any,
    bigquery: Any,
    not_found: type[Exception],
    table_id: str,
    summary: dict[str, Any],
    recorded_at: str,
) -> None:
    schema = [
        bigquery.SchemaField("experiment_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("manifest_digest", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("base_sha", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("payload_digest", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("summary_payload_json", "STRING", mode="REQUIRED"),
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
        raise RuntimeError("Immutable Day 25 summary conflict.")
    if not existing:
        row = {
            "experiment_id": EXPERIMENT,
            "manifest_digest": MANIFEST_DIGEST,
            "base_sha": BASE_SHA,
            "payload_digest": summary["summary_digest"],
            "summary_payload_json": canonical_json(summary),
            "recorded_at_utc": recorded_at,
        }
        job = client.load_table_from_json(
            [row],
            table_id,
            job_config=bigquery.LoadJobConfig(
                schema=schema,
                write_disposition="WRITE_APPEND",
            ),
        )
        job.result()


def main() -> int:
    args = _args()
    if not args.project:
        raise SystemExit("AIDY_GCP_PROJECT_ID or --project is required.")

    from google.api_core.exceptions import NotFound
    from google.cloud import bigquery
    from google.oauth2 import service_account

    secret = os.environ.get("AIDY_GCP_SERVICE_ACCOUNT_JSON")
    if not secret:
        raise SystemExit("AIDY_GCP_SERVICE_ACCOUNT_JSON is required.")
    credentials = service_account.Credentials.from_service_account_info(json.loads(secret))
    client = bigquery.Client(
        project=args.project,
        credentials=credentials,
        location=args.location,
    )
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    recorded_at = datetime.now(UTC).isoformat()

    queries = _load_queries(client, bigquery, args.project, args.dataset)
    cases = _load_candidates(client, args.project, args.dataset)
    j5 = run_j5_epoch_effect(cases)
    if not verify_j5_digest(j5) or j5["j5_version"] != J5_VERSION:
        raise RuntimeError("J5 result failed its frozen digest/version contract.")

    # The 36 source cases are immutable for this experiment, so enrich them once.
    # Rebuilding the same derived cases inside each of 1,000 queries adds compute
    # without adding evidence or a new determinism check.
    prepared_cases = [enrich_historical_case_with_market_structure(case=case) for case in cases]

    result_rows: list[dict[str, Any]] = []
    artifact_rows: list[dict[str, Any]] = []
    query_epochs: Counter[str] = Counter()
    evidence_states: Counter[str] = Counter()
    exclusion_counts: Counter[str] = Counter()
    known_epoch_relaxation_count = 0
    reproducible_count = 0

    for index, source_query in enumerate(queries, start=1):
        query = enrich_query_with_market_structure(source_query)
        retrieval = retrieve_analogues_v2(query=query, candidate_cases=prepared_cases)
        reversed_retrieval = retrieve_analogues_v2(
            query=query,
            candidate_cases=list(reversed(prepared_cases)),
        )
        if not verify_retrieval_digest_v2(retrieval):
            raise RuntimeError(f"Day 25 delegated retrieval digest failed at query {index}.")
        if retrieval["retrieval_digest"] != reversed_retrieval["retrieval_digest"]:
            raise RuntimeError(f"Candidate-order determinism failed at query {index}.")
        reproducible_count += 1

        epoch = str(query["analogue_features"]["market_structure_epoch"])
        query_epochs[epoch] += 1
        evidence_states[str(retrieval["evidence_state"])] += 1
        exclusion_counts.update(retrieval["exclusion_counts"])
        forbidden = "market_structure_epoch_unavailable_pre_day25"
        if any(item.get("name") == forbidden for item in retrieval["gate_relaxations"]):
            known_epoch_relaxation_count += 1

        payload = {
            "source_query_id": source_query["query_id"],
            "enriched_query_id": query["query_id"],
            "query_market_structure_epoch": epoch,
            "retrieval": retrieval,
        }
        payload_digest = digest(payload)
        source_query_id = str(source_query["query_id"])
        result_rows.append(
            {
                "experiment_id": EXPERIMENT,
                "manifest_digest": MANIFEST_DIGEST,
                "base_sha": BASE_SHA,
                "query_index": index,
                "source_query_id": source_query_id,
                "payload_digest": payload_digest,
                "result_payload_json": canonical_json(payload),
                "recorded_at_utc": recorded_at,
            }
        )
        artifact_rows.append(
            {
                "query_index": index,
                "source_query_id": source_query_id,
                "enriched_query_id": query["query_id"],
                "payload_digest": payload_digest,
                "query_market_structure_epoch": epoch,
                "evidence_state": retrieval["evidence_state"],
                "returned_match_count": retrieval["returned_match_count"],
                "exclusion_counts": retrieval["exclusion_counts"],
                "gate_relaxations": retrieval["gate_relaxations"],
            }
        )

    candidate_epochs = Counter(
        str(market_structure_epoch_at(str(case["as_of_utc"]))["market_structure_epoch"])
        for case in cases
    )
    no_comparable = int(evidence_states["no_comparable_case"])
    summary: dict[str, Any] = {
        "ok": True,
        "experiment_id": EXPERIMENT,
        "base_sha": BASE_SHA,
        "market_structure_context_version": MARKET_STRUCTURE_CONTEXT_VERSION,
        "frozen_manifest_digest": MANIFEST_DIGEST,
        "frozen_query_count": len(queries),
        "query_removed_or_replaced": False,
        "candidate_store_snapshot_digest": CANDIDATE_DIGEST,
        "candidate_case_count": len(cases),
        "prepared_candidate_case_count": len(prepared_cases),
        "candidate_enrichment_reused_across_queries": True,
        "query_epoch_counts": dict(sorted(query_epochs.items())),
        "candidate_epoch_counts": dict(sorted(candidate_epochs.items())),
        "retrieval_evidence_states": dict(sorted(evidence_states.items())),
        "no_comparable_case_count": no_comparable,
        "no_comparable_case_rate": _q(Decimal(no_comparable) / Decimal(QUERY_COUNT)),
        "aggregate_exclusion_counts": dict(sorted(exclusion_counts.items())),
        "pre_day25_epoch_relaxation_query_count": known_epoch_relaxation_count,
        "candidate_order_reproducible_query_count": reproducible_count,
        "day24_gates_unchanged": {
            "min_similarity_score": "0.72",
            "min_component_coverage": "0.65",
            "embargo_minutes": 240,
            "episode_horizon_minutes": 240,
        },
        "outcome_values_used_for_epoch_assignment": False,
        "outcome_values_used_for_retrieval_selection": False,
        "j5": j5,
        "bigquery_evidence": {
            "result_table": RESULT_TABLE,
            "summary_table": SUMMARY_TABLE,
            "result_rows": len(result_rows),
        },
    }
    summary["summary_digest"] = digest(summary)

    result_table = f"{args.project}.{args.dataset}.{RESULT_TABLE}"
    summary_table = f"{args.project}.{args.dataset}.{SUMMARY_TABLE}"
    _persist_rows(client, bigquery, NotFound, result_table, result_rows)
    _persist_summary(client, bigquery, NotFound, summary_table, summary, recorded_at)

    with (output / "retrieval_results.jsonl").open("w", encoding="utf-8") as handle:
        for row in artifact_rows:
            handle.write(canonical_json(row) + "\n")
    (output / "j5.json").write_text(canonical_json(j5) + "\n", encoding="utf-8")
    (output / "summary.json").write_text(canonical_json(summary) + "\n", encoding="utf-8")
    (output / "frozen_manifest_reference.json").write_text(
        canonical_json(
            {
                "day23_experiment": DAY23_EXPERIMENT,
                "manifest_digest": MANIFEST_DIGEST,
                "candidate_store_snapshot_digest": CANDIDATE_DIGEST,
                "query_count": QUERY_COUNT,
                "candidate_count": CANDIDATE_COUNT,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    print(canonical_json(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
