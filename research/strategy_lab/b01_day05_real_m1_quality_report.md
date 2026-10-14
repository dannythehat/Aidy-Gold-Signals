# Day 05 — Full historical XAUUSD M1 archive audit

Status: PASSED for whole-archive structural checks, not yet session completeness. Date: 2026-10-14.

Evidence: https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/38520233350
BigQuery read-only job: `f26e9bf2-5203-4a7b-abfb-416fbd07572a` (dry-run 243294211 bytes).

| Test | 2024 | 2025 |
|---|---:|---:|
| Stored candles | 355592 | 353951 |
| Distinct timestamps | 355592 | 353951 |
| Invalid numeric OHLC | 0 | 0 |
| Nonpositive OHLC | 0 | 0 |
| Invalid OHLC relationships | 0 | 0 |
| Off-minute timestamps | 0 | 0 |
| Gap intervals | 307 | 291 |
| Raw missing minutes | 169946 | 170147 |
| Largest missing span (minutes) | 4441 | 4381 |
| Archive hashes | 1 | 1 |
| Payload hashes | 1 | 1 |
| Source clock types | 1 | 1 |
| Price bases | 1 | 1 |

**Caveats:** Gap intervals include legitimate market closures and holidays; the count is not an outage count. These checks do not establish session-by-session completeness, external vendor licensing, price outlier validity, bid/ask historical fill fidelity or broker-clock equivalence. No price records were changed. Day 06 and Day 07 must address bid/ask coverage and session clocks.
