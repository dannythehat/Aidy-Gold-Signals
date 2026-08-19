# Day 6 PIT as-of reconstruction live-acceptance evidence

- Trigger commit: fe0ac08b101e4bb048056c865a90df47d7f8ce29
- Observed at UTC: 2026-08-19T14:01:55Z
- Dependencies: PASS
- Code gate: FAIL
- Code gate status: ruff=1 compile=0 pytest=0
- Structural PIT boundary: NOT_REACHED_OR_FAILED
- Credential preflight: NOT_REACHED_OR_FAILED
- BigQuery dependency: NOT_REACHED_OR_FAILED
- Warehouse anchor/control rows: NOT_REACHED_OR_FAILED
- Before first snapshot -> explicit unknown: NOT_REACHED_OR_FAILED
- At first snapshot -> known with provenance: NOT_REACHED_OR_FAILED
- Retrospective history excluded: NOT_REACHED_OR_FAILED

## ruff
```text
DTZ001 `datetime.datetime()` called without a `tzinfo` argument
   --> tests/test_pit_reconstruction.py:247:46
    |
245 | def test_as_of_requires_timezone_awareness() -> None:
246 |     with pytest.raises(ValueError, match="timezone-aware"):
247 |         select_latest_events_as_of([], as_of=datetime(2026, 8, 19, 10, 0))
    |                                              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
help: Pass a `datetime.timezone` object to the `tzinfo` parameter

Found 1 error.
```

## compile
```text
```

## pytest
```text
........................................................................ [ 76%]
......................                                                   [100%]
94 passed in 0.61s
```
