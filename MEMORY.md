# AIDY Repository Memory

Updated: 2026-09-21

This file is the repo-level handoff entry point for the live AIDY Gold-learning system.














## Build 14 — Session / Participation Expert COMPLETE

Build 14 of the environment-aware expert-gate programme is complete and engineering-proven.

Expert:
`aidy_gold_session_participation_expert_v1`

What Build 14 adds:
- DST-safe regional session state using the existing London/New York session engine;
- explicit active-market list and London/New York overlap state;
- session phase retained from the frozen cycle environment;
- exact completed-M1 15-minute realised volatility and range;
- matched weekday × UTC 15-minute clock baselines;
- event-clean baseline population preferred when enough clean history exists;
- unusual/high/quiet activity state from clock-matched volatility and range percentiles;
- existing Day-42 genuine GC trade-volume and pre-trade BBO spread z-scores admitted as descriptive participation context when qualified;
- retrospective GC context remains research-only unless PIT-qualified;
- event-time confounding explicitly represented so unusual activity is not automatically attributed to the session;
- Build-3 conditional trust scopes for session activity, clock participation and event confounding;
- no hardcoded session-direction assumptions.

Acceptance on PR #217 candidate:
- Evidence Semantic Change Gate: PASS;
- static checks: PASS;
- focused workflow suite: 263 passed;
- full repository regression: 1515 passed;
- UK DST transition: PASS;
- US DST transition: PASS;
- London/New York overlap identification: PASS;
- matched weekday-clock activity baseline: PASS;
- event-confounded history exclusion when enough clean history exists: PASS;
- event-time confounding representation: PASS;
- genuine GC volume/spread kept descriptive: PASS;
- unqualified GC context remains UNKNOWN: PASS;
- insufficient clock history remains UNKNOWN: PASS;
- PIT/no-future and chronological freeze: PASS;
- no session-direction rule: PASS.

Build 14 remains research/shadow intelligence. It does not replace the live marker brain, change Super Signals execution/provider rules, alter the owner 1% risk directive, or grant live-money authority. No Worker deployment is required for this expert library alone.

**Next:** Build 15 — Macro / Event Expert. It will turn the existing official event stack into a Gold-specific specialist using event classes, pre-event features, consensus/actual/revisions, Gold-learned event tiers, standardized surprise where valid, clustering, post-release confirmation and historical conditional response, while preserving first-observed timestamps and no-hindsight boundaries.


## Build 14 — Session / Participation Expert COMPLETE

Build 14 of the environment-aware expert-gate programme is complete and engineering-proven.

Expert:
`aidy_gold_session_participation_expert_v1`

What Build 14 adds:
- deterministic DST-safe London, New York and Asia regional-session context;
- explicit active-market list and London/New York overlap state;
- current completed-M1 15-minute realised-volatility and range activity;
- exact weekday × UTC 15-minute clock-slot baselines;
- event-clean historical baselines when enough clean samples exist;
- explicit event-time confounding so unusual activity is not automatically attributed to the session;
- qualified genuine GC exchange-volume and pre-trade BBO spread context using the existing GC microstructure baseline;
- unqualified/incomplete GC participation remains UNKNOWN;
- ordinary session activity explicitly cannot count as alpha by itself;
- no hardcoded session-direction rule and no individual-participant identity claim;
- PIT/no-future chronological freeze and Build-3 conditional trust.

Acceptance on PR #217 candidate:
- Evidence Semantic Change Gate: PASS;
- static checks: PASS;
- focused workflow suite: 263 passed;
- full repository regression: 1515 passed;
- London DST transition: PASS;
- New York DST transition: PASS;
- London/New York overlap and active-market identity: PASS;
- exact weekday-clock baseline filtering: PASS;
- event-row exclusion when clean baseline is sufficient: PASS;
- current event-time confounding: PASS;
- genuine GC volume/spread descriptive context: PASS;
- unqualified GC context -> UNKNOWN: PASS;
- no session-direction rule: PASS;
- PIT/no-future and chronological freeze: PASS.

