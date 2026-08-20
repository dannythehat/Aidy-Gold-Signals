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
from aidy.evidence_grading import build_evidence_report
from aidy.historical_backfill import RETROSPECTIVE_PROVENANCE

DEFAULT_DATASET = "aidy_analytics_test"
DEFAULT_LOCATION = "EU"


def _parse_utc(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Day 18 probe timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a bounded real Day 18 evidence-grading probe."
    )
    parser.add_argument("--project", default=os.environ.get("AIDY_GCP_PROJECT_ID"))
    parser.add_argument(
        "--dataset",
        default=os.environ.get("AIDY_BIGQUERY_DATASET", DEFAULT_DATASET),
    )
    parser.add_argument(
        "--location",
        default=os.environ.get("AIDY_BIGQUERY_LOCATION", DEFAULT_LOCATION),
    )
    parser.add_argument("--candidate-limit", type=int, default=DEFAULT_CANDIDATE_LIMIT)
    parser.add_argument("--max-results", type=int, default=200)
    return parser


def _query_parameters(bigquery: Any, params: dict[str, Any]) -> list[Any]:
    return [
        bigquery.ScalarQueryParameter("symbol", "STRING", params["symbol"]),
        bigquery.ScalarQueryParameter(
            "query_as_of",
            "TIMESTAMP",
            _parse_utc(str(params["query_as_of"])),
        ),
        bigquery.ArrayQueryParameter(
            "allowed_provenance",
            "STRING",
            params["allowed_provenance"],
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
            "candidate_limit",
            "INT64",
            params["candidate_limit"],
        ),
    ]


def _row_mapping(row: Any) -> dict[str, Any]:
    return dict(row.items())


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
    source_sql = f"""
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
    source_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "provenance",
                "STRING",
                RETROSPECTIVE_PROVENANCE,
            )
        ]
    )
    source_rows = list(client.query(source_sql, job_config=source_config).result())
    if not source_rows:
        raise SystemExit("Day 18 requires at least one accepted Day 16 historical case.")

    source_case = reconstruct_case_from_storage_row(_row_mapping(source_rows[0]))
    analogue_query = build_analogue_query(
        input_boundary=source_case["input_boundary"],
        allowed_provenance=(RETROSPECTIVE_PROVENANCE,),
        source_case_id=str(source_case["case_id"]),
        max_results=args.max_results,
    )

    sql = candidate_query_sql(project=args.project, dataset=args.dataset)
    params = candidate_query_parameters(
        analogue_query,
        candidate_limit=args.candidate_limit,
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

    retrieval = retrieve_analogues(
        query=analogue_query,
        candidate_cases=candidates,
    )
    report = build_evidence_report(retrieval=retrieval)

    if report["source_selection_digest"] != retrieval["selection_digest"]:
        raise SystemExit("Day 18 grading mutated the Day 17 selection identity.")
    if report["grading_applied_after_analogue_selection"] is not True:
        raise SystemExit("Day 18 grading must occur after analogue selection.")
    if report["outcome_values_used_for_dataset_grade"] is not False:
        raise SystemExit("Day 18 dataset grade illegally used outcome values.")

    statistic_summaries = [
        {
            "name": statistic["name"],
            "n": statistic["n"],
            "grade": statistic["grade"],
            "probability_like_wording_allowed": statistic[
                "probability_like_wording_allowed"
            ],
            "decision_weight_allowed": statistic["decision_weight_allowed"],
            "rates_emitted": statistic["rates"] is not None,
        }
        for statistic in report["statistics"]
    ]

    result = {
        "ok": True,
        "query_id": analogue_query["query_id"],
        "query_as_of_utc": analogue_query["as_of_utc"],
        "source_case_id": source_case["case_id"],
        "candidate_rows_from_bigquery": len(candidate_rows),
        "retrieved_match_count": retrieval["returned_match_count"],
        "retrieval_evidence_state": retrieval["evidence_state"],
        "selection_digest": retrieval["selection_digest"],
        "evidence_report_version": report["evidence_report_version"],
        "evidence_grade_version": report["evidence_grade_version"],
        "dataset_grade": report["dataset_grade"]["grade"],
        "dataset_grade_label": report["dataset_grade"]["grade_label"],
        "dataset_n": report["dataset_grade"]["n"],
        "dataset_metrics": report["dataset_grade"]["metrics"],
        "probability_like_wording_allowed": report[
            "probability_like_wording_allowed"
        ],
        "decision_weight_allowed": report["decision_weight_allowed"],
        "standalone_trade_decision_allowed": report[
            "standalone_trade_decision_allowed"
        ],
        "grading_applied_after_analogue_selection": report[
            "grading_applied_after_analogue_selection"
        ],
        "selection_mutated_by_grading": report["selection_mutated_by_grading"],
        "outcome_values_used_for_dataset_grade": report[
            "outcome_values_used_for_dataset_grade"
        ],
        "statistics": statistic_summaries,
        "query_latency_ms": latency_ms,
        "query_total_bytes_processed": int(job.total_bytes_processed or 0),
        "query_cache_hit": bool(job.cache_hit),
        "report_digest": report["report_digest"],
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
