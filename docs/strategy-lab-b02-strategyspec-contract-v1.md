# B02 Day 08 — Canonical StrategySpec v1 (actual implementation)

Status: **DAY 08 IMPLEMENTED AND CI PASSED (2026-10-14)**. Research branch only; no production deployment, order execution or user-code execution.

## Implemented interface
- `src/aidy/strategy_lab_spec.py`: frozen, typed `StrategySpec` object graph, `from_wire`, `from_json`, `to_wire`, `to_json`.
- Exact schema version: `aidy.strategy_spec.v1`, canonical lower-case strategy identifier, positive revision, candidate class (complete mechanical / indicator / variant / opaque), attributable source author/language/licence/optional URL/source snapshot reference and required SHA-256. Publisher-claimed performance is stored under `origin.claimed_performance`, NEVER a verified result.
- Market declares XAUUSD, signal timeframe, data source, source clock and signal quote basis. Source clocks are explicitly `UTC` or `EST_FIXED_UTC_MINUS_05`; source broker-clock equivalence is not inferred.
- Indicators declare IDs, type (SMA/EMA/RSI/ATR), timeframe, input OHLC, lookback period and exact additional numeric parameters; undeclared indicator references fail.
- Signals are structured operands/predicates with closed-bar-only offsets and supported comparisons/cross events. Long and short entry plans are independently enabled/disabled. **No arbitrary Python/Pine/MQL code is evaluated.**
- Both sides explicitly declare stop, target, trailing stop, partial exits, maximum hold, opposite-signal exits and session-close behaviour. Distances are structured in ticks / price / percentage / ATR multiples.
- Explicit session clock, allowed weekday clock windows, date exclusions and flat-outside-session flag; sizing is either specified fixed lots or exact equity-risk percent; max positions, hedging/pyramiding and total-risk cap are explicit. Execution rules require closed-bar signals and next-tradable-quote entry intent.
- No financial defaults silently inserted by a parser. Unknown JSON keys, missing JSON keys, wrong data types, non-finite decimals, negative offsets, duplicate indicators/JSON keys and unsupported expressions fail closed. Binary float inputs prohibited for financial numbers.

## Scope boundaries
- `research/strategy_lab/fixtures/strategy_spec_v1_sample.json` is an **illustrative test fixture** and NOT a sourced external or profitable trading strategy. Its illustrative SHA-256 is not asserted to match an archived publisher original. Tests only establish strict schema round trip and rejection semantics.
- This schema records rule *structure*, it does not evaluate signals or independently verify indicator semantics. The B02 Day 09 validator must refuse VERIFIED status if rules, source snapshots, warmup, sessions, ATR dependencies, exit policy or interpretation are incomplete/ambiguous.
- Frozen schema objects parsed through documented `from_wire/from_json` public interface. Direct dataclass construction is intended only for internal, already-validated objects.
- Full platform-source parity (Pine/MQL/Python), broker cost/lot contract and USD execution ledger come at later gates. No live AIDY or GoldThinker changes.

## Acceptance
1. Production-intended, importable Python schema module exists in isolated AIDY feature branch.
2. Full JSON example fixture round-trips without data loss and with deterministic canonical textual representation.
3. Focused positive/negative tests pass in GitHub CI with Ruff/source compilation.
4. Document commit and CI URL after results are actually observed.

## Verified acceptance record — 14 October 2026

- [Successful full Day 08 workflow](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38526223342), job `115727085660`: compiled, Ruff passed, **60 automated tests passed** (one warning), illustrative JSON fixture imported and deterministically round-tripped.
- Input fixture SHA-256, directly computed by GitHub CI: `3bad6f58a1849e6035407e21cdd8e2eedcd52ba8d29c1861a14274de43beb045`.
- Source version used in passing CI: commit `b9752beb2a410c69d2bb31f6baef616fd3da064b`; schema implementation `src/aidy/strategy_lab_spec.py`.
- Source fixture is **synthetic and illustrative**: no actual publisher-authored strategy was verified, no strategy signals were executed, no historical trades were made and no returns were calculated. This satisfies Day 08's strict contract/examples gate, **not** B02's full rule-completeness/parity/version-hash acceptance.

## Next
Day 09 rule completeness validator + independent no-lookahead declarations; Day 10 canonical content hash / version registry, after Day 09 acceptance.