Build 14 remains research/shadow intelligence. It does not replace the live marker brain, change Super Signals execution/provider rules, alter the owner 1% risk directive, or grant live-money authority. No Worker deployment is required for this expert library alone.

**Next:** Build 15 — Macro / Event Expert. It will turn the existing official-source event stack into a Gold-specific specialist with pre-event features, first-observed actuals/revisions, standardized surprise where valid, event clustering, post-release confirmation and Gold-learned event tiers based on independent episodes rather than vendor importance labels.

## Build 13 — Volatility / Jump Expert COMPLETE

Build 13 of the environment-aware expert-gate programme is complete and engineering-proven.

Expert:
`aidy_gold_volatility_jump_expert_v1`

What Build 13 adds:
- a direction-neutral volatility context brain;
- exact completed-M1 15-minute realised volatility;
- clock-normalised volatility percentile using prior observations from the same UTC 15-minute clock bucket;
- compression, expansion and compression-to-expansion transitions;
- qualified PIT jump-versus-continuous state;
- event-proximate jump classification without claiming the event caused the move;
- qualified vol-of-vol context;
- optional GVZ and IV/RV context only when evidence is PIT-qualified;
- sparse or unqualified GVZ/IV remains UNKNOWN;
- simple M15 ATR/RV band retained as the explicit ablation baseline;
- richer-regime complexity earns no automatic influence and must beat the simple ATR baseline on sufficient historical samples;
- Build-3 conditional trust scopes for clock-volatility, jump regime and richer volatility regime.

Acceptance on PR #216 candidate:
- Evidence Semantic Change Gate: PASS;
- static checks: PASS;
- focused workflow suite: 249 passed;
- full repository regression: 1501 passed;
- no forced direction: PASS;
- clock-normalised compression-to-expansion detection: PASS;
- continuous expansion distinguished from jump: PASS;
- event-proximate jump distinguished without causal claim: PASS;
- sparse GVZ/IV remains UNKNOWN: PASS;
- retrospective/unqualified volatility state rejected from PIT context: PASS;
- simple ATR versus richer-regime ablation retained: PASS;
- PIT/no-future and chronological freeze: PASS.

Build 13 remains research/shadow intelligence. It does not replace the live marker brain, change Super Signals execution/provider rules, alter the owner 1% risk directive, or grant live-money authority. No Worker deployment is required for this expert library alone.

**Next:** Build 14 — Session / Participation Expert. It will quantify who is likely active and whether current activity is unusual for this time using DST-safe sessions, session phase/overlap, weekday-clock volatility/range baselines, and historical GC volume/spread baselines where available, with event-time confounding represented explicitly and no hardcoded session-direction rule.

## Build 12 — Liquidity / Reclaim Expert COMPLETE

Build 12 of the environment-aware expert-gate programme is complete and engineering-proven.

Expert:
`aidy_gold_liquidity_reclaim_expert_v1`

What Build 12 adds:
- named high/low reference-level sweep/reclaim proxies from Build-11 location references;
- exact penetration depth in USD and bps;
- reclaim speed in completed M1 bars;
- confirmation-close count;
- retest and retest-hold detection;
- reclaim-candle rejection geometry;
- nearest competing-level distance;
- session/phase and volatility-conditioned trust;
- directional proxy votes only for confirmed/retest-hold reclaims;
- failed/unconfirmed penetrations remain neutral;
- explicit proxy-not-order-flow language in every event;
- retrospective genuine GC-flow rows stored in a separate evidence channel that is never used in the OHLC proxy calculation or expert conclusion.

Acceptance on PR #215 candidate:
- Evidence Semantic Change Gate: PASS;
- static checks: PASS;
- focused workflow suite: 235 passed;
- full repository regression: 1487 passed;
- synthetic high sweep/reclaim/retest: PASS;
- synthetic low sweep/reclaim: PASS;
- no-sweep neutral: PASS;
- failed reclaim not rewarded: PASS;
- competing-level distance: PASS;
- session/volatility trust separation: PASS;
- forbidden fake-order-flow language guard: PASS;
- retrospective genuine GC flow kept separate: PASS;
- gapped M1 fails closed: PASS;
- PIT/no-future and chronological freeze: PASS.

