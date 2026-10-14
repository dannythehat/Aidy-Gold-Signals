"""Day 06 read-only source evidence: full available research bid/ask archive coverage."""
import json
import os
from datetime import UTC, datetime
from pathlib import Path

SQL = """
SELECT source_period,
       COUNT(*) AS manifest_rows,
       MAX(tick_rows) AS reported_ticks,
       MAX(minute_quote_rows) AS reported_minutes,
       MIN(first_tick_utc) AS first_tick_utc,
       MAX(last_tick_utc) AS last_tick_utc,
       COUNT(DISTINCT source_file_sha256) AS archive_hashes
FROM `aidy-signals.aidy_analytics_test.research_bidask_manifest`
WHERE symbol = 'XAUUSD' AND source = 'histdata'
GROUP BY source_period ORDER BY source_period
"""
QUOTE_SQL = """
SELECT FORMAT_TIMESTAMP('%Y-%m', minute_utc) AS period,
 COUNT(*) AS n, COUNT(DISTINCT minute_utc) AS unique_minutes,
 COUNTIF(SAFE_CAST(bid AS NUMERIC) <= 0 OR SAFE_CAST(ask AS NUMERIC) <= 0
   OR SAFE_CAST(ask AS NUMERIC) < SAFE_CAST(bid AS NUMERIC)) AS bad_quotes,
 MIN(minute_utc) first_utc, MAX(minute_utc) last_utc
FROM `aidy-signals.aidy_analytics_test.research_bidask_minute_quotes`
WHERE symbol='XAUUSD' AND source='histdata'
GROUP BY period ORDER BY period
"""
def main():
    from google.cloud import bigquery
    from google.oauth2 import service_account
    out=Path("artifacts/day06_quote_inventory.json")
    out.parent.mkdir(parents=True,exist_ok=True)
    try:
        info=json.loads(os.environ["AIDY_GCP_SERVICE_ACCOUNT_JSON"])
        client=bigquery.Client(project=info["project_id"],location="EU",
            credentials=service_account.Credentials.from_service_account_info(info))
        output={}
        jobs=[]
        for name,sql in (("manifests",SQL),("minute_quotes",QUOTE_SQL)):
            dry=client.query(sql,job_config=bigquery.QueryJobConfig(dry_run=True,use_query_cache=False))
            estimated=int(dry.total_bytes_processed or 0)
            if estimated>500_000_000:raise RuntimeError("QUERY_COST_CAP")
            job=client.query(sql,job_config=bigquery.QueryJobConfig(use_query_cache=False,maximum_bytes_billed=500_000_000))
            output[name]=[{k:v.isoformat() if isinstance(v,datetime) else v for k,v in row.items()}
                          for row in job.result(timeout=120)]
            jobs.append({"name":name,"job_id":job.job_id,"estimated_bytes":estimated})
        result={"status":"PASS","observed_utc":datetime.now(UTC).isoformat(),
                "query_jobs":jobs,"rows":output,"limitations":"Materialized last tick/minute is not full tick-event replay; HistData is not Vantage executable broker data."}
    except Exception as e:
        result={"status":"BLOCKED","reason_type":type(e).__name__}
    out.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result))
    return 0 if result["status"]=="PASS" else 1
if __name__=="__main__":
    raise SystemExit(main())
