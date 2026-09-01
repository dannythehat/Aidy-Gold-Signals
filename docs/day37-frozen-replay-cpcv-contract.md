# Day 37 — Frozen replay, CPCV, purge/embargo and chronological holdout contract

Decision date: 2026-09-01

Authoritative base: `d988a4ff29160e2d10a32e6c151d028001e941f2`

## Objective

Build a deterministic historical replay/evaluation harness around AIDY's accepted research stack without allowing hindsight, temporal overlap, holdout tuning or external side effects. The harness exists to test frozen versions, not to manufacture a favourable backtest.

## Frozen dataset identity

Every replay begins from a digest-protected dataset manifest containing the exact historical case IDs, case digests, input digests, case times and future-outcome availability times. Case order is deterministic and the manifest is immutable.

Changing a case, case identity, source snapshot, dataset version or code head changes the dataset manifest identity.

## Point-in-time evidence boundary

Model-facing replay evidence must be explicitly decision-input eligible and its `first_observed_timestamp` must be at or before replay time T. Evidence first observed after T fails closed; it is never silently admitted because it is historically available today.

Future outcome objects remain evaluation-only and become usable only for scoring after their recorded `available_after_utc`.

## Chronological split contract

The primary evaluation layout is strictly chronological:

1. train
2. development
3. calibration
4. holdout

Boundaries must be strictly increasing. The holdout is frozen by identity and may score a frozen evaluation trial; it may not tune the version that sees it.

### Purging

Before each later split, prior cases are removed when their label/outcome interval overlaps the boundary or falls inside the configured pre-boundary purge buffer. This prevents a training label from carrying information across an evaluation boundary.

### Embargo

Cases immediately after a split boundary are excluded for the configured embargo interval. This reduces dependence created by tightly adjacent observations.

Purged and embargoed case IDs remain explicitly recorded in the split manifest rather than disappearing.

## CPCV contract

Combinatorial purged cross-validation is performed only on the pre-holdout research pool. Cases are deterministically divided into contiguous temporal groups. Each fold selects one or more groups as test groups; candidate training cases whose label intervals overlap the test interval expanded by purge/embargo are removed.

The frozen holdout is never used as CPCV train or test data.

## Day-32 trial registry binding

Every replay experiment is bound to a valid Day-32 trial record and records:

- trial identity/digest;
- dataset version and manifest digest;
- chronological split digest;
- CPCV digest;
- holdout identity;
- frozen code/model/version digest;
- frozen configuration plus configuration digest.

Configuration mutation after preregistration is forbidden. A tuning trial receives no holdout access.

## Holdout access

Holdout access is an explicit digest-protected event. It is allowed only for a Day-32 `evaluation` trial and only for case IDs in the frozen holdout identity.

Once accessed:

- the same holdout cannot be reused for tuning;
- tuning after access is forbidden for that frozen evaluation;
- silent promotion is forbidden;
- any changed version/configuration requires a new preregistered trial and appropriate unseen evaluation evidence.

Null, insufficient and failed evaluations remain valid scientific outcomes and are not discarded.

## Reproducible scoring

A score record freezes, for every evaluated case:

- case ID;
- replay input digest;
- retrieval identity/digest;
- decision digest;
- deterministic score payload.

The same frozen trial, dataset, split, version and per-case records must produce the same logical score record and digest.

## Side-effect boundary

Historical replay has no Telegram, broker, follower, execution or Super Signals side effects. It cannot create a live trading gate and makes no predictive-edge claim by itself.

## Acceptance

Before merge:

1. changed-file Ruff passes;
2. focused Day-37 adversarial tests pass;
3. evidence-first-observed-after-T tests fail closed;
4. dataset/case manifest mutation tests fail closed;
5. chronological overlap/purge/embargo tests pass;
6. CPCV never touches holdout and purges expanded test overlap;
7. tuning trial holdout access is rejected;
8. holdout scoring is logged and digest-protected;
9. replay input/retrieval/decision/score identity is deterministic;
10. full repository regression passes;
11. two exact-head acceptance artifacts are byte-identical;
12. merge uses expected-head protection.
