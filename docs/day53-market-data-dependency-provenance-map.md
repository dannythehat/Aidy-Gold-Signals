# Day 53 — market-data dependency and provenance map

Status: **FROZEN BEFORE STEP 2 EMPIRICAL QUALIFICATION**  
Audit date: 2 September 2026  
Purpose: enumerate the known consumers of feed-sensitive Gold features and pre-ledger setup geometry before any HistData/Twelve Data inheritance experiment is run.

This document is a dependency/provenance inventory, not an equivalence result. It does not authorize any blocked constant, setup rule or cross-source comparison.

## Scientific boundary

The current Twelve Data epoch must not ask only whether a numerical feature distribution looks similar to HistData. Qualification must cover the downstream decision surface that consumes that feature.

The dependency classes used below are:

- **direct numeric** — consumes the numerical feature or scale itself;
- **derived numeric** — computes another numerical quantity from it;
- **categorical downstream** — converts the numerical value into a label;
- **retrieval eligibility** — determines whether a historical candidate can enter comparison;
- **retrieval ranking/selection** — changes analogue similarity, ranking or threshold passage;
- **setup eligibility** — determines whether a deterministic setup candidate exists;
- **descriptive/context** — appears in decision context but is not itself an action;
- **decision-gating** — a later deterministic gate can admit/reject a model action because of the affected output.

## Dependency graph

### H1 `atr_14_bps`

Origin: `feature_engine._atr_bps`, ATR(14) divided by the latest close and multiplied by 10,000. It is therefore price-level normalized in basis points.

Known consumers:

1. `regime_classifier.classify_volatility_band`
   - class: **categorical downstream**
   - thresholds: `<20 bps => low`, `20–<50 => normal`, `>=50 => high`
   - Twelve status: **BLOCKED** pending preregistered inheritance/equivalence qualification or registered re-derivation.

2. `historical_cases` analogue feature view
   - class: **descriptive/context** and retrieval input
   - field: `h1_atr_14_bps`
   - makes H1 ATR available to analogue scoring.

3. `analogue_retrieval.py` V1
   - class: **retrieval ranking/selection**
   - numeric scale: `40 bps`, weight `0.75`
   - Twelve status: **legacy/unqualified**; legacy V1 retrieval cannot qualify the Twelve epoch.

4. `analogue_retrieval_v2.py`
   - class: **retrieval ranking/selection**
   - numeric scale: `40 bps`, weight `1.00`
   - similarity component is `max(0, 1 - abs(query-candidate)/40)` before weighted aggregation.
   - Twelve status: **BLOCKED** pending Step 2 qualification.

5. `setup_detector` risk basis
   - class: **derived numeric / descriptive-context**
   - carries `h1_atr_14_bps` into the research-normalized `1.0x_H1_ATR_stop_with_1R_and_2R_targets` risk basis.
   - current contract says `research_normalization_only=true` and `trade_recommendation=false`.
   - Twelve status: **BLOCKED from promotion to economic/live geometry** unless separately qualified.

### H1 `volatility_band` from the 20/50 thresholds

Known consumers:

1. `regime_classifier`
   - class: **categorical downstream**.

2. `historical_cases` analogue feature view via regime labels
   - class: **retrieval input**.

3. `analogue_retrieval.py` V1
   - class: **retrieval ranking/selection** as a categorical component.
   - legacy only for the Twelve epoch.

4. `analogue_retrieval_v2._hard_gate`
   - class: **retrieval eligibility**.
   - query and candidate `regime.volatility_band` must both be known and equal; mismatch excludes the candidate before soft similarity.
   - Twelve status: **BLOCKED** until the upstream 20/50 classification surface is qualified.

5. `setup_detector` — four setup definitions
   - class: **setup eligibility** and, indirectly, **decision-gating** because post-model safety only accepts setup codes present in current deterministic setup evidence.
   - affected setups:
     - `low_vol_break_pressure_long` requires `volatility_band == low`;
     - `low_vol_break_pressure_short` requires `volatility_band == low`;
     - `high_vol_recovery_long` requires `volatility_band == high`;
     - `high_vol_recovery_short` requires `volatility_band == high`.
   - Twelve status: **BLOCKED with the 20/50 regime thresholds**.