Build 12 remains research/shadow intelligence. It does not replace the live marker brain, change Super Signals execution/provider rules, alter the owner 1% risk directive, or grant live-money authority. No Worker deployment is required for this expert library alone.

**Next:** Build 13 — Volatility / Jump Expert. It will classify clock-normalised volatility, compression/expansion transitions, continuous versus jump behaviour, vol-of-vol and optional IV/RV context when qualified, while remaining direction-neutral.

## Build 11 — Price Location Expert COMPLETE

Build 11 of the environment-aware expert-gate programme is complete and engineering-proven.

Expert:
`aidy_gold_price_location_expert_v1`

What Build 11 adds:
- a true context-only price-location brain;
- frozen prior-day, Asia, active-session and opening-range references from the cycle-start environment;
- confirmed M15/H1 swing references and recent M5/M15 extrema from completed Build-4 bars;
- deterministic round-number references;
- exact distance in USD, bps and ATR units for every reference;
- separate geometric-nearest and structural-priority rankings;
- fully auditable priority tiers/reasons;
- multi-category confluence clusters within 0.25 ATR;
- nearby level bracketing/conflict on both sides within 0.50 ATR;
- Build-3 location-specific trust scopes;
- explicit policy that location alone has no directional edge and cannot vote BUY/SELL without a separately tested reaction rule.

Acceptance on PR #214 candidate:
- Evidence Semantic Change Gate: PASS;
- static checks: PASS;
- focused workflow suite: 223 passed;
- full repository regression: 1475 passed;
- exact nearest-level calculation: PASS;
- structural priority separated from geometric nearest: PASS;
- confluence/conflict representation: PASS;
- round numbers descriptive-only: PASS;
- ATR-normalised distance: PASS;
- missing mid fails closed: PASS;
- PIT/no-future and chronological freeze: PASS.

Build 11 remains research/shadow intelligence. It does not replace the live marker brain, change Super Signals execution/provider rules, alter the owner 1% risk directive, or grant live-money authority. No Worker deployment is required for this expert library alone.

**Next:** Build 12 — Liquidity / Reclaim Expert. It will make sweep/reclaim reasoning measurable through level identity, penetration depth, reclaim speed, confirmation closes, retest, rejection geometry, competing-level distance and session/volatility context, while explicitly keeping OHLC sweep logic as a proxy rather than pretending it is real order flow.

## Build 10 — Momentum / Impulse Expert COMPLETE

Build 10 of the environment-aware expert-gate programme is complete and engineering-proven.

Expert:
`aidy_gold_momentum_impulse_expert_v1`

What Build 10 adds:
- exact completed-M1 backward returns for 1/5/15/30/60 minutes;
- realised-volatility normalisation for each horizon;
- 30-minute persistence and path-efficiency quality;
- recent 5-minute versus prior 5-minute acceleration/deceleration;
- continuation impulse versus persistent drift versus noisy/unconfirmed movement;
- single-bar concentration and an explicit exhaustion/reversal hypothesis;
- a hard guard preventing one oversized final candle from becoming sustained momentum when persistence is poor;
- multi-horizon agreement and family-balanced aggregation;
- regime/clock-conditioned trust using volatility state, session, session phase and 15-minute UTC clock bucket;
- explicit price-expert overlap tags so correlated price-derived influence can be penalised in a later fusion build rather than double-counted;
- contiguous-M1 requirement and PIT/no-future chronological freeze.

Acceptance on PR #213 candidate:
- Evidence Semantic Change Gate: PASS;
- static checks: PASS;
- focused workflow suite: 211 passed;
- full repository regression: 1463 passed;
- clean bullish/bearish continuation impulse: PASS;
- one large final candle does not equal persistent momentum: PASS;
- noisy/choppy direction rejection: PASS;
- gapped/insufficient M1 fails closed: PASS;
- volatility-regime and clock-bucket trust-scope separation: PASS;
- correlated price-expert influence tagging: PASS;
- PIT/no-future and chronological freeze: PASS.

