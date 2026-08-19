# Day 8 official macro evidence live-acceptance evidence

- Trigger commit: d17a9a4443cedfa7e131e2abac73f363f81e7905
- Observed at UTC: 2026-08-19T15:04:31Z
- Dependencies: PASS
- Code gate: FAIL
- Code gate status: ruff=1 compile=0 pytest=0
- Official/PIT structural boundary: NOT_REACHED_OR_FAILED
- Live Fed/BLS/BEA probe: NOT_REACHED_OR_FAILED
- Append-only revision + event-window proof: NOT_REACHED_OR_FAILED

## ruff
```text
641 | /             async with httpx.AsyncClient(
642 | |                 timeout=self._timeout,
643 | |                 follow_redirects=False,
644 | |                 transport=self._transport,
645 | |             ) as client:
646 | |                 async with client.stream("GET", url, headers=headers) as response:
    | |__________________________________________________________________________________^
647 |                       if response.status_code == 304:
648 |                           return FetchedSource(source_key, url, None)
    |
help: Combine `with` statements
    |
644 |                 transport=self._transport,
    -             ) as client:
    -                 async with client.stream("GET", url, headers=headers) as response:
    -                     if response.status_code == 304:
    -                         return FetchedSource(source_key, url, None)
    -                     if response.status_code != 200:
    -                         raise OfficialMacroError(f"official_macro_http_{response.status_code}")
    -                     declared = response.headers.get("content-length", "").strip()
    -                     if declared.isdigit() and int(declared) > _MAX_SOURCE_BYTES:
645 +             ) as client, client.stream("GET", url, headers=headers) as response:
646 +                 if response.status_code == 304:
647 +                     return FetchedSource(source_key, url, None)
648 +                 if response.status_code != 200:
649 +                     raise OfficialMacroError(f"official_macro_http_{response.status_code}")
650 +                 declared = response.headers.get("content-length", "").strip()
651 +                 if declared.isdigit() and int(declared) > _MAX_SOURCE_BYTES:
652 +                     raise OfficialMacroError("official_macro_source_too_large")
653 +                 body = bytearray()
654 +                 async for chunk in response.aiter_bytes():
655 +                     body.extend(chunk)
656 +                     if len(body) > _MAX_SOURCE_BYTES:
657 |                         raise OfficialMacroError("official_macro_source_too_large")
    -                     body = bytearray()
    -                     async for chunk in response.aiter_bytes():
    -                         body.extend(chunk)
    -                         if len(body) > _MAX_SOURCE_BYTES:
    -                             raise OfficialMacroError("official_macro_source_too_large")
    -                     encoding = response.encoding or "utf-8"
    -                     validators = (
    -                         response.headers.get("etag"),
    -                         response.headers.get("last-modified"),
    -                     )
658 +                 encoding = response.encoding or "utf-8"
659 +                 validators = (
660 +                     response.headers.get("etag"),
661 +                     response.headers.get("last-modified"),
662 +                 )
663 |         except httpx.TimeoutException as exc:
    |

BLE001 Do not catch blind exception: `Exception`
   --> src/aidy/storage_contracts.py:139:20
    |
137 |             try:
138 |                 await self._archive.put_immutable(item)
139 |             except Exception as exc:  # archive provider errors are deliberately isolated
    |                    ^^^^^^^^^
140 |                 failed += 1
141 |                 await self._operational.mark_archive_failure(
    |

I001 [*] Import block is un-sorted or un-formatted
 --> tests/test_migration_offline.py:1:1
  |
1 | / from __future__ import annotations
2 | |
3 | | import importlib.util
4 | | import io
5 | | from pathlib import Path
6 | |
7 | | from alembic.migration import MigrationContext
8 | | from alembic.operations import Operations
  | |_________________________________________^
help: Organize imports
   |
9  |
   -
10 | _MIGRATION = Path("migrations/versions/0001_aidy_market_evidence.py")
   |

I001 [*] Import block is un-sorted or un-formatted
 --> tests/test_no_postgres_runtime.py:1:1
  |
1 | / from __future__ import annotations
2 | |
3 | | from pathlib import Path
  | |________________________^
help: Organize imports
  |
4 |
  -
5 | PRODUCTION_FILES = (
  |

I001 [*] Import block is un-sorted or un-formatted
  --> tests/test_official_macro.py:1:1
   |
 1 | / from __future__ import annotations
 2 | |
 3 | | import json
 4 | | from datetime import UTC, datetime, timedelta
 5 | | from uuid import uuid4
 6 | |
 7 | | import httpx
 8 | | import pytest
 9 | |
10 | | from aidy.fomc_calendar_parser import parse_fomc_calendar
11 | | from aidy.macro_event_windows import reconstruct_macro_event_window
12 | | from aidy.official_macro import (
13 | |     BLS_CALENDAR_URL,
14 | |     FetchedSource,
15 | |     OfficialMacroError,
16 | |     OfficialMacroGateway,
17 | |     parse_bea_current_releases_html,
18 | |     parse_bea_schedule_html,
19 | |     parse_bls_calendar_ics,
20 | |     parse_bls_release_rss,
21 | | )
22 | | from aidy.official_macro_recorder import AidyOfficialMacroRecorderService
   | |_________________________________________________________________________^
help: Organize imports
   |
23 |
   -
24 | BLS_ICS = """BEGIN:VCALENDAR
   |

F401 [*] `aidy.official_macro.BLS_CALENDAR_URL` imported but unused
  --> tests/test_official_macro.py:13:5
   |
11 | from aidy.macro_event_windows import reconstruct_macro_event_window
12 | from aidy.official_macro import (
13 |     BLS_CALENDAR_URL,
   |     ^^^^^^^^^^^^^^^^
14 |     FetchedSource,
15 |     OfficialMacroError,
   |
help: Remove unused import: `aidy.official_macro.BLS_CALENDAR_URL`
   |
12 | from aidy.official_macro import (
   -     BLS_CALENDAR_URL,
13 |     FetchedSource,
   |

PIE810 Call `endswith` once with a `tuple`
  --> tests/test_postgres_integration.py:29:13
   |
27 |     parsed = make_url(raw)
28 |     database = (parsed.database or "").lower()
29 |     if not (database.endswith("_scratch") or database.endswith("_test")):
   |             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
30 |         pytest.fail(
31 |             "Refusing destructive migration test: AIDY_TEST_DATABASE_URL database name "
   |
help: Merge into a single `endswith` call

Found 18 errors.
[*] 6 fixable with the `--fix` option (1 hidden fix can be enabled with the `--unsafe-fixes` option).
```

## pytest
```text
........................................................................ [ 60%]
................................................                         [100%]
120 passed in 0.90s
```
