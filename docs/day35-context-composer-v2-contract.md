# Day 35 — Context Composer V2 contract

Decision date: 2026-09-01

Authoritative base: `e182084fa4484836a0e971892fde2890a7ee4890`

## Objective

Context Composer V2 is the deterministic, leak-safe dossier between authenticated point-in-time AIDY state and the Master Trader. It makes contradictory evidence at least as visible as supportive evidence and exposes the independence and quality limits of historical analogues.

## Frozen inputs

The composer accepts only:

- authenticated current context with a valid context hash;
- current AIDY regime/setup/state metadata;
- one valid Day-24 independent-episode retrieval result;
- one valid Day-24 V2 evidence report bound to that exact retrieval and selection identity;
- an explicit hypothesis direction and setup family when directional;
- optional current invalidation inputs that pass the same recursive PIT/runtime firewall.

## Symmetry and ordering

Support and counter-evidence are derived from the same Day-24 retrieval selection and the same evidence-report identity. Both use the same schema, retrieval digest, selection digest, report digest, effective independent N, raw N and evidence grade.

Counter-evidence is serialized before support evidence. The composer does not issue a second retrieval, substitute analogue cases, use outcomes to optimize selection or include raw historical `future_evaluation` objects. Only aggregate statistics validated by the bound Day-24 evidence report may enter the dossier.

## Mandatory fields under budget pressure

Optional explanatory detail may be removed deterministically. The following may never be removed:

- composer/dossier identity and current context identity;
- retrieval, selection and report digests;
- effective independent N, raw N and evidence grade;
- counter-evidence and support-evidence summaries;
- uncertainty and temporal-dispersion diagnostics;
- gate relaxations and `NO_COMPARABLE_CASE` reason;
- setup-family failure profile;
- supplied invalidation inputs;
- provenance;
- canonical prompt section ordering.

If the byte budget cannot hold the mandatory dossier, composition fails closed instead of dropping required evidence.

## Leak and runtime firewall

Recursive validation rejects future/evaluation objects, outcomes, realised P/L, MFE/MAE, raw trade outcomes, secret-bearing fields or values, API credentials, broker/account/follower state, Telegram/MetaAPI/Vantage runtime state, position sizing state and hidden reasoning traces.

## Honest sparse-history behavior

`NO_COMPARABLE_CASE` and query-insufficient states are first-class outputs. They retain zero effective N and explicit reasons. The composer never invents a historical signal to fill missing evidence.

## Day 35 boundaries

Day 35 does not:

- promote Context Composer V2 into the OpenAI gateway;
- alter Day-22 safety gates;
- create or weaken a trading/risk gate;
- claim predictive edge;
- access a broker/account/follower;
- modify Super Signals;
- store hidden chain-of-thought.

## Acceptance

Before merge:

1. changed-file Ruff passes;
2. focused Day-35 adversarial tests pass;
3. the full repository regression passes;
4. two exact-head acceptance artifact runs are byte-identical;
5. the accepted PR head is merged only after the above evidence is green.
