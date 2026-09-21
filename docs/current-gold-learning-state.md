# Current Gold Learning State

Authoritative current design note for the AIDY Gold learning runtime.

Updated: 2026-09-21












## Build 12 COMPLETE — Liquidity / Reclaim Expert

Build 12 adds `aidy_gold_liquidity_reclaim_expert_v1`.

The expert measures OHLC sweep/reclaim behaviour around named reference levels from Build 11. Every event carries level identity, penetration depth, reclaim speed, confirmation closes, retest/retest-hold state, rejection geometry and competing-level distance. Only confirmed or retest-held reclaims can emit a directional proxy vote; no-sweep, unconfirmed penetration and failed reclaim cases remain neutral.

The language boundary is explicit: these are OHLC price-action proxies, not genuine order flow. Any retrospective genuine GC-flow research rows are stored separately with `used_in_ohlc_proxy_calculation=false` and `used_in_expert_conclusion=false`.

Engineering acceptance on PR #215 candidate: semantic gate PASS, static checks PASS, focused workflow suite 235 passed, full repository regression 1487 passed. Synthetic sweep/no-sweep/reclaim/failure, competing-level distance, session/volatility trust separation, fake-order-flow language protection, separate GC-flow storage, gapped-M1 fail-closed, PIT safety and chronological freeze all pass.

Build 12 is research/shadow only and does not change execution, provider activation, owner 1% risk, formal-forward or live-money authority. No Worker deployment is required for this library-only build.

**Next build:** Build 13 — Volatility / Jump Expert. It will classify clock-normalised volatility, compression/expansion transitions, continuous versus jump state, vol-of-vol and optional IV/RV context when qualified, without forcing direction.

## Build 11 COMPLETE — Price Location Expert

Build 11 adds `aidy_gold_price_location_expert_v1`.

The expert answers where Gold is rather than where it is moving. It combines frozen prior-day, Asia, active-session and opening-range references with confirmed swings, recent extrema and round numbers, then measures every level using exact USD, bps and ATR-normalised distance.

Geometric nearness and structural priority are deliberately separate. The closest level is reported independently from the highest-priority structural reference, and every priority tier/reason is exposed for audit. Nearby levels are clustered for confluence and the expert explicitly records when price is bracketed by nearby references on both sides.

The gate is context-only. Location alone cannot create directional edge, conviction or a BUY/SELL call. A future reaction rule must be separately defined and tested before location can influence direction.

Engineering acceptance on PR #214 candidate: semantic gate PASS, static checks PASS, focused workflow suite 223 passed, full repository regression 1475 passed. Exact distance math, priority auditability, confluence/conflict, descriptive-only round numbers, ATR normalisation, missing-mid fail-closed, PIT safety and chronological freeze all pass.

Build 11 is research/shadow only and does not change execution, provider activation, owner 1% risk, formal-forward or live-money authority. No Worker deployment is required for this library-only build.

**Next build:** Build 12 — Liquidity / Reclaim Expert. It will make sweep/reclaim reasoning measurable and multi-step while explicitly treating OHLC sweep logic as a proxy, not real order flow.

## Build 10 COMPLETE — Momentum / Impulse Expert

Build 10 adds `aidy_gold_momentum_impulse_expert_v1`.

The expert works from exact completed M1 history and calculates 1/5/15/30/60-minute backward returns rather than approximating them from coarser bars. It volatility-normalises each horizon, measures path persistence and efficiency, compares recent and prior 5-minute momentum for acceleration, classifies impulse versus drift versus noise, measures single-bar concentration, and exposes an exhaustion/reversal hypothesis when one bar dominates a weakly persistent path.

A single giant final candle is explicitly prevented from masquerading as sustained momentum. If the move is concentrated in one bar and the path lacks persistence, continuation cannot be promoted merely because all raw horizons point the same way.

Momentum trust is conditioned on volatility regime and clock/session context. Every price-derived calculator is tagged as correlated with the earlier price experts so a later fusion build can penalise overlapping evidence instead of counting it twice.

Engineering acceptance on PR #213 candidate: semantic gate PASS, static checks PASS, focused workflow suite 211 passed, full repository regression 1463 passed. Single-candle veto, noisy-path rejection, gapped-M1 fail-closed, clock/regime trust separation, correlation tags, PIT safety and chronological freeze all pass.

