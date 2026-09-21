# AIDY Repository Memory

Updated: 2026-09-21

This file is the repo-level handoff entry point for the live AIDY Gold-learning system.

















## Build 24 — Live Forward Shadow Soak & Permanent Scorecard — ENGINEERING COMPLETE / LIVE PROOF IN PROGRESS

Build 24 adds `aidy_gold_expert_shadow_v1` and `aidy_gold_expert_scorecard_v1`, completing the planned 24-build expert-gate implementation.

What is built and already proven:
- prospective activation is persisted before any eligible shadow cycle can freeze;
- only cycles decided at or after that activation can enter the Build-24 programme;
- the existing 15-minute Gold cycle remains the single clock and point-in-time boundary;
- every eligible shadow cycle carries all 15 expected expert-gate identities;
- currently connected price/structure/location/momentum/liquidity/volatility/session experts run from the exact admitted PIT snapshot;
- currently disconnected macro/event, rates/USD/cross-asset, futures/microstructure, news/mechanism and analogue/episode live sources remain explicit UNKNOWN context gates with zero invented directional authority;
- Build-20 dependency state, Build-21 selector and Build-22 final AIDY view are frozen before the target window;
- outcomes are read only from the later `aidy_gold_cycle_outcomes` resolver;
- gate/subcalculator scores use the existing Build-3 +/-2/+/-1/0 rules and refresh environment-specific trust scorebooks only after resolution;
- the authenticated Provider Context exposes a permanent scorecard with gate mini-environment, N, raw/shrunk reliability, net score, drift, uncertainty, dependency adjustment, calibration, current trust and last score time;
- restart/idempotency is structural through persisted activation and conflict-safe immutable inserts;
- the scorecard is read-only context and is not imported into the private-forward decision-input builder;
- formal-forward and live-money authority remain OFF.

Engineering acceptance:
- implementation PR #238 tested head: `a0b8710abc3fe4ea569deed868ea6538294169ad`;
- implementation merge: `6644892d12be6ae497f07db2a69119eaa58e0d27`;
- Build 24 acceptance run: `35623113260` — PASS;
- Evidence Semantic Change Gate: `35623113461` — PASS;
- Ruff + compile: PASS;
- focused Build-24/component suite: 103 passed;
- full repository regression: 1664 passed;
- Day-53 Twelve Data and live-forward safety workflows: PASS.
- public Worker health already exposes `aidy_gold_expert_shadow_v1` and `aidy_gold_expert_scorecard_v1`, with capture fresh and formal-forward OFF.

Live completion evidence is being collected by PR #239 / run `35623618474`: schema, deploy, Worker safety and the first genuine prospective 15-minute shadow cycle have passed. The final delayed post-window score/scorecard proof must pass before this section is promoted from LIVE PROOF IN PROGRESS to COMPLETE.

## Build 23 — Chronological Replay, Ablation & Untouched Holdout COMPLETE

Build 23 adds `aidy_gold_meta_replay_report_v1` and the versioned meta-replay dataset/split/policy contracts.

What is built and proven:
- immutable replay cases separate pre-outcome decision state from later evaluation-only outcomes;
- deterministic versioned input/case/report digests;
- chronological development, validation and untouched holdout partitions;
- purge + embargo around split boundaries;
- holdout tuning and holdout recommendation updates are forbidden;
- frozen comparisons cover legacy simple 15m, every gate alone, full system, full-minus-each-gate and full system with/without dependency penalties;
- metrics cover directional accuracy by class, +2/+1/-1/-2 impact score, Brier where confidence exists, coverage/abstention, environment performance, time stability, incremental contribution and sample N;
- gate pruning/retention recommendations are derived from validation only;
- a flashy development-only gate cannot earn promotion from in-sample beauty;
- changing holdout outcomes cannot change gate/dependency recommendations;
- dependency penalty is explicitly ablated rather than assumed useful;
- acceptance data are explicitly tagged `acceptance_fixture` and cannot be represented as real-market edge;
- real-market-edge flag remains false;
- formal-forward OFF and live-money authority OFF.

