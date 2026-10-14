import json
import os
from pathlib import Path
from google.cloud import bigquery
from google.oauth2 import service_account

info = json.loads(os.environ['AIDY_GCP_SERVICE_ACCOUNT_JSON'])
client = bigquery.Client(project=info['project_id'], location='EU', credentials=service_account.Credentials.from_service_account_info(info))
result = {'scope': 'BigQuery metadata only', 'datasets': []}
for dataset in client.list_datasets():
    entry = {'dataset': dataset.dataset_id, 'tables': []}
    try:
        for table in client.list_tables(dataset.reference):
            entry['tables'].append({'id': table.table_id, 'type': table.table_type})
    except Exception as e:
        entry['error_type'] = type(e).__name__
    result['datasets'].append(entry)
Path('artifacts').mkdir(exist_ok=True)
Path('artifacts/day06b_bigquery_catalog.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
