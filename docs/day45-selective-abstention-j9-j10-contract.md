# Day 45 — Shadow selective abstention and J9/J10

## Purpose

Day 45 makes abstention measurable without allowing the Master Trader to judge its own trustworthiness. The layer is deterministic around fit/calibration/test boundaries and remains shadow-only.

## Frozen architecture

- Fit, calibration and test windows are chronological and non-overlapping.
- The baseline is fitted only on the fit window.
- Split-conformal nonconformity is calibrated only on the calibration window.
- Test outcomes are untouched until evaluation.
- Model/LLM confidence is prohibited as a baseline feature or gate input.
- Risk–coverage uses episode-independent/effective N; raw counts are also reported.
- J9 compares selective abstention with deterministic random abstention at exactly matched coverage on the same independent episode pool.
- J10 tests whether the pre-declared volatility-instability state conditions abstention behaviour.
- No result on Day 45 may block the Master Trader, block publication, promote a feature, claim predictive edge or count as formal forward evidence.
- Any later promotion requires a separate owner-approved architecture decision.

## Scientific cohort

Acceptance reads the already-frozen `research_gold_cases` warehouse snapshot used by the accepted Architecture V2 evaluation stack. Only single-setup cases with complete 240-minute outcomes and known Day-11 volatility bands are eligible. A greedy chronological 240-minute outcome-blind episode rule converts overlapping historical cases into independent evaluation episodes before fit/calibration/test evaluation.

The accepted frozen historical store is small. Therefore `INSUFFICIENT` is an expected and valid scientific result if effective-N floors are not met. The implementation must not lower sample floors, alter thresholds, or tune the test set to manufacture a conclusion.

## Baseline and conformal wrapper

The deterministic baseline fits an adverse-outcome base rate plus simple per-feature centered slopes. Prediction is clipped to `[0, 1]`. Split-conformal calibration uses absolute binary residuals and the finite-sample quantile `ceil((n+1)*(1-alpha))`. The shadow position is `accept` only when the conformal upper-risk bound is no greater than the pre-declared risk ceiling.

This is a research risk-position output, not a trading instruction.

## J9

Hypothesis: selective abstention has lower adverse risk than random abstention at identical coverage.

The random comparator is generated deterministically from a frozen identity and episode ID. It selects the same number of independent test episodes as the selective layer. No repeated random search is permitted.

## J10

Hypothesis: volatility instability conditions selective abstention behaviour.

The initial threshold is frozen at `0.5` on the normalized instability field. It is not tuned on test outcomes. High/low subgroups must each meet their own effective-N floor before a conclusion is permitted.

## Acceptance

Day 45 passes as an architecture/research milestone when:

1. chronology and non-overlap are enforced;
2. test leakage into fit/calibration is structurally blocked;
3. model confidence cannot enter the layer;
4. raw and episode-independent/effective counts are visible;
5. matched-coverage J9 is deterministic;
6. J10 uses a frozen volatility threshold;
7. null/insufficient results are retained;
8. full repository regression remains green;
9. genuine frozen BigQuery cases are evaluated deterministically twice with byte-identical evidence; and
10. no trading/publication/promotion side effect exists.

Formal forward evidence still begins only at Day 53.