6. model dossier/current context
   - class: **descriptive/context**.
   - the model sees authenticated current context and deterministic setup/evidence surfaces derived from this regime. Any change in band assignment can therefore alter both current-context interpretation and which setup codes are legally admissible post-model.

### M15 `realized_vol_20_bps`

Origin: `feature_engine._realized_vol_bps`, population standard deviation of 20 decimal close-to-close returns multiplied by 10,000.

Known consumers:

1. `historical_cases` analogue feature view
   - class: **descriptive/context / retrieval input**.

2. `analogue_retrieval.py` V1
   - class: **retrieval ranking/selection**.
   - scale: `30 bps`, weight `0.50`.
   - Twelve status: **legacy/unqualified**.

3. `analogue_retrieval_v2.py`
   - the V2 manifest explicitly lists `m15_realized_vol_20_bps` among `deliberately_excluded_redundant_soft_votes`.
   - therefore the `30 bps` scale is **not an active V2 soft-similarity parameter**.
   - it remains a provenance concern only for legacy V1 retrieval or any future surface that reintroduces it.

Disposition: do not spend Step 2 trials requalifying `30 bps` for the authoritative V2 Twelve path unless a mapped active consumer is first reintroduced. Preserve the legacy block so V1 cannot silently qualify the Twelve epoch.

### M15 `atr_14_bps` and `m15_range_atr_ratio`

`setup_detector._observations` computes:

`m15_range_atr_ratio = M15 range_bps / M15 atr_14_bps`

when ATR is known and positive.

Known consumers:

- `low_vol_break_pressure_long`: requires ratio `>=1.00`;
- `low_vol_break_pressure_short`: requires ratio `>=1.00`.

Class: **derived numeric -> setup eligibility -> decision-gating**.

The ratio is dimensionless, so there is no nominal Gold-price rescaling problem. It remains candle/feed-semantic because both numerator and denominator depend on the source candle construction. Its `1.00` threshold predates the Step 0 trials ledger and has no clean preregistered discovery history established by this audit.

Disposition: **AMBER / pre-ledger provenance audit required**. It does not automatically require numerical re-scaling, but it cannot be advertised as cleanly preregistered discovery.

## Setup-detector provenance inventory

The current taxonomy manifest labels the rules `fixed_v1_descriptive_not_future_outcome_calibrated`. That statement describes intended use; it does not provide a recoverable ex-ante trial history. The detector predates the Step 0 immutable trials ledger. Therefore no setup threshold below may be represented as having clean ledger-backed discovery provenance.

### Category A — inherits the blocked 20/50 Twelve volatility surface

These setups cannot be qualified independently of the H1 volatility-band consumer graph:

- `low_vol_break_pressure_long`
- `low_vol_break_pressure_short`
- `high_vol_recovery_long`
- `high_vol_recovery_short`

The low-volatility pair also consumes the pre-ledger `m15_range_atr_ratio >= 1.00` rule.

### Category B — dimensionless thresholds, but pre-ledger and candle/session-semantic-sensitive

These include rules based on:

- M15 20-bar range position thresholds: `0.20`, `0.25`, `0.35`, `0.45`, `0.55`, `0.65`, `0.75`, `0.80`;
- session range-position thresholds: `0.15`, `0.20`, `0.80`, `0.85`;
- M15 close-location thresholds: `0.33`, `0.40`, `0.45`, `0.55`, `0.60`, `0.67`;
- M15 range/ATR ratio: `1.00`.

Affected setup families include trend pullback, trend momentum, recent/session extreme pressure, extreme rejection, countertrend reversal, range/session reversion, volatility transition and volatility recovery.

Disposition: **AMBER**. These quantities are dimensionless and must not be numerically changed merely because Gold's nominal price changed. However their original threshold-selection search history predates the ledger and the observed values depend on accepted candle/session semantics. Step 1.5 records that limitation before any Step 2 claim is made.

### Category C — sign/equality rules with no non-zero numerical calibration identified

