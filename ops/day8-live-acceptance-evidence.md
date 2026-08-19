# Day 8 official macro evidence live-acceptance evidence

- Trigger commit: e8a450bceed555eac00ac12f79d56a88e55c1978
- Observed at UTC: 2026-08-19T15:22:15Z
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
........................................................................ [ 59%]
..................................................                       [100%]
122 passed in 0.75s
```

## live-probe.stderr
```text
DAY8_OFFICIAL_MACRO_PROBE_ERROR=OfficialMacroError:bls_calendar_no_supported_events:[{"dtstart":[["DTSTART;TZID=US-Eastern","20250103T100000"]],"summary":[["SUMMARY","Metropolitan Area Employment and Unemployment (Monthly)"]]},{"dtstart":[["DTSTART;TZID=US-Eastern","20250107T100000"]],"summary":[["SUMMARY","Job Openings and Labor Turnover Survey"]]},{"dtstart":[["DTSTART;TZID=US-Eastern","20250110T083000"]],"summary":[["SUMMARY","Employment Situation"]]},{"dtstart":[["DTSTART;TZID=US-Eastern","20250114T083000"]],"summary":[["SUMMARY","Producer Price Index"]]},{"dtstart":[["DTSTART;TZID=US-Eastern","20250115T083000"]],"summary":[["SUMMARY","Real Earnings"]]}]
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
  File "/home/runner/work/Aidy-Gold-Signals/Aidy-Gold-Signals/scripts/day8_probe_official_macro.py", line 47, in probe
    bls_calendar = parse_bls_official_calendar(fetched.text)
  File "/home/runner/work/Aidy-Gold-Signals/Aidy-Gold-Signals/src/aidy/bls_calendar_parser.py", line 160, in parse_bls_official_calendar
    raise OfficialMacroError(
    ...<2 lines>...
    )
aidy.official_macro.OfficialMacroError: bls_calendar_no_supported_events:[{"dtstart":[["DTSTART;TZID=US-Eastern","20250103T100000"]],"summary":[["SUMMARY","Metropolitan Area Employment and Unemployment (Monthly)"]]},{"dtstart":[["DTSTART;TZID=US-Eastern","20250107T100000"]],"summary":[["SUMMARY","Job Openings and Labor Turnover Survey"]]},{"dtstart":[["DTSTART;TZID=US-Eastern","20250110T083000"]],"summary":[["SUMMARY","Employment Situation"]]},{"dtstart":[["DTSTART;TZID=US-Eastern","20250114T083000"]],"summary":[["SUMMARY","Producer Price Index"]]},{"dtstart":[["DTSTART;TZID=US-Eastern","20250115T083000"]],"summary":[["SUMMARY","Real Earnings"]]}]
```
