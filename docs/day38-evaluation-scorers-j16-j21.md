# Day 38 — Evaluation scorers, post-hardening J16 and J21

Decision date: 2026-09-01

Authoritative base: `d800f417c8a93671875ed22378ef01eb8018c3c6`

## Objective

Day 38 creates the judgement-measurement layer required before AIDY can interpret paper or replay performance. It measures evidence use, safety, restraint, stability and falsifiability separately from outcomes, then runs the authoritative post-Day-24 J16 evidence-grade validity evaluation and the frozen Day-15 J21 setup-taxonomy differentiation evaluation.

A lucky P/L result is not a substitute for grounded or safe reasoning.

## Versioned judgement scorer

The scorer has eight required dimensions:

1. grounding;
2. schema/safety compliance;
3. setup/direction consistency;
4. factual accuracy/errors;
5. restraint/no-trade quality;
6. stability/disagreement;
7. thesis-invalidation correctness;
8. outcome dispersion.

Every score reports both `raw_n` and episode-independent `effective_n`. Grounding and schema/safety are non-compensatory gates: a failure in either makes a quality claim ineligible regardless of the other dimensions or realised P/L.

A subjective component cannot become authoritative merely because an LLM emitted a number. If a subjective component is used, it must reference an accepted, digest-protected calibration record based on a human-reviewed sample and reviewer protocol.

## Post-hardening J16

Day 23's J16 remains a descriptive baseline only. Day 38 evaluates the accepted Day-24 independent-episode evidence grades against realised 240-minute outcome dispersion from the exact frozen Day-23/24 case store.

The genuine warehouse runner verifies:

- all 1,000 accepted Day-24 result identities and payload digests;
- the frozen Day-23 query manifest digest;
- the frozen Day-24 candidate-store snapshot digest;
- no replacement or expanded dataset is silently used.

Evaluation query anchors are thinned chronologically with a frozen, outcome-blind 240-minute non-overlap rule before inferential summaries are formed. A grade is evaluable only when it has at least 10 independent evaluation episodes, at least 10 complete dispersion observations and at least 30 days of temporal span.

The result is one of `pass`, `null`, or `inconclusive`. `null` and `inconclusive` are retained scientific results. Day-38 architecture acceptance does not require J16 to pass.

## Risk–coverage

Risk–coverage operates on deduplicated episode identities, never raw message/decision bursts. Its confidence threshold grid must be frozen before evaluation. The evaluation output reports the curve but never chooses or recommends the best threshold from the same evaluation set.

## J21 setup-taxonomy differentiation

J21 evaluates exactly the 20 frozen Day-15 setup variants. No new label may be introduced after outcomes are observed.

Only historical cases with one unambiguous setup and a complete 240-minute outcome are eligible for the genuine warehouse evaluation. Evaluation episodes are selected chronologically using the same outcome-blind 240-minute non-overlap principle. Outcomes are direction-aligned and residualised within decision-time-known regime/session strata.

Each setup reports raw N, independent N, controlled effective N, controlled mean outcome and controlled dispersion. A setup needs at least 10 independent and controlled observations to be considered sufficient. Overall J21 is `differentiated`, `null`, or `inconclusive`. The pre-specified practical differentiation threshold is a controlled setup-mean span of at least 0.25 pooled standard deviations.

A null J21 is accepted evidence for later consolidation review. It never authorises taxonomy expansion or automatic consolidation.

## Scientific boundaries

- Outcomes do not define setup labels.
- Outcome values do not determine which temporal evaluation episodes are selected.
- Day-23 J16 cannot be promoted to authoritative status.
- Safety/grounding cannot be averaged away by P/L.
- Raw burst counts cannot substitute for effective N.
- Evaluation-set risk thresholds cannot be tuned in-place.
- Null and inconclusive results are preserved.
- No predictive-edge claim is created by Day 38.
- No live trading gate is created.
- No Telegram, broker or Super Signals side effects are permitted.

## Acceptance

Before merge:

1. changed-file Ruff passes;
2. focused Day-38 adversarial tests pass;
3. full repository regression passes;
4. genuine BigQuery acceptance reads the exact frozen Day-23/24 evidence;
5. J16 and J21 actual statuses are recorded even if null/inconclusive;
6. two exact-head warehouse acceptance runs produce byte-identical evidence artifacts;
7. the accepted result is persisted insert-only/idempotently by exact-head experiment identity;
8. merge uses the exact accepted PR head.