Build 10 remains research/shadow intelligence. It does not replace the live marker brain, change Super Signals execution/provider rules, alter the owner 1% risk directive, or grant live-money authority. No Worker deployment is required for this expert library alone.

**Next:** Build 11 — Price Location Expert. It will answer where Gold is relative to prior-day, Asia, active-session and opening-range references, swings, recent extrema and round numbers, with exact distance/priority/confluence logic and no directional vote unless a separately tested location-reaction rule exists.

## Build 9 — D1 Context Expert COMPLETE

Build 9 of the environment-aware expert-gate programme is complete and engineering-proven.

Expert:
`aidy_gold_d1_context_expert_v1`

What Build 9 adds:
- a true context-only D1 gate rather than another directional BUY/SELL brain;
- slow daily trend, structure, range-location and breakout context from completed D1 bars;
- explicit freshness gating with a 72-hour maximum context age;
- core completeness gating for daily trend/location evidence;
- confirmed daily swing/breakout context allowed to remain UNKNOWN without invalidating otherwise usable fresh D1 trend/location context;
- automatic ABSTAIN from usable context when D1 evidence is stale, missing or genuinely partial;
- zero direct 15-minute directional authority and zero default next-15m weight;
- a historical evaluator that measures context uplift versus a baseline separately from direct D1 directional accuracy;
- Build-3 conditional trust for the D1 context gate and its context calculators.

Acceptance on PR #212 candidate:
- Evidence Semantic Change Gate: PASS;
- static checks: PASS;
- focused workflow suite: 199 passed;
- full repository regression: 1451 passed;
- stale D1 -> ABSTAIN: PASS;
- partial/missing D1 -> ABSTAIN: PASS;
- strong D1 trend cannot emit bullish/bearish gate conclusion: PASS;
- context value vs direct forecast value measured separately: PASS;
- PIT/no-future and chronological freeze: PASS.

Build 9 remains research/shadow intelligence. It does not replace the live marker brain, change Super Signals execution/provider rules, alter the owner 1% risk directive, or grant live-money authority. No Worker deployment is required for this context library alone.

**Next:** Build 10 — Momentum / Impulse Expert. It will distinguish continuation-quality momentum from noisy direction using multi-horizon returns, volatility normalisation, acceleration, persistence, path efficiency, impulse/drift, exhaustion and agreement. One large candle alone must not equal persistent momentum.


## Build 9 — D1 Context Expert COMPLETE

Build 9 of the environment-aware expert-gate programme is complete and engineering-proven.

Expert:
`aidy_gold_d1_context_expert_v1`

What Build 9 adds:
- a true context-only D1 expert rather than another BUY/SELL timeframe brain;
- daily trend, structure, location and breakout context from completed D1 bars;
- explicit freshness gating with a 72-hour maximum context age;
- core daily completeness gating for trend/location inputs;
- swing and breakout context allowed to remain UNKNOWN when pivots are not yet confirmed, without incorrectly invalidating otherwise usable D1 trend/location context;
- stale, missing or materially partial D1 evidence -> ABSTAIN from usable context;
- zero direct 15-minute directional authority and zero default next-15m weight;
- a separate evaluator for context value versus direct directional forecast value;
- Build-3 conditional trust attached to the D1 context gate and sub-calculators;
- context-only dependency/correlation metadata;
- PIT/no-future and chronological-freeze guarantees.

Acceptance on PR #212 candidate:
- Evidence Semantic Change Gate: PASS;
- static checks: PASS;
- focused workflow suite: 199 passed;
- full repository regression: 1451 passed;
- stale D1 abstention: PASS;
- partial/missing D1 abstention: PASS;
- strong D1 trend cannot force a 15-minute direction: PASS;
- context-value and direct-forecast metrics remain separate: PASS;
- PIT/no-future and chronological freeze: PASS.

