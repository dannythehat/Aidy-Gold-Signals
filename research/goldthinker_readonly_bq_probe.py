"""One-off, read-only audit of AIDY's existing historical XAUUSD rows.

No raw prices or secrets leave BigQuery. No mutation of AIDY tables or workers.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import bigquery
from google.oauth2 import service_account

PROJECT = "aidy-signals"
DATASET = "aidy_analytics_test"
TABLE = f"{PROJECT}.{DATASET}.research_candles"
MAX_BYTES = 750_000_000

def main() -> None:
    raw = os.environ.get("AIDY_GCP_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise SystemExit("BLOCKED: GitHub Actions BigQuery service-account secret unavailable")
    info = json.loads(raw)
    if info.get("type") != "service_account" or info.get("project_id") != PROJECT:
        raise SystemExit("BLOCKED: unexpected service-account project or schema")
    credentials = service_account.Credentials.from_service_account_info(info)
    client = bigquery.Client(project=PROJECT, location="EU", credentials=credentials)
    sql = f"""
    SELECT
      EXTRACT(YEAR FROM open_time_utc) AS calendar_year,
      timeframe,
      COUNT(*) AS row_count,
      COUNT(DISTINCT research_identity) AS unique_research_ids,
      COUNT(DISTINCT candle_key) AS unique_candle_keys,
      COUNTIF(pit_eligible) AS pit_eligible_rows,
      COUNT(DISTINCT source_file_sha256) AS source_archive_versions,
      MIN(open_time_utc) AS first_utc,
      MAX(open_time_utc) AS last_utc
    FROM `{TABLE}`
    WHERE open_time_utc >= TIMESTAMP('2024-01-01 00:00:00+00')
      AND open_time_utc < TIMESTAMP('2026-01-01 00:00:00+00')
      AND source = 'histdata'
      AND symbol = 'XAUUSD'
      AND provenance_class = 'retrospective_history'
    GROUP BY calendar_year, timeframe
    ORDER BY calendar_year, timeframe
    """
    dry = client.query(
        sql, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False, maximum_bytes_billed=MAX_BYTES),
        location="EU",
    )
    estimated = dry.total_bytes_processed
    if estimated is None or estimated > MAX_BYTES:
        raise SystemExit(f"BLOCKED: estimated_bytes={estimated} exceeds safety budget={MAX_BYTES}")
    job = client.query(
        sql, job_config=bigquery.QueryJobConfig(maximum_bytes_billed=MAX_BYTES, use_query_cache=False),
        location="EU",
        job_id_prefix="goldthinker_readonly_probe_",
    )
    rows = list(job.result(timeout=80))
    output = {
        "status": "PASS" if rows else "EMPTY",
        "source": "AIDY BigQuery accepted research_candles, read-only",
        "project": PROJECT,
        "dataset": DATASET,
        "table": "research_candles",
        "utc_checked": datetime.now(timezone.utc).isoformat(),
        "dry_run_bytes_estimate": estimated,
        "charged_bytes_reported": job.total_bytes_billed,
        "max_bytes_billed": MAX_BYTES,
        "groups": [
            {
                "year": r.calendar_year,
                "timeframe": r.timeframe,
                "rows": r.row_count,
                "unique_research_ids": r.unique_research_ids,
                "unique_candle_keys": r.unique_candle_keys,
                "pit_eligible_rows": r.pit_eligible_rows,
                "source_archive_versions": r.source_archive_versions,
                "first_utc": r.first_utc.isoformat() if r.first_utc else None,
                "last_utc": r.last_utc.isoformat() if r.last_utc else None,
            }
            for r in rows
        ],
    }
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/goldthinker-readonly-bq-probe.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "status": output["status"],
        "group_count": len(output["groups"]),
        "m1_2024": next((r["rows"] for r in output["groups"] if r["year"] == 2024 and r["timeframe"] == "M1"), None),
        "m1_2025": next((r["rows"] for r in output["groups"] if r["year"] == 2025 and r["timeframe"] == "M1"), None),
        "dry_run_bytes": estimated,
        "charged_bytes": job.total_bytes_billed,
    }, sort_keys=True))
    if not rows:
        raise SystemExit("BLOCKED: Query succeeded but returned no historical research rows")

if __name__ == "__main__":
    main()
