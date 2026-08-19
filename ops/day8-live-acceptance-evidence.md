# Day 8 official macro evidence live-acceptance evidence

- Trigger commit: 6ed3a2d71b3dda71cb05ad2bc3c8be9f711f0669
- Observed at UTC: 2026-08-19T15:10:45Z
- Dependencies: PASS
- Code gate: FAIL
- Code gate status: ruff=1 compile=0 pytest=0
- Official/PIT structural boundary: NOT_REACHED_OR_FAILED
- Live Fed/BLS/BEA probe: NOT_REACHED_OR_FAILED
- Append-only revision + event-window proof: NOT_REACHED_OR_FAILED

## ruff
```text
I001 [*] Import block is un-sorted or un-formatted
  --> tests/test_official_macro.py:1:1
   |
 1 | / from __future__ import annotations
 2 | |
 3 | | import json
 4 | | from datetime import UTC, datetime, timedelta
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
21 |
   -
22 | BLS_ICS = """BEGIN:VCALENDAR
   |

Found 1 error.
[*] 1 fixable with the `--fix` option.
All checks passed!
```

## pytest
```text
........................................................................ [ 60%]
................................................                         [100%]
120 passed in 0.74s
```
