# AIDY Memory — Gold Learning Brain

Last updated: 2026-09-21

This file is the repo-local handoff for the live Gold-learning architecture. Read this before changing AIDY's cycle-learning, Gold-state, movement-memory, toolbox or Provider Context code.

## Why this exists

AIDY must not behave like a fixed indicator stack. The owner wants AIDY to understand the *environment* Gold is trading in, inspect its full toolbox, form an auditable 15-minute impression, observe what actually happened, score the individual markers that contributed, and gradually learn which evidence deserves more trust under comparable conditions.

The target loop is:

`cycle-start facts -> environment fingerprint -> full toolbox review -> directional markers -> contextual weights -> frozen view/reasoning -> realised 15m outcome -> per-marker score -> environment scorebooks -> better weighting next time`

The 15-minute cycle is one learning lens, not AIDY's entire specification. The wider Gold-first movement/causal-learning architecture remains primary.

## Cycle-start facts

The canonical cycle environment is built before the target 15-minute window starts. It separates factual state from predictive marker opinions.

Exact audit facts include, where PIT-safe and available:
- UTC decision timestamp and target-window start;
- session and minutes/phase since the active session opened;
- completed M5/M15/H1/H4/D1 structure;
- recent 5m/15m/60m path and range;
- current Gold mid;
- exact distances to prior-day, Asia, session and opening-range references;
- position inside prior-day, Asia, active-session and opening ranges;
- nearest $10/$50 round-number distances;
- measured liquidity sweep/reclaim proxies and breakout/reclaim state;
- realised-volatility/jump/vol-of-vol/GVZ/IV-RV availability state;
- scheduled-event timing and minutes to next known event;
- known cross-market series, their age and their PIT value/unit when present;
- compound regime and explicit unknowns.

Exact continuous values are retained for audit but are not blindly used as the environment identity.

## Repeatable learning dimensions

AIDY learns from categorical/bucketed conditions so similar cycles can actually accumulate together. Current dimensions include:
- session;
- session phase;
- weekday;
- current 15m observed state;
- M5/M15/H1/H4/D1 direction;
- recent displacement/range regime;
- 60m direction;
- nearest structural/liquidity reference;
- side of that reference;
- distance-to-reference band;
- prior-day / Asia / active-session price zone;
- liquidity/reclaim signature;
- prior-day breakout/reclaim state;
- volatility and jump state;
- event timing/proximity;
- cross-market availability/age pattern;
- compound regime.

Two cycles with slightly different exact Gold prices can therefore share one learnable environment when the actual market condition is equivalent.

## Environment scorebooks

Directional marker results are stored across nested contextual scopes rather than one global score.

Current scopes:
1. global;
2. session;
3. session phase;
4. session + observed 15m state;
5. higher-timeframe state;
6. liquidity + price location;
7. session + liquidity;
8. location + higher-timeframe structure;
9. session + movement/range regime;
10. volatility + movement regime;
11. session + state + event timing;
12. event regime;
13. full environment.

AIDY uses the most specific scope with sufficient sample size and falls back to broader scopes while evidence is thin.

## Toolbox rule

The canonical Gold toolbox must be considered every cycle.

Each capability is recorded as:
- a scoreable directional marker when it can legitimately emit a PIT-safe bullish/bearish/neutral vote;
- a factual environment/context marker;
- downstream-only context unavailable to the standalone cycle;
- known research not live/PIT-connected;
- known unknown.

Unavailable or non-directional tools must never be given fabricated directional votes merely so they can receive a score.

## Marker scoring

The live contextual brain uses impact-aware scoring:
- +2 = correct on a meaningful/large 15m move;
- +1 = correct on a normal directional move;
- 0 = unavailable/not legitimately scoreable;
- -1 = wrong on a normal directional move;
- -2 = wrong on a meaningful/large move.

Current large-move threshold: `abs(realised 15m return) >= 5 bps`.

Plain accuracy is stored separately from impact score.

Original marker weights remain bootstrap priors. Learned trust is bounded between 0.5x and 1.5x and strengthens gradually with sample size. A few observations must not dominate the brain.

## Existing live proof before environment v2

The first resolved cycle-learning example was the 2026-09-21 04:00-04:15 UTC miss:
- AIDY view: bearish;
- realised direction: bullish;
- realised return: +6.8 bps;
- H4 bullish marker: +2;
- H1 bearish: -2;
- M15 structure bearish: -2;
- recent M15 move bearish: -2;
- M5 bearish: -2;
- abnormal movement detector bearish: -2.

That produced six marker results across the contextual scorebooks and proved the marker-outcome loop was operational.

## Environment v2 purpose

Environment v1 proved contextual scoring but was too coarse. Environment v2 adds the market-location and timing geometry the owner identified as essential: where Gold is relative to liquidity and structural references, where it sits inside active ranges, how far it is from those levels, where the session is in its lifecycle, what the recent path/volatility regime is, and what scheduled/cross-market facts are actually known at the cycle start.

The reason is simple: an M15 bearish marker should not be assumed to behave the same when Gold is in open space versus when it has just swept and reclaimed a prior low while H4 remains bullish.

## Safety boundaries

This brain is research/shadow intelligence only.

Do not silently change:
- Super Signals execution;
- MetaAPI/MT5/Vantage;
- owner risk rule (1% per trade);
- provider activation/best-side rules;
- formal-forward/live-money authority.

No-hindsight rule remains strict: cycle-start environment and marker reasoning are frozen before the target window; outcomes attach only after complete forward evidence exists.

## Completion rule

A Gold-learning build is not complete until:
1. repo implementation is merged;
2. tests/regression pass;
3. Cloudflare Worker is deployed;
4. minute cron and health versions are verified;
5. a live cycle using the new contract is observed where timing permits;
6. this repo-local memory is updated with what changed and why;
7. the separate `dannythehat/Memory` AIDY handoff is updated and reread.
