# Day 7 deterministic Gold feature engine live-acceptance evidence

- Trigger commit: daaa7335a621daca7656b56c57d81346e93e842d
- Observed at UTC: 2026-08-19T14:31:10Z
- Dependencies: PASS
- Code gate: FAIL
- Code gate status: ruff=1 compile=0 pytest=0
- Structural boundary: NOT_REACHED_OR_FAILED
- Credential preflight: NOT_REACHED_OR_FAILED
- BigQuery dependency: NOT_REACHED_OR_FAILED
- Warehouse anchors: NOT_REACHED_OR_FAILED
- Deterministic retrospective packet: NOT_REACHED_OR_FAILED
- PIT packet / no retrospective leakage: NOT_REACHED_OR_FAILED
- Compact packet summary: NOT_REACHED_OR_FAILED

## ruff
```text
I001 [*] Import block is un-sorted or un-formatted
  --> src/aidy/feature_engine.py:1:1
   |
 1 | / from __future__ import annotations
 2 | |
 3 | | import json
 4 | | from collections.abc import Iterable, Mapping
 5 | | from dataclasses import dataclass
 6 | | from datetime import UTC, datetime
 7 | | from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
 8 | | from hashlib import sha256
 9 | | from itertools import pairwise
10 | | from typing import Any
11 | |
12 | | from aidy.historical_backfill import RETROSPECTIVE_PROVENANCE
13 | | from aidy.market_sessions import session_code_at
   | |________________________________________________^
14 |
15 |   FEATURE_DEFINITION_VERSION = "aidy_gold_features_v1"
   |
help: Organize imports
  |
6 | from datetime import UTC, datetime
  - from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
7 + from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
8 | from hashlib import sha256
  |

Found 1 error.
[*] 1 fixable with the `--fix` option.
```

## compile
```text
```

## pytest
```text
........................................................................ [ 64%]
.......................................                                  [100%]
111 passed in 0.90s
```
