# Day 53 — Step 2 existing-constant equivalence preregistration

Status: **PREREGISTERED — NO STEP 2 RESULT EXISTS YET**  
Registration date: 2 September 2026  
Contract version: `aidy_day53_step2_existing_constant_equivalence_v2`

## Pre-result revision from v1

This v2 preregistration supersedes the repository-only v1 preregistration after review and **before** any D1 research-family/equivalence-contract append, empirical Step 2 scoring, qualification result visibility or new Twelve Data vendor request.

The revision makes four design choices explicit and digest-bound:

- PASS uses a **logical conjunction of every mandatory criterion**, not a composite score;
- the near-threshold region is exactly an **inclusive ±5 bps** window triggered when either source lies in that region;
- a HistData/Twelve H1 pair must be the **exact same UTC H1 interval**, matching both start and end after each source constructs its bar independently; and
- the scoring guard must prove the repository manifest contract digest equals the append-only D1 ledger contract digest before scoring can begin.

No numerical acceptance threshold, minimum-evidence requirement, singleton parameter value or timestamp-hash sampling rule changed from v1. No empirical result was observed between v1 and v2.

## Question being tested

Does changing only the Gold market-data semantic family from HistData to Twelve Data preserve the existing active V2 decision surface sufficiently to inherit the existing:

- H1 ATR volatility threshold `20 bps`;
- H1 ATR volatility threshold `50 bps`; and
- V2 H1 ATR analogue similarity scale `40 bps`?

This is an **inheritance/equivalence qualification**, not a search for better constants. There is one registered configuration: `20 / 50 / 40`. If it fails, Step 3 must open a new preregistered re-derivation family. The Step 2 tolerances and parameter values may not be changed because the result is inconvenient.

The legacy V1 M15 realised-volatility scale `30 bps` is explicitly outside this contract. V2 deliberately excludes that feature from its soft similarity votes.

## Why PASS is conjunctive

PASS is deliberately a **logical conjunction of all mandatory coverage and decision-surface tests**. There is no weighted or composite score and no compensating rule under which strong performance on one metric offsets failure on another.

That stringency is intentional and was chosen before result visibility. This is an inheritance test, so the burden sits on retaining the old constants. If any registered mandatory surface fails while evidence coverage is sufficient, the result is FAIL rather than a partially favourable composite score.

## Prior knowledge disclosure

This experiment is informed, not blind. Before this preregistration the team had already observed approximate HistData/Twelve reconciliation differences of:

- median absolute difference: about `10–14 bps`;
- p95 absolute difference: about `38–57 bps`;
- tail maximum: about `97 bps`.

Those observations are prior evidence. They are disclosed so the acceptance rules cannot later be presented as if they were selected without any knowledge of the source difference. They do **not** count as the Step 2 qualification sample.

## Source identities

The contract binds the exact current deterministic HistData and Twelve Data semantic identity digests produced by `market_data_semantics.py`. A result produced against a different source identity, candle-construction version, session/DST policy, price-basis identity or completeness rule does not satisfy this contract.

## Frozen population and exact H1 pairing

The eligible H1 population is mechanically constructed from bucket ends between:

- `2026-01-01T00:00:00+00:00`, inclusive; and
- `2026-08-31T23:00:00+00:00`, inclusive.

The two sources must refer to the **same calendar H1 interval**. Comparable-but-different calendar periods are forbidden.

Each source constructs its H1 candle using its own frozen source semantics first. HistData uses its fixed EST source clock and source-hour aggregation without the AIDY New York session filter. Twelve uses UTC vendor M1 rows, the AIDY New York gold-session calendar, exact expected-minute completeness and UTC-epoch H1 boundaries.

Only after those source-native constructions exist may a pair be formed. The pair key is the half-open interval `[start_utc, end_utc)`, and both of these equalities are mandatory:

- `histdata.open_time_utc == twelve.open_time_utc`; and
- `histdata.open_time_utc + 60 minutes == twelve.open_time_utc + 60 minutes`.