Examples:

- `return_1_bps > 0` / `< 0`;
- `body_bps > 0` / `< 0`;
- categorical direction equality (`bullish`/`bearish`);
- trend-structure equality (`bullish_trend`, `bearish_trend`, `range`).

Disposition: **GREEN for nominal-price scaling, AMBER for candle-semantic provenance**. Zero/sign and categorical equality do not create an obvious numerical scale-transfer problem, but the upstream candle direction can still differ across feeds. They remain subject to end-to-end Twelve fixture qualification.

## Decision-surface chains that Step 2 must preserve or explicitly replace

### Chain 1 — volatility regime

`Twelve M1 -> aggregate H1 -> H1 ATR(14) bps -> 20/50 band -> analogue hard gate + volatility-dependent setup eligibility -> post-model setup gate`

A Step 2 test that examines only ATR distribution is insufficient. It must report band-classification disagreement and downstream hard-gate/setup eligibility disagreement under the preregistered comparison population.

### Chain 2 — analogue H1 ATR geometry

`Twelve H1 ATR bps -> historical-case analogue feature -> 40 bps numeric similarity -> overall similarity score -> min-similarity passage -> rank/episode representative selection -> evidence report/dossier`

A Step 2 test must therefore assess not only absolute ATR error but also similarity-score, threshold-passage and neighbour/episode-selection stability.

### Chain 3 — low-volatility expansion setups

`M15 range + M15 ATR -> range/ATR ratio -> low_vol_break_pressure setup` plus `H1 ATR -> volatility_band=low`.

Both branches can change setup eligibility; preserving only one does not preserve the setup decision surface.

## Evidence-grading dependency

`evidence_grading_v2` operates after analogue selection and grades the returned independent episodes using effective N, similarity/coverage/quality and temporal-dispersion metrics. It does not choose the 20/50/40/30 constants itself.

However it is **downstream-sensitive**: if those upstream parameters change the returned analogue set, the evidence grade/statistics presented to the model can change. Therefore evidence grading is not a calibration consumer, but it is part of the decision-surface comparison that Step 2 should observe.

## Context-composer dependency

`context_composer_v2` validates the selected retrieval and evidence report, then presents symmetric support/counter evidence, uncertainty and current authenticated context to the model. It does not calibrate 20/50/40/30 itself.

For the Twelve epoch, `aidy_semantic_context_composer_v1` is the required outer boundary: a verified semantic context and `aidy_semantic_analogue_retrieval_v1` must be supplied before the legacy Day-35 composer can receive the already-semantic-gated base retrieval. The final dossier binds the semantic identity and semantic retrieval digest.

## Step 2 prerequisites frozen by this map

Before any empirical inheritance test begins:

1. the research question/family and parameter space must be registered in the append-only research ledger;
2. the record must disclose the already-seen reconciliation figures (approximately 10–14 bps median absolute difference, 38–57 bps p95, tail near 97 bps) as prior knowledge;
3. PASS, FAIL and INSUFFICIENT criteria must be fixed before the new comparison results are observed;
4. the comparison population and sampling rule must be fixed;
5. downstream decision-surface statistics must be fixed, not selected after inspection;
6. FAIL and INSUFFICIENT both prohibit inheritance;
7. no setup or analogue parameter may be changed merely to improve the resulting forward decision rate.

## Current disposition

- `20/50`: **BLOCKED / active authoritative-path dependency**.
- `40 bps H1 ATR analogue scale`: **BLOCKED / active V2 dependency**.
- `30 bps M15 realized-vol scale`: **BLOCKED for legacy V1 reuse, not active in V2 soft similarity**.
- four volatility-band setups: **BLOCKED with 20/50**.
- `m15_range_atr_ratio >=1.00`: **AMBER, dimensionless but pre-ledger and feed-semantic**.
- remaining range-position/close-location thresholds: **AMBER, dimensionless but pre-ledger and candle-semantic-sensitive**.
- sign/equality rules: **no nominal-price rescaling requirement identified; still subject to Twelve candle-semantic qualification**.

No empirical parameter qualification was performed while producing this map.
