# Day 40 — Architecture V2 pre-paper acceptance and adversarial failure gate

Decision date: 2026-09-01

Authoritative base: `cb31e28c38d38c173ab857badb487a75ac601b0f`

## Objective

Day 40 is the Architecture V2 hard stop before any formal forward-paper evidence can become authoritative.

The gate is machine-readable and contains exactly 18 P0 requirements. A requirement is passed only when its accepted implementation evidence is present in the repository and the required contract markers remain intact. The gate also runs an adversarial fail-closed matrix and records the market-data procurement decision required before the GC shadow/research work begins.

No Day 40 result authorizes live-money trading.

## J16 interpretation

Day 40 does **not** convert the Day 38 J16 result into a positive claim.

The accepted interpretation is:

- effective independent N, not raw N, is authoritative for grading;
- post-hardening J16 evidence is `INCONCLUSIVE`;
- when effective N is inadequate, the evidence is revised to `insufficient`;
- no monotonic or predictive ordering of evidence grades is claimed.

This satisfies the Architecture V2 requirement through conservative revision, not by inventing a relationship the data did not demonstrate.

## Formal-paper boundary

Any formal paper-performance metric generated before the Day 40 gate is non-authoritative and must be rejected by the gate.

Forward evaluation may only become authoritative after the later roadmap gates are satisfied.

## Adversarial failure matrix

The Day 40 matrix covers stale data, missing data, conflicting data, provider outage, OpenAI outage, storage outage, malformed model output, source revision, duplicate input and restart/replay.

Every scenario must fail closed to `no_trade` and must prove:

- no broker mutation;
- no Telegram publication;
- no Super Signals mutation.

Super Signals remains outside the AIDY architecture.

## Market-data procurement decision

### Decision

**GO: GC research architecture.**

**NO-GO: paid live GC subscription at this stage.**

AIDY will use free/public CME evidence and the Databento new-account historical-data credit before any recurring market-data subscription is considered.

Paid live GC is an evidence-triggered later decision, not a Day 40 requirement.

### Historical provider selected

Databento is the preferred historical GC provider for the free-first phase.

Dataset: `GLBX.MDP3`

GC research symbology:

- parent definitions/contract discovery: `GC.FUT`
- OI-ranked continuous research contract: `GC.n.0`

The continuous contract is used only as a vendor-resolved reference to the underlying genuine contract. Raw contract identity and provenance must be retained when data is archived.

### Approved schemas during the free-credit phase

- `definition`
- `statistics`
- `ohlcv-1m`
- `ohlcv-1h`
- `ohlcv-1d`
- `trades`
- `tbbo`
- `bbo-1m`

The following are deliberately prohibited during this phase:

- `mbo`
- `mbp-10`

AIDY does not need L2/L3/MBO simply because the provider offers them.

### Credit protection

The recorded free-credit policy is:

- signup credit reference: `$125`;
- maximum Day 40/41 committed credit: `$75`;
- reserve kept untouched: `$50`;
- maximum individual request: `$5`;
- every request must call Databento `metadata.get_cost` before download;
- the request is re-quoted immediately before download;
- any price increase after approval fails closed;
- no live subscription code exists in the Day 40 adapter;
- no paid activation is permitted without explicit owner approval.

These are ceilings, not spending targets.

### What is being built now

`src/aidy/databento_gc.py` provides a minimal historical-only Databento client using the existing `httpx` dependency.

It can:

- authenticate using `DATABENTO_API_KEY`;
- confirm the `GLBX.MDP3` entitlement;
- list schemas;
- inspect the account's available historical range;
- estimate request cost;
- enforce the free-credit policy;
- download a bounded JSONL historical request only after an approved quote;
- hash the downloaded bytes and return a provenance receipt.

It contains no Databento live-streaming implementation.

## Day 41 interpretation

The Day 40 procurement decision supersedes any practical interpretation that would force AIDY to buy a live GC feed merely to keep the calendar moving.

Day 41 may build and validate the GC shadow/research spine from properly licensed historical/delayed data while XAUUSD remains the live Gold observation/reference layer.

A paid live GC feed should be proposed only when a preregistered experiment demonstrates that information unavailable from the free stack has enough incremental value to justify live measurement.

## Acceptance

Day 40 can pass only when:

- the machine-readable P0 checklist reports `18/18`;
- all adversarial scenarios fail closed;
- full repository regression is green;
- the procurement decision is present and digest-bound;
- the Databento historical adapter and cost guardrails pass focused tests;
- no paid market-data subscription is activated;
- no live GC subscription is activated;
- no formal forward-paper evaluation is started;
- no broker, Telegram, or Super Signals side effect is introduced.
