# Day 8 official macro evidence live-acceptance evidence

- Trigger commit: 55c7329738140bfc55a2a72b2bbe588d7fe28679
- Observed at UTC: 2026-08-19T15:07:54Z
- Dependencies: PASS
- Code gate: FAIL
- Code gate status: ruff=1 compile=0 pytest=0
- Official/PIT structural boundary: NOT_REACHED_OR_FAILED
- Live Fed/BLS/BEA probe: NOT_REACHED_OR_FAILED
- Append-only revision + event-window proof: NOT_REACHED_OR_FAILED

## ruff
```text
DTZ001 `datetime.datetime()` called without a `tzinfo` argument
  --> src/aidy/fomc_calendar_parser.py:39:42
   |
37 |             continue
38 |         day = int(match.group(1))
39 |         scheduled = _eastern_wall_to_utc(datetime(year, month, day, hour, minute))
   |                                          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
40 |         logical = f"{year:04d}-{month:02d}"
41 |         event_key = sha256(f"Federal Reserve\0{event_class}\0{logical}".encode()).hexdigest()
   |
help: Pass a `datetime.timezone` object to the `tzinfo` parameter

I001 [*] Import block is un-sorted or un-formatted
  --> tests/test_official_macro.py:1:1
   |
 1 | / from __future__ import annotations
 2 | |
 3 | | from datetime import UTC, datetime, timedelta
 4 | | import json
 5 | | from uuid import uuid4
 6 | |
 7 | | import pytest
 8 | |
 9 | | from aidy.fomc_calendar_parser import parse_fomc_calendar
10 | | from aidy.macro_event_windows import reconstruct_macro_event_window
11 | | from aidy.official_macro import (
12 | |     FetchedSource,
13 | |     OfficialMacroError,
14 | |     OfficialMacroGateway,
15 | |     parse_bea_current_releases_html,
16 | |     parse_bea_schedule_html,
17 | |     parse_bls_calendar_ics,
18 | |     parse_bls_release_rss,
19 | | )
20 | | from aidy.official_macro_recorder import AidyOfficialMacroRecorderService
   | |_________________________________________________________________________^
help: Organize imports
   |
2  |
3  + import json
4  | from datetime import UTC, datetime, timedelta
   - import json
5  | from uuid import uuid4
--------------------------------------------------------------------------------
20 | from aidy.official_macro_recorder import AidyOfficialMacroRecorderService
   -
21 |
   |

Found 2 errors.
[*] 1 fixable with the `--fix` option.
DTZ007 Naive datetime constructed using `datetime.datetime.strptime()` without %z
   --> src/aidy/official_macro.py:210:17
    |
208 |         return None
209 |     try:
210 |         local = datetime.strptime(value.rstrip("Z"), "%Y%m%dT%H%M%S")
    |                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
211 |     except ValueError:
212 |         try:
    |
help: Call `.replace(tzinfo=<timezone>)` or `.astimezone()` to convert to an aware datetime

DTZ007 Naive datetime constructed using `datetime.datetime.strptime()` without %z
   --> src/aidy/official_macro.py:213:21
    |
211 |     except ValueError:
212 |         try:
213 |             local = datetime.strptime(value.rstrip("Z"), "%Y%m%dT%H%M")
    |                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
214 |         except ValueError:
215 |             return None
    |
help: Call `.replace(tzinfo=<timezone>)` or `.astimezone()` to convert to an aware datetime

DTZ001 `datetime.datetime()` called without a `tzinfo` argument
   --> src/aidy/official_macro.py:460:45
    |
458 |         if match.group(4).upper() == "AM" and hour == 12:
459 |             hour = 0
460 |         scheduled_at = _eastern_wall_to_utc(datetime(year, month, day, hour, minute))
    |                                             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
461 |         links = [link for cell in row for link in cell["links"]]
462 |         release_url = next((urljoin(BEA_SCHEDULE_URL, link) for link in links if link), None)
    |
help: Pass a `datetime.timezone` object to the `tzinfo` parameter

DTZ001 `datetime.datetime()` called without a `tzinfo` argument
   --> src/aidy/official_macro.py:568:45
    |
566 |         hour = 14
567 |         minute = 0 if event_class == "fomc_decision" else 30
568 |         scheduled_at = _eastern_wall_to_utc(datetime(year, month, day, hour, minute))
    |                                             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
569 |         title = "FOMC Meeting" if event_class == "fomc_decision" else "FOMC Press Conference"
570 |         event_key = _event_key(agency="Federal Reserve", event_class=event_class, title=f"{title} {year}-{month:02d}-{day:02d}")
    |
help: Pass a `datetime.timezone` object to the `tzinfo` parameter

Found 4 errors.
```

## pytest
```text
........................................................................ [ 60%]
................................................                         [100%]
120 passed in 0.83s
```
