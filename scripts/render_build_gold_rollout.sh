#!/usr/bin/env bash
set -euo pipefail

: "${CLOUDFLARE_API_TOKEN:?CLOUDFLARE_API_TOKEN required}"

REAL_PYTHON="${AIDY_REAL_PYTHON:?AIDY_REAL_PYTHON required}"
export AIDY_D1_DATABASE_NAME="aidy-ops-test"
export AIDY_D1_DATABASE_ID="3588d82a-d686-4430-872d-d4c0e62c3d5d"
export AIDY_R2_BUCKET_NAME="aidy-memory-test"

export CLOUDFLARE_ACCOUNT_ID="$(
  curl -fsS -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    "https://api.cloudflare.com/client/v4/accounts" |
  "$REAL_PYTHON" -c 'import json,sys; p=json.load(sys.stdin); assert p.get("success") is True,p; r=p.get("result") or []; assert len(r)==1,r; print(r[0]["id"])'
)"
test -n "$CLOUDFLARE_ACCOUNT_ID"
echo "cloudflare_account_resolved=true"

# Run the repository-owned safe deployment path from current main code.
bash scripts/cloudflare_native_deploy.sh

# Verify live Worker contract.
ok=0
for attempt in $(seq 1 30); do
  if curl -fsS -H 'Cache-Control: no-cache' \
    "https://aidy-signals-test.dannythehat2.workers.dev/health?gold_rollout=${attempt}" \
    > /tmp/aidy-health.json; then
    if "$REAL_PYTHON" - <<'PY'
import json
h=json.load(open('/tmp/aidy-health.json',encoding='utf-8'))
assert h.get('capture_enabled') is True,h
assert h.get('formal_forward_enabled') is False,h
assert h.get('market_data_source') == 'twelve_data',h
assert h.get('market_data_ownership') == 'public_independent',h
assert h.get('provider_context_api_version') == 'aidy_provider_context_api_v5',h
assert h.get('gold_state_engine_version') == 'aidy_gold_state_engine_v1',h
assert h.get('gold_movement_investigator_version') == 'aidy_gold_movement_investigator_v1',h
assert h.get('gold_movement_memory_version') == 'aidy_gold_movement_memory_v1',h
PY
    then
      ok=1
      break
    fi
  fi
  sleep 5
done
test "$ok" = "1"
echo "worker_health_versions_verified=true"

curl -fsS \
  -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
  "https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ACCOUNT_ID}/workers/scripts/aidy-signals-test/schedules" \
  > /tmp/aidy-schedules.json
"$REAL_PYTHON" - <<'PY'
import json
p=json.load(open('/tmp/aidy-schedules.json',encoding='utf-8'))
assert p.get('success') is True,p
crons={s.get('cron') for s in ((p.get('result') or {}).get('schedules') or [])}
assert '* * * * *' in crons,p
PY
echo "capture_cron_present=true"

"$REAL_PYTHON" - <<'PY'
import json, os, urllib.request
account=os.environ['CLOUDFLARE_ACCOUNT_ID']
token=os.environ['CLOUDFLARE_API_TOKEN']
db=os.environ['AIDY_D1_DATABASE_ID']
sql="SELECT name FROM sqlite_master WHERE type='table' AND name IN ('aidy_gold_movement_investigations','aidy_gold_movement_learning_cards') ORDER BY name;"
req=urllib.request.Request(
    f'https://api.cloudflare.com/client/v4/accounts/{account}/d1/database/{db}/query',
    data=json.dumps({'sql':sql}).encode(),
    method='POST',
    headers={'Authorization':f'Bearer {token}','Content-Type':'application/json'},
)
with urllib.request.urlopen(req,timeout=30) as r:
    p=json.load(r)
assert p.get('success') is True,p
rows=(p.get('result') or [{}])[0].get('results') or []
names={r.get('name') for r in rows}
assert names == {'aidy_gold_movement_investigations','aidy_gold_movement_learning_cards'},p
PY
echo "gold_movement_d1_schema_verified=true"
echo "gold_movement_rollout_complete=true"
