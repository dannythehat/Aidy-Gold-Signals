# Day 5 historical XAUUSD backfill live-acceptance evidence

- Trigger commit: 4cbb7598592dcde6b3cbd1f0f8dd3629d3cf3455
- Observed at UTC: 2026-08-19T11:49:52Z
- Dependencies: PASS
- Code gate: FAIL
- Code gate status: ruff=1 compile=0 pytest=0
- Structural retrospective/live boundary: NOT_REACHED_OR_FAILED
- Credential preflight: NOT_REACHED_OR_FAILED
- BigQuery dependency: NOT_REACHED_OR_FAILED
- Two-year 2024-2025 backfill: NOT_REACHED_OR_FAILED
- Forced 2025 idempotency: NOT_REACHED_OR_FAILED
- Checkpoint resume: NOT_REACHED_OR_FAILED
- BigQuery provenance/live contamination proof: NOT_REACHED_OR_FAILED

## ruff
```text
207 |       @property
208 |       def candle_key(self) -> str:
209 |           raw = "\0".join(
    |  _______________^
210 | |             (
211 | |                 HISTDATA_SOURCE,
212 | |                 self.symbol,
213 | |                 self.timeframe,
214 | |                 self.open_time_utc.isoformat(),
215 | |             )
216 | |         )
    | |_________^
217 |           return sha256(raw.encode()).hexdigest()
    |
help: Replace with f-string

FLY002 Consider f-string instead of string join
   --> src/aidy/historical_backfill.py:271:11
    |
270 | def chunk_key(*, symbol: str, period: HistDataPeriod) -> str:
271 |     raw = "\0".join((HISTDATA_SOURCE, HISTDATA_DATASET, symbol, period.key))
    |           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
272 |     return sha256(raw.encode()).hexdigest()
    |
help: Replace with f-string

DTZ007 Naive datetime constructed using `datetime.datetime.strptime()` without %z
   --> src/aidy/historical_backfill.py:388:18
    |
386 | def _parse_source_time(raw: str, *, line_number: int) -> datetime:
387 |     try:
388 |         parsed = datetime.strptime(raw, "%Y%m%d %H%M%S")
    |                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
389 |     except ValueError as exc:
390 |         raise ValueError(f"Invalid HistData timestamp at line {line_number}: {raw!r}") from exc
    |
help: Call `.replace(tzinfo=<timezone>)` or `.astimezone()` to convert to an aware datetime

I001 [*] Import block is un-sorted or un-formatted
  --> tests/test_historical_backfill.py:1:1
   |
 1 | / from datetime import UTC, datetime
 2 | | from hashlib import sha256
 3 | | from pathlib import Path
 4 | | import zipfile
 5 | |
 6 | | import pytest
 7 | |
 8 | | from aidy.historical_backfill import (
 9 | |     DERIVATION_VERSION,
10 | |     HISTDATA_SOURCE_TIMEZONE,
11 | |     RESEARCH_BACKFILL_MANIFEST,
12 | |     RESEARCH_CANDLES,
13 | |     RETROSPECTIVE_PROVENANCE,
14 | |     HistDataArchive,
15 | |     HistDataPeriod,
16 | |     _token_from_html,
17 | |     backfill_identity,
18 | |     build_research_candles,
19 | |     chunk_key,
20 | |     manifest_merge_sql,
21 | |     manifest_row,
22 | |     merge_sql,
23 | |     parse_histdata_m1,
24 | |     planned_periods,
25 | |     read_histdata_archive,
26 | |     request_signature,
27 | |     stage_fields,
28 | | )
   | |_^
help: Organize imports
  |
1 + import zipfile
2 | from datetime import UTC, datetime
3 | from hashlib import sha256
4 | from pathlib import Path
  - import zipfile
5 |
  |

FLY002 Consider f-string instead of string join
  --> tests/test_historical_backfill.py:45:12
   |
44 |   def sample_text() -> str:
45 |       return "\n".join(
   |  ____________^
46 | |         [
47 | |             "20240102 000000;2000.00;2001.00;1999.00;2000.50;0",
48 | |             "20240102 000100;2000.50;2002.00;2000.00;2001.50;0",
49 | |             "20240102 000200;2001.50;2003.00;2001.00;2002.50;0",
50 | |             "20240102 000300;2002.50;2004.00;2002.00;2003.50;0",
51 | |             "20240102 000400;2003.50;2005.00;2003.00;2004.50;0",
52 | |             "20240102 000500;2004.50;2006.00;2004.00;2005.50;0",
53 | |         ]
54 | |     )
   | |_____^
help: Replace with f-string

Found 9 errors.
[*] 3 fixable with the `--fix` option (3 hidden fixes can be enabled with the `--unsafe-fixes` option).
```

## compile
```text
```

## pytest
```text
........................................................................ [ 94%]
....                                                                     [100%]
76 passed in 0.62s
```
