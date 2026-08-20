from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from aidy.analogue_retrieval import (
    DEFAULT_CANDIDATE_LIMIT,
    build_analogue_query,
    candidate_query_parameters,
    candidate_query_sql,
    reconstruct_case_from_storage_row,
    retrieve_analogues,
)
from aidy.historical_backfill import RETROSPECTIVE_PROVENANCE

DEFAULT_DATASET = "aidy_analytics_test"
DEFAULT_LOCATION = "EU"


def _parse_utc(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Day 17 probe timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a bounded deterministic Day 17 analogue retrieval probe."
    )
    parser.add_argument("--project", default=os.environ.get("AIDY_GCP_PROJECT_ID"))
    parser.add_argument("--dataset", default=os.environ.get("AIDY_BIGQUERY_DATASET", DEFAULT_DATASET))
    parser.add_argument("--location", default=os.environ.get("AIDY_BIGQUERY_LOCATION", DEFAULT_LOCATION))
    parser.add_argument("--candidate-limit", type=int, default=DEFAULT_CANDIDATE_LIMIT)
    parser.add_argument("--max-results", type=int, default=5)
    return parser


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
            "feature_definition_version",
            "STRING",
            params["feature_definition_version"],
        ),
        bigquery.ScalarQueryParameter(
            "regime_definition_version",
            "STRING",
            params["regime_definition_version"],
        ),
        bigquery.ScalarQueryParameter(
            "setup_taxonomy_version",
            "STRING",
            params["setup_taxonomy_version"],
        ),
        bigquery.ScalarQueryParameter(
            "setup_detector_version",
            "STRING",
            params["setup_detector_version"],
        ),
        bigquery.ScalarQueryParameter(
            "candidate_limit", "INT64", params["candidate_limit"]
        ),
    ]


def _row_mapping(row: Any) -> dict[str, Any]:
    return dict(row.items())


def _top_match_summary(match: dict[str, Any]) -> dict[str, Any]:
    future = match["future_evaluation"]
    return {
        "rank": match["rank"],
        "case_id": match["case_id"],
        "as_of_utc": match["as_of_utc"],
        "provenance_class": match["provenance_class"],
        "similarity_score": match["similarity"]["similarity_score"],
        "component_coverage": match["similarity"]["component_coverage"],
        "setup_detector_state": match["setup_detector_state"],
        "candidate_setup_ids": match["candidate_setup_ids"],
        "has_move_bundle": future.get("move_bundle") is not None,
        "has_trade_outcome_bundle": future.get("trade_outcome_bundle") is not None,
        "outcome_used_for_similarity": match["outcome_used_for_similarity"],
    }


def main() -> int:
    args = _parser().parse_args()
    if not args.project:
        raise SystemExit("AIDY_GCP_PROJECT_ID or --project is required.")
    if args.candidate_limit <= 0 or args.max_results <= 0:
        raise SystemExit("Candidate and result limits must be positive.")

    from google.cloud import bigquery
    from google.oauth2 import service_account

    raw_credentials = os.environ.get("AIDY_GCP_SERVICE_ACCOUNT_JSON")
    if not raw_credentials:
        raise SystemExit("AIDY_GCP_SERVICE_ACCOUNT_JSON is required.")
    info = json.loads(raw_credentials)
    credentials = service_account.Credentials.from_service_account_info(info)
    client = bigquery.Client(
        project=args.project,
        credentials=credentials,
        location=args.location,
    )

    table = f"{args.project}.{args.dataset}.research_gold_cases"
    query_case_sql = f"""
        SELECT case_digest, case_version, case_id, symbol, as_of_utc,
               provenance_class, input_digest, feature_definition_version,
               regime_definition_version, setup_taxonomy_version,
               setup_detector_version, data_quality_grade,
               future_available_after_utc, input_boundary, future_evaluation
        FROM `{table}`
        WHERE symbol = 'XAUUSD'
          AND provenance_class = @provenance
          AND data_quality_grade != 'insufficient'
        ORDER BY as_of_utc DESC, case_id
        LIMIT 1
    """
    query_case_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "provenance", "STRING", RETROSPECTIVE_PROVENANCE
            )
        ]
    )
    query_case_rows = list(client.query(query_case_sql, job_config=query_case_config).result())
    if not query_case_rows:
        raise SystemExit("Day 17 requires at least one accepted Day 16 historical case.")

    query_case = reconstruct_case_from_storage_row(_row_mapping(query_case_rows[0]))
    analogue_query = build_analogue_query(
        input_boundary=query_case["input_boundary"],
        allowed_provenance=(RETROSPECTIVE_PROVENANCE,),
        source_case_id=str(query_case["case_id"]),
        max_results=args.max_results,
    )

    sql = candidate_query_sql(project=args.project, dataset=args.dataset)
    params = candidate_query_parameters(
        analogue_query, candidate_limit=args.candidate_limit
    )
    candidate_config = bigquery.QueryJobConfig(
        query_parameters=_query_parameters(bigquery, params)
    )
    started = perf_counter()
    job = client.query(sql, job_config=candidate_config)
    candidate_rows = list(job.result())
    latency_ms = int((perf_counter() - started) * 1000)
    candidates = [
        reconstruct_case_from_storage_row(_row_mapping(row))
        for row in candidate_rows
    ]

    first = retrieve_analogues(query=analogue_query, candidate_cases=candidates)
    second = retrieve_analogues(query=analogue_query, candidate_cases=list(reversed(candidates)))
    if first["selection_digest"] != second["selection_digest"]:
        raise SystemExit("Day 17 retrieval selection is not reproducible under candidate reordering.")
    if [item["case_id"] for item in first["matches"]] != [
        item["case_id"] for item in second["matches"]
    ]:
        raise SystemExit("Day 17 retrieval ranking changed under candidate reordering.")
    if first["outcomes_used_for_selection"] is not False:
        raise SystemExit("Day 17 retrieval illegally used outcomes for selection.")

    result = {
        "ok": True,
        "query_id": analogue_query["query_id"],
        "query_as_of_utc": analogue_query["as_of_utc"],
        "source_case_id": query_case["case_id"],
        "source_case_provenance": query_case["provenance_class"],
        "retrieval_version": first["retrieval_version"],
        "similarity_feature_version": first["similarity_feature_version"],
        "evidence_state": first["evidence_state"],
        "candidate_rows_from_bigquery": len(candidate_rows),
        "eligible_candidate_count": first["eligible_candidate_count"],
        "sufficient_match_count": first["sufficient_match_count"],
        "returned_match_count": first["returned_match_count"],
        "selection_digest": first["selection_digest"],
        "selection_reproducible_under_reordering": True,
        "outcomes_used_for_selection": False,
        "probability_claims_included": False,
        "hard_pit_guards": {
            "candidate_as_of_before_query": True,
            "outcome_available_by_query_time": True,
            "explicit_provenance_filter": True,
            "version_compatibility_filter": True,
        },
        "query_latency_ms": latency_ms,
        "query_total_bytes_processed": int(job.total_bytes_processed or 0),
        "query_cache_hit": bool(job.cache_hit),
        "top_matches": [_top_match_summary(item) for item in first["matches"]],
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
