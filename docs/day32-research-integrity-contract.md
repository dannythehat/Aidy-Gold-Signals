# Day 32 — PIT attestation, leak audit and immutable trial registry

Day 32 makes Architecture V2 anti-hindsight and experiment discipline machine-auditable. It layers
new registries over accepted Day 0–31 contracts and does not mutate earlier scientific meaning.

Every leaf in the active context-packet V7 model-facing surface receives an immutable attestation.
An attestation names the field/contract/version, source and evidence family, observation and
publication or conservative first-observed time, staleness/quality state, PIT reconstructability,
reconstruction method/version, retrospective/evaluation eligibility, decision eligibility and the
covered context hash. Missing coverage, duplicate identities, illegal PIT/decision combinations or
digest tampering fail closed.

The deliberate leak audit has ten blocking categories: later revisions, overwritten vendor files,
publication lag, missing historical release times, retrospective evidence before first observation,
timezone/date-only/DST ambiguity, future outcomes in decisions, UNKNOWN converted to ABSENT,
context-hash coverage gaps and attestation/contract mismatch. Findings remain immutable and visible
after resolution.

Every experiment is pre-registered with a monotonic trial identity, hypothesis/null, dataset and
feature/context versions, frozen parameters, chronological split, purge/embargo, evaluation and
holdout identities, exact code/evidence digests and pre-execution time. Results include passed, null,
insufficient and failed. Trial records are digest-chained. Holdout reuse for tuning is forbidden.

Acceptance requires changed-file Ruff, adversarial focused tests, full regression, deterministic
artifact reruns and bounded reconciliation to four deliberate EU BigQuery tables. Day 32 creates no
predictive claim, trading gate, paid source, production resource or Super Signals change.
