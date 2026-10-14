#!/usr/bin/env python3
"""B00 Day 02: bounded read-only verification of existing BigQuery XAUUSD history.

Uses an existing service account; cannot create jobs that write tables. Query results
contain aggregates and metadata only, never raw historical prices or credentials.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path


def query_text(project: str, dataset: str) -> str:
    # Fully qualified names come from constant/validated identifiers, never SQL text from users.
    for value in (project, dataset):
        if not value or not all(c.isalnum() or c in "_-" for c in value):
            raise ValueError("Invalid BigQuery project/dataset identifier")
    return f"""
    SELECT EXTRACT(YEAR FROM open_time_utc) AS year,
           COUNT(*) AS row_count,
           COUNT(DISTINCT open_time_utc) AS distinct_minutes,
           COUNTIF(pit_eligible) AS pit_eligible_rows,
           COUNT(DISTINCT research_identity) AS distinct_identities,
           COUNTIF(open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL) AS missing_ohlc,
           MIN(open_time_utc) AS first_utc,
           MAX(open_time_utc) AS last_utc
    FROM `{project}.{dataset}.research_candles`
    WHERE symbol='XAUUSD' AND timeframe='M1' AND source='histdata'
      AND open_time_utc >= TIMESTAMP('2024-01-01')
      AND open_time_utc < TIMESTAMP('2026-01-01')
    GROUP BY year ORDER BY year
    """


def run() -> dict:
    from google.cloud import bigquery
    from google.oauth2 import service_account

    raw = os.environ.get("AIDY_GCP_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError("AIDY_GCP_SERVICE_ACCOUNT_JSON not configured")
    info = json.loads(raw)
    project = info["project_id"]
    dataset = os.environ.get("AIDY_BIGQUERY_DATASET", "aidy_analytics_test")
    location = os.environ.get("AIDY_BIGQUERY_LOCATION", "EU")
    credentials = service_account.Credentials.from_service_account_info(info)
    client = bigquery.Client(project=project, location=location, credentials=credentials)
    # BigQuery dry run proves query admissibility before consuming any actual read budget.
    sql = query_text(project, dataset)
    dry = client.query(sql, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False))
    cost = int(dry.total_bytes_processed or 0)
    cap = int(os.environ.get("AIDY_B00_MAX_BYTES", "1000000000"))
    if cost > cap:
        raise RuntimeError(f"Dry-run bytes {cost} exceed safety cap {cap}")
    job = client.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            use_query_cache=False,
            maximum_bytes_billed=cap,
            priority=bigquery.QueryPriority.BATCH,
        ),
    )
    rows = list(job.result(timeout=120))
    summary = []
    for row in rows:
        summary.append({
            "year": int(row["year"]),
            "row_count": int(row["row_count"]),
            "distinct_minutes": int(row["distinct_minutes"]),
            "pit_eligible_rows": int(row["pit_eligible_rows"]),
            "distinct_identities": int(row["distinct_identities"]),
            "missing_ohlc": int(row["missing_ohlc"]),
            "first_utc": row["first_utc"].isoformat(),
            "last_utc": row["last_utc"].isoformat(),
        })
    return {
        "probe": "aidy_b00_day02_read_only_v1",
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "table": f"{project}.{dataset}.research_candles",
        "location": location,
        "dry_run_estimated_bytes": cost,
        "job_id": job.job_id,
        "dml_operations": 0,
        "query_rows": summary,
        "expected_prior_acceptance": {"2024": 355592, "2025": 353951},
        "historical_counts_match": {str(r["year"]): r["row_count"] for r in summary}
          == {"2024": 355592, "2025": 353951},
        "note": "Counts and uniqueness only; session-gap classification and data quality remain B01 tasks.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("artifacts/b00_day02_warehouse.json"))
    args = parser.parse_args()
    try:
        result = run()
    except Exception as exc:
        # Never print credentials or source exception details (some libraries echo auth data).
        result = {"probe": "aidy_b00_day02_read_only_v1",
                  "status": "BLOCKED", "error_type": type(exc).__name__}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result))
        return 1
    result["status"] = "PASS" if (
        result["historical_counts_match"] and len(result["query_rows"]) == 2
        and all(r["row_count"] == r["distinct_minutes"] == r["distinct_identities"]
                and r["pit_eligible_rows"] == 0 and r["missing_ohlc"] == 0
                for r in result["query_rows"])
    ) else "FAIL"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
