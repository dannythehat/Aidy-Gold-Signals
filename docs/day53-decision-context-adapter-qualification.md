# Day 53 — decision-context adapter qualification

Qualification status: **NOT YET QUALIFIED FOR NEW TWELVE DATA COHORT**  
Audit date: 2 September 2026

## Separate contract

Market-feed qualification answers: “Can AIDY deterministically ingest the intended market instrument and construct complete current candles?”

Decision-context qualification answers: “Can AIDY construct the exact point-in-time decision packet from qualified inputs, with no stale, retrospective, differently scaled or future-derived evidence entering the model surface?”

Passing the first does not imply passing the second. Bootstrap is history population only. Live decision readiness is evaluated separately on a scheduler tick after the required current buckets are complete.

## Authoritative Twelve Data semantic path

For the new Twelve Data evidence epoch, the legacy historical-case and analogue-retrieval APIs are **not sufficient for qualification** even if they remain available for legacy research and regression compatibility.

The qualified path must use all of the following protected contracts:

- `aidy_market_data_semantic_identity_v1`
- `aidy_semantic_case_input_wrapper_v1`
- `aidy_semantic_analogue_query_v1`
- `aidy_semantic_analogue_retrieval_v1`

A Twelve Data PIT case input must carry the deterministic market-data semantic identity derived from the Gold feature packet source links. A historical candidate must carry its own semantic identity. Missing, invalid, mixed or differing semantic identities fail closed **before** the legacy similarity geometry is evaluated.

A cross-source candidate may enter the comparison set only when the authoritative append-only research ledger itself proves all of the following:

1. the full supplied research-ledger chain validates;
2. a `market_data_equivalence_contract_registered` record exists for the exact pair of semantic identity digests;
3. a later `qualification_result` record references the exact digest of that contract;
4. the result is `pass` and `inheritance_allowed=true`;
5. the qualification evidence digest is present and valid.

A caller-supplied equivalence string, agent assertion, document note or unverified in-memory flag is not admissible proof.

The research ledger must also remain consistent with the latest committed `aidy_research_ledger_anchor_v1` repository checkpoint. A D1 restore, table recreation or schema rewrite that moves the ledger behind the committed anchored sequence, changes the anchored digest/genesis, or drops the raw attempted-trial count below its committed floor is a qualification failure until reconciled by new append-only evidence. The checkpoint is a rollback-detection control, not a replacement research ledger.

## Required qualification record

The adapter may turn on for a formal cohort only when one immutable qualification record binds all of the following to the accepted code SHA:

1. **Gold market-data semantic identity**
   - Twelve Data source identity and XAU/USD mapping
   - raw M1 adapter version
   - session/DST/maintenance contract
   - aggregate candle-construction version
   - completeness/readiness rule version
   - no admitted candle from an incomplete/failed bootstrap window
   - Twelve Data price basis remains explicitly `vendor_ohlc_price_basis_not_contractually_identified` unless a separate evidence-semantic change qualifies a more specific basis

2. **Point-in-time boundary**
   - every admitted row has `first_observed_at <= as_of_utc`
   - retrospective HistData cannot enter a PIT feature packet
   - future/evaluation/outcome fields are structurally rejected
   - source revisions are selected only as known at the decision as-of time

3. **Current-bucket binding**
   - required M1/M15/H1/H4/D1 inputs refer to the current decision bucket where the contract requires them
   - stale prior H4/D1 IDs cannot satisfy current readiness
   - incomplete current buckets fail closed rather than falling back to stale aggregates

4. **Cross-source parameter and analogue boundary**
   - all source-scale-sensitive thresholds and numeric scales have an accepted provenance disposition
   - Twelve Data PIT cases use `aidy_semantic_case_input_wrapper_v1`
   - analogue queries use `aidy_semantic_analogue_query_v1`
   - analogue retrieval uses `aidy_semantic_analogue_retrieval_v1`
   - missing semantic identity is an automatic exclusion
   - differing HistData/Twelve Data identities are an automatic exclusion unless the append-only research ledger proves an exact-pair PASS equivalence result
   - legacy `build_pit_case_input` / `build_analogue_query` / `retrieve_analogues_v2` calls cannot by themselves satisfy the new Twelve Data cohort qualification

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
   - an invalid research-ledger chain or repository-anchor inconsistency blocks any ledger-derived equivalence permission

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
- attempted Twelve Data query against a HistData candidate with no accepted ledger equivalence: candidate excluded before similarity scoring
- attempted candidate with missing market-data semantic identity: candidate excluded before similarity scoring
- invalid/broken research-ledger chain presented as equivalence evidence: equivalence rejected
- D1 research-ledger state behind the latest committed repository anchor: qualification blocked

## Turn-on rule

The decision-context adapter remains **off for formal accumulation** until every mandatory item above is green under one accepted code head.

A successful feed bootstrap, a healthy HTTP endpoint, a successful model call or a non-empty context packet is not sufficient evidence of qualification.

The first scheduler-generated decision packet after qualification must still pass live current-bucket readiness. Qualification authorizes the adapter contract; it does not waive per-tick data-quality gates.

For Step 2 equivalence preregistration, the record must explicitly state that criteria are **informed rather than blind**: the team has already observed reconciliation differences of approximately 10–14 bps median absolute difference, approximately 38–57 bps at p95, and a tail maximum near 97 bps. Those prior observations do not determine PASS/FAIL, but they must remain visible as prior knowledge when the acceptance and rejection tolerances are frozen.