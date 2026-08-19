# Day 9 cross-market evidence live-acceptance evidence

- Trigger commit: 6bd5c2b1ecd9b420c1359d093ae00968461f0106
- Observed at UTC: 2026-08-19T15:59:44Z
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
I001 [*] Import block is un-sorted or un-formatted
  --> scripts/day9_export_cross_market_to_bigquery.py:1:1
   |
 1 | / from __future__ import annotations
 2 | |
 3 | | import argparse
 4 | | import json
 5 | | import os
 6 | | import sys
 7 | | from datetime import UTC, datetime
 8 | | from pathlib import Path
 9 | | from uuid import uuid4
10 | |
11 | | from aidy.bigquery_exporter import EXPORT_MANIFEST
12 | | from aidy.cross_market_bigquery import ArchivedCrossMarketEvidence, CROSS_MARKET_TABLE
   | |______________________________________________________________________________________^
13 |
14 |   try:
   |
help: Organize imports
   |
11 | from aidy.bigquery_exporter import EXPORT_MANIFEST
   - from aidy.cross_market_bigquery import ArchivedCrossMarketEvidence, CROSS_MARKET_TABLE
12 + from aidy.cross_market_bigquery import CROSS_MARKET_TABLE, ArchivedCrossMarketEvidence
13 |
   |

Found 1 error.
[*] 1 fixable with the `--fix` option.
```

## pytest
```text
........................................................................ [ 53%]
..............................................................           [100%]
134 passed in 0.79s
```
