# Day 53 — immediate formal-forward start amendment

Amendment date: **1 September 2026**  
Amendment effective floor: `2026-09-01T16:07:00+00:00`  
Accepted predecessor main: `010abc653c274b14d0a64941af9ca22eb88aa658`

## Why this amendment exists

Architecture V2 originally scheduled the Day 53 formal private forward cohort for 20 September 2026. That date was a calendar sequencing assumption made while Days 23–52 were still expected to consume the intervening period. It was not a model-training, warm-up or statistical prerequisite.

Days 23–52 were completed and accepted materially earlier than that plan. On 1 September 2026, **before any Day 53 formal forward outcome existed**, the owner approved an ex-ante amendment: begin the frozen private forward cohort immediately after this amendment passes exact-head acceptance and is merged.

The old 20 September readiness artifact remains immutable historical evidence. This amendment creates a new manifest/cohort version rather than rewriting that evidence.

## What does not change

The scientific controls remain intact:

- no pre-activation result can be backfilled into the cohort;
- the actual activation timestamp is the earliest eligible evaluation timestamp;
- forward outcomes cannot tune an active cohort;
- the Day 45 selective/conformal layer remains shadow-only and cannot gate trading or publication;
- GC/XAU remains shadow-only and is not silently promoted;
- only a material safety/data-integrity defect, forced model/API deprecation, or objectively documented market-structure/venue-rule change may break the freeze;
- performance improvement is never a valid freeze-break reason;
- Super Signals, broker/account/follower state, MT5, MetaAPI and Vantage remain outside AIDY;
- no live-money execution is enabled.

## Day 54 remains sample-gated

Day 54 remains **8 October 2026 as the earliest review checkpoint**, not a deadline.

Formal J17/J20 inference still requires at least **300 episode-independent model-resolved decision episodes**. `pre_model_blocked`, data-quality failures and model failures may be logged as forward evidence but **cannot** satisfy the 300-episode gate. Raw bursts cannot substitute for independent N.

This matters immediately because the currently accepted live Gold-API reference is mid-only and does not provide genuine live OHLC or spread. Existing safety gates must not be weakened to manufacture tradability. If the evidence is insufficient, AIDY must record the blocked/unknown state and make no OpenAI trading call.

## What “start now” means operationally

There are three distinct states:

1. **Architecture amended** — this document and the Notion Architecture V2 source of truth permit immediate start.
2. **Code/freeze accepted** — exact-head CI proves the amended manifest, no-backfill rule, sample accounting and all existing regressions.
3. **Cohort activated** — after merge, the final signed `main` SHA is bound into a new frozen manifest and an active cohort row is written to Cloudflare D1 with the real activation timestamp.

Only state 3 begins formal forward evidence. PR acceptance itself does not backdate or fabricate an activation.

## Runtime reality

Day 52 produced a complete callable end-to-end trading engine, but the currently deployed Cloudflare queue path still runs evidence capture only. Therefore activation and runtime collection are treated separately from this PR acceptance. The live forward runtime must remain Cloudflare-based, fail closed, and preserve the same PIT/safety boundaries.

Until genuine decision-grade live OHLC/spread is available, a correct formal-forward runtime may produce `pre_model_blocked` observations rather than trades. That is valid evidence, not a reason to relax the gates.
