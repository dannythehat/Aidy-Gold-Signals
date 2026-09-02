# Day 53 data-integrity repair — genuine live Gold feed

This change repairs the formal forward cohort's market-data blocker without changing trading judgement, thresholds, promotion rules, Telegram publication, account state, or execution.

## Source

AIDY adds `argentapi` as a broker-free `public_independent` live Gold source. The live REST endpoint is `/v1/spot/gold`; the API key is accepted only from the Cloudflare Worker secret `AIDY_ARGENT_API_KEY` and is sent only as `X-API-Key`. It is never placed in a URL, D1/R2 evidence, health/status response, or exception message.

The public service advertises live bid/ask/mid, freshness (`fetchedAt`, `ageMs`, `stale`), historical candles, and a free one-request-per-minute tier with no monthly request cap. This implementation intentionally relies only on the documented spot response until a native candle endpoint is independently verified in live acceptance.

## OHLC semantics

AIDY does not invent an exchange candle. It creates versioned `argentapi_quote_rollup_v1` candles only from genuine timestamped live midpoint observations already captured by AIDY. The candle is therefore an **observed-mid sampled OHLC**, not an exchange/tick-complete bar.

For each closed 1m/5m/15m/1h/4h/1d UTC bucket:

- open = first genuine observed mid;
- high/low = max/min genuine observed mid;
- close = last genuine observed mid;
- spread = spread on the final observed sample;
- tick_volume = number of distinct observed minute samples (not market volume);
- volume = null;
- source = `argentapi_quote_rollup_v1`;
- payload digest binds the exact ordered input snapshot identities and coverage.

Except for 1m (one genuine minute sample is the free-tier maximum), materialization requires at least 90% of expected minute observations. Sparse or stale history fails closed and leaves that timeframe's latest candle ID absent. No retrospective HistData row can seed these live IDs.

## Formal-forward behavior

The current Day 53 cohort is not mutated by this PR. PR acceptance is local/simulated only. After merge, remote activation must prove the new quote source with formal forward disabled before any cohort replacement.

If the remote source is proven, the existing blocked cohort may be closed only under `material_safety_or_data_integrity_defect`, recording that it had no model-resolved independent episodes. A replacement cohort must bind the new signed `main` and begin without backfill.

Even after quote + six timeframe IDs are available, this repair does **not** enable the production decision-context adapter. The next fail-closed state remains `production_decision_context_adapter_not_enabled` until that adapter receives its own explicit acceptance.

## Boundaries

- no MetaAPI, MT5, Vantage, broker, follower, or Super Signals dependency;
- no live-money execution;
- no Telegram publication change;
- no model prompt/threshold/risk change;
- blocked/data-failure cycles cannot count toward the Day 54 300-episode gate;
- no performance information is used to justify this repair.
