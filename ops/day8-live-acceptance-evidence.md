# Day 8 official macro evidence live-acceptance evidence

- Trigger commit: 45c54922c456e5fe1e61d95b0d2a36f485e7ad6d
- Observed at UTC: 2026-08-19T15:24:11Z
- Dependencies: PASS
- Code gate: PASS
- Code gate status: ruff=0 compile=0 pytest=0
- Official/PIT structural boundary: PASS
- Live Fed/BLS/BEA probe: PASS
- Append-only revision + event-window proof: PASS

## ruff
```text
All checks passed!
All checks passed!
```

## pytest
```text
........................................................................ [ 58%]
...................................................                      [100%]
123 passed in 0.69s
```

## focused
```text
...                                                                      [100%]
3 passed in 0.10s
```

## live-official-source-probe
```json
{"accepted_classes": ["cpi", "employment_cost_index", "employment_situation", "fomc_decision", "fomc_press_conference", "gdp", "international_trade", "jolts", "personal_income_outlays_pce", "ppi"], "observed_at": "2026-08-19T15:24:08.718871+00:00", "sources": {"bea_releases": {"classes": ["gdp", "international_trade", "personal_income_outlays_pce"], "observations": 5}, "bea_schedule": {"classes": ["gdp", "international_trade", "personal_income_outlays_pce"], "observations": 43}, "bls_calendar": {"classes": ["cpi", "employment_cost_index", "employment_situation", "jolts", "ppi"], "observations": 124}, "bls_cpi": {"classes": ["cpi"], "observations": 12}, "bls_eci": {"classes": ["employment_cost_index"], "observations": 12}, "bls_employment_situation": {"classes": ["employment_situation"], "observations": 12}, "bls_jolts": {"classes": ["jolts"], "observations": 12}, "bls_ppi": {"classes": ["ppi"], "observations": 12}, "fed_press_monetary": {"observations": 15}, "federal_reserve_calendars": {"classes": ["fomc_decision", "fomc_press_conference"], "monthly_counts": {"fed_calendar_2026_08": 0, "fed_calendar_2026_09": 2, "fed_calendar_2026_10": 2, "fed_calendar_2026_11": 0}, "observations": 4}}, "status": "PASS"}

```
