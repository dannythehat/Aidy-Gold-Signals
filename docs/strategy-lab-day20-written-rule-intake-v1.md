# B06 Day 20 — Written-rule intake and source-to-StrategySpec adapter

**Status: IMPLEMENTED; do not tick until GitHub CI passes and PR is merged.**

## Scope — deliberately narrow, fail-closed

This first written-rule adapter recognises **one strictly enumerated AIDY-internal EMA crossover text grammar**, taken from the exact Day09 internally authored source fixture. It is not a general natural-language trading-rule inference model. Source text is treated as UTF-8 data; no expressions or arbitrary Python are evaluated.

The adapter requires original source bytes plus a separate JSON review envelope containing a full human-confirmed Day08 `StrategySpec v1`, the declared source hash, snapshot reference, reviewer identifier and UTC confirmation timestamp. Tests generate a **synthetic review envelope**, explicitly NOT an owner's approval or an external trader's original rules.

The adapter verifies:

1. The full normalised source text matches a supported, explicitly enumerated grammar. Extra clauses, missing conditions, alternative markets, cross-down or RSI rules are rejected as `UNSUPPORTED_WRITTEN_RULES`, never inferred.
2. The review document is well-formed, pins the original source bytes by SHA-256 and includes a strict `StrategySpec` which rebinds to those exact bytes and reference.
3. Every supported material rule agrees literally: EMA(10/30) indicator periods, fully closed M5 crossover direction, bid OHLC source with fixed-EST clock, no shorts, 50 closed-bar warmup, Monday–Friday UTC 07:00–21:00 sessions, stop 120 broker ticks, target 240 ticks, maximum 48 bars, 1% risk/2% portfolio risk, no hedging or pyramiding, next tradable quote execution. The adapter also explicitly **rejects unmentioned additional** filters, days off, trailing rules or partial exits rather than adding them.
4. The Day09 rule-completeness validator rechecks the typed StrategySpec and byte-matched source. Approval is *source and rule completeness for further reproduction only*. It is never a strategy performance, broker parity, source platform replication or owner sign-off claim.
5. Two **independently implemented** closed-bar EMA signal evaluators, one driven by parsed source periods and one driven by the typed StrategySpec, must produce identical crossover indices on the **frozen synthetic M5 price sequence**. Both explicitly use an SMA-seeded recursive EMA rule as a test convention, which the original source itself warns is not yet platform qualified. Thus mathematical test parity on artificial prices **does not imply parity with the original indicator platform**.

Original document: `research/strategy_lab/fixtures/day09_internal_source_rules.txt`. Independent M5 price test data: `research/strategy_lab/fixtures/day20_closed_ema_parity_prices.json`. No source at this stage is a claimed third-party published trading system.

## API

`admit_written_rules(source_bytes, review_bytes) -> WrittenRuleAdmission` verifies source hash, reviewer envelope, exact supported grammar and typed spec with Day09 completeness checks.

`read_supported_written_rules(source_bytes)` returns only explicitly recoverable supported fields, never invented default indicators.

`written_source_signal_indices(source_bytes, closes)` and `strategy_spec_signal_indices(spec, closes)` are independent test-only interpreters of the narrow EMA crossing subset and return closed-bar **indices**, not broker orders.

## Limits and next requirements

A review envelope's plain-text reviewer field is not an authenticated human signature. No owner acceptance was obtained. Genuine external written strategies remain **BLOCKED** unless their complete rules are confirmed and supported. EMA seeding/platform parity, live broker data, holiday schedules, source redistribution rights and historic 2020–26 quote normalisation remain separate research gates.

Day21 introduces a securely restricted Python strategy interface and isolation; Day22 Pine and Day23 MQL are different, independent source-platform adapters.

## Acceptance result

Pending real CI evidence and main-branch merge. Never tick Day20 for a failing or queued check.
