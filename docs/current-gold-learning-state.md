# Current Gold Learning State

Authoritative current design note for the AIDY Gold learning runtime.

Updated: 2026-09-21

## Why this exists

AIDY must not learn that a tool is simply "good" or "bad" in all markets.

Gold behaves differently depending on the factual environment present at the moment a
decision is made. A bearish M15 marker near an unswept low during quiet Asia is not the
same situation as a bearish M15 marker after a London low sweep/reclaim with expanding
volatility and a bullish H4.

The learning loop therefore separates:

1. **cycle-start environment facts** — what was already known before the target window;
2. **toolbox markers** — directional opinions produced from qualified evidence;
3. **frozen AIDY view** — the combined impression before the outcome;
4. **realised outcome** — attached only after the full window closes;
5. **contextual scores** — how each marker performed in that environment.

This is research intelligence only. It does not create broker or live-money authority.

## Live Gold cycle architecture

The active 15-minute learning loop is:

`freeze environment -> inspect full toolbox -> create legitimate markers -> retrieve contextual trust -> form/freeze view -> observe outcome -> score markers -> update contextual scorebooks`

AIDY evaluates the full canonical toolbox every cycle. Directional tools can become
scoreable markers. Context-only or unavailable tools remain explicit and are never
forced into fake bullish/bearish votes.

## Canonical cycle-start environment

Environment contract:
`aidy_gold_cycle_environment_v2`

The environment is frozen before the target 15-minute window starts.

It stores exact facts for audit, but it does **not** use exact price values as the primary
learning identity. Exact values would make almost every cycle unique and destroy useful
sample accumulation.

Instead AIDY learns from repeatable condition buckets.

### Exact facts retained for audit

Where PIT-safe evidence exists, the frozen environment keeps:

- decision timestamp and lead time before the target cycle;
- session and minutes since Asia/London/New York opens;
- M5/M15/H1/H4/D1 completed-bar state;
- recent 5m/15m/60m path and return/range;
- current Gold mid;
- exact distances to known price references;
- exact positions inside prior-day, Asia and session ranges;
- liquidity sweep/reclaim proxies;
- prior-day breakout/reclaim state;
- realised-volatility/jump/vol-of-vol/GVZ/IV-RV availability state;
- scheduled-event timing and minutes to the next known event;
- known cross-market series availability;
- current compound regime;
- explicit unknowns.

Unavailable evidence remains UNKNOWN.

### Repeatable learning dimensions

The environment fingerprint buckets those facts into conditions that can recur:

- session;
- session phase;
- UTC weekday;
- observed prior 15-minute state;
- M5/M15/H1/H4/D1 direction;
- recent displacement regime;
- recent range-expansion/compression regime;
- 60-minute direction;
- nearest known reference;
- which side of that reference Gold is on;
- distance-to-reference band;
- prior-day range zone;
- Asia range zone;
- active-session range zone;
- liquidity reclaim signature;
- prior-day breakout/reclaim state;
- volatility state;
- jump/continuous state;
- scheduled-event timing/proximity;
- number of known cross-market inputs;
- compound market regime.

Two cycles with slightly different prices but the same meaningful condition buckets may
share the same environment identity. A real condition change — for example moving from
2 bps to 10 bps from a liquidity reference — changes the environment.

## Contextual scorebooks

Marker performance is maintained at multiple levels so AIDY can learn broad patterns
first and become more specific as evidence grows.

Current scopes:

- global;
- session;
- session phase;
- session + observed 15m state;
- higher-timeframe alignment;
- liquidity + price location;
- session + liquidity;
- location + higher-timeframe structure;
- session + movement regime;
- volatility + movement regime;
- session + state + event timing;
- event regime;
- full environment.

AIDY chooses the most specific sufficiently-sampled scorebook and falls back to broader
contexts when evidence is thin.

## Marker scoring

Current bounded impact score:

- +2: correct on a meaningful/large 15-minute move;
- +1: correct on a normal directional move;
- 0: unavailable or legitimately unscoreable;
- -1: wrong on a normal directional move;
- -2: wrong on a meaningful/large move.

Current large-move threshold:
`abs(realised 15m return) >= 5 bps`.

Plain accuracy is stored separately from impact score.

Learned weight multipliers remain bounded between 0.5x and 1.5x. Bootstrap weights remain
visible and immutable in each frozen marker observation.

## Important learning rule

Environment facts are not automatically predictions.

Example:
- H4 bullish is a factual environment observation.
- The H4 marker can then be scored on whether that observation was useful for the next
  15-minute direction under similar environments.

This prevents AIDY from confusing "what the market currently is" with "what happens next."

## Historical and forward learning

Historical M15 cycle memory is retrospective research only and remains non-PIT for live
authority. Forward cycle views are frozen before their target windows and scored only
after complete admitted M1 evidence exists.

The environment/marker brain must never rewrite an old frozen view after seeing the
result.

## Permanent safety boundaries

This learning layer does not change:

- Super Signals execution;
- MetaAPI / MT5 / Vantage;
- owner 1% risk;
- provider activation rules;
- formal forward/live-money authority.

Formal forward remains OFF unless separately and explicitly graduated.

## Current toolbox rule

The canonical toolbox is inspected every cycle.

A capability can be:
- a scoreable directional marker;
- a factual environment/context input;
- downstream-only for that cycle;
- known research not live connected;
- known unknown.

AIDY must record the status instead of silently ignoring a tool or inventing missing
evidence.

## Build rationale

The purpose of this architecture is to let weeks of forward cycles create a useful
"impression brain": AIDY gradually learns which evidence deserves more trust in specific
Gold conditions, while preserving an auditable chain from factual environment -> marker
history -> learned weight -> decision -> outcome.

## 2026-09-21 live-learning hardening

The cycle learner now treats every canonical toolbox item as an explicit reasoning input on every cycle. Each tool writes a human-readable condition state, including readable buckets such as liquidity intensity (none/low/medium/high), reclaim side, reference-distance bucket, session phase, timeframe direction, volatility state, event proximity and cross-market coverage, plus a stable condition key. A capability must be recorded as a directional vote, context used, downstream dependency, explicit unavailable, or explicit unknown. Silent omission is not allowed.

Outcome resolution was also hardened so old incomplete windows cannot starve newer complete 15-minute cycles. Only matured cycles with all 15 decision-admitted M1 bars enter the scoring batch. This protects continuous marker scoring and contextual weight updates.


## Readable calculator context

Directional calculators now carry the exact learned context that selected their live weight. The reason payload includes the selected scope key, a stable context payload, and a human-readable label such as session=asia, session_phase=late_gt240m, liquidity=low_side_reclaim, liquidity_intensity=low. This makes the learned multiplier auditable and lets future reviews see not only which calculator AIDY trusted, but the repeatable market condition under which that trust was earned.

The deploy gate also verifies that every canonical toolbox item has a readable state and explicit reasoning action in the live cycle trace, and that the environment coverage count matches the full toolbox count.


## Intraday evidence self-heal v2

A fresh scheduled capture can still be Provider-Context-ineligible when an older minute inside the latest H1/H4 evidence bucket is missing. The previous self-heal handled only gaps whose entire span was <=30 minutes, so a small number of missing minutes spread across a wider H1 bucket could remain stuck indefinitely.

Self-heal v2 keeps the safety limits but can split one repair into at most two bounded vendor requests. Total missing minutes remain capped at 30 and each request span remains capped at 30 minutes. Larger gaps still fail closed. After successful repair the normal canonical capture is rerun so Provider Context and the AIDY cycle learner receive a fresh complete snapshot.
