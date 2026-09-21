#!/usr/bin/env bash
set -euo pipefail

: "${AIDY_D1_DATABASE_NAME:?AIDY_D1_DATABASE_NAME is required}"
: "${AIDY_D1_DATABASE_ID:?AIDY_D1_DATABASE_ID is required}"
: "${AIDY_R2_BUCKET_NAME:?AIDY_R2_BUCKET_NAME is required}"

python -m pip install --disable-pip-version-check --quiet uv
uv sync

uv run ruff check \
  src/aidy/provider_market_api.py \
  src/aidy/provider_context_api.py \
  src/aidy/gold_state_engine.py \
  src/aidy/gold_movement_investigator.py \
  src/aidy/gold_movement_memory.py \
  src/aidy/private_forward_context.py \
  src/aidy/twelve_data_intraday_repair.py \
  src/aidy/runtime.py \
  src/aidy/data_health.py \
  src/provider_entry.py

uv run python -m compileall -q src tests
uv run pytest -q \
  tests/test_provider_market_api.py \
  tests/test_provider_context_api.py \
  tests/test_gold_state_engine.py \
  tests/test_gold_movement_investigator.py \
  tests/test_gold_movement_memory.py \
  tests/test_twelve_data_intraday_repair.py \
  tests/test_aidy_data_health.py \
  tests/test_twelve_data_retrospective.py

uv run python scripts/build_cloudflare_live_config.py
npx --yes wrangler@4 d1 migrations apply AIDY_OPS --remote \
  --config wrangler.research.live.jsonc

cp wrangler.research.live.jsonc wrangler.jsonc
uv run pywrangler deploy

echo "cloudflare_native_deploy_complete=true"
