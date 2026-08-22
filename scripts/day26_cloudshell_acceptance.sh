#!/usr/bin/env bash
set -euo pipefail

BASE_SHA="262bf436dcd948d0dabe554f93d64edb82726121"
PROJECT_ID="aidy-signals"
DATASET="aidy_analytics_test"
LOCATION="EU"
CANDIDATE_DIGEST="bd3c81b54ec05b2150e6e6ecbdffbc3c1e4f943c6a23c9a8ee4977c1dc1c3a88"

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
HEAD_SHA="$(git rev-parse HEAD)"

export AIDY_GCP_PROJECT_ID="$PROJECT_ID"
export AIDY_BIGQUERY_DATASET="$DATASET"
export AIDY_BIGQUERY_LOCATION="$LOCATION"
export DAY26_HEAD_SHA="$HEAD_SHA"

printf '\nAIDY Day 26 Cloud Shell acceptance\n'
printf 'Base: %s\n' "$BASE_SHA"
printf 'Head: %s\n' "$HEAD_SHA"
printf 'Project: %s / %s (%s)\n\n' "$PROJECT_ID" "$DATASET" "$LOCATION"

# 1. Change control: exact accepted Day-25 ancestry and no edits to frozen modules.
git cat-file -e "${BASE_SHA}^{commit}"
test "$(git merge-base "$BASE_SHA" HEAD)" = "$BASE_SHA"
git diff --exit-code "$BASE_SHA" -- \
  src/aidy/feature_engine.py \
  src/aidy/context_packet.py \
  src/aidy/context_packet_v2.py \
  src/aidy/market_sessions.py \
  src/aidy/market_structure_context.py \
  src/aidy/historical_case_context_v2.py \
  src/aidy/analogue_retrieval_v2.py \
  src/aidy/analogue_retrieval_v3.py \
  src/aidy/evidence_grading_v2.py \
  src/aidy/j5_epoch_effect.py \
  scripts/day25_market_structure_acceptance.py
printf 'PASS change-control\n'

# 2. Use the already-authenticated Cloud Shell Google identity. No secret is printed.
command -v gcloud >/dev/null
gcloud config set project "$PROJECT_ID" >/dev/null
ACTIVE_ACCOUNT="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' | head -n 1)"
test -n "$ACTIVE_ACCOUNT"
printf 'PASS Google Cloud authenticated account present\n'

# 3. Reproducible Python 3.13 environment.
if ! command -v uv >/dev/null 2>&1; then
  python3 -m pip install --user --disable-pip-version-check --quiet uv
  export PATH="$HOME/.local/bin:$PATH"
fi
uv python install 3.13
uv sync --python 3.13
printf 'PASS Python/project environment\n'

# 4. Cheap checks first.
uv run --python 3.13 ruff check \
  src/aidy/price_structure_v2.py \
  src/aidy/context_packet_v3.py \
  tests/test_day26_price_structure.py \
  scripts/day26_acceptance_support.py \
  scripts/day26_price_structure_acceptance.py
uv run --python 3.13 python -m compileall -q src scripts tests
uv run --python 3.13 python - <<'PY'
import re
from pathlib import Path

pattern = re.compile(
    r"\b(?:RSI|MACD|Stochastics|Bollinger|Ichimoku)\b|stop hunt|liquidity sweep",
    re.IGNORECASE,
)
for name in ("src/aidy/price_structure_v2.py", "src/aidy/context_packet_v3.py"):
    match = pattern.search(Path(name).read_text(encoding="utf-8"))
    if match:
        raise SystemExit(f"Forbidden Day-26 vocabulary in {name}: {match.group(0)}")
print("PASS prohibited-vocabulary check")
PY
printf 'PASS static/vocabulary checks\n'

# 5. Focused Day-26 tests, then the full accumulated regression exactly once.
mkdir -p day26_artifacts
uv run --python 3.13 pytest -q tests/test_day26_price_structure.py \
  | tee day26_artifacts/focused-tests.txt
printf 'PASS focused tests\n'
uv run --python 3.13 pytest -q \
  | tee day26_artifacts/full-regression.txt
printf 'PASS full regression\n'

# 6. BigQuery is the expensive gate and deliberately runs only after all code tests pass.
uv pip install --python .venv/bin/python --quiet 'google-cloud-bigquery>=3.42,<4'
.venv/bin/python scripts/day26_price_structure_acceptance.py \
  --project "$PROJECT_ID" \
  --dataset "$DATASET" \
  --location "$LOCATION" \
  --output-dir day26_artifacts \
  | tee day26_artifacts/warehouse-summary.stdout

# 7. Enforce the same frozen evidence contract independently of the producer.
.venv/bin/python - <<'PY'
import json
import os
from datetime import datetime

with open('day26_artifacts/summary.json', encoding='utf-8') as handle:
    result = json.load(handle)

assert result['ok'] is True, result
assert result['base_sha'] == '262bf436dcd948d0dabe554f93d64edb82726121', result
assert result['head_sha'] == os.environ['DAY26_HEAD_SHA'], result
assert result['candidate_store_snapshot_digest'] == 'bd3c81b54ec05b2150e6e6ecbdffbc3c1e4f943c6a23c9a8ee4977c1dc1c3a88', result
assert result['retrospective_anchor_count'] == 36, result
assert result['retrospective_input_order_reproducible_count'] == 36, result
assert result['real_pit_probe_count'] == 1, result
assert result['pit_input_order_reproducible'] is True, result
assert result['bigquery_evidence']['result_rows'] == 37, result
assert all(result['prior_period_known_anchor_counts'].get(key, 0) > 0 for key in ('prior_day', 'prior_week', 'prior_month')), result
assert result['retrospective_arrival_latency_fabricated'] is False, result
assert result['historical_spread_inference_included'] is False, result
assert result['threshold_based_feed_health_gate_included'] is False, result
assert result['future_values_used'] is False, result
assert result['predictive_edge_claimed'] is False, result
assert result['accepted_prior_modules_modified'] is False, result
assert datetime.fromisoformat(result['pit_probe_as_of_utc']) <= datetime.fromisoformat(result['pit_probe_cutoff_utc']), result
print('PASS frozen Day-26 evidence contract')
PY

# 8. Preserve local evidence hashes. BigQuery already preserves the canonical result rows/summary.
(
  cd day26_artifacts
  find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 \
    | sort -z \
    | xargs -0 sha256sum > SHA256SUMS
)
printf '\nDAY26_CLOUDSHELL_ACCEPTANCE=PASS\n'
printf 'HEAD_SHA=%s\n' "$HEAD_SHA"
printf 'Summary:\n'
.venv/bin/python -m json.tool day26_artifacts/summary.json
printf '\nEvidence hashes:\n'
cat day26_artifacts/SHA256SUMS
