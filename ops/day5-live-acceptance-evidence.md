# Day 5 historical XAUUSD backfill live-acceptance evidence

- Trigger commit: 32a1fdef4bf3beb7b36141adc14ccf3d64866d39
- Observed at UTC: 2026-08-19T12:04:46Z
- Dependencies: PASS
- Code gate: FAIL
- Code gate status: ruff=0 compile=0 pytest=1
- Structural retrospective/live boundary: NOT_REACHED_OR_FAILED
- Credential preflight: NOT_REACHED_OR_FAILED
- BigQuery dependency: NOT_REACHED_OR_FAILED
- Two-year 2024-2025 backfill: NOT_REACHED_OR_FAILED
- Forced 2025 idempotency: NOT_REACHED_OR_FAILED
- Checkpoint resume: NOT_REACHED_OR_FAILED
- BigQuery provenance/live contamination proof: NOT_REACHED_OR_FAILED

## ruff
```text
All checks passed!
```

## compile
```text
```

## pytest
```text
.............................................F.......................... [ 94%]
....                                                                     [100%]
=================================== FAILURES ===================================
______________ test_out_of_order_and_ohlc_invariants_fail_closed _______________

    def test_out_of_order_and_ohlc_invariants_fail_closed():
>       with pytest.raises(ValueError, match="out of order"):
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       Failed: DID NOT RAISE ValueError

tests/test_historical_backfill.py:81: Failed
=========================== short test summary info ============================
FAILED tests/test_historical_backfill.py::test_out_of_order_and_ohlc_invariants_fail_closed - Failed: DID NOT RAISE ValueError
1 failed, 75 passed in 0.65s
```