Build 10 is research/shadow only and does not change execution, provider activation, owner 1% risk, formal-forward or live-money authority. No Worker deployment is required for this library-only build.

**Next build:** Build 11 — Price Location Expert. It will know where Gold sits relative to prior day, Asia, active session, opening ranges, swings, recent extrema and round numbers, with auditable nearest-level priority/confluence and no directional vote unless a separately tested reaction rule earns one.

## Build 9 COMPLETE — D1 Context Expert

Build 9 adds `aidy_gold_d1_context_expert_v1`.

D1 is context-only by contract. It can describe slow daily trend, structure, macro-location and breakout state, but it cannot emit or force a 15-minute bullish/bearish conclusion. Default next-15m weight is zero.

Freshness and completeness are explicit. Stale, missing or genuinely partial daily evidence causes the usable D1 context decision to ABSTAIN. Confirmed daily swings are treated separately: if they do not yet exist, trend/location context can still be usable while swing/breakout context remains UNKNOWN.

Historical evaluation separates two questions: whether adding D1 context improved another forecast, and whether a direct D1 directional guess was accurate. These are never conflated.

Engineering acceptance on PR #212 candidate: semantic gate PASS, static checks PASS, focused workflow suite 199 passed, full repository regression 1451 passed. Stale/partial abstention, zero 15m direction authority, separate context-vs-direct value, PIT safety and chronological freeze all pass.

Build 9 is research/shadow only and does not change execution, provider activation, owner 1% risk, formal-forward or live-money authority. No Worker deployment is required for this library-only build.

**Next build:** Build 10 — Momentum / Impulse Expert. It distinguishes persistent continuation-quality momentum from noisy direction using multi-horizon returns, volatility-normalised movement, acceleration, persistence, path efficiency, impulse/drift, exhaustion and multi-horizon agreement.


## Build 9 COMPLETE — D1 Context Expert

Build 9 adds `aidy_gold_d1_context_expert_v1`, the slowest context layer.

D1 is deliberately context-only. It can describe daily trend, structure, macro-location and breakout state, but it cannot emit or force a 15-minute bullish/bearish call. Its default next-15m weight is zero.

Freshness and completeness are explicit. Stale or materially partial D1 evidence causes the context layer to abstain. Confirmed daily swings are treated separately from core context completeness, so a clean daily trend can remain usable even before enough pivots exist for a reliable swing/breakout read; those unavailable components stay UNKNOWN instead of contaminating the whole daily context.

Historical evaluation separates two questions:
1. did adding D1 context improve another forecast; and
2. was D1 direction itself predictive.

The second metric never grants direct 15-minute authority.

Engineering acceptance on PR #212 candidate: semantic gate PASS, static checks PASS, focused workflow suite 199 passed, full repository regression 1451 passed. Stale/partial/missing D1 abstention, no direct 15m direction, PIT/no-future, chronological freeze and separate context-value testing all pass.

Build 9 is research/shadow only and does not change execution, provider activation, owner 1% risk, formal-forward or live-money authority. No Worker deployment is required for this library-only build.

**Next build:** Build 10 — Momentum / Impulse Expert. It will separate genuine continuation-quality momentum from noisy direction using multi-horizon returns, vol-normalised movement, acceleration, persistence, path efficiency, impulse/drift, exhaustion and multi-horizon agreement.

## Build 8 COMPLETE — H4 Price Structure Expert

Build 8 adds `aidy_gold_h4_price_structure_expert_v1`.

H4 is deliberately a slow structural expert, not a privileged vote. Its current packet contains zero automatic timeframe bonus and zero default next-15m weight. Any future influence on a short-horizon forecast must first prove incremental conditional value against the lower-timeframe baseline with enough historical samples.

H4 evaluates slow trend quality using 32h/52h path evidence, slope/R², persistence, efficiency and volatility-normalised displacement, alongside swing structure, breakout acceptance/reclaim, acceleration and candle pressure. Conflict with M5/M15/H1 is emitted as its own scoreable hypothesis so Aidy can learn when the slow timeframe disagreement was useful or harmful.

