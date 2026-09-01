# Day 39 — Controlled strategy promotion, multiple-testing controls and rollback

## Scope

Day 39 adds a controlled learning layer above the accepted Day 32 experiment registry and Day 37 frozen replay/holdout harness. It does **not** authorize autonomous strategy changes or live trading.

The layer creates immutable strategy/config identities across feature, retrieval, composer, prompt, model and safety versions. Champion and challenger records are append-only. Promotion or rollback changes only the active-version pointer through a separately digested registry event; prior versions remain preserved.

## Required evidence before promotion

A challenger must be bound before evaluation to:

- an immutable champion version digest;
- an immutable challenger version digest;
- a frozen promotion-policy digest;
- the complete Day 32 trial count;
- a preregistered evaluation identity and chronological holdout identity;
- a valid Day 37 holdout-access record.

Failed, null and insufficient attempts remain part of the trial history and selection-bias accounting. The same holdout cannot be recycled for tuning.

## Promotion policy

Promotion is deliberately non-compensatory.

- At least three primary metrics must be pre-specified.
- Every primary metric must be non-degrading.
- A configured minimum number of primary metrics must meet their improvement thresholds.
- Every safety metric must be non-degrading.
- A terminal `passed` evaluation trial is required.
- If a Sharpe-style performance claim is supplied, Deflated Sharpe Ratio evidence is required and uses the complete verified trial count.
- If no Sharpe claim exists, Day 39 records trial-count-only multiple-testing control and does not invent a DSR.
- Owner approval is still required before any registry change.

A single attractive metric cannot compensate for weaker safety, grounding, stability, restraint or another pre-specified primary dimension.

## Deflated Sharpe boundary

Day 39 implements a versioned Deflated Sharpe calculation when Sharpe is actually claimed. The trial count is the full verified Day 32 registry, including failed/null/insufficient attempts. This is a multiple-testing/selection-bias control, not proof of predictive edge.

The architecture acceptance uses synthetic fixture statistics only to exercise the positive code path. They are not AIDY performance evidence and cannot promote a real strategy.

## Rollback

Rollback is append-only and deterministic in target/trigger semantics, but manual in execution.

Allowed triggers are limited to:

- safety regression;
- data-integrity failure;
- strategy-contract violation;
- forced model/API deprecation;
- objectively documented market-structure change.

Performance disappointment by itself is not a valid Day 39 rollback trigger. The rollback target must already exist as an immutable registered version.

## Architecture acceptance fixture

The acceptance harness creates two non-live fixture strategy versions, four preregistered trials (`null`, `insufficient`, `failed`, `passed`), a valid holdout-access record, a multiple-testing report, a positive promotion fixture and a safety-regression rollback fixture. It then verifies that the original champion is restored without deleting or rewriting either strategy version.

The acceptance summary must state all of the following:

- `architecture_fixture_only=true`;
- `actual_strategy_promotion_performed=false`;
- `promotion_authorized_for_live_strategy=false`;
- `predictive_edge_claimed=false`;
- `trading_gate_created=false`;
- broker, Telegram and Super Signals side effects are false.

## BigQuery evidence

The exact-head acceptance run persists append-only/idempotent evidence to:

- `research_day39_strategy_versions`;
- `research_day39_trial_registry`;
- `research_day39_registry_events`;
- `research_day39_promotion_summary`.

A repeated run at the same code head must reconcile to identical payload digests. A changed payload under the same immutable identity is a hard failure.

## Explicit exclusions

Day 39 does not:

- promote any real AIDY strategy;
- create a live trading gate;
- claim predictive edge;
- weaken deterministic safety gates;
- allow self-modification;
- add broker, Telegram or Super Signals execution authority;
- reuse Day 38's inconclusive J16/J21 evidence as a positive promotion signal.