For H1, HistData's fixed UTC-05 whole-hour boundaries and Twelve's UTC-epoch whole-hour boundaries both land on UTC hour boundaries. The harness must still test equality rather than assume it. This statement is specific to H1; it does not assert equivalence for H4/D1 construction.

An H1 bucket is pairable only when both source-native constructions contain the complete information required to calculate H1 ATR(14). Twelve rows connected to failed or incomplete bootstrap provenance are forbidden. There is no imputation, winsorisation, outlier trimming or exclusion based on observed source difference, regime, similarity, rank or result.

The qualification subset is selected without looking at values:

`sha256("aidy-day53-step2-v1|" + h1_bucket_end_utc) mod 4 == 0`

The retrieval-query subset is then selected from that qualification set using:

`sha256("aidy-day53-step2-v1|retrieval|" + h1_bucket_end_utc) mod 4 == 0`

Those timestamp-hash rules are unchanged from v1.

The historical candidate universe is all otherwise-eligible frozen HistData retrospective cases at or before the cutoff. Its exact case-ID universe digest must be registered before scoring begins.

The cross-source comparison is a **qualification-only research harness** and is never decision input. For the Step 2 retrieval comparison, non-target query components are held fixed to the HistData baseline and only H1 ATR(14) bps plus its derived 20/50 volatility band are substituted from Twelve Data. This isolates the surface under test rather than silently treating the other Step 1.5 amber candle-derived features as already qualified.

## Frozen near-threshold region

The sensitive-region window is exactly **±5 bps, inclusive**, around each threshold separately.

For a threshold `T` in `{20, 50}`, an observation belongs to that threshold region when:

`abs(HistData_ATR14_bps - T) <= 5 OR abs(Twelve_ATR14_bps - T) <= 5`

The two threshold regions are evaluated independently. An observation may enter both regions if the two sources are sufficiently far apart that one source triggers the 20-bps region and the other triggers the 50-bps region. That possibility is retained rather than discarded because it is itself evidence of source-semantic disagreement.

No percentile-defined, adaptive or post-result boundary window is permitted.

## Minimum evidence before a result may be evaluated

All of the following are required:

- at least `600` paired H1 qualification observations;
- at least `60` distinct New York trading dates;
- at least `20` distinct dates under New York UTC-05 and `20` under UTC-04;
- at least `60` observations in the frozen inclusive ±5 bps region around the `20 bps` threshold;
- at least `60` observations in the frozen inclusive ±5 bps region around the `50 bps` threshold;
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
- around each frozen ±5 bps threshold region separately, disagreement ≤ `12.5%`;
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

Every mandatory rule must pass. There is no borderline committee override and no composite score.

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

## Repository ↔ D1 digest equality before scoring

The repository preregistration manifest records the exact SHA-256 digest of `build_step2_equivalence_contract_payload()` and of the Step 2 research-family payload.

Before an empirical scorer may inspect or score the paired observations, the guard must verify all of the following:

1. the repository manifest is still in `preregistered_no_result` state;
2. its contract digest equals the contract digest computed from the checked-out code;
3. its research-family payload digest equals the research-family digest computed from the checked-out code;
4. the full supplied D1 research-ledger chain validates;
5. exactly one matching `research_family_registered` record exists and its payload digest equals the repository/code family digest;
6. exactly one matching `market_data_equivalence_contract_registered` record exists and its payload digest equals the repository/code contract digest; and
7. the research-family record precedes the equivalence-contract record in the append-only chain.

Any divergence fails loudly. It may not be reconciled by hand inside the scoring run.

## Registration and result chronology

The code module `src/aidy/day53_step2_preregistration.py`, this document and the repository preregistration manifest freeze the question, source pair, population rule, singleton parameter space, metrics and acceptance boundaries before Step 2 result computation.

Before an empirical Step 2 runner is allowed to score the data, matching research-family and `market_data_equivalence_contract_registered` payloads must also be appended to the validated D1 research-ledger chain. The repository preregistration proves what was frozen in Git; it is not a substitute for the runtime ledger append.

No Step 2 experiment or Twelve Data vendor request is performed by this preregistration revision.