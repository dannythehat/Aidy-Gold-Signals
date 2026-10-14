# B06 Day 21 — Restricted Python Strategy Adapter (v1)

**Scope: closed-indicator signal-only Python subset, using exact source-bytes and
StrategySpec identity. Not general-purpose Python execution.**

## New production research interfaces

- `src/aidy/strategy_lab_python_predicate_adapter.py`
- `admit_python_predicate(original_source_bytes, spec_json, expected_source_sha256, source_snapshot_ref)`
  binds original source SHA-256 to a supplied strict typed StrategySpec with
  `origin.source_language=python`. Every spec field remains caller-supplied;
  no stop/target, commission, indicator history, session or risk rule is inferred.
- `evaluate_restricted_python(adapter, closed_M5_samples)` rechecks original
  source bytes and spec on every evaluation, checks all timestamps are consecutive
  UTC five-minute **closed-bar** samples with finite positive Decimal values,
  then returns only signal timestamps. No broker orders are sent.
- `compare_python_with_spec(adapter, samples)` independently compares the
  restricted Python signal against Day20's source-bound StrategySpec predicate
  evaluator, refusing any mismatch. Outputs source/spec hashes and explicit
  `unrestricted_python_executed=false`,
  `external_python_strategy_qualified=false`, and
  `original_broker_platform_parity=false`.

## Executable-language restriction

The accepted **AST grammar** consists of exactly:

```python
def signal(fast_prev, slow_prev, fast_now, slow_now):
    return fast_prev <= slow_prev and fast_now > slow_now
```

The order of the two conjunction operands may vary, but no other statements,
parameters, function calls, module imports, decorators, assignments, attributes,
subscripts, loops, comprehensions, extra predicates, disjunctions or expressions
are permitted. `ast.parse()` constructs data only; a **hand-written Decimal
comparison interpreter** evaluates it. No `compile()`, `eval()` or `exec()`
ever receives the untrusted source. Rejected source does not run. This is
substantially narrower and safer than treating a subprocess as a security
sandbox: it is **not** a general unrestricted Python interpreter.

This subset deliberately does **not** yet support arbitrary external published
Python strategies. Such code must remain BLOCKED, rather than silently given
filesystem, network or execution privileges. Expanding the language requires
separate security review and sandbox enforcement.

## Research integrity and tested reference

- Internal synthetic text fixture: `research/strategy_lab/fixtures/day21_internal_python_signal.py.txt`.
  It is not a claimed third-party strategy or live account source.
- The Day20 independently implemented closed EMA crossing predicate is
  used as a parity oracle on the same frozen 58-record artificial indicator
  trace; expected matches occur at bars 50 and 54 only.
- Source, spec and AST fingerprints remain stable for deterministic repeated
  runs. Any source corruption, changed original source SHA, forged adapter
  dataclass or mismatched operator is rejected.
- Changes in unknown future samples do not affect earlier signals. Missing
  warmup, out-of-order candles, naive clock fields, nonfinite values and
  non-tuple trace payloads are rejected, not silently fixed.
- All other Day20 source-confirmation metadata is separate from this signal
  function. `source_platform_parity_verified=false` because original EMA
  seeding, provider indicator calculations and authentic broker fills have
  not been compared.

## Gate

Day-level technical PASS requires verified GitHub CI including module compile,
strict Ruff, Day21 hostile-source rejection tests, Day20 regression and
independent synthetic signal parity, then **actual merge to `main`** and update
of the real Notion Day21 row. This does not confer B06 stage or owner sign-off.

**Evidence to insert only after CI and merge:** immutable run URL, job ID, count,
source hash, merge SHA, and any limitations.