Acceptance evidence:
- implementation merge from PR #235: `12d5f0f17b6678a426890fd8bcd643d3984d1d27`;
- corrective post-merge verification PR #237 tested head: `0c5e2f2a072e20e1671db13ac90f3ccce88cf11f`;
- verified main after corrective merge: `5c370ac4182b96a8fb2d06be7927d8de141914a1`;
- Build 23 verification workflow run: `35619195819` — PASS;
- Evidence Semantic Change Gate: `35619195958` — PASS;
- static/compile checks: PASS;
- focused replay suite: 54 passed;
- dedicated anti-overfit/holdout suite: 6 passed;
- full repository regression: 1652 passed;
- development-only star rejected by validation: PASS;
- strong validation contributor retained candidate: PASS;
- dependency-penalty ablation: PASS;
- holdout recommendation immutability: PASS;
- fixture/real-market evidence separation: PASS;
- deterministic replay: PASS.

Build 23 proves the replay and pruning machinery. Its acceptance fixture is not a claim that AIDY has already demonstrated real-market predictive edge. Fresh prospective market evidence is the purpose of Build 24.

**Next:** Build 24 — Live Forward Shadow Soak & Permanent Scorecard. This is the final planned build and will persist fresh expert packets, selector state, final AIDY view and later outcomes on every eligible cycle for permanent environment-specific scoring.

## Build 22 — AIDY Meta Direction Aggregator & Explanation COMPLETE

Build 22 adds `aidy_gold_meta_direction_aggregator_v1`.

What is built and proven:
- combines Build-21 selected gates into one bullish/bearish/neutral/abstain research view;
- every contribution binds to the exact selector row and verified expert packet digest;
- supporting, opposing, context-only and unavailable gates are exposed separately;
- strong high-trust cross-gate contradiction can force abstention;
- context-only gates remain unsigned and cannot cast directional votes;
- readable why text identifies supporting/opposing gates and authority totals;
- numerical confidence is never invented: it is withheld unless sufficient historical meta-calibration observed before the current cycle exists;
- small meta-calibration samples and future calibration rows cannot create confidence;
- current outcome injection into expert inputs fails closed;
- deterministic replay is invariant to expert-result ordering;
- research-only, formal-forward OFF, live-money authority OFF.

Acceptance evidence:
- exact tested PR #233 head: `5eb5a20f7aa5003aec38ccf6a5714f7adf8b559f`;
- implementation merge: `25be25ddb973e9c419002630a481e2b6c4cb5d05`;
- Build 22 workflow run: `35615805313` — PASS;
- Evidence Semantic Change Gate: `35615805343` — PASS;
- focused suite: 74 passed;
- dedicated aggregator gate: 6 passed;
- full repository regression: 1637 passed.

**Next:** Build 23 — Chronological Replay, Ablation & Untouched Holdout.

## Build 21 — Environment-Aware Gate Selector COMPLETE

Build 21 adds `aidy_gold_environment_gate_selector_v1`.

What is built and proven:
- consumes frozen Build-2 packets plus Build-3 trust envelopes rather than creating a parallel trust system;
- uses the exact current environment and exact gate as-of;
- respects Build-3 exact/reduced/global trust-scope fallback;
- applies Build-3 hierarchical shrinkage and sample confidence;
- applies an explicit scope-backoff multiplier;
- applies historical calibration quality from records observed before the current cycle only;
- applies recent drift state, with recently-weaker gates reduced and no recency boost above 1;
- applies Build-20 dependency multipliers at gate level;
- small-N star performers remain reduced;
- strong large-N contextual performers can rise to high trust;
- missing/unknown gates get exactly zero authority;
- weak gates remain observable with a low non-zero observation weight;
- context-only gates can remain observable but never receive directional authority;
- selector input strips full expert results to pre-outcome packet + trust data;
- current outcome injection fails closed;
- deterministic replay is invariant to gate-input ordering.

Acceptance evidence:
- exact tested PR #231 head: `a5f4892909d5eeaffb7143a2d579c0e12eea528d`;
- implementation merge: `49632b75c773b207f857e23387e4f7ec5428fe52`;
- Build 21 workflow run: `35613740266` — PASS;
- Evidence Semantic Change Gate: `35613740343` — PASS;
- static/compile checks: PASS;
- focused suite: 84 passed;
- dedicated selector gate: 6 passed;
- full repository regression: 1622 passed;
- small-N suppression: PASS;
- strong large-N contextual promotion: PASS;
- unavailable gate zero authority: PASS;
- weak gate retained for observation: PASS;
- recently-weaker drift reduction: PASS;
- historical calibration adjustment: PASS;
- future calibration exclusion: PASS;
- Build-20 dependency penalty propagation: PASS;
- independent liquidity/macro/structure preservation: PASS;
- context-only zero directional authority: PASS;
- current outcome injection rejection: PASS;
- deterministic replay: PASS.

