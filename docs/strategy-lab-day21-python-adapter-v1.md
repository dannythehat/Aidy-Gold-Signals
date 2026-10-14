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

**Verified day-level technical acceptance (14 October 2026): PASS.**

- [GitHub Actions Day21 acceptance, run 38562202791](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38562202791), job `115845796004`: **177 Day08/09/20/21 tests PASSED**, strict Ruff and compilation PASS (one non-fatal existing pytest `asyncio_mode` configuration warning).
- [PR #266 merged into main](https://github.com/dannythehat/Aidy-Gold-Signals/pull/266); source/test HEAD `4c161e77ccfefb6e458d040a27a569fe6c7d2c2e`, verified main squash commit `e8e60a599c8316e5abb023dd2aea32954c9e366e`.
- Frozen internal Python source SHA256 `06db12a5c067fedf4d61a30596886e1844913f4870d1e4d3e16a0189f439b3fa`; source-bound canonical typed spec SHA256 `75b5eb7883b97c6c5dd1bcf438a62bb36f37f6bf6bcca5bbf7ddc98db10c5553`; source predicate AST SHA256 `c5afb4334aad2beff8f74255c946c3f3f4a1e0b68c2a847aacac863cdbe0bc4e`.
- Independent closed M5 synthetic signal timestamps matched: `2026-10-14T12:10:00Z` and `2026-10-14T12:30:00Z`. `untrusted_source_executed=false` and `independent_third_party_platform_parity=false` verified in CI.
- Day21 accepted only for the **strict no-exec AST-only predicate subset**, not a general-purpose Python sandbox, not unrestricted script execution and not original platform EMA/broker parity.