Engineering acceptance on PR #211 candidate: semantic gate PASS, static checks PASS, focused workflow suite 187 passed, full repository regression 1439 passed. Explicit H4 conflict scoring, zero timeframe-derived next-15m authority, incremental-value gating, PIT safety, chronological freeze, separate H4 trust and legacy-H4 ablation all pass.

Build 8 is research/shadow only and does not change execution, provider activation, owner 1% risk, formal-forward or live-money authority. No Worker deployment is required for this library-only build.

**Next build:** Build 9 — D1 Context Expert. D1 provides slow structural/macro-location context, abstains on stale/partial evidence, never forces 15-minute direction, and must prove context value separately from direct forecast value.

## Build 7 COMPLETE — H1 Price Structure Expert

Build 7 adds `aidy_gold_h1_price_structure_expert_v1`.

H1 now judges genuine hourly trend quality rather than first-close versus last-close. Its trend specialist combines 8h/13h slope and R², persistence, path efficiency and volatility-normalised displacement, then applies an explicit quality gate. A net-positive H1 path with poor persistence/choppy structure cannot become a bullish H1 trend conclusion merely because it finished higher.

H1 also scores confirmed swing structure, breakout acceptance/reclaim, acceleration and completed-candle pressure separately. Its explanations explicitly include slope, quality, swings/breakout, location and contradictions. H1 conditional trust is separate from M15.

Engineering acceptance on PR #210 candidate: semantic gate PASS, static checks PASS, focused workflow suite 172 passed, full repository regression 1424 passed. The blueprint's positive-but-choppy H1 acceptance case passes, as do PIT, chronological-freeze, dependency metadata, separate H1 trust and legacy-H1 ablation tests.

Build 7 is research/shadow only and does not change execution, provider activation, owner 1% risk, formal-forward or live-money authority. No Worker deployment is required for this library-only build.

**Next build:** Build 8 — H4 Price Structure Expert. It is the slow structural expert, but timeframe alone cannot give it dominance. H4 must prove incremental conditional value and any conflict with lower-timeframe experts must remain explicit and scoreable.

## Build 6 COMPLETE — M15 Price Structure Expert

Build 6 adds `aidy_gold_m15_price_structure_expert_v1`, the second timeframe specialist.

M15 is calibrated independently from M5. Its primary path expert explicitly evaluates the 8-bar / 120-minute path using return, slope/R², persistence, efficiency and volatility-normalised displacement. Latest completed 15-minute momentum is a separate opinion, alongside swing structure, breakout acceptance/reclaim and candle pressure.

Dependency-family and correlation-group metadata are explicit. Correlated observations remain separately scoreable for learning, while family-balanced aggregation prevents duplicated structure or latest-bar evidence from manufacturing current confidence.

The expert carries a 60-minute target horizon, M15-specific decision thresholds, an M15 mini-environment, Build-3 exact/reduced/global trust scopes, explicit NEUTRAL/ABSTAIN/UNKNOWN states, and a retained legacy-M15 ablation baseline.

Engineering acceptance on PR #209 candidate: semantic gate PASS, static checks PASS, focused workflow suite 159 passed, full repository regression 1411 passed. PIT and chronological-freeze tests remain green.

Build 6 is research/shadow only and does not change execution, provider activation, owner 1% risk, formal-forward or live-money authority. No Worker deployment is required for this library-only build.

**Next build:** Build 7 — H1 Price Structure Expert. It will judge true hourly trend quality, swing structure, acceleration and breakout acceptance, explicitly preventing a choppy positive H1 path from being mislabeled as strong bullish and keeping H1 historical trust separate from M15.

## Build 5 COMPLETE — M5 Price Structure Expert

Build 5 adds `aidy_gold_m5_price_structure_expert_v1`, the first actual timeframe expert in the programme.

It consumes the Build-4 completed-bar mathematics and emits one Build-2 auditable M5 expert packet with separately visible sub-calculators for:
- trend/path quality;
- confirmed swing structure;
- breakout acceptance/reclaim;
- momentum transition;
- completed-candle pressure;
- range location (context only);
- contradiction diagnostics (context only).