Build 9 remains research/shadow intelligence. It does not replace the live marker brain, change Super Signals execution/provider rules, alter the owner 1% risk directive, or grant live-money authority. No Worker deployment is required for this context library alone.

**Next:** Build 10 — Momentum / Impulse Expert. It will distinguish continuation-quality momentum from noisy direction using multi-horizon returns, volatility-normalisation, acceleration, persistence, path efficiency, impulse/drift, exhaustion and multi-horizon agreement, while tagging correlated price-expert influence for later penalty.

## Build 8 — H4 Price Structure Expert COMPLETE

Build 8 of the environment-aware expert-gate programme is complete and engineering-proven.

Expert:
`aidy_gold_h4_price_structure_expert_v1`

What Build 8 adds:
- the slow H4 structural mini-brain, independently calibrated for 4-hour bars;
- H4 trend quality using 32h/52h path evidence, log-slope/R², persistence, efficiency and ATR-normalised displacement;
- separately scoreable H4 swing structure, breakout acceptance/reclaim, acceleration and candle pressure;
- explicit lower-timeframe conflict against M5/M15/H1 as a scoreable hypothesis rather than an override;
- zero automatic higher-timeframe priority bonus;
- zero default next-15m weight;
- an incremental-value evaluator that only marks H4 eligible for future next-15m influence when a minimum historical sample exists and accuracy improves versus the lower-timeframe baseline;
- H4-specific dependency/correlation metadata and Build-3 conditional trust;
- legacy-H4 comparison and chronological replay retained for ablation.

Acceptance on PR #211 candidate:
- Evidence Semantic Change Gate: PASS;
- static checks: PASS;
- focused workflow suite: 187 passed;
- full repository regression: 1439 passed;
- H4-vs-lower-timeframe conflict explicit and scoreable: PASS;
- no automatic next-15m authority/weight from timeframe: PASS;
- incremental-value proof gate with minimum sample: PASS;
- PIT/no-future, chronological freeze, separate H4 trust and legacy comparison: PASS.

Build 8 remains research/shadow intelligence. It does not replace the live marker brain, change Super Signals execution/provider rules, alter the owner 1% risk directive, or grant live-money authority. No Worker deployment is required for this expert library alone.

**Next:** Build 9 — D1 Context Expert. D1 is the slowest structural/macro-location context. It must abstain when daily evidence is stale or partial, must not force a 15-minute direction, and historical testing must distinguish context value from direct forecast value.

## Build 7 — H1 Price Structure Expert COMPLETE

Build 7 of the environment-aware expert-gate programme is complete and engineering-proven.

Expert:
`aidy_gold_h1_price_structure_expert_v1`

What Build 7 adds:
- a genuine hourly trend-quality specialist using 8h/13h return and log-slope/R², path efficiency, close-step persistence and ATR-normalised displacement;
- an H1 quality gate requiring sufficient R², efficiency, persistence and directional quality before a net hourly move can become a directional trend vote;
- an H1 trend-quality guard that downgrades a same-direction conclusion to ABSTAIN when the net path is positive/negative but its internal quality fails;
- separately scoreable H1 swing structure, breakout acceptance/reclaim, acceleration and completed-candle pressure;
- context-only H1 range location and contradiction diagnostics;
- explanations that explicitly expose slope, quality, swings/breakout, location and contradictions;
- H1-specific dependency/correlation metadata and Build-3 conditional trust scopes separate from M15;
- legacy-H1 baseline and chronological replay retained for ablation.

Acceptance on PR #210 candidate:
- Evidence Semantic Change Gate: PASS;
- static checks: PASS;
- focused workflow suite: 172 passed;
- full repository regression: 1424 passed;
- explicit positive-first-to-last but choppy H1 path test: PASS;
- PIT/no-future, chronological freeze, separate H1 trust scope, dependency metadata and legacy comparison: PASS.

Build 7 remains research/shadow intelligence. It does not replace the live marker brain, change Super Signals execution/provider rules, alter the owner 1% risk directive, or grant live-money authority. No Worker deployment is required for this expert library alone.

