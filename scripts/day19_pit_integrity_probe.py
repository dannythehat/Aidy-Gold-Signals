from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aidy.analogue_retrieval import (
    build_analogue_query,
    candidate_query_parameters,
    candidate_query_sql,
    reconstruct_case_from_storage_row,
    retrieve_analogues,
)
from aidy.historical_backfill import RETROSPECTIVE_PROVENANCE
from aidy.pit_integrity import attack_catalogue, build_integrity_report
from aidy.pit_reconstruction import query_contract


def _utc(value: object) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Day 19 probe timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=os.environ.get("AIDY_GCP_PROJECT_ID"))
    parser.add_argument("--dataset", default="aidy_analytics_test")
    parser.add_argument("--location", default="EU")
    parser.add_argument("--candidate-limit", type=int, default=250)
    parser.add_argument("--max-results", type=int, default=200)
    return parser.parse_args()


def _bq_params(bigquery: Any, values: dict[str, Any]) -> list[Any]:
    return [
        bigquery.ScalarQueryParameter("symbol", "STRING", values["symbol"]),
        bigquery.ScalarQueryParameter("query_as_of", "TIMESTAMP", _utc(values["query_as_of"])),
        bigquery.ArrayQueryParameter(
            "allowed_provenance", "STRING", values["allowed_provenance"]
        ),
        *[
            bigquery.ScalarQueryParameter(name, "STRING", values[name])
            for name in (
                "feature_definition_version",
                "regime_definition_version",
                "setup_taxonomy_version",
                "setup_detector_version",
            )
        ],
        bigquery.ScalarQueryParameter("candidate_limit", "INT64", values["candidate_limit"]),
    ]


def _source_boundary() -> tuple[bool, dict[str, list[str]]]:
    forbidden = {
        "research_candles",
        "research_move_labels",
        "research_trade_outcomes",
        "research_no_trade_counterfactuals",
        "research_gold_cases",
    }
    files = (
        "src/aidy/pit_reconstruction.py",
        "src/aidy/feature_engine.py",
        "src/aidy/context_packet.py",
        "src/aidy/regime_classifier.py",
        "src/aidy/setup_detector.py",
    )
    hits: dict[str, list[str]] = {}
    for filename in files:
        text = Path(filename).read_text(encoding="utf-8").lower()
        matched = sorted(token for token in forbidden if token in text)
        if matched:
            hits[filename] = matched
    return not hits, hits


def _day6_sql_clean(project: str, dataset: str) -> bool:
    combined = "\n".join(
        query.sql.lower()
        for query in query_contract(project=project, dataset=dataset).values()
    )
    forbidden = (
        "research_candles",
        "research_move_labels",
        "research_trade_outcomes",
        "research_no_trade_counterfactuals",
        "research_gold_cases",
    )
    return (
        "first_observed_at <= @as_of" in combined
        and "captured_at <= @as_of" in combined
        and not any(token in combined for token in forbidden)
    )


def main() -> int:
    args = _args()
    if not args.project or args.candidate_limit <= 0 or args.max_results <= 0:
        raise SystemExit("Project and positive limits are required.")

    from google.cloud import bigquery
    from google.oauth2 import service_account

    raw = os.environ.get("AIDY_GCP_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise SystemExit("AIDY_GCP_SERVICE_ACCOUNT_JSON is required.")
    credentials = service_account.Credentials.from_service_account_info(json.loads(raw))
    client = bigquery.Client(
        project=args.project, credentials=credentials, location=args.location
    )

    table = f"{args.project}.{args.dataset}.research_gold_cases"
    source_sql = f"""
SELECT case_digest, case_version, case_id, symbol, as_of_utc, provenance_class,
       input_digest, feature_definition_version, regime_definition_version,
       setup_taxonomy_version, setup_detector_version, data_quality_grade,
       future_available_after_utc, input_boundary, future_evaluation
FROM `{table}`
WHERE symbol = 'XAUUSD' AND provenance_class = @provenance
  AND data_quality_grade != 'insufficient'
ORDER BY as_of_utc DESC, case_id
LIMIT 1
""".strip()
    source_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "provenance", "STRING", RETROSPECTIVE_PROVENANCE
            )
        ]
    )
    source_rows = list(client.query(source_sql, job_config=source_config).result())
    if not source_rows:
        raise SystemExit("Day 19 requires an accepted Day 16 case.")
    source = reconstruct_case_from_storage_row(dict(source_rows[0].items()))

    query = build_analogue_query(
        input_boundary=source["input_boundary"],
        allowed_provenance=(RETROSPECTIVE_PROVENANCE,),
        source_case_id=str(source["case_id"]),
        max_results=args.max_results,
    )
    params = candidate_query_parameters(query, candidate_limit=args.candidate_limit)
    config = bigquery.QueryJobConfig(query_parameters=_bq_params(bigquery, params))
    rows = list(
        client.query(
            candidate_query_sql(project=args.project, dataset=args.dataset),
            job_config=config,
        ).result()
    )
    raw_rows = [dict(row.items()) for row in rows]
    cutoff = _utc(query["as_of_utc"])
    future_violations = sum(_utc(row["as_of_utc"]) >= cutoff for row in raw_rows)
    unavailable_violations = sum(
        row.get("future_available_after_utc") is None
        or _utc(row["future_available_after_utc"]) > cutoff
        for row in raw_rows
    )
    candidates = [reconstruct_case_from_storage_row(row) for row in raw_rows]
    retrieval = retrieve_analogues(query=query, candidate_cases=candidates)
    similarity_violations = sum(
        match.get("outcome_used_for_similarity") is not False
        for match in retrieval["matches"]
    )
    source_clean, source_hits = _source_boundary()
    sql_clean = _day6_sql_clean(args.project, args.dataset)
    if any(
        (
            future_violations,
            unavailable_violations,
            similarity_violations,
            retrieval.get("outcomes_used_for_selection") is not False,
            not source_clean,
            not sql_clean,
        )
    ):
        raise SystemExit("Day 19 real PIT-integrity probe found a boundary violation.")

    report = build_integrity_report(
        blocked_attack_ids=[item["attack_id"] for item in attack_catalogue()],
        evidence={
            "query_id": query["query_id"],
            "candidate_rows": len(rows),
            "returned_matches": retrieval["returned_match_count"],
            "selection_digest": retrieval["selection_digest"],
            "source_table_hits": source_hits,
        },
    )
    output = {
        "ok": report["all_attacks_blocked"],
        **report,
        "candidate_rows_from_bigquery": len(rows),
        "candidate_future_case_violations": future_violations,
        "candidate_unavailable_outcome_violations": unavailable_violations,
        "outcome_similarity_violations": similarity_violations,
        "outcomes_used_for_selection": retrieval["outcomes_used_for_selection"],
        "day6_sql_excludes_outcome_tables": sql_clean,
        "decision_builders_exclude_research_tables": source_clean,
    }
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
