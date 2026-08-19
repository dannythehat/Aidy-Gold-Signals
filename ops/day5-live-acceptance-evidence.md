# Day 5 historical XAUUSD backfill live-acceptance evidence

- Trigger commit: 6353a71ea1b6ef57ced0d335e9d63ee93fb6a334
- Observed at UTC: 2026-08-19T12:25:08Z
- Dependencies: PASS
- Code gate: PASS
- Code gate status: ruff=0 compile=0 pytest=0
- Structural retrospective/live boundary: PASS
- Credential preflight: PASS
- BigQuery dependency: PASS
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
........................................................................ [ 93%]
.....                                                                    [100%]
77 passed in 0.71s
```

## day5-first
```json

```

## day5-first-stderr
```text
DAY5_BACKFILL_ERROR=RuntimeError:Missing BigQuery research timeframe after load: M1
Traceback (most recent call last):
  File "/home/runner/work/Aidy-Gold-Signals/Aidy-Gold-Signals/scripts/day5_backfill_histdata.py", line 767, in <module>
    raise SystemExit(main())
                     ~~~~^^
  File "/home/runner/work/Aidy-Gold-Signals/Aidy-Gold-Signals/scripts/day5_backfill_histdata.py", line 748, in main
    result = run_backfill(
        client=client,
    ...<7 lines>...
        force_process=args.force_process,
    )
  File "/home/runner/work/Aidy-Gold-Signals/Aidy-Gold-Signals/scripts/day5_backfill_histdata.py", line 634, in run_backfill
    process_period(
    ~~~~~~~~~~~~~~^
        client,
        ^^^^^^^
    ...<6 lines>...
        force_process=force_process,
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/home/runner/work/Aidy-Gold-Signals/Aidy-Gold-Signals/scripts/day5_backfill_histdata.py", line 537, in process_period
    reconciliation = _reconcile_candles(
        client,
    ...<5 lines>...
        expected=expected,
    )
  File "/home/runner/work/Aidy-Gold-Signals/Aidy-Gold-Signals/scripts/day5_backfill_histdata.py", line 388, in _reconcile_candles
    raise RuntimeError(f"Missing BigQuery research timeframe after load: {timeframe}")
RuntimeError: Missing BigQuery research timeframe after load: M1
```