**Next:** Build 8 — H4 Price Structure Expert. H4 becomes a slow structural expert, but it cannot dominate a next-15m forecast simply because it is a higher timeframe. It must prove incremental conditional value, and conflict with lower timeframes must remain explicit and scoreable.

## Build 6 — M15 Price Structure Expert COMPLETE

Build 6 of the environment-aware expert-gate programme is complete and engineering-proven.

Expert:
`aidy_gold_m15_price_structure_expert_v1`

What Build 6 adds:
- the second timeframe mini-brain, specialised for M15;
- an explicit two-hour M15 8-bar path calculator using the 8-bar return, 8-bar log-slope/R², path efficiency, persistence and ATR/RV-normalised displacement;
- a separately scoreable latest-completed-15-minute momentum calculator using one-bar return, M15 ATR, candle body and close location;
- confirmed M15 swing structure and breakout acceptance/reclaim specialists;
- M15 candle-pressure, range-location and contradiction evidence;
- explicit dependency families plus correlation groups, so overlapping structure/momentum evidence remains individually learnable without being double-counted in current conviction;
- an independently calibrated 60-minute target horizon and M15-specific thresholds rather than copied M5 settings;
- Build-3 conditional trust for the M15 gate and every scoreable M15 sub-calculator;
- explicit NEUTRAL / ABSTAIN / UNKNOWN handling;
- retained legacy-M15 baseline and chronological replay comparison for ablation.

Acceptance on PR #209 candidate:
- Evidence Semantic Change Gate: PASS;
- static checks: PASS;
- focused workflow suite: 159 passed;
- full repository regression: 1411 passed;
- clean uptrend/downtrend/chop/reversal/missing-data/PIT/chronological-freeze/trust/dependency-metadata/legacy-comparison cases passed.

Build 6 remains research/shadow intelligence. It does not replace the live marker brain, change Super Signals execution/provider rules, alter the owner 1% risk directive, or grant live-money authority. No Worker deployment is required for this expert library alone.

**Next:** Build 7 — H1 Price Structure Expert. It will focus on genuine hourly trend quality, swing structure, acceleration and breakout acceptance. A positive first-to-last H1 move will not be enough to call the hour strongly bullish when persistence/quality are poor, and its historical scorebook remains separate from M15.

## Build 5 — M5 Price Structure Expert COMPLETE

Build 5 of the environment-aware expert-gate programme is complete and engineering-proven.

Expert:
`aidy_gold_m5_price_structure_expert_v1`

What Build 5 adds:
- the first real timeframe mini-brain, dedicated to M5 price structure;
- five separately auditable directional sub-calculators for trend/path quality, confirmed swing structure, breakout acceptance/reclaim, momentum transition and completed-candle pressure;
- context-only M5 range-location and contradiction diagnostics;
- an M5-specific mini-environment for conditional learning;
- Build-3 historical trust lookup for both the overall M5 gate and each scoreable sub-calculator;
- family-balanced aggregation so correlated calculations cannot gain extra weight merely by being numerous;
- explicit NEUTRAL / ABSTAIN / UNKNOWN handling when M5 evidence is weak or contradictory;
- a retained legacy-M5 baseline and chronological replay summary for ablation/comparison.

PIT/no-hindsight properties remain intact: only completed candles enter Build-4 mathematics, the Build-2 expert packet is immutable/auditable, future values are excluded, and historical trust remains separate from current internal conviction.

Acceptance on PR #206:
- Evidence Semantic Change Gate: PASS;
- static checks: PASS;
- focused acceptance/regression suite: 148 passed;
- full repository regression: 1400 passed;
- clean uptrend/downtrend/chop/reversal/missing-data/PIT/chronological-freeze/trust/legacy-comparison cases passed.

Merged to `main`:
`eaa6f49636ae4ae9f73d6a17db4c9d8f46d8743a`

Build 5 does not replace the legacy live marker brain, alter Super Signals execution, change owner 1% risk, or grant AIDY live-money authority.

