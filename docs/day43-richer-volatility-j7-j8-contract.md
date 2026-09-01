# Day 43 — Richer volatility regime and J7/J8 research contract

Decision date: 2026-09-01

Authoritative base: `3d32b5c8afebdfc29552cc76c61c4d254606e122`

## Objective

Build the richer volatility regime on top of the accepted Day 31 volatility foundation and run the formal Architecture V2 J7/J8 research contracts without inventing new volatility estimators or promoting shadow evidence into trading authority.

## Accepted estimator foundation

Day 43 reuses, rather than duplicates:

- Cboe GVZ as a GLD options-implied volatility proxy with an explicit 30-calendar-day horizon;
- XAUUSD realised-volatility horizons of 5, 10 and 21 trading days;
- the explicit GVZ-versus-XAUUSD IV−RV comparison caveat: different underlying proxy and horizon conventions;
- realised variation minus bipower variation for jump-versus-continuous decomposition;
- 21-trading-day sample dispersion of daily realised volatility for vol-of-vol.

No RSI/MACD/Bollinger-style volatility proxies or redundant realised-volatility estimators are added.

## Event IV term-structure kink

An event-kink feature is accepted only if a timestamped options term structure was genuinely observed before the event and is PIT reconstructable. Near and far expiries and their horizons must be explicit.

If such evidence does not exist, the correct state is `unavailable_no_pit_options_term_structure`. The system must not infer the kink from later options history, the realised event move, news, or narrative reconstruction.

## Unexplained market shock

`unexplained_market_shock` is a mechanical market-state candidate only. It is built from abnormal market measurements such as volatility, genuine volume, spread and cross-asset reaction z-scores under frozen thresholds.

It never contains:

- a geopolitical/news sentiment input;
- a causal narrative;
- an intent label;
- a claim about who traded or why.

The label means only that the market itself is behaving abnormally without an attributed cause.

## J7 — implied-volatility regime value

Hypothesis: frozen IV−RV and realised-volatility regime state adds incremental information about outcome dispersion or intelligent restraint after chronological controls.

Null: after the same controls, the state adds no incremental information.

## J8 — jump/instability value

Hypothesis: frozen jump-versus-continuous and volatility-instability state differentiates subsequent outcome dispersion after chronological controls.

Null: after the same controls, it does not differentiate subsequent outcome dispersion.

## Research-integrity boundary

The complete J7/J8 plan is frozen before results. Both experiments bind to:

- the accepted Day 31 J7/J8 foundation digest;
- Day 32 monotonic trial registry;
- Day 37 chronological split contract;
- purge and embargo;
- episode-independent effective N;
- holdout-tuning prohibition;
- exact candidate code head.

The minimum independent evaluation N remains 30 for this research contract. An insufficient result is a valid retained result and is not a reason to lower the floor.

No threshold is tuned on the evaluation cohort. A single non-null result cannot create a trading gate.

## CVOL boundary

CME CVOL remains deferred. Day 43 does not purchase, license, fetch or activate CVOL. Any later CVOL proposal requires evidence that the existing GVZ channel is useful plus explicit owner approval for spend/licensing.

## Shadow-only status

Day 43 outputs are research/shadow evidence. They do not become decision inputs, regime/abstention gates, formal Day-53 forward evidence, account-risk authority, broker instructions, Telegram publication, or Super Signals integration.

## Acceptance

Day 43 passes only if:

- the exact Day 42 base and bounded five-file surface are proven;
- Day 31 current/retrospective states and J7/J8 foundation still verify;
- all IV/RV/jump/vol-of-vol horizons and estimator identities remain explicit;
- no redundant estimator is added;
- missing ex-ante options term structure stays unavailable rather than fabricated;
- unexplained shock remains market-derived with no narrative/intent label;
- J7/J8 are preregistered under Day 32/37 contracts and retain null/insufficient outcomes;
- focused adversarial and full regression tests are green;
- deterministic acceptance evidence is byte-identical across repeated runs;
- CVOL is unpurchased/unlicensed and no trading gate, predictive claim, formal-forward evidence, broker/Telegram/Super Signals side effect or autonomous promotion is created.