Build 21 selects attention only. It does not create the final Gold direction, change Super Signals execution/provider rules, change owner 1% risk, create formal-forward evidence or grant live-money authority.

**Next:** Build 22 — AIDY Meta Direction Aggregator & Explanation. It will combine the selected gate set into one traceable bullish/bearish/neutral/abstain research view, with contradictions, environment, trust/N, dependency adjustment and a readable why.

## Build 20 — Evidence Dependency & Double-Counting Engine COMPLETE

Build 20 adds `aidy_gold_evidence_dependency_engine_v1`.

What is built and proven:
- explicit evidence-family graph with declared parent/child relationships;
- structure, momentum and location share the `price_action` parent;
- event, rates/USD, cross-market and news share the `macro_information` parent;
- liquidity, volatility, participation/microstructure, analogue memory and data quality retain separate roots;
- exact duplicate evidence adds zero incremental weight;
- contradictory interpretations of the same evidence are split symmetrically rather than order-biased;
- same correlation-group signals are damped even before enough empirical history exists;
- rolling pre-outcome signal correlations use only rows observed before the current as-of;
- highly correlated signals under the same parent are empirically damped;
- same-root incremental evidence is capped so five price-derived signals cannot manufacture five votes;
- independent-root agreement gets only a small bounded bonus and only when at least three genuinely distinct roots align;
- context-only gates remain observable but receive zero directional weight;
- no outcome field is allowed into dependency diagnostics.

Acceptance evidence:
- exact tested PR #229 head: `b5cf46b5751cb9a9f7dc565b88bd08dccf3810d4`;
- implementation merge: `35de6056cbbbdde2309a2185c07914f7df375797`;
- Build 20 workflow run: `35611781428` — PASS;
- Evidence Semantic Change Gate: `35611781415` — PASS;
- static/compile checks: PASS;
- focused suite: 144 passed;
- dedicated double-counting gate: 5 passed;
- full repository regression: 1607 passed;
- exact duplicate zero increment: PASS;
- removing an exact duplicate leaves the dependency-adjusted score unchanged: PASS;
- highly correlated M5/M15/momentum damping: PASS;
- five price-derived votes capped at 1.5 leader-equivalents: PASS;
- independent liquidity + macro + structure preserved as three distinct roots: PASS;
- future correlation rows excluded: PASS;
- historical outcome fields rejected: PASS;
- deterministic input reordering: PASS.

Build 20 is dependency infrastructure for Build 21. It does not independently select live gates, change Super Signals execution/provider rules, change owner 1% risk, create formal-forward evidence or grant live-money authority.

**Next:** Build 21 — Environment-Aware Gate Selector. It will combine contextual trust with Build-20 dependency multipliers, sample shrinkage, calibration and drift so AIDY knows which gates deserve attention in the current environment.

## Build 19 — Analogue / Episode Expert COMPLETE

Build 19 adds `aidy_gold_analogue_episode_expert_v1`.

What is built and proven:
- reuses the accepted analogue retrieval v1/v2/v3 stack rather than creating a parallel engine;
- exact PIT state snapshots bind gate/environment similarity to immutable input identity;
- gate-state similarity and environment similarity are explicit, auditable components;
- historical v2 overlapping-window episode collapse is preserved before Build 19 re-ranking;
- semantic analogue retrieval may be attached only when its existing semantic wrapper verifies;
- movement episode learning cards are eligible only after their own available-at timestamp;
- continuation/retrace distributions are computed only after analogue selection;
- positive analogues and symmetric counterexamples are both preserved;
- changing future outcome content cannot change selected case identity or similarity;
- chronological holdout requires purge + embargo and forbids holdout tuning;
- context-only: no automatic BUY/SELL authority.

