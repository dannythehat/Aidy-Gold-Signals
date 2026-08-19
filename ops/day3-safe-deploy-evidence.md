# Day 3 safe-deploy evidence

- Trigger commit: b0f13454c0dfe2be9a689b9896bc6dd86d463be6
- Observed at UTC: 2026-08-19T08:52:18Z
- Dependencies: PASS
- Cloudflare credentials present: PASS
- Ruff/compile/tests: FAIL
- Code gate status: ruff=1 compile=0 pytest=0
- Safe-off config built: NOT_REACHED_OR_FAILED
- D1 migrations: NOT_REACHED_OR_FAILED
- Worker safe-off deploy: NOT_REACHED_OR_FAILED
- Scheduler safe-off deploy: NOT_REACHED_OR_FAILED
- Health + continuity fail-closed proof: NOT_REACHED_OR_FAILED

## ruff output
```text
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

Found 10 errors.
[*] 3 fixable with the `--fix` option (1 hidden fix can be enabled with the `--unsafe-fixes` option).
```

## compile output
```text
```

## pytest output
```text
...............................................                          [100%]
47 passed in 0.54s
```

## Remaining live gate
Enable capture only with an independently owned AIDY market-data source, restore the one-minute Cloudflare scheduler, then require a clean 5+ minute /day3/continuity window with D1/R2 reconciliation.
