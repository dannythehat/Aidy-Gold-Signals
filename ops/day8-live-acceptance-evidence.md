# Day 8 official macro evidence live-acceptance evidence

- Trigger commit: ce99ede00948ddc33498d2fd55d4ee363b49a822
- Observed at UTC: 2026-08-19T15:14:36Z
- Dependencies: PASS
- Code gate: PASS
- Code gate status: ruff=0 compile=0 pytest=0
- Official/PIT structural boundary: PASS
- Live Fed/BLS/BEA probe: FAIL
- Append-only revision + event-window proof: NOT_REACHED_OR_FAILED

## ruff
```text
All checks passed!
All checks passed!
```

## pytest
```text
........................................................................ [ 60%]
................................................                         [100%]
120 passed in 0.90s
```

## live-probe.stderr
```text
DAY8_OFFICIAL_MACRO_PROBE_ERROR=RuntimeError:BLS calendar missing required classes: ['cpi', 'employment_cost_index', 'employment_situation', 'jolts', 'ppi']
Traceback (most recent call last):
  File "/home/runner/work/Aidy-Gold-Signals/Aidy-Gold-Signals/scripts/day8_probe_official_macro.py", line 159, in <module>
    raise SystemExit(main())
                     ~~~~^^
  File "/home/runner/work/Aidy-Gold-Signals/Aidy-Gold-Signals/scripts/day8_probe_official_macro.py", line 151, in main
    print(json.dumps(asyncio.run(probe()), sort_keys=True))
                     ~~~~~~~~~~~^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.13.15/x64/lib/python3.13/asyncio/runners.py", line 196, in run
    return runner.run(main)
           ~~~~~~~~~~^^^^^^
  File "/opt/hostedtoolcache/Python/3.13.15/x64/lib/python3.13/asyncio/runners.py", line 119, in run
    return self._loop.run_until_complete(task)
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "/opt/hostedtoolcache/Python/3.13.15/x64/lib/python3.13/asyncio/base_events.py", line 726, in run_until_complete
    return future.result()
           ~~~~~~~~~~~~~^^
  File "/home/runner/work/Aidy-Gold-Signals/Aidy-Gold-Signals/scripts/day8_probe_official_macro.py", line 57, in probe
    raise RuntimeError(
        f"BLS calendar missing required classes: {sorted(required_bls - bls_schedule_classes)}"
    )
RuntimeError: BLS calendar missing required classes: ['cpi', 'employment_cost_index', 'employment_situation', 'jolts', 'ppi']
```