Acceptance evidence:
- exact tested PR #227 head: `87a793066af3ac0cb9855399416c0a01f55aa02d`;
- implementation merge: `aba5ebc275646b31ec8132af3fed7179c1b5046f`;
- Build 19 workflow run: `35610105516` — PASS;
- Evidence Semantic Change Gate: `35610105748` — PASS;
- static/compile checks: PASS;
- focused suite: 115 passed;
- dedicated chronological/counterexample gate: 5 passed;
- full repository regression: 1591 passed;
- future-outcome mutation selection invariance: PASS;
- duplicate overlapping episodes collapse: PASS;
- exact input-digest binding: PASS;
- positive + counterexample retrieval: PASS;
- chronological holdout-only boundary: PASS;
- deterministic candidate reordering: PASS.

Build 19 remains research/shadow intelligence. It does not change Super Signals execution/provider rules, owner 1% risk, formal-forward authority or live-money authority.

**Next:** Build 20 — Evidence Dependency & Double-Counting Engine. It will stop correlated or duplicated evidence from voting multiple times while preserving genuinely independent agreement.

## Build 18 — News / Movement Mechanism Expert COMPLETE

Build 18 adds `aidy_gold_news_movement_mechanism_expert_v1` plus the bounded Finnhub market-news adapter `aidy_finnhub_market_news_adapter_v1`.

What is built and proven:
- reuses the frozen Gold movement investigator and scheduled-event evidence;
- bounded Finnhub market-news source contract using `FINNHUB_API_KEY`;
- publication timestamp and first-observed timestamp enforcement;
- future news rows are excluded from frozen decisions;
- explicit source-authority classification;
- exact/syndicated duplicate-story collapse before agreement scoring;
- mechanism-tag extraction for Fed policy, inflation, labour/growth, USD/rates, geopolitical risk, trade policy, risk sentiment, energy/inflation and Gold-specific context;
- scheduled-event versus credible-news agreement;
- credible-source agreement and disagreement handling;
- unsupported narratives are retained as unsupported and never admitted as evidence;
- disagreement remains unresolved instead of being fabricated away;
- news is context-only and can never automatically create BUY/SELL direction;
- no causal claim from a single headline;
- no live-money authority.

Final acceptance:
- exact tested PR #225 head: `6ca20729e1925dde30d2cfe123648371d437e648`;
- implementation merge: `5270f17b536d496d39d231b52da76ad391d4a610`;
- Evidence Semantic Change Gate: PASS — run `35608776114`;
- Build 18 acceptance workflow: PASS — run `35608776007`;
- static/compile checks: PASS;
- focused suite: 61 passed;
- full repository regression: 1577 passed;
- scheduled-event fixture: PASS;
- credible-news fixture: PASS;
- duplicate-story anti-double-counting: PASS;
- unsupported-narrative fixture: PASS;
- UNKNOWN fixture: PASS;
- credible-source disagreement remains unresolved: PASS;
- scheduled-event/news agreement without causal claim: PASS;
- future-news PIT exclusion: PASS;
- Finnhub response-schema adapter test: PASS;
- news directional authority: FALSE.

The Finnhub adapter is built and tested against the real response contract, and the user already owns a valid `FINNHUB_API_KEY` on the separate Super Signals Render runtime. Build 18 does not create a Super Signals dependency or copy that secret into AIDY automatically. The optional authenticated live-smoke step remains available when the same key is installed in AIDY's own secret store.

No execution/provider/risk authority changed. Formal-forward and live-money authority remain OFF.

**Next:** Build 19 — Analogue / Episode Expert. It will retrieve comparable historical Gold states without hindsight, using movement episode memory and analogue retrieval with duplicate collapse, environment/gate-state similarity, symmetric counterexamples and continuation/retrace distributions.

## Build 17 — Futures / Microstructure Expert COMPLETE

Build 17 adds `aidy_gold_futures_microstructure_expert_v1` and has now passed its genuine Phase-A acceptance gate.

What is built and proven:
- genuine historical Databento COMEX GC TBBO trade volume;
- known-side aggressor flow with unknown side preserved as UNKNOWN;
- pre-trade BBO spread;
- trade-price/size VWAP plus session/anchored VWAP;
- matched weekday × clock normalization;
- official CME daily open-interest / active-contract / roll state;
- frozen spot-OHLC versus spot+microstructure retrospective comparator;
- chronological split with purge, embargo and no holdout tuning;
- explicit null, underperformance and insufficient states;
- no depth/order-book/L2/L3/MBO/MBP10 claim without depth data;
- Phase-B paid/live activation remains separate and owner-gated.

