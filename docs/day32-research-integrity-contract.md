# Day 32 — PIT attestation, leak audit and immutable trial registry

Day 32 makes Architecture V2 anti-hindsight and experiment discipline machine-auditable. It layers
new registries over accepted Day 0–31 contracts and does not mutate earlier scientific meaning.

## Field-level PIT attestations

Every leaf in the accepted context-packet V7 surface receives an immutable attestation. Day 32 also
records whether that leaf is already on the active Master Trader decision surface or is an accepted
staged V2–V7 field awaiting the later Context Composer V2 integration. Day 32 does not silently
pretend that the existing Master Trader already consumes all V7 fields.

An attestation names the field/contract/version, source and evidence family, provenance class,
observation/effective timestamp, publication timestamp when known, first-observed timestamp,
timing semantics, staleness rule, quality state, PIT reconstructability, reconstruction
method/version, historical-backfill policy, retrospective/evaluation eligibility, decision
eligibility, surface state and the covered context hash.

Timing is source-aware rather than forced into one ordering. Ordinary observations cannot be known
before they exist. Deterministic as-of fields share one derived timestamp. Official forward schedules
may legitimately be known before their future effective event time, but they must still carry the
actual publication/first-observed boundary that made the schedule knowable.

Historical backfill is never inferred merely because a field is decision eligible. First-observed
sources such as current Gold, official cross-market capture, CME capture and GVZ may only be
reconstructed from their real captured boundary unless a separate accepted historical contract says
otherwise. Missing coverage, duplicate identities, illegal PIT/decision combinations, impossible
timing, unsupported historical backfill or digest tampering fail closed.

## Deliberate leak audit

The deliberate leak audit has ten blocking categories: later revisions, overwritten vendor files,
publication lag, missing historical release times, retrospective evidence before first observation,
timezone/date-only/DST ambiguity, future outcomes in decisions, UNKNOWN converted to ABSENT,
context-hash coverage gaps and attestation/contract mismatch.

Every leak finding must reference a real attested field identity. Synthetic labels that are not in
the manifest are rejected. Acceptance adversarial fixtures remain immutable and visible after they
are resolved; an unresolved blocking finding makes decision input ineligible.

## Immutable experiment trial registry

Every experiment is pre-registered with a monotonic trial identity, hypothesis/null, dataset and
feature/context versions, frozen parameters, chronological split, purge/embargo, evaluation and
holdout identities, exact code/evidence digests and pre-execution time. Results include passed, null,
insufficient and failed. Trial records are digest-chained. Holdout reuse for tuning is forbidden.

## BigQuery acceptance boundary

The four bounded EU Day-32 tables remain analytical memory, not source truth. Their write contract is
insert-only and idempotent, consistent with the accepted Day-4 BigQuery contract.

For a new experiment identity, the exact immutable rows may be inserted once. On an exact rerun,
Day 32 reads the existing identity/digest/payload set and must reconcile it byte-for-byte without
writing again. Existing experiment rows are never deleted or overwritten to make a rerun pass.
Duplicate identities, identity-set drift, digest mismatch or payload mismatch fail acceptance.

## Acceptance

Acceptance requires changed-file Ruff, adversarial focused tests, full regression, deterministic
artifact reruns and genuine bounded reconciliation to the four deliberate EU BigQuery tables. The
summary must separately report active Master Trader decision fields and accepted staged V7 fields.
Day 32 creates no predictive claim, trading gate, paid source, production resource, broker/account
access or Super Signals change.
