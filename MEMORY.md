# AIDY Repository Memory

Updated: 2026-09-21

This file is the repo-level handoff entry point for the live AIDY Gold-learning system.


## Build 2 — Expert Gate Contract v1 COMPLETE

Build 2 of the environment-aware expert-gate programme is complete and engineering-proven.

Contract:
`aidy_gold_expert_gate_contract_v1`

What Build 2 adds:
- every future expert gate must bind to one verified frozen Environment v3 packet;
- every gate gets a separate specialist mini-environment with its own stable digest/key;
- evidence inputs carry source/path/observed timestamp/state/value/provenance and immutable value digests;
- sub-calculators have explicit identity/version/role/dependency family/state/vote/strength/evidence refs/observation/explanation;
- directional, context-only, NEUTRAL, ABSTAIN and UNKNOWN are explicit contract states;
- missing evidence cannot manufacture a directional conclusion;
- context-only experts cannot accidentally vote bullish/bearish;
- a bullish/bearish gate conclusion requires a matching scoreable sub-calculator;
- internal conviction is stored separately from historical reliability;
- every readable explanation/contradiction must cite a real calculator or evidence input;
- future/outcome-labelled fields and future-dated evidence fail closed;
- packet, mini-environment, evidence and calculator digests make later mutation detectable;
- live-money authority remains false and research-only remains true.

Acceptance on PR #202:
- Evidence Semantic Change Gate: PASS;
- static checks: PASS;
- focused Build 2/regression gate: PASS;
- focused workflow tests: 108 passed;
- full repository regression: 1360 passed.

Build 2 is a contract/foundation library. It does not yet change live AIDY gate reasoning or weights, so no Worker deployment is required for completion.

**Next:** Build 3 — Conditional Trust & Score Engine v3. Build 3 will give each gate and each scoreable sub-calculator different historical reliability under different environments, with small-sample shrinkage and hierarchical backoff.

## Build 1 — Environment Contract v3 COMPLETE

Build 1 of the environment-aware expert-gate programme is complete and production-verified.

Live contract: `aidy_gold_cycle_environment_v3`.

Merged implementation/verification commits:
- `2b42c3484254a7fd50508f8a2e201d6d652c353e` — Environment Contract v3;
- `968909df73eada5bc9603ea45894395b54ca2c9b` — deploy-gate coverage;
- `3cab838f7f7308bbcd8827220ff68a64ea3352b9` — live v3 verification hardening.

Build 1 changes the environment spine only. It adds a canonical dimension registry, a factorised global environment, explicit data-quality state, 15-minute UTC clock buckets, weekend/pre/post-weekend state, explicit PIT/hindsight rejection, factor-specific keys and a compact global-core key. It deliberately removes the old monolithic `full_environment` scope so later expert gates can use smaller specialist mini-environments without fragmenting learning into near-unique combinations.

Build 1 does **not** upgrade M5/M15/H1/H4/D1 decision logic. Those expert-gate builds come later after the shared contract and scoring foundations are accepted.

Engineering acceptance: semantic-change gate PASS; static checks PASS; focused market-data tests PASS; full repository regression PASS (1346 tests). Production deployment and live D1 verification PASS.

## Read first

Authoritative current architecture and rationale:
`docs/current-gold-learning-state.md`

That document explains:
- the 15-minute Gold cycle learner;
- the canonical PIT-safe cycle-start environment;
- the full-toolbox marker model;
- contextual marker scoring;
- +2/+1/0/-1/-2 outcome scoring;
- learned trust multipliers;
- historical cycle analogues;
- why environment facts are separated from directional predictions;
- permanent execution/risk boundaries.

## Current live environment brain

The live cycle-start environment contract is:
`aidy_gold_cycle_environment_v3`

AIDY freezes the factual market environment before each target 15-minute window and stores:
- session + session phase;
- M5/M15/H1/H4/D1 state;
- recent 5m/15m/60m path;
- exact Gold location for audit;
- repeatable price-location buckets for learning;
- distance/side relative to known liquidity references;
- prior-day/Asia/session range position;
- sweep/reclaim state;
- volatility/jump state;
- scheduled-event proximity where live evidence exists;
- cross-market availability/state;
- compound regime;
- explicit UNKNOWN fields.

Exact values remain in the audit record. Learning uses repeatable buckets so similar market
conditions can accumulate meaningful sample sizes.

## Contextual learning

The marker brain is:
`aidy_gold_contextual_marker_brain_v2`

