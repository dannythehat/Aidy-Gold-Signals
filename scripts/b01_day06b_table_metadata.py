import json
import os
from google.cloud import bigquery
from google.oauth2 import service_account

info=json.loads(os.environ["AIDY_GCP_SERVICE_ACCOUNT_JSON"])
client=bigquery.Client(project=info["project_id"],location="EU",credentials=service_account.Credentials.from_service_account_info(info))
tables=["market_candles","_stage_market_candles","research_candles","_stage_research_candles",
"research_bidask_minute_quotes","_stage_day27_bidask_minute_quotes","research_bidask_manifest",
"research_backfill_manifest","_stage_research_backfill_manifest","market_snapshots"]
results=[]
for name in tables:
    table_id=f"{info['project_id']}.aidy_analytics_test.{name}"
    try:
        table=client.get_table(table_id)
        results.append({"table":name,"rows_metadata":table.num_rows,
          "size_bytes":table.num_bytes,
          "columns":[f.name for f in table.schema],
          "created":table.created.isoformat() if table.created else None,
          "modified":table.modified.isoformat() if table.modified else None})
    except Exception as exc:
        results.append({"table":name,"status":"INACCESSIBLE","error_type":type(exc).__name__})
print(json.dumps({"scope":"read-only BigQuery table metadata, all listed tables","results":results},default=str))
