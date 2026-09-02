# Day 53 Step 0 — evidence governance and trials ledger

Status: encoded before any empirical Twelve Data constant requalification.

## Purpose

Step 0 exists so empirical search cannot happen off-ledger and later be presented as preregistered evidence.

The authoritative record is the append-only `research_evidence_ledger`. Governance rules, research-family registrations, trial starts, terminal trial states, equivalence contracts, qualification results, effective-trial-count methods and governance amendments are all records in the same ledger.

The ledger is code-head-bound and hash-chained. D1 rejects `UPDATE` and `DELETE` at the database boundary.

## Frozen governance principle

The genesis governance record contains this rule:

> AIDY is permitted to conclude that no actionable edge exists. No research, qualification, accumulation or promotion rule may be changed solely because the evidence is approaching or has reached an unfavourable conclusion.

The rule is not kept only in this document. This document describes the implementation; the actual rule lives in the ledger genesis record. Any later amendment must be a new append-only governance-amendment record referencing the superseded record digest and evidence/reason for the amendment.

## Research families and trials

A research family must be registered before any result from that family is visible. Its registration includes:

- research family id
- question the family is intended to answer
- hypothesis
- optional preregistered parameter-space digest
- code head and immutable ledger timestamp through the enclosing ledger record

Every evaluated configuration is a trial. Failed, aborted and unattractive trials remain visible.

Mechanical/preregistered provenance is not accepted by self-report. A trial claiming preregistered enumeration or an ex-ante adaptive search must prove membership in the parameter space digest registered before first result visibility. Unknown provenance is treated as post-result/adaptive, not preregistered.

## Raw and effective trial counts

Raw attempted trials are factual and never decrease.

Any effective trial count used for Deflated Sharpe or another multiplicity adjustment is a derived statistic and must use a separately versioned, preregistered method. Reports must expose both raw and effective counts.

## Equivalence qualification

The default qualification state is `insufficient_evidence`.

A HistData/Twelve Data equivalence contract must be registered before the comparison run and must contain explicit:

- source semantic identity digests
- comparison-population digest
- minimum paired sample
- coverage requirements
- distribution metrics
- decision-surface metrics
- PASS criteria
- FAIL criteria
- INSUFFICIENT EVIDENCE criteria

Distributional similarity alone is insufficient. For the 20/50 bps regime bands, the contract must test resulting classification semantics around the thresholds. For 40/30 bps analogue geometry, it must test resulting distance/neighbour semantics.

Only affirmative `pass` allows inheritance. `fail` and `insufficient_evidence` both block inheritance.

## Sequencing

Empirical selection must not begin before Step 0 is operational.

Deterministic safety work may proceed in parallel:
- market-data semantic identity propagation
- cross-source analogue vetoes
- fail-closed readiness and provenance enforcement

Empirical work that must be ledgered includes:
- retaining or replacing 20/50 bps regime thresholds
- retaining or replacing 40/30 bps analogue geometry
- COT transform/lookback selection
- event-blackout duration estimation
- any parameter or configuration chosen after seeing earlier results

Formal Twelve Data accumulation remains zero until the qualification sequence is complete and a new evidence epoch is explicitly opened.
