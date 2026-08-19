# Day 5 historical XAUUSD backfill live-acceptance evidence

- Trigger commit: add6ab85d80116b3fb79145044a4f4a82646458d
- Observed at UTC: 2026-08-19T13:21:34Z
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
77 passed in 0.63s
```

## day5-first
```json

```

## day5-first-stderr
```text
DAY5_BACKFILL_ERROR=RuntimeError:Missing BigQuery research timeframe after load: M1
Traceback (most recent call last):
  File "/home/runner/work/Aidy-Gold-Signals/Aidy-Gold-Signals/scripts/day5_backfill_histdata.py", line 823, in <module>
    raise SystemExit(main())
                     ~~~~^^
  File "/home/runner/work/Aidy-Gold-Signals/Aidy-Gold-Signals/scripts/day5_backfill_histdata.py", line 804, in main
    result = run_backfill(
        client=client,
    ...<7 lines>...
        force_process=args.force_process,
    )
  File "/home/runner/work/Aidy-Gold-Signals/Aidy-Gold-Signals/scripts/day5_backfill_histdata.py", line 690, in run_backfill
    process_period(
    ~~~~~~~~~~~~~~^
        client,
        ^^^^^^^
    ...<6 lines>...
        force_process=force_process,
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/home/runner/work/Aidy-Gold-Signals/Aidy-Gold-Signals/scripts/day5_backfill_histdata.py", line 593, in process_period
    reconciliation = _reconcile_candles(
        client,
    ...<5 lines>...
        expected=expected,
    )
  File "/home/runner/work/Aidy-Gold-Signals/Aidy-Gold-Signals/scripts/day5_backfill_histdata.py", line 444, in _reconcile_candles
    raise RuntimeError(f"Missing BigQuery research timeframe after load: {timeframe}")
RuntimeError: Missing BigQuery research timeframe after load: M1
```
