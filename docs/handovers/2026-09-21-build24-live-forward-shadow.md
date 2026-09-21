# Build 24 — Live Forward Shadow Soak & Permanent Scorecard

Date: 2026-09-21

Status: **ENGINEERING COMPLETE / LIVE DELAYED-SCORE PROOF IN PROGRESS**

## Purpose

Build 24 is the final planned expert-gate implementation build. It turns Builds 1-23 into a prospective, permanent learning loop instead of another retrospective exam.

## Frozen runtime contract

For every eligible fresh 15-minute Gold cycle after the persisted Build-24 activation timestamp:

1. use the already-admitted point-in-time snapshot and frozen cycle environment;
2. freeze all 15 expected expert-gate identities;
3. run connected experts from evidence known at T;
4. preserve disconnected optional evidence as explicit UNKNOWN rather than substitute/backfill it;
5. freeze dependency state, selector state and the final research-only AIDY view;
6. do not read the target-window outcome;
7. after the existing cycle outcome resolver has 15 complete M1 bars, score gate/subcalculator opinions and the final AIDY view;
8. update permanent environment-specific trust scorebooks without rewriting the frozen cycle.

## Runtime/storage

Versions:
- shadow runtime: `aidy_gold_expert_shadow_v1`
- scorecard: `aidy_gold_expert_scorecard_v1`
- D1 migration: `0027_gold_expert_shadow_scorecard.sql`

New D1 tables:
- `aidy_gold_expert_shadow_runtime_state`
- `aidy_gold_expert_shadow_cycles`
- `aidy_gold_expert_gate_snapshots`
- `aidy_gold_expert_subcalculator_snapshots`
- `aidy_gold_meta_view_results`
- `aidy_gold_expert_shadow_sync_health`

The existing Build-3 tables remain the canonical expert outcome/context-score stores.

## Gate coverage

All 15 expected gates are represented every eligible cycle.

Live-computable from the current admitted PIT candle/environment feed:
- M5 Price Structure
- M15 Price Structure
- H1 Price Structure
- H4 Price Structure
- D1 Context
- Price Location
- Momentum / Impulse
- Liquidity / Reclaim
- Volatility / Jump
- Session / Participation

Retained explicitly UNKNOWN until a valid live source is connected:
- Macro / Event
- Rates / USD / Cross-Asset
- Futures / Microstructure
- News / Movement Mechanism
- Analogue / Episode

UNKNOWN gates have zero invented directional authority.

## Safety and PIT boundaries

- activation is persisted before the first eligible Build-24 cycle;
- pre-activation cycles cannot be backfilled into the prospective programme;
- exact admitted snapshot/candles are loaded at the frozen cycle as-of;
- later outcomes never enter packet, dependency, selector or meta-view construction;
- scoring reads only already-resolved `aidy_gold_cycle_outcomes`;
- immutable/conflict-safe inserts make restarts idempotent;
- Provider Context exposes the scorecard read-only;
- the scorecard is not an input to private-forward decision construction;
- formal-forward OFF;
- AIDY live-money authority OFF;
- Super Signals owner 1% risk unchanged.

## Engineering acceptance

Implementation PR: #238  
Tested head: `a0b8710abc3fe4ea569deed868ea6538294169ad`  
Implementation merge: `6644892d12be6ae497f07db2a69119eaa58e0d27`

- Build-24 acceptance run `35623113260`: PASS
- semantic gate run `35623113461`: PASS
- focused Build-24/component tests: **103 passed**
- full repository regression: **1664 passed**
- Day-53 feed/live-forward safety workflows on the exact PR head: PASS

Public Worker health after merge already proves:
- capture enabled;
- Twelve Data/public-independent;
- direct cron;
- `aidy_gold_expert_shadow_v1`;
- `aidy_gold_expert_scorecard_v1`;
- fresh scheduled capture + Provider Context;
- formal-forward disabled.

## Live forward completion gate

One-shot live acceptance PR #239, run `35623618474`.

Already passed:
- remote D1 migration/schema;
- Build-24 Worker deploy;
- Worker health/safety;
- first genuine prospective shadow cycle with all 15 gate identities.

Still required before Build 24 may be called COMPLETE:
- target 15-minute window finishes naturally;
- existing outcome resolver writes the realised result;
- all 15 gate packets are represented in the outcome ledger;
- context scorebook is non-empty/updated;
- final AIDY meta view is scored;
- sync health remains OK.

This final wait is intentional evidence that the implementation is not using hindsight.

## Interpretation

Build 24 starts permanent prospective learning. Passing it proves the machinery is running prospectively and can accumulate real market evidence. It does **not** by itself prove profitable predictive edge and does not authorize live-money decisions.

