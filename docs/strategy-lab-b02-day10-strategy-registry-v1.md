# B02 Day 10 — Strategy registry and canonical version hashes

Status: **DAY 10 IMPLEMENTED AND CI PASSED (2026-10-14)**. Production-intended isolated research component; no production AIDY, customer accounts, broker or GoldThinker access.

## Built in AIDY
- `src/aidy/strategy_lab_registry.py`: actual SQLite storage with transactional registration, read-back, source retrieval and integrity verification.
- Uses the **real Day08 StrategySpec schema** and Day09 `assess_rule_completeness` gate. Structurally incomplete, unqualified, or source-SHA-mismatched specs cannot be registered.
- Original input bytes retained as BLOB in `source_snapshots`, addressed by SHA-256. Source is treated as bytes only: no untrusted code execution, network calls, or claims of external source-platform parity.
- Version records preserve canonical JSON, exact author, original source reference, source SHA, full canonical specification SHA, *rule-only* SHA and previous version identity.
- Deterministic `version_id` binds strategy ID, revision, spec and rules hash, original source hash and preceding version. SHA calculations use sorted JSON, explicit version/domain separation for version/rules.
- Rules digest includes exact market/timeframe/clock, indicators, entry/exit, session, sizing, risk and execution. Title/author/source metadata edits change spec and version digests but not the trading rule digest.
- Enforces **revision=1 initially**, exact +1 subsequent revisions, and only exact repeats of existing revisions are idempotent. Changed rules or source cannot silently overwrite an existing revision.
- Four SQL write/delete triggers prohibit ordinary mutations of `versions` and `source_snapshots`. Read verification recomputes canonical hash/source checks and validates complete version chains.
- Local path is caller-chosen SQLite DB under an isolated research directory; no automatic production writes or migrations. An owner-level administrator with control of the database can bypass triggers, so this is **append-only application protection and independent rehash verification, not cryptographic immutability against privileged actors**. Future R2/object retention, off-site signed audit roots, multi-tenant authentication and backup policy require separate approval.

## API
`book = StrategyRegistry(Path('research_local/strategy_registry.sqlite3'))`;
`book.initialize()`;
`record = book.register(StrategySpec.from_wire(data), ORIGINAL_SOURCE_BYTES)`;
`book.versions('strategy_id')`;
`book.source_bytes('strategy_id', 1)`;
`book.verify_all()`.

`VersionRecord.to_wire()` yields stable source/spec/rules/version hashes, version, author, snapshot reference and original canonical JSON.

## Real acceptance criteria
1. Run actual SQLite transactions via temp file and reopen in another connection, including original bytes verification.
2. Exact repeats idempotent, rule changes require a new revision, revisions cannot skip, stable metadata-only rules hash is distinct from full spec hash, cross-strategy identities differ.
3. Direct UPDATE/DELETE blocked; missing trigger and forged stored JSON, altered source bytes or broken chain fail integrity checks after inspection.
4. Missing/contradictory rule or mismatched source hash cannot persist.
5. Github CI compilation, Ruff, Day08+09 regression and Day10 persistence tests PASS with the SHA of the original internal source fixture recorded.

## Proof and limits
The registered strategy in these tests is an **internal illustrative fixture**, not an independently reproduced third-party profitable strategy. No historical trades, MT5 fills or cash ledgers are claimed; B02 stage and user approval remain pending. Do not mark Day10 complete until linked CI evidence confirms all criteria.

## Confirmed Day 10 acceptance — 14 October 2026

- **CI:** [GitHub Actions run 38528470185](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38528470185), job `115734360892`; **117 tests passed**, strict Ruff/compilation passed (one non-fatal pytest config warning).
- **Passing build commit:** `b682c1f000523f0ab6279cd686c8e6a568e65e2d`.
- **Original internal test source SHA-256:** `01d539024f28d37d0770bf9c4a58fc72ad24a29dc934c088fc022399051d0909` (actual CI `sha256sum`).
- **Frozen canonical spec digest:** `de4fe9b278c77643508f6e88bd7ac2eb00a4d3b7abaece8a32b007de20a83a59`.
- **Rule-only digest:** `3e19350241ea3af65905fac1d8e42ca08e20d08a3294d783f34ef0c5fb7313f9`.
- **Version identity:** `aidy-v1-d8816e720a950cfcfa8b9cb40437cb9fd0d8c84dd2c62949bcd7a315ec22e32c`.
- **Disk-backed proof:** real SQLite database opened and a source-matched StrategySpec saved; a separate reopened reader recovered the exact record and original bytes. Negative tests tested malicious updates/deletes, invalid source, same-revision conflict and breaks in the version chain.
- **No real third-party strategy was imported**, and no broker fill or equity result was calculated. SQLite protection covers normal application modification, not a privileged attacker rewriting and rehashing a full database. Customer tenant controls, off-site immutable archives and B02 owner acceptance are separate later gates.
