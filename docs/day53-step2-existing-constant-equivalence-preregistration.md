# Day 53 — Step 2 existing-constant equivalence preregistration

Status: **PREREGISTERED — NO STEP 2 RESULT EXISTS YET**  
Registration date: 2 September 2026  
Contract version: `aidy_day53_step2_existing_constant_equivalence_v1`

## Question being tested

Does changing only the Gold market-data semantic family from HistData to Twelve Data preserve the existing active V2 decision surface sufficiently to inherit the existing:

- H1 ATR volatility threshold `20 bps`;
- H1 ATR volatility threshold `50 bps`; and
- V2 H1 ATR analogue similarity scale `40 bps`?

This is an **inheritance/equivalence qualification**, not a search for better constants. There is one registered configuration: `20 / 50 / 40`. If it fails, Step 3 must open a new preregistered re-derivation family. The Step 2 tolerances and parameter values may not be changed because the result is inconvenient.

The legacy V1 M15 realised-volatility scale `30 bps` is explicitly outside this contract. V2 deliberately excludes that feature from its soft similarity votes.

## Prior knowledge disclosure

This experiment is informed, not blind. Before this preregistration the team had already observed approximate HistData/Twelve reconciliation differences of:

- median absolute difference: about `10–14 bps`;
- p95 absolute difference: about `38–57 bps`;
- tail maximum: about `97 bps`.

Those observations are prior evidence. They are disclosed so the acceptance rules cannot later be presented as if they were selected without any knowledge of the source difference. They do **not** count as the Step 2 qualification sample.

## Source identities

The contract binds the exact current deterministic HistData and Twelve Data semantic identity digests produced by `market_data_semantics.py`. A result produced against a different source identity, candle-construction version, session/DST policy, price-basis identity or completeness rule does not satisfy this contract.

## Frozen population

The eligible H1 population is mechanically constructed from bucket ends between:

- `2026-01-01T00:00:00+00:00`, inclusive; and
- `2026-08-31T23:00:00+00:00`, inclusive.

An H1 bucket is pairable only when both source-native constructions contain the complete information required to calculate H1 ATR(14). Twelve rows connected to failed or incomplete bootstrap provenance are forbidden. There is no imputation, winsorisation, outlier trimming or exclusion based on observed source difference, regime, similarity, rank or result.

The qualification subset is selected without looking at values:

`sha256("aidy-day53-step2-v1|" + h1_bucket_end_utc) mod 4 == 0`

The retrieval-query subset is then selected from that qualification set using:

`sha256("aidy-day53-step2-v1|retrieval|" + h1_bucket_end_utc) mod 4 == 0`

The historical candidate universe is all otherwise-eligible frozen HistData retrospective cases at or before the cutoff. Its exact case-ID universe digest must be registered before scoring begins.

The cross-source comparison is a **qualification-only research harness** and is never decision input. For the Step 2 retrieval comparison, non-target query components are held fixed to the HistData baseline and only H1 ATR(14) bps plus its derived 20/50 volatility band are substituted from Twelve Data. This isolates the surface under test rather than silently treating the other Step 1.5 amber candle-derived features as already qualified.

## Minimum evidence before a result may be evaluated

All of the following are required:

- at least `600` paired H1 qualification observations;
- at least `60` distinct New York trading dates;
- at least `20` distinct dates under New York UTC-05 and `20` under UTC-04;
- at least `60` observations where either source is within ±5 bps of the `20 bps` threshold;
- at least `60` observations where either source is within ±5 bps of the `50 bps` threshold;
- at least `250` deterministic retrieval queries;
- at least `150` queries where both baseline and comparison retrievals are non-empty;
- at least `50` retrieval queries in each of Asia, London and New York session labels; and
- paired feature coverage of at least `95%` of the mechanically defined common scheduled H1 universe.

If any minimum is missing, the outcome is **INSUFFICIENT EVIDENCE**, not PASS by discretion.

## Frozen statistics

Binomial agreement/disagreement rates use a two-sided Wilson score 95% interval. Set overlap uses Jaccard similarity. Jaccard is evaluated only where at least one retrieval is non-empty; empty/empty cases remain in the separate retrieval-state agreement statistic. Percentiles use deterministic nearest-rank calculation.

