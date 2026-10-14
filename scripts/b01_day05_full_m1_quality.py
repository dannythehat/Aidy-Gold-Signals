#!/usr/bin/env python3
"""B01 Day05: full-source M1 quality audit, aggregate-only, read-only BigQuery."""
import json
import os
from datetime import UTC, datetime
from pathlib import Path

SQL = """
WITH ordered AS (
 SELECT EXTRACT(YEAR FROM open_time_utc) yr, open_time_utc ts,
        SAFE_CAST(open AS NUMERIC) o, SAFE_CAST(high AS NUMERIC) h,
        SAFE_CAST(low AS NUMERIC) l, SAFE_CAST(close AS NUMERIC) c,
        source_file_sha256 archive_sha, source_payload_sha256 payload_sha,
        source_timezone tz, price_basis basis, provenance_class provenance,
        LAG(open_time_utc) OVER (PARTITION BY EXTRACT(YEAR FROM open_time_utc)
                                ORDER BY open_time_utc) prev_ts
 FROM `aidy-signals.aidy_analytics_test.research_candles`
 WHERE symbol='XAUUSD' AND timeframe='M1' AND source='histdata'
 AND open_time_utc >= TIMESTAMP('2024-01-01')
 AND open_time_utc < TIMESTAMP('2026-01-01')
), audit AS (
 SELECT *, TIMESTAMP_DIFF(ts,prev_ts,MINUTE) delta
 FROM ordered
)
SELECT yr, COUNT(*) n, COUNT(DISTINCT ts) unique_minutes,
 COUNTIF(o IS NULL OR h IS NULL OR l IS NULL OR c IS NULL) invalid_decimals,
 COUNTIF(o <= 0 OR h <= 0 OR l <= 0 OR c <= 0) nonpositive,
 COUNTIF(h < GREATEST(o,c,l) OR l > LEAST(o,c,h)) invalid_ohlc,
 COUNTIF(EXTRACT(SECOND FROM ts) != 0) off_minute,
 COUNTIF(delta > 1) gap_intervals,
 SUM(IF(delta>1, delta-1, 0)) missing_minutes_raw,
 MAX(IF(delta>1,delta-1,0)) max_missing_minutes,
 COUNTIF(delta <= 0) nonpositive_deltas,
 COUNT(DISTINCT archive_sha) archive_hashes,
 COUNT(DISTINCT payload_sha) payload_hashes,
 COUNT(DISTINCT tz) source_clocks,
 COUNT(DISTINCT basis) price_bases,
 COUNT(DISTINCT provenance) provenance_classes,
 MIN(ts) first_utc, MAX(ts) last_utc,
 MIN(o) min_open, MAX(h) max_high
FROM audit GROUP BY yr ORDER BY yr
"""

def main():
    from google.cloud import bigquery
    from google.oauth2 import service_account
    out=Path("artifacts/b01_day05_quality.json")
    out.parent.mkdir(parents=True,exist_ok=True)
    try:
        info=json.loads(os.environ["AIDY_GCP_SERVICE_ACCOUNT_JSON"])
        client=bigquery.Client(project=info["project_id"],location="EU",
            credentials=service_account.Credentials.from_service_account_info(info))
        cap=1_000_000_000
        dry=client.query(SQL,job_config=bigquery.QueryJobConfig(dry_run=True,use_query_cache=False))
        if int(dry.total_bytes_processed or 0)>cap:raise RuntimeError("QUERY_COST_CAP")
        job=client.query(SQL,job_config=bigquery.QueryJobConfig(
            use_query_cache=False,maximum_bytes_billed=cap))
        rows=[]
        for row in job.result(timeout=150):
            rows.append({k:(v.isoformat() if isinstance(v,datetime) else str(v) if k in ("min_open","max_high") else v) for k,v in row.items()})
        passed=len(rows)==2 and {int(x["yr"]):x["n"] for x in rows}=={2024:355592,2025:353951} and all(
            x[k]==0 for x in rows for k in ("invalid_decimals","nonpositive","invalid_ohlc","off_minute","nonpositive_deltas"))
        result={"status":"PASS" if passed else "FAIL","observed_at":datetime.now(UTC).isoformat(),
          "job_id":job.job_id,"bytes_estimate":int(dry.total_bytes_processed or 0),
          "scope":"Full 2024-2025 HistData XAUUSD M1 stored records; raw gaps not yet classified as legitimate sessions",
          "rows":rows}
    except Exception as e:
        result={"status":"BLOCKED","error_type":type(e).__name__}
    out.write_text(json.dumps(result,indent=2,default=str)+"\n")
    print(json.dumps(result,default=str))
    return 0 if result["status"]=="PASS" else 1

if __name__=="__main__":
    raise SystemExit(main())
