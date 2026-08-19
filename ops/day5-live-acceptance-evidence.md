# Day 5 historical XAUUSD backfill live-acceptance evidence

- Trigger commit: e95a1aa4dcf0ca37d31d0e1d4669ed036b03d170
- Observed at UTC: 2026-08-19T11:54:23Z
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
 7 | from datetime import UTC, datetime
 8 | from pathlib import Path
 9 | from typing import Any, Iterable
   | ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
10 | from uuid import uuid4
   |
help: Import from `collections.abc`
   |
8  | from pathlib import Path
   - from typing import Any, Iterable
9  + from typing import Any
10 + from collections.abc import Iterable
11 | from uuid import uuid4
   |

PLC0206 Extracting value from dictionary without calling `.items()`
   --> scripts/day5_backfill_histdata.py:418:9
    |
417 | def _iter_candle_rows(candles: dict[str, list[Any]]) -> Iterable[dict[str, object]]:
418 |     for timeframe in candles:
    |         ^^^^^^^^^^^^^^^^^^^^
419 |         for candle in candles[timeframe]:
    |                       ------------------
420 |             yield candle.to_row()
    |
help: Use `for timeframe, value in candles.items()` instead

BLE001 Do not catch blind exception: `Exception`
   --> scripts/day5_backfill_histdata.py:554:20
    |
552 |                     run_id=run_id,
553 |                 )
554 |             except Exception as exc:
    |                    ^^^^^^^^^
555 |                 cleanup_errors.append(f"{spec.name}: {type(exc).__name__}: {exc}")
556 |     if cleanup_errors:
    |

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

Found 5 errors.
[*] 2 fixable with the `--fix` option (1 hidden fix can be enabled with the `--unsafe-fixes` option).
```

## compile
```text
```

## pytest
```text
........................................................................ [ 94%]
....                                                                     [100%]
76 passed in 0.63s
```
