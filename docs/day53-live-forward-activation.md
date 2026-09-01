# Day 53 — live private-forward activation

This change finishes the operational step left after the 1 September 2026 immediate-start amendment.

## What becomes live

After exact-head pull-request acceptance and merge to `main`, the post-merge workflow:

1. reruns the focused and full repository test gates on the final `main` SHA;
2. applies the complete Cloudflare D1 migration chain, including the Day 53 forward tables;
3. builds a fresh amended frozen manifest bound to that exact final `main` SHA;
4. activates exactly one amended private-forward cohort using the real UTC activation timestamp;
5. deploys the existing broker-free AIDY Worker with `AIDY_FORMAL_FORWARD_ENABLED=true`;
6. redeploys the one-minute Cloudflare scheduler;
7. requires a genuine scheduled post-activation row in `aidy_forward_evaluations`;
8. verifies the deployed status endpoint reports the same cohort and exact accepted code head.

No PR workflow is permitted to create the remote cohort. The live cohort is created only from the final merged `main` SHA.

## Five-minute forward observation cadence

The Worker continues its normal one-minute evidence-capture queue. The formal-forward observer is due every five minutes and consumes only the snapshot produced by that scheduled capture cycle.

The nominal scheduler timestamp is not treated as the moment the evidence became known. The formal evaluation timestamp is stamped no earlier than the actual snapshot capture time, preserving point-in-time ordering.

A repeated queue delivery in the same five-minute bucket is idempotent and cannot create a second formal evaluation.

## Current live market-data boundary

The accepted public Gold API provides an indicative XAU/USD mid reference but no genuine bid/ask spread and no genuine live OHLC candle chain. Therefore the correct current formal-forward behavior is:

`pre_model_blocked -> missing_genuine_live_ohlc_and_spread`

Equivalent data-quality block reasons are allowed when the reference itself is partial, unavailable, stale or malformed.

These are valid forward observations, but they are not model-resolved decision episodes and cannot satisfy the Day 54 300-independent-episode gate.

The observer does not call OpenAI when a deterministic pre-model data gate has already failed.

## Deliberate decision-adapter boundary

This activation does not silently invent a production decision-context adapter. If genuine live OHLC and spread suddenly become present before that adapter is explicitly enabled and accepted, the observer records `failed_closed` with reason `production_decision_context_adapter_not_enabled`.

That is intentional. Activation of evidence collection is not permission to bypass the existing Architecture V2 composition, k=3 OpenAI, deterministic safety, immutable ledger, paper simulator or watcher contracts.

## Failure behavior

A successful market capture is never retried merely because the forward observer failed. Retrying the whole queue item would create unnecessary duplicate market captures and distort the evidence stream.

In the test Cloudflare environment, forward-observer failures are written to `diagnostics/day53-forward-observer-error.json` in R2. The post-merge live workflow fails if it cannot prove a genuine scheduled forward row. If deployment has already occurred, it redeploys the Worker with the formal-forward flag disabled as a safe-off action.

## Hard boundaries retained

- no pre-activation backfill;
- no Super Signals dependency;
- no broker, account or follower state;
- no MT5, MetaAPI or Vantage access;
- no live-money execution;
- no Telegram publication from this activation;
- Day 45 selective output remains shadow-only;
- GC/XAU remains shadow-only;
- forward outcomes cannot tune the active cohort;
- performance improvement is never a valid freeze-break reason;
- Day 54 remains sample-gated at at least 300 episode-independent **model-resolved** decisions.