Final genuine evidence:
- implementation PR #220 merge: `f6ac451c90ae49f5bbe795af5a25757b65afb8ce`;
- genuine holdout PR #223 exact tested head: `ca49a6dd541ec17b09b11b25604722d7ef256b32`;
- PR #223 merge: `b1e6e2f491c1cf31fdb30a94a88929e4f092fc18`;
- Evidence Semantic Change Gate: PASS — run `35605952419`;
- acceptance workflow: PASS — run `35605952385`;
- focused suite: 313 passed;
- full repository regression: 1565 passed;
- valid genuine weekly episodes: 61;
- normalization episodes: 20;
- development episodes: 10;
- embargo episodes: 1;
- untouched holdout episodes: 30;
- selected development-only rule: `override_1p5_0p5`;
- spot-only holdout accuracy: 20.0000%;
- spot + microstructure holdout accuracy: 23.3333%;
- genuine incremental accuracy: +3.3333 percentage points;
- holdout state: `incremental_value_observed`;
- quoted Databento research spend: $0.148881077766.

This satisfies the Build-17 blueprint requirement that a genuine retrospective holdout show incremental value beyond the spot-OHLC expert baseline. It does **not** mean the microstructure expert is statistically validated, formally forward-proven, promoted to live gate weight, or authorized for live-money execution.

No paid/live Databento subscription, depth claim, execution change, provider-rule change, owner-risk change, formal-forward authority or live-money authority was created.

**Next:** Build 18 — News / Movement Mechanism Expert. It must explain abnormal Gold moves using evidence-backed scheduled-event/news mechanisms without inventing causality; unsupported narratives and source disagreement remain UNKNOWN/unresolved, and news context does not automatically become direction.

## Build 16 — Rates / USD / Cross-Asset Expert COMPLETE

Build 16 of the environment-aware expert-gate programme is complete and engineering-proven.

Expert:
`aidy_gold_rates_usd_cross_asset_expert_v1`

What Build 16 adds:
- PIT-vintaged DGS2/DGS10/DFII10/T10YIE daily context;
- explicit 1/5/20-observation rate changes;
- hard guard that daily cash rates cannot masquerade as 15m/60m reactions;
- qualified Day-44 policy/cross-asset observations;
- genuinely timestamped futures can carry 15m/60m changes only when fresh and decision-qualified;
- broad USD/EURUSD/USDJPY/VIX official daily/fix context cannot masquerade as intraday;
- regime-specific rolling Gold beta/correlation;
- positive, negative, weak and sign-flipping relationships all representable;
- relationship-stability state from chronological subwindows;
- divergence between current Gold and the learned relationship;
- cross-asset breadth counted once per dependency group rather than once per correlated series;
- explicit dependency tags for rates curve, policy path, USD mechanism, precious complex and risk state;
- no permanent Gold/USD or Gold/real-yield sign assumption.

Acceptance on PR #219 candidate:
- Evidence Semantic Change Gate: PASS;
- static checks: PASS;
- focused workflow suite: 292 passed;
- full repository regression: 1544 passed;
- Gold rising with USD and real yields representable: PASS;
- relationship sign flip representable: PASS;
- stale/daily series cannot masquerade as intraday: PASS;
- fresh exchange-timestamped futures support intraday changes: PASS;
- retrospective current observations do not become decision-qualified intraday inputs: PASS;
- same-mechanism series dependency-tagged: PASS;
- breadth counts dependency groups not raw series: PASS;
- learned-sign divergence: PASS;
- future PIT rows excluded: PASS.

Build 16 remains research/shadow intelligence. It does not replace the live marker brain, change Super Signals execution/provider rules, alter the owner 1% risk directive, or grant live-money authority. No Worker deployment is required for this expert library alone.

**Next:** Build 17 — Futures / Microstructure Expert. Phase A will test genuine historical COMEX GC TBBO signed aggressor imbalance, BBO spread, trade volume, VWAP, clock-normalised baselines, roll state and available CME volume/OI for incremental value beyond spot OHLC. Phase B live/delayed paid data remains separately gated by entitlement review and owner approval.

## Build 15 — Macro / Event Expert COMPLETE

Build 15 of the environment-aware expert-gate programme is complete and engineering-proven.

Expert:
`aidy_gold_macro_event_expert_v1`