**Next:** Build 6 — M15 Price Structure Expert. It will apply the same expert contract independently to M15, with M15-specific horizons/thresholds, explicit 8-bar path and latest-15m momentum/swing/breakout evidence, dependency metadata and the legacy M15 baseline retained for ablation.

## Build 4 — Common Price Expert Mathematics COMPLETE

Build 4 of the environment-aware expert-gate programme is complete and engineering-proven.

Library:
`aidy_gold_price_expert_math_v1`

What Build 4 adds:
- shared multi-lookback returns across all Gold timeframes;
- deterministic log-price OLS slope plus R² trend quality;
- close-step persistence;
- path efficiency (net displacement / travelled path);
- ATR(14) and realised-volatility normalisation;
- recent-vs-prior acceleration/deceleration;
- deterministic confirmed swing highs/lows with wing-2 confirmation and no look-ahead;
- swing-sequence structure (HH/HL/LH/LL);
- close-based structure breaks;
- breakout lifecycle: penetration, close acceptance, hold, retest-hold and reclaim;
- 20/50-bar range position;
- latest completed candle body/wick/close-location geometry;
- explicit contradiction diagnostics rather than silently averaging conflicting evidence;
- a unique primitive manifest so one feature family is not counted twice accidentally.

The library uses only completed bars at the frozen as-of time. Partial current candles are excluded. It emits factual mathematics only: no expert vote, no historical trust weight and no live-money action.

Acceptance on PR #205:
- Evidence Semantic Change Gate: PASS;
- static checks: PASS;
- focused workflow suite: 122 passed;
- full repository regression: 1390 passed;
- clean synthetic fixtures covered trend, downtrend, chop, reversal, breakout, rejection, partial-bar exclusion and no-lookahead swing confirmation.

Build 4 does not change the current live marker brain. It provides the common mathematics that the first real timeframe mini-brain will consume.

**Next:** Build 5 — M5 Price Structure Expert.

## Build 3 — Conditional Trust & Score Engine v3 COMPLETE

Build 3 of the environment-aware expert-gate programme is complete, merged and production-verified.

Engine:
`aidy_gold_expert_conditional_trust_v3`

What Build 3 adds:
- separate historical scorebooks for future expert gates and their scoreable sub-calculators;
- the owner-approved +2/+1/0/-1/-2 outcome rule;
- exact mini-environment, gate-defined reduced context, global-core and gate-global trust scopes;
- deterministic hierarchical shrinkage so small samples borrow from broader history;
- minimum-sample gates before a specific context can override broader evidence;
- long-term and bounded recent statistics kept separately;
- Wilson 95% directional-accuracy intervals and explicit uncertainty state;
- strict pre-decision as-of filtering so current/future outcomes cannot enter trust lookup;
- stable/idempotent result identities and immutable result digests;
- a trust envelope that keeps current gate conviction separate from historical reliability;
- D1 raw outcome ledger and aggregate context-scorebook schema.

A gate-specific reduced environment is never guessed by the generic engine. Each later expert build must explicitly declare which of its mini-environment dimensions survive at each fallback level.

Acceptance on PR #203:
- Evidence Semantic Change Gate: PASS;
- static checks: PASS;
- focused workflow suite: 122 passed;
- full repository regression: 1374 passed.

The legacy live marker-brain weighting path is intentionally unchanged.

Production proof:
- merge commit: `76cbedc410dbb4f298687bdccff754f444048036`;
- deploy run: `35580744094`;
- Worker version: `bb0a1553-5b85-44aa-8ca7-6cba85fad081`;
- D1 migration `0026_gold_expert_conditional_trust.sql`: applied successfully;
- `aidy_gold_expert_outcome_ledger`: present in production D1;
- `aidy_gold_expert_context_scores`: present in production D1;
- minute capture cron: present;
- existing v3 environment/cycle audit: healthy;
- future values: 0;
- live-money authority: 0.

**Next:** Build 4 — Common Price Expert Mathematics.

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
