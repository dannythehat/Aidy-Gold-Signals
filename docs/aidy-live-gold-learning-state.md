# AIDY Live Gold Learning State

Last architectural update: 2026-09-21

## Purpose

AIDY is a Gold-first research and decision-intelligence system.

The current learning loop is designed to answer a specific question:

> Given the market environment that was objectively known before a 15-minute Gold cycle began, which evidence tools have historically been trustworthy in that type of environment?

This is deliberately different from learning one universal ranking of indicators. A marker may be useful in London trend expansion and poor in Asia range compression. AIDY therefore learns marker reliability **conditional on environment**.

This document is the repo-local handoff for the live Gold learning architecture. It should be read before changing the cycle learner, marker brain, Gold toolbox, movement memory, or Provider Context.

## Core learning flow

```
facts known before cycle
    -> canonical cycle-start environment
    -> inspect complete toolbox
    -> freeze legitimate directional markers
    -> retrieve contextual marker history
    -> apply bounded learned trust
    -> freeze 15-minute Gold view + reasons
    -> observe realised 15-minute path
    -> score contributing markers
    -> update contextual scorebooks
    -> reuse only after sample thresholds are met
```

No future values may enter the environment or frozen view.

## Cycle-start environment

The canonical environment contract is:

- module: `src/aidy/gold_cycle_environment.py`
- contract: `aidy_gold_cycle_environment_v2`

It separates **exact audit facts** from **repeatable learning dimensions**.

### Exact facts retained for audit

At decision time AIDY may record, where genuinely available:

- absolute decision timestamp and target cycle start;
- decision lead time;
- deterministic Gold session and minutes since relevant session open;
- M5 / M15 / H1 / H4 / D1 completed-bar structure;
- recent 5m / 15m / 60m path, return and range;
- current Gold mid;
- distance/side versus prior-day, Asia, session and opening-range references;
- position inside prior-day / Asia / session / opening ranges;
- round-number distances;
- measured liquidity sweep/reclaim proxies;
- prior-day breakout/reclaim state;
- realised-volatility / jump / vol-of-vol / GVZ / IV-RV availability state;
- scheduled-event state, next event and minutes to it;
- known cross-market series availability;
- compound regime;
- explicit unknowns.

These values are audit evidence. Exact continuous values are **not** used directly as environment identity.

### Repeatable learning dimensions

For learning, exact facts are reduced to repeatable categories such as:

- session;
- session phase;
- weekday;
- observed 15m state;
- M5 / M15 / H1 / H4 / D1 direction;
- recent displacement/range regime;
- 60m direction;
- nearest named reference level;
- side of that reference;
- distance-to-reference band;
- prior-day / Asia / active-session location zone;
- liquidity reclaim signature;
- prior-day breakout state;
- volatility/jump state;
- event timing/proximity;
- number of known cross-market series;
- compound regime.

This is intentional. Two cycles at slightly different exact prices should still be comparable if they represent the same market condition.

## Environment scorebooks

Every scoreable marker can accumulate evidence under multiple scopes.

Current scopes include:

1. global;
2. session;
3. session phase;
4. session + observed state;
5. higher-timeframe configuration;
6. liquidity + price location;
7. session + liquidity;
8. location + higher-timeframe structure;
9. session + movement/range regime;
10. volatility + movement regime;
11. session + state + event timing;
12. event + regime;
13. full environment fingerprint.

AIDY selects the most specific scorebook with enough observations and falls back to broader scopes while evidence is thin.

Specific environments are therefore allowed to become useful gradually without overfitting a handful of cycles.

## Toolbox rule

The canonical toolbox is defined in:

`src/aidy/gold_toolbox_registry.py`

Every known capability is considered every cycle.

Each capability is recorded as one of:

- scoreable directional marker;
- environment/context marker;
- downstream context not available in the standalone cycle;
- known research not live-connected;
- known unknown.

AIDY must never invent a directional vote merely so that a capability can receive a score.

Directional markers are scored only when the underlying evidence legitimately implies bullish, bearish or neutral.

Context-only evidence helps describe the environment in which other tools are scored.

## Marker scoring

The contextual marker brain is implemented in:

`src/aidy/gold_marker_brain.py`

Impact score range:

- +2 = correct on a meaningful/large move;
- +1 = correct on a normal move;
- 0 = unavailable/unscoreable;
- -1 = wrong on a normal move;
- -2 = wrong on a meaningful/large move.

Current large-move threshold:

`abs(realised 15m return) >= 5 bps`

Plain accuracy is stored separately from impact score.

This prevents a few large moves from hiding ordinary hit rate while still rewarding/penalising important calls more heavily.

## Learned weights

Original directional weights remain bootstrap priors.

Contextual marker history creates a bounded learned multiplier:

- minimum: 0.5x;
- maximum: 1.5x.

Specific contexts require minimum samples before they can be selected. Broader scorebooks are used while evidence is sparse.

This prevents one or two outcomes from rewriting AIDY's behaviour.

## 15-minute cycle memory

The cycle learner is implemented in:

`src/aidy/gold_cycle_memory.py`

Each frozen cycle view stores:

- bullish / bearish / neutral / unknown view;
- confidence;
- reasoning summary;
- supporting reasons;
- contradictory reasons;
- unavailable evidence;
- toolbox considered;
- toolbox actually used;
- selected marker score profile;
- learned multiplier/effective weight;
- canonical environment;
- immutable digest.

After the window closes, the outcome stores:

- realised direction;
- return bps;
- MFE;
- MAE;
- exact-direction score;
- post-result reasoning review.

The original reasoning is never rewritten after the outcome is known.

## Historical memory

Historical 15-minute cycle analogues are descriptive research evidence.

They may help AIDY ask:

- have I seen this day/path before?
- how long did the state persist?
- what usually followed?
- when did similar sequences reverse?

Retrospective history must remain explicitly non-PIT and cannot silently create live-money authority.

## Provider Context

Provider Context exposes:

- Gold State Engine;
- movement investigation;
- movement analogues where applicable;
- canonical toolbox manifest;
- cycle memory;
- latest marker profiles;
- current environment summary;
- resolved cycle scoring available by the requested as-of timestamp.

This allows downstream reasoning to audit the complete chain:

```
world state -> contextual score history -> marker weighting -> AIDY view -> realised result
```

## Gold movement learning

The separate abnormal-movement loop remains active.

It detects meaningful Gold moves in either direction, investigates evidence-backed mechanisms, stores immutable episodes, waits for genuine future outcomes, then creates learning cards.

The cycle environment brain complements this system. It does not replace it.

## Safety boundary

This learning architecture is research-only.

It does not itself change:

- Super Signals broker execution;
- MetaAPI;
- MT5;
- Vantage;
- provider activation rules;
- owner 1% risk;
- live-money authority.

Any future graduation of AIDY into trading authority requires a separate explicit acceptance gate.

## Why this architecture exists

A fixed-weight rule such as “M15 matters more than H4” cannot adapt to different Gold environments.

The intended behaviour is instead:

> In this exact type of environment, which pieces of evidence have actually been useful over repeated resolved cycles?

Over weeks of forward cycles AIDY should accumulate an increasingly useful conditional memory of:

- what tends to matter;
- what tends to fail;
- where a tool is strong;
- where it is weak;
- which contradictions deserve respect;
- and when evidence is too thin to claim confidence.

Unknown remains UNKNOWN. Sample size remains visible. Exact reasons remain auditable.