The final M5 conclusion is family-balanced rather than calculator-count weighted. Correlated structure or momentum calculations can all be scored and learned from, but they do not multiply current conviction merely because several versions of the same evidence agree. The expert preserves NEUTRAL, ABSTAIN and UNKNOWN when evidence is weak or conflicted.

Build-3 conditional trust is attached separately for the M5 gate and every scoreable sub-calculator using the gate's own M5 mini-environment and reduced fallback contexts. The legacy M5 direction remains an explicit baseline for chronological ablation rather than being silently replaced.

Engineering acceptance on PR #206: semantic gate PASS, static checks PASS, focused suite 148 passed, full repository regression 1400 passed. Merged as `eaa6f49636ae4ae9f73d6a17db4c9d8f46d8743a`.

No Worker deployment was required because Build 5 is not yet wired into live gate weighting. Research/shadow only; owner 1% risk and live-money authority remain unchanged.

**Next build:** Build 6 — M15 Price Structure Expert. It will use the same contract with independently calibrated M15 horizons/thresholds, separate M15 8-bar path, latest 15-minute momentum and swing/breakout features, explicit dependency metadata, and the legacy M15 baseline retained for ablation.

## Build 4 COMPLETE — Common Price Expert Mathematics

Build 4 adds `aidy_gold_price_expert_math_v1`, the shared deterministic mathematics layer for the future M5/M15/H1/H4/D1 expert gates.

The library computes the same auditable primitive families on each timeframe:
- returns over multiple completed-bar lookbacks;
- log-price OLS slope and R²;
- close-step persistence;
- path efficiency;
- ATR/RV-normalised movement;
- acceleration/deceleration;
- confirmed wing-2 swing sequences;
- structure breaks;
- breakout acceptance/retest/reclaim state;
- 20/50-bar range location;
- candle body/wick/close geometry;
- contradiction diagnostics.

Important safety/quality properties:
- only completed bars at T are admitted;
- partial current candles are excluded;
- swing pivots appear only after their right-hand confirmation bars are known;
- the primitive manifest is unique and duplicate-feature counting is rejected;
- flat/choppy paths remain measurably low-efficiency/low-quality rather than being promoted to strong trend;
- output is factual only and emits no directional gate decision;
- historical outcomes are not used;
- research-only=true and live-money authority=false.

Engineering acceptance on PR #205: semantic gate PASS, static checks PASS, focused workflow suite 122 passed, full repository regression 1390 passed.

**Next build:** Build 5 — M5 Price Structure Expert. Build 5 will turn these common primitives into the first actual expert mini-brain, with its own mini-environment, sub-calculator votes, contradictions, explanation and Build-3 conditional trust lookup.

## Build 3 — Conditional Trust & Score Engine v3

Build 3 is complete and production-verified. It introduces `aidy_gold_expert_conditional_trust_v3` for the expert-gate programme.

The engine does not use raw win percentage as trust. It maintains separate directional accuracy and impact score, shrinks small environment samples toward broader history, and only lets a more-specific mini-environment win once its configured minimum sample is met.

Trust lookup order is:

`exact gate mini-environment -> gate-declared reduced mini-environment(s) -> global core -> gate global -> neutral prior`

Key safeguards:
- 8/10 does not automatically outrank 137/200;
- every gate defines its own reduced-context dimensions instead of the engine guessing them;
- current/future outcomes are excluded by strict resolved-before-as-of filtering;
- gate/sub-calculator outcomes use +2/+1/0/-1/-2;
- unscoreable/UNKNOWN/context-only observations stay 0 rather than becoming fake misses or wins;
- long-term and recent-window performance are stored separately;
- Wilson intervals and sample-confidence expose uncertainty;
- current gate conviction remains separate from historical reliability;
- scoring is deterministic and outcome resolution has stable identities.

D1 migration `0026_gold_expert_conditional_trust.sql` adds a raw expert-outcome ledger and expert context scorebooks for future gate runtime integration.

Engineering acceptance on PR #203: semantic gate PASS, static checks PASS, focused workflow suite 122 passed, full repository regression 1374 passed.