What Build 15 adds:
- a context-only Gold macro/event specialist layered on the accepted official event stack;
- strict point-in-time schedule selection from official-source observations;
- pre-event Gold structure from closed bars only;
- PIT-known consensus plus immutable first print for raw surprise;
- later revisions kept separate and never allowed to replace the first print used for surprise;
- standardized surprise only when same-class/same-unit PIT history has enough independent episodes;
- event clustering from PIT-known schedules;
- post-release Gold confirmation from completed M1 bars;
- historical conditional Gold response by event class and surprise direction;
- matched no-news control samples for comparison;
- Gold-specific event tiers from independent Gold episodes, never vendor importance labels;
- no trade P/L in tiering or response estimates;
- Build-3 conditional trust scopes for event tier/timing, surprise/cluster and historical response.

Acceptance on PR #218 candidate:
- Evidence Semantic Change Gate: PASS;
- static checks: PASS;
- focused workflow suite: 276 passed;
- full repository regression: 1528 passed;
- pre-event boundary cannot see actual first observed seconds later: PASS;
- actual appears only at/after first_observed_at: PASS;
- revisions remain separate from first print: PASS;
- standardized surprise uses PIT historical episodes only: PASS;
- event tier uses independent Gold episodes, not vendor labels: PASS;
- event clustering: PASS;
- post-release confirmation: PASS;
- historical response versus matched no-news control: PASS;
- insufficient no-news control remains UNKNOWN: PASS;
- future historical rows excluded: PASS;
- PIT/no-future chronological freeze: PASS.

Build 15 remains research/shadow intelligence. It does not replace the live marker brain, change Super Signals execution/provider rules, alter the owner 1% risk directive, or grant live-money authority. No Worker deployment is required for this expert library alone.

**Next:** Build 16 — Rates / USD / Cross-Asset Expert. It will model Gold's opportunity-cost and risk mechanisms using broad USD, DGS2/DGS10/DFII10/T10YIE, policy-path research, and qualified SI/ES/VIX/EURUSD/USDJPY evidence, with rolling beta/correlation, relationship stability, divergence and breadth — while explicitly forbidding permanent sign assumptions and stale daily data masquerading as intraday reaction.


## Build 15 — Macro / Event Expert COMPLETE

Build 15 of the environment-aware expert-gate programme is complete and engineering-proven.

Expert:
`aidy_gold_macro_event_expert_v1`

What Build 15 adds:
- a Gold-specific context-only macro/event specialist layered on the accepted official event stack;
- strict as-of schedule visibility;
- pre-event Gold features that cannot see actual release values;
- PIT-known consensus plus immutable first-print surprise;
- later revisions kept separate from the first print;
- standardized surprise only when enough independent PIT historical observations exist with the same unit;
- Gold-learned event tiers from independent Gold episodes, never vendor importance labels;
- event clustering within 30/60 minutes;
- post-release Gold confirmation from completed M1 bars;
- historical conditional Gold response by event class and surprise direction;
- matched no-news controls;
- event-versus-no-news comparison;
- Build-3 conditional trust across event class/tier, surprise/cluster and historical response context.

Acceptance on PR #218 candidate:
- Evidence Semantic Change Gate: PASS;
- static checks: PASS;
- focused workflow suite: 276 passed;
- full repository regression: 1528 passed;
- pre-event gate cannot see actual: PASS;
- actual visible only after first_observed_at: PASS;
- revision separated from first-print surprise: PASS;
- standardized surprise PIT history only: PASS;
- Gold event tier from independent episodes, not vendor label: PASS;
- event clustering: PASS;
- post-release completed-bar confirmation: PASS;
- independent historical response: PASS;
- matched no-news control: PASS;
- future rows excluded / chronological freeze: PASS.

Build 15 remains research/shadow intelligence. It does not replace the live marker brain, change Super Signals execution/provider rules, alter the owner 1% risk directive, or grant live-money authority. No Worker deployment is required for this expert library alone.

**Next:** Build 16 — Rates / USD / Cross-Asset Expert. It will model Gold opportunity-cost/risk mechanisms using USD, Treasury/real-rate/breakeven series and qualified cross-assets across multiple horizons, with rolling Gold beta/correlation, relationship stability, divergence and cross-asset breadth, while explicitly allowing sign relationships to change by regime.

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
