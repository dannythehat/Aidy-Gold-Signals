# AIDY Repository Memory

Updated: 2026-09-21

This file is the repo-level handoff entry point for the live AIDY Gold-learning system.

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
`aidy_gold_cycle_environment_v2`

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

Final environment-v2 audit observed a live cycle for:
`2026-09-21T05:45:00+00:00`

The frozen environment showed:
- environment version: `aidy_gold_cycle_environment_v2`;
- session: Asia;
- session phase: late >240m;
- nearest reference: `asia_opening_30m_low`;
- Gold below that reference;
- distance band: 3-8 bps;
- prior-day zone: lower-middle;
- liquidity signature: low-side reclaim;
- H1 bearish;
- H4 bullish;
- 4 known cross-market series;
- 34 toolbox items considered;
- 13 environment scopes;
- future-values used: 0;
- live-money authority: 0.

Cycle-sync health was also live and `status=ok`.

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