The paired ATR absolute-difference median, p95 and maximum must always be reported, but distribution similarity alone cannot create a PASS.

## PASS criteria — all mandatory

### 20/50 volatility decision surface

- paired feature-availability agreement ≥ `98%`;
- three-class `low / normal / high` volatility-band agreement ≥ `97.5%`;
- Wilson 95% lower bound for overall band agreement ≥ `96%`;
- around each threshold separately, disagreement ≤ `12.5%`;
- around each threshold separately, Wilson 95% upper bound for disagreement ≤ `20%`;
- V2 volatility hard-gate boolean agreement ≥ `97.5%`;
- Wilson 95% lower bound for V2 hard-gate agreement ≥ `96%`; and
- the low/high volatility-band predicate used by the four affected setup definitions agrees ≥ `97.5%`.

The four mapped setups are:

- `low_vol_break_pressure_long`;
- `low_vol_break_pressure_short`;
- `high_vol_recovery_long`; and
- `high_vol_recovery_short`.

Only the band-dependent predicate is a Step 2 PASS criterion. Full setup eligibility is diagnostic because the remaining setup inputs include Step 1.5 amber source/candle-sensitive surfaces that this experiment does not claim to qualify.

### 40 bps V2 analogue geometry

Under the controlled substitution described above:

- baseline/comparison empty-vs-non-empty retrieval state agreement ≥ `95%`;
- Wilson 95% lower bound for that state agreement ≥ `93%`;
- selected independent-episode set Jaccard median ≥ `0.80`;
- selected-set Jaccard p10 ≥ `0.60`;
- top-ranked selected episode agreement ≥ `90%`;
- Wilson 95% lower bound for top-rank agreement ≥ `87%`;
- at least `95%` of queries have selected-episode count difference ≤ 1;
- evidence-grade agreement ≥ `95%`; and
- Wilson 95% lower bound for evidence-grade agreement ≥ `93%`.

Every mandatory rule must pass. There is no borderline committee override.

## FAIL, INSUFFICIENT and invalid-run rules

**FAIL:** required coverage exists but any mandatory PASS boundary fails. Existing 20/50/40 inheritance remains blocked.

**INSUFFICIENT EVIDENCE:** any minimum sample/coverage requirement is missing, the candidate universe cannot be frozen, or a required uncertainty statistic cannot be computed. Existing 20/50/40 inheritance remains blocked.

**INVALID RUN:** contract/digest mismatch, outcome/P&L leakage, post-result exclusion, changed criteria, or another integrity violation invalidates that run. The attempted run remains part of research history but cannot emit an inheritance PASS.

No P&L, trade result, future return, target/stop outcome or forward evidence is allowed in the Step 2 equivalence calculation.

## Permission boundary

A Step 2 PASS means only that the frozen `20 / 50 / 40` constants may be inherited for their registered scale-sensitive surface.

It **does not** grant full HistData-to-Twelve cross-source analogue retrieval permission. The contract scope is:

`active_scale_sensitive_20_50_40_inheritance_only`

and `cross_source_retrieval_permission_on_pass=false`.

This distinction is deliberate. V2 and the wider dossier still consume additional candle/source-sensitive features recorded as amber in Step 1.5. Full cross-source retrieval therefore remains fail-closed until a later qualification record explicitly carries the separate scope `full_authoritative_v2_analogue_retrieval` and itself satisfies the append-only ledger rules.

## Registration and result chronology

The code module `src/aidy/day53_step2_preregistration.py`, this document and the repository preregistration manifest freeze the question, source pair, population rule, singleton parameter space, metrics and acceptance boundaries before Step 2 result computation.

Before an empirical Step 2 runner is allowed to score the data, matching research-family and `market_data_equivalence_contract_registered` payloads must also be appended to the validated D1 research-ledger chain. The repository preregistration proves what was frozen in Git; it is not a substitute for the runtime ledger append.

No Step 2 experiment or Twelve Data vendor request is performed by this preregistration change.
