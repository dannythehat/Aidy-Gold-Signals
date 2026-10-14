# B02 Day 09 — Rule Completeness and No-Lookahead Admission Gate

Status: **DAY 09 IMPLEMENTED AND CI PASSED**. Research branch only; no merge/deployment or broker authority.

## Contract and boundaries
- `src/aidy/strategy_lab_rule_validator.py` reads strictly parsed `StrategySpec v1` objects and optionally **actual source snapshot bytes from a trusted caller**. It reparses the wire representation so an unchecked directly-constructed dataclass cannot bypass schema validation.
- `assess_rule_completeness(spec, source_snapshot=...)` returns a deterministic `RuleAssessment` and machine-readable sorted diagnostics: `BLOCKED` or `RULES_COMPLETE_SOURCE_MATCHED`.
- A `RULES_COMPLETE_SOURCE_MATCHED` result means **structurally complete, internally consistent rules with the supplied source bytes matching declared SHA-256**. It does **NOT** establish original source authenticity beyond those bytes, code/source-platform parity, executability by the future engine, complete data coverage, valid broker contracts, returns or eligibility for VERIFIED strategy scoring.
- Source snapshot must be referenced, byte-present and match the declared SHA-256. Example file is a **deliberately illustrative, internally authored text fixture**, not an external publisher strategy; the validator is tested against its real bytes in CI.
- A full audit requires a mechanical candidate, no outstanding interpretation questions, declared supported market/timeframe and source-bid/clock contract, actual trading session windows, at least one enabled side and complete protective stop/terminal exit plan.
- Fail closed for unknown/source-unmatched data, D1/unqualified source trading-day sessions, unsupported multi-timeframe indicator release times, unknown indicator parameters or smoothing rules, missing/insufficient warm-up, non-closed/future bar offsets (also rejected by Day08), contradictory risk budgets, session overlaps and ambiguous overnight schedules.
- Reject identical simultaneous long/short entry logic, duplicated or self-comparing predicates and **provably impossible** numeric upper/lower bounds. This does NOT claim to solve all logical contradiction forms.
- Partial, trailing and opposite-side exits are represented by Day08, but require frozen precedence and platform semantics not in StrategySpec v1. Validator explicitly refuses to certify them instead of inventing execution behaviour.
- Structured scope currently admits EMA/SMA baseline indicators on same signal timeframe; actual reference computations and source-platform parity will be tested at later execution/adapter gates. RSI/ATR smoothing is not yet frozen; those indicator rules are therefore rejected for reproduction. Tick-distance monetary interpretation awaits a qualified broker contract.

## Testable acceptance (Day 09)
1. An internally authored complete XAUUSD reference-spec fixture with independently supplied and SHA-256-matching source bytes passes rule completeness with deterministic output.
2. Day08 example *without* a source snapshot is blocked despite passing the schema-only tests.
3. Negative tests cover omissions, contradictory risk bounds/sessions/exits, source provenance mismatch, same-bar/HTF availability, insufficient warmup, invalid direct-dataclass construction, impossible conditions and unsupported semantics.
4. GitHub CI independently runs both Day08 schema and Day09 validator tests, source compilation, Ruff and the frozen original source digest; link immutable logs/commit after pass.

## Explicit non-claims
This is **not** a strategy interpreter, indicator calculator, source-parity engine, broker fill simulator, historical-data rights determination or profit report. No strategy was traded. No live AIDY/GoldThinker/MT5 behaviour changed.

Day 10 builds the canonical versioned registry and persistent content hashes. Later B06 adapters must independently reproduce source-platform signals before any VERIFIED label.

## Day 09 verified acceptance record (14 October 2026)

**Day-level result: PASS** — isolated code, nontrivial negative tests and documented internal-source fixture. No external strategy profitability or platform-parity claim.

- **CI:** [Day 09 real GitHub Actions acceptance](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38527183781) (job `115730191293`): **98 passing Day08+Day09 tests**, Ruff/static compilation pass, one non-failing warning.
- **CI source commit:** `da05c2b78938d38d0fd09cf0a7ea39af369c467a`; implementing module `src/aidy/strategy_lab_rule_validator.py`.
- **Actual internally authored source fixture digest:** SHA-256 `01d539024f28d37d0770bf9c4a58fc72ad24a29dc934c088fc022399051d0909` (computed by GitHub Actions with `sha256sum`).
- **Canonical parsed sample spec digest:** `de4fe9b278c77643508f6e88bd7ac2eb00a4d3b7abaece8a32b007de20a83a59`.
- **Live CI demonstration:** prior Day08 example without original snapshot returns `BLOCKED`; the same internal example supplemented with source reference and matching real bytes returns `RULES_COMPLETE_SOURCE_MATCHED`.
- **Clarification:** example rules are internal **synthetic rules**, no independent source-platform parity, true historical signals, fill simulation or historical profitability. Positive validation certifies syntactic/completeness and source-byte matching only, **not** strategy edge or commercial licensing. B02 stage NOT owner-accepted.
