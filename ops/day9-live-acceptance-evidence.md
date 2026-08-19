# Day 9 cross-market evidence live-acceptance evidence

- Trigger commit: e285809b669dc849ea5626447c4a6b48dc6be2fc
- Observed at UTC: 2026-08-19T15:54:26Z
- Dependencies: PASS
- Code gate: FAIL
- Code gate status: ruff=1 compile=0 pytest=0
- Source/PIT structural boundary: NOT_REACHED_OR_FAILED
- Repeated live source probe: NOT_REACHED_OR_FAILED
- Credential preflight: NOT_REACHED_OR_FAILED
- Live config: NOT_REACHED_OR_FAILED
- D1 migration: NOT_REACHED_OR_FAILED
- Worker deployed: NOT_REACHED_OR_FAILED
- Broker-free health: NOT_REACHED_OR_FAILED
- Two real Worker samples: NOT_REACHED_OR_FAILED
- D1 identity reconciliation: NOT_REACHED_OR_FAILED
- R2 reconciliation: NOT_REACHED_OR_FAILED
- BigQuery dependency: NOT_REACHED_OR_FAILED
- BigQuery double-export + PIT as-of: NOT_REACHED_OR_FAILED

## ruff
```text
29 |             raise RuntimeError(f"Implausible Treasury yield: {item.series_id}")
   |

FURB157 [*] Verbose expression in `Decimal` constructor
  --> scripts/day9_probe_cross_market.py:28:76
   |
26 |             raise RuntimeError(f"Unexpected cross-market source host: {item.series_id}")
27 |         value = Decimal(item.value)
28 |         if item.unit == "percent" and not Decimal("-20") < value < Decimal("30"):
   |                                                                            ^^^^
29 |             raise RuntimeError(f"Implausible Treasury yield: {item.series_id}")
30 |         if item.unit == "index_jan_2006_100" and not Decimal("20") < value < Decimal("300"):
   |
help: Replace with `30`
   |
27 |         value = Decimal(item.value)
   -         if item.unit == "percent" and not Decimal("-20") < value < Decimal("30"):
28 +         if item.unit == "percent" and not Decimal("-20") < value < Decimal(30):
29 |             raise RuntimeError(f"Implausible Treasury yield: {item.series_id}")
   |

FURB157 [*] Verbose expression in `Decimal` constructor
  --> scripts/day9_probe_cross_market.py:30:62
   |
28 |         if item.unit == "percent" and not Decimal("-20") < value < Decimal("30"):
29 |             raise RuntimeError(f"Implausible Treasury yield: {item.series_id}")
30 |         if item.unit == "index_jan_2006_100" and not Decimal("20") < value < Decimal("300"):
   |                                                              ^^^^
31 |             raise RuntimeError("Implausible broad-dollar index value.")
32 |         output[item.series_id] = {
   |
help: Replace with `20`
   |
29 |             raise RuntimeError(f"Implausible Treasury yield: {item.series_id}")
   -         if item.unit == "index_jan_2006_100" and not Decimal("20") < value < Decimal("300"):
30 +         if item.unit == "index_jan_2006_100" and not Decimal(20) < value < Decimal("300"):
31 |             raise RuntimeError("Implausible broad-dollar index value.")
   |

FURB157 [*] Verbose expression in `Decimal` constructor
  --> scripts/day9_probe_cross_market.py:30:86
   |
28 |         if item.unit == "percent" and not Decimal("-20") < value < Decimal("30"):
29 |             raise RuntimeError(f"Implausible Treasury yield: {item.series_id}")
30 |         if item.unit == "index_jan_2006_100" and not Decimal("20") < value < Decimal("300"):
   |                                                                                      ^^^^^
31 |             raise RuntimeError("Implausible broad-dollar index value.")
32 |         output[item.series_id] = {
   |
help: Replace with `300`
   |
29 |             raise RuntimeError(f"Implausible Treasury yield: {item.series_id}")
   -         if item.unit == "index_jan_2006_100" and not Decimal("20") < value < Decimal("300"):
30 +         if item.unit == "index_jan_2006_100" and not Decimal("20") < value < Decimal(300):
31 |             raise RuntimeError("Implausible broad-dollar index value.")
   |

FURB162 Unnecessary timezone replacement with zero offset
   --> src/aidy/cross_market.py:146:39
    |
144 |         return None
145 |     try:
146 |         return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    |                                       ^^^^^^^^^^^^^^^^^^^^^^^^^^
147 |     except ValueError:
148 |         try:
    |
help: Remove `.replace()` call

TRY004 Prefer `TypeError` exception for invalid type
   --> src/aidy/cross_market_storage.py:224:13
    |
222 |         payload = _row_value(row, "payload_json")
223 |         if not isinstance(payload, str):
224 |             raise RuntimeError("Cross-market outbox points to missing evidence.")
    |             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
225 |         return payload
    |

BLE001 Do not catch blind exception: `Exception`
   --> src/aidy/storage_contracts.py:179:20
    |
177 |             try:
178 |                 await self._archive.put_immutable(item)
179 |             except Exception as exc:  # archive provider errors are deliberately isolated
    |                    ^^^^^^^^^
180 |                 failed += 1
181 |                 await self._operational.mark_archive_failure(
    |

I001 [*] Import block is un-sorted or un-formatted
  --> tests/test_cross_market.py:1:1
   |
 1 | / from __future__ import annotations
 2 | |
 3 | | from datetime import UTC, date, datetime, timedelta
 4 | | import json
 5 | |
 6 | | import pytest
 7 | |
 8 | | from aidy.cross_market import (
 9 | |     CrossMarketError,
10 | |     CrossMarketGateway,
11 | |     CrossMarketObservation,
12 | |     SERIES_US10Y,
13 | |     SERIES_US10Y_REAL,
14 | |     SERIES_US2Y,
15 | |     SERIES_USD_BROAD,
16 | |     parse_fred_broad_dollar_csv,
17 | |     parse_treasury_yield_xml,
18 | | )
19 | | from aidy.cross_market_asof import reconstruct_cross_market_as_of
20 | | from aidy.cross_market_bigquery import ArchivedCrossMarketEvidence
21 | | from aidy.cross_market_recorder import AidyCrossMarketRecorderService
22 | | from aidy.cross_market_storage import cross_market_archive_key
   | |______________________________________________________________^
help: Organize imports
   |
2  |
3  + import json
4  | from datetime import UTC, date, datetime, timedelta
   - import json
5  |
6  | import pytest
7  |
8  | from aidy.cross_market import (
   -     CrossMarketError,
   -     CrossMarketGateway,
   -     CrossMarketObservation,
9  +     SERIES_US2Y,
10 |     SERIES_US10Y,
11 |     SERIES_US10Y_REAL,
   -     SERIES_US2Y,
12 |     SERIES_USD_BROAD,
13 +     CrossMarketError,
14 +     CrossMarketGateway,
15 +     CrossMarketObservation,
16 |     parse_fred_broad_dollar_csv,
--------------------------------------------------------------------------------
22 | from aidy.cross_market_storage import cross_market_archive_key
   -
23 |
   |

RUF100 [*] Unused `noqa` directive (non-enabled: `SLF001`)
   --> tests/test_cross_market.py:283:59
    |
281 |     gateway = CrossMarketGateway()
282 |     with pytest.raises(CrossMarketError, match="source_not_allowed"):
283 |         await gateway._fetch("https://example.com/fake")  # noqa: SLF001
    |                                                           ^^^^^^^^^^^^^^
help: Remove unused `noqa` directive
    |
282 |     with pytest.raises(CrossMarketError, match="source_not_allowed"):
    -         await gateway._fetch("https://example.com/fake")  # noqa: SLF001
283 +         await gateway._fetch("https://example.com/fake")
    |

Found 10 errors.
[*] 7 fixable with the `--fix` option (1 hidden fix can be enabled with the `--unsafe-fixes` option).
```

## pytest
```text
........................................................................ [ 53%]
..............................................................           [100%]
134 passed in 0.81s
```