Each cycle:
1. freezes the environment;
2. evaluates the complete canonical toolbox;
3. creates directional markers only where the evidence legitimately supports a direction;
4. retrieves marker performance from the most specific sufficiently-sampled environment;
5. applies bounded learned trust;
6. freezes AIDY's view and reasons;
7. waits for the complete 15-minute outcome;
8. scores each marker;
9. updates contextual scorebooks.

Current marker outcome scores:
- +2 = correct on a meaningful/large move;
- +1 = correct on a normal move;
- 0 = unavailable/unscoreable;
- -1 = wrong on a normal move;
- -2 = wrong on a meaningful/large move.

Current large-move threshold:
`abs(realised 15m return) >= 5 bps`.

Learned marker multipliers stay bounded to 0.5x-1.5x and use sample-size minimums before
specific environment scopes are trusted.

## Live proof

Build 1 production deployment run `35576676324` completed successfully.

Worker version:
`a20dcfe9-cd46-40c2-aef5-5d6c524cc6c1`

A real stored Gold cycle for `2026-09-21T08:15:00+00:00`, frozen at
`2026-09-21T08:10:56.620000+00:00`, proved:

- environment version: `aidy_gold_cycle_environment_v3`;
- environment key: `envcore_dbc84cde1e97205580e27172f2e1a756`;
- environment schema: `aidy_gold_environment_contract_schema_v1`;
- registered environment dimensions: 34;
- monolithic full-environment key used: 0;
- legacy `full_environment` scopes: 0;
- toolbox items considered: 34;
- toolbox trace count: 34;
- environment toolbox coverage: 34;
- missing readable tool states: 0;
- missing score contexts: 0;
- future-values used: 0;
- live-money authority: 0.

The minute capture cron remained present, capture remained enabled, market source remained
Twelve Data/public-independent, and formal-forward remained OFF.

## Permanent boundaries

Do not silently change:
- Super Signals execution;
- MetaAPI / MT5 / Vantage;
- owner 1% risk;
- provider activation rules;
- formal-forward/live-money authority.

The AIDY Gold-learning layer remains research/shadow intelligence unless separately and
explicitly graduated.

## Why this exists

The owner wants AIDY to build an evidence-backed "impression brain" over weeks: understand
the factual Gold environment first, then learn which tools deserve more or less trust under
those conditions. The goal is not one universal tool ranking; it is conditional trust by
market environment.

If this file and `docs/current-gold-learning-state.md` disagree, treat the more recently
updated file on `main` as authoritative and reconcile them before changing live learning logic.

## 2026-09-21 live-learning hardening

The cycle learner now treats every canonical toolbox item as an explicit reasoning input on every cycle. Each tool writes a human-readable condition state, including readable buckets such as liquidity intensity (none/low/medium/high), reclaim side, reference-distance bucket, session phase, timeframe direction, volatility state, event proximity and cross-market coverage, plus a stable condition key. A capability must be recorded as a directional vote, context used, downstream dependency, explicit unavailable, or explicit unknown. Silent omission is not allowed.

Outcome resolution was also hardened so old incomplete windows cannot starve newer complete 15-minute cycles. Only matured cycles with all 15 decision-admitted M1 bars enter the scoring batch. This protects continuous marker scoring and contextual weight updates.


## Readable calculator context

Directional calculators now carry the exact learned context that selected their live weight. The reason payload includes the selected scope key, a stable context payload, and a human-readable label such as session=asia, session_phase=late_gt240m, liquidity=low_side_reclaim, liquidity_intensity=low. This makes the learned multiplier auditable and lets future reviews see not only which calculator AIDY trusted, but the repeatable market condition under which that trust was earned.

The deploy gate also verifies that every canonical toolbox item has a readable state and explicit reasoning action in the live cycle trace, and that the environment coverage count matches the full toolbox count.


## Intraday evidence self-heal v2

A fresh scheduled capture can still be Provider-Context-ineligible when an older minute inside the latest H1/H4 evidence bucket is missing. The previous self-heal handled only gaps whose entire span was <=30 minutes, so a small number of missing minutes spread across a wider H1 bucket could remain stuck indefinitely.

Self-heal v2 keeps the safety limits but can split one repair into at most two bounded vendor requests. Total missing minutes remain capped at 30 and each request span remains capped at 30 minutes. Larger gaps still fail closed. After successful repair the normal canonical capture is rerun so Provider Context and the AIDY cycle learner receive a fresh complete snapshot.
