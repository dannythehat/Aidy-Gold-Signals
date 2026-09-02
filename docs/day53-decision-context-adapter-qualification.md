# Day 53 — decision-context adapter qualification

Qualification status: **NOT YET QUALIFIED FOR NEW TWELVE DATA COHORT**  
Audit date: 2 September 2026

## Separate contract

Market-feed qualification answers: “Can AIDY deterministically ingest the intended market instrument and construct complete current candles?”

Decision-context qualification answers: “Can AIDY construct the exact point-in-time decision packet from qualified inputs, with no stale, retrospective, differently scaled or future-derived evidence entering the model surface?”

Passing the first does not imply passing the second. Bootstrap is history population only. Live decision readiness is evaluated separately on a scheduler tick after the required current buckets are complete.

## Required qualification record

The adapter may turn on for a formal cohort only when one immutable qualification record binds all of the following to the accepted code SHA:

1. **Gold market-data semantic identity**
   - Twelve Data source identity and XAU/USD mapping
   - raw M1 adapter version
   - session/DST/maintenance contract
   - aggregate candle-construction version
   - completeness/readiness rule version
   - no admitted candle from an incomplete/failed bootstrap window

2. **Point-in-time boundary**
   - every admitted row has `first_observed_at <= as_of_utc`
   - retrospective HistData cannot enter a PIT feature packet
   - future/evaluation/outcome fields are structurally rejected
   - source revisions are selected only as known at the decision as-of time

3. **Current-bucket binding**
   - required M1/M15/H1/H4/D1 inputs refer to the current decision bucket where the contract requires them
   - stale prior H4/D1 IDs cannot satisfy current readiness
   - incomplete current buckets fail closed rather than falling back to stale aggregates

4. **Cross-source parameter boundary**
   - all source-scale-sensitive thresholds and numeric scales have an accepted provenance disposition
   - analogue retrieval cannot compare Twelve Data live-query features with HistData-derived candidates until a same-instrument history, deterministic equivalence proof or preregistered normalization contract is accepted

5. **Macro/event context**
   - event rows are selected as-of, not by latest-known-today state
   - scheduled/published/first-observed timestamps are explicit
   - missing macro evidence is represented as `unknown`, never silently treated as clear

6. **Cross-market context**
   - each series has an explicit as-of reconstruction contract
   - missing/stale series remain missing/stale in the packet
   - no later revisions leak backward

7. **Signal lifecycle context**
   - only AIDY-owned signal lifecycle state is admitted
   - broker/account/follower/MetaAPI/MT5/Vantage/Super Signals state remains forbidden

8. **Replay/live determinism**
   - a fixed fixture set passed through replay and the live adapter produces identical canonical context payloads and hashes when the same qualified evidence is supplied
   - timestamp ordering, session labels, feature values and missingness states must match exactly

9. **Failure semantics**
   - unavailable/stale/incomplete evidence produces a deterministic fail-closed or explicit-unknown state
   - an infrastructure/data-quality failure cannot be recorded as a genuine `no_trade`
   - failed bootstrap or partial persistence cannot become visible canonical decision state

10. **Qualification immutability**
    - qualification record includes accepted code SHA, context contract version, source-semantic digest, parameter-provenance audit digest, fixture-set digest and test-result digest
    - any evidence-semantic change invalidates the qualification and follows the Day 53 cohort reset/preservation-proof rule

## Minimum acceptance fixtures

The qualification suite must include at least these deterministic cases:

- normal open-session scheduler tick with all current buckets complete
- cold bootstrap during an incomplete H4 bucket: history may ingest, decision readiness remains false
- incomplete current D1 bucket: no stale D1 fallback
- DST transition week under `America/New_York`
- maintenance-gap boundary
- one missing required vendor minute
- interrupted D1 persistence after at least one canonical write attempt
- stale macro evidence
- missing cross-market series
- attempted retrospective HistData injection into PIT context
- attempted cross-instrument analogue retrieval

## Turn-on rule

The decision-context adapter remains **off for formal accumulation** until every mandatory item above is green under one accepted code head.

A successful feed bootstrap, a healthy HTTP endpoint, a successful model call or a non-empty context packet is not sufficient evidence of qualification.

The first scheduler-generated decision packet after qualification must still pass live current-bucket readiness. Qualification authorizes the adapter contract; it does not waive per-tick data-quality gates.