Production deployment run `35580744094` applied D1 migration `0026_gold_expert_conditional_trust.sql`, verified both expert-trust tables on the real D1 database, and deployed Worker version `bb0a1553-5b85-44aa-8ca7-6cba85fad081`. Existing capture cron, environment v3, toolbox coverage, no-hindsight and live-money-disabled checks all remained green.

Build 3 does not yet make M5/M15/H1/H4/D1 smarter and does not change the live legacy marker weights. **Next: Build 4 — Common Price Expert Mathematics**, which will build the shared slope, trend-quality, persistence, path-efficiency, swing, breakout/reclaim, volatility-normalisation and acceleration primitives used by the timeframe mini-brains.

## Build 2 COMPLETE — Expert Gate Contract v1

The standard expert-gate packet contract is now:
`aidy_gold_expert_gate_contract_v1`.

Every later mini-brain must use this contract. It binds the gate to the frozen Environment v3 digest, stores a gate-specific mini-environment, requires timestamped evidence references, records each sub-calculator separately, distinguishes directional gates from context-only gates, and preserves NEUTRAL / ABSTAIN / UNKNOWN rather than forcing a BUY/SELL opinion.

The contract also enforces:
- evidence timestamps cannot be later than the gate as-of;
- future/outcome-labelled fields are rejected;
- known calculations require known evidence;
- context-only calculations cannot create directional votes;
- bullish/bearish gate conclusions need a matching scoreable sub-calculator;
- readable explanations and contradictions must reference actual evidence/calculators;
- internal conviction is separate from historical reliability;
- packet/evidence/calculator/mini-environment digests detect mutation;
- research-only and live-money-disabled safety flags are mandatory.

Engineering acceptance on PR #202: semantic gate PASS, static checks PASS, focused workflow tests 108 passed, full repository regression 1360 passed.

Build 2 does not alter the current live marker brain. It provides the mandatory interface that Builds 4+ expert gates will use after Build 3 supplies the conditional trust engine.

**Next build:** Build 4 — Common Price Expert Mathematics.

## Build 1 COMPLETE — factorised environment contract v3

The live environment contract is `aidy_gold_cycle_environment_v3`. Build 1 is merged, deployed and production-verified.

The v3 contract keeps exact PIT facts for audit but separates learning identity into factor families: time/participation, structure, movement, location, liquidity, volatility, event, cross-market, regime and data quality. The shared `environment_key` is now a compact global-core key rather than a digest of every condition. Each factor also gets its own key. This prevents a single giant cross-product from making most historical environments unique.

New mandatory environment state includes:
- 15-minute UTC clock bucket;
- weekday/week-transition state;
- explicit market-calendar/weekend state;
- explicit data-quality state;
- registered factor families and dimension registry digest;
- an explicit declaration that expert-gate mini-environments are deferred to later builds.

Build 1 also rejects labelled future/outcome fields before environment freeze and preserves UNKNOWN rather than fabricating missing evidence.

The current directional marker logic is intentionally unchanged in Build 1. Expert-gate intelligence begins only after the shared environment and trust foundations pass their own acceptance gates.

## Build 1 production proof

Deployment run `35576676324` passed with Worker version
`a20dcfe9-cd46-40c2-aef5-5d6c524cc6c1`.

The live D1 audit found a v3 environment on the `2026-09-21T08:15:00+00:00` Gold cycle,
frozen at `2026-09-21T08:10:56.620000+00:00`, with:

- schema `aidy_gold_environment_contract_schema_v1`;
- 34 registered environment dimensions;
- an `envcore_` shared environment key;
- 0 monolithic full-environment key usage;
- 0 legacy `full_environment` scopes;
- 34/34 toolbox trace and environment coverage;
- 0 missing readable tool states;
- 0 missing score contexts;
- 0 future values;
- 0 live-money authority.

Capture remained enabled, the one-minute cron remained present, market data remained
Twelve Data/public-independent, and formal-forward remained OFF.

**Next build:** Build 2 — Expert Gate Contract v1.

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
`aidy_gold_cycle_environment_v3`

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

Current factorised score scopes:

- global;
- global core;
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
- event regime.

The old monolithic `full_environment` scope is deliberately removed. Later expert gates will add
smaller specialist mini-environments instead of one sparse cross-product.

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
