# B06 Day 20 — Explicit written-rule intake and evidence-bound StrategySpec

**Scope:** Real tested source-integrity intake and restricted closed-signal parity, not autonomous NLP, not external third-party strategy reproduction, not a profitable backtest.

## Data contract

`src/aidy/strategy_lab_written_rule_intake.py` provides `intake_written_rules(source_bytes, spec_json, evidence, expected_source_sha256, snapshot_ref)`:

- Original written-rule text must be preserved as exact UTF-8 bytes (<=250KB) with SHA-256 matching the caller's pinned expected source, `origin.source_sha256` and `origin.source_snapshot_ref`.
- The human-supplied StrategySpec v1 is parsed through Day08's strict schema. The intake **does not fill in missing indicator settings, stop prices, session hours, cost assumptions or short-side exit behavior**.
- The reviewer must supply every one of **18 independently enumerated, mandatory evidence groups**: identity, author/source, market/source basis, warmup, indicators, entry, stop, target, maximum holding, exit timing, no opposite-exit, no trailing, no partials, short-side disabled, UTC session calendar, sizing, portfolio risk, and entry execution.
- Each group binds all its full field values to one exact, unambiguous written-source excerpt; mismatches, missing or extraneous groups, source hash drift, altered fields and absent numerical values fail closed.
- Runs Day09's rule completeness/source hash assessment. Only a structurally accepted complete strategy proceeds.
- The supported predicate adapter covers only **closed M5 EMA(10) crossing above EMA(30)** on supplied fast/slow indicator values, where prior fast <= slow and current fast > slow, with 50 completed warmup bars. It does not calculate EMA indicators or claim the author's platform used identical EMA seed/rounding; source/platform parity remains for later B06.
- `WrittenRuleReceipt` pins source/spec/evidence SHA and completion status. Internal fixture flags explicitly show `internal_fixture_only=true`, `original_platform_parity_verified=false`, `independent_human_attestation_verified=false`.
- No external source was silently classified as verified. An excerpt's presence is **not** itself proof that a human checked the semantic mapping; independent reviewer approval and actual platform signal reproduction require later verified workflow.

## Tested reference case

`research/strategy_lab/fixtures/day20_internal_written_rules.txt` is an original, internally authored explicit EMA long-only reference, independent of any actual publisher. Tests use `research/strategy_lab/fixtures/strategy_spec_v1_sample.json` only after setting its original-source hash to that exact Day20 source file and explicitly completing all 18 source passages. No invented third-party rules or profits.

The independent oracle uses closed-bar previous/current fast/slow values, comparing `fast_prev <= slow_prev AND fast_now > slow_now`. Separate compiled StrategySpec predicate evaluation must match the oracle over a 58-bar trace, including crossing, equality boundary, later indicator changes, no lookahead, missing warmup and unordered 5-minute timestamps.

## Limitations for next day

Day21 implements a sandboxed Python source adapter. This Day20 module **never executes arbitrary source text or untrusted Python**, never connects to a trading account and never accesses private brokerage credentials. Commercial source rights, HistData chronology normalisation, actual Vantage contract evidence and historical platform parity remain open.

## Acceptance evidence

Populate immutable CI/job ID, source hash, actual test total, merge SHA and Notion day-level acceptance only **after** the independently passing run.
