# Day 4 BigQuery live-acceptance evidence

- Trigger commit: df3ee6d4a95c5ee3953ce941ec9c6e87d8881136
- Observed at UTC: 2026-08-19T10:30:42Z
- Dependencies: PASS
- Code gate: FAIL
- Code gate status: ruff=1 compile=0 pytest=0
- Live-recorder/BigQuery import boundary: NOT_REACHED_OR_FAILED
- Recorder health before export: NOT_REACHED_OR_FAILED
- Credential preflight: NOT_REACHED_OR_FAILED
- Genuine R2 snapshot retrieval: NOT_REACHED_OR_FAILED
- BigQuery dependency: NOT_REACHED_OR_FAILED
- R2 -> BigQuery repeated round-trip: NOT_REACHED_OR_FAILED
- BigQuery-failure isolation from recorder: NOT_REACHED_OR_FAILED

## ruff
```text
S110 `try`-`except`-`pass` detected, consider logging the exception
   --> scripts/day4_export_r2_to_bigquery.py:388:13
    |
386 |                       run_id=run_id,
387 |                   )
388 | /             except Exception:
389 | |                 pass
    | |____________________^
390 |
391 |       return {
    |

BLE001 Do not catch blind exception: `Exception`
   --> scripts/day4_export_r2_to_bigquery.py:388:20
    |
386 |                     run_id=run_id,
387 |                 )
388 |             except Exception:
    |                    ^^^^^^^^^
389 |                 pass
    |

TRY004 Prefer `TypeError` exception for invalid type
   --> src/aidy/bigquery_exporter.py:156:13
    |
154 |             raise ValueError("R2 evidence object is not valid JSON.") from exc
155 |         if not isinstance(parsed, dict):
156 |             raise ValueError("R2 evidence object must be a JSON object.")
    |             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
157 |         required = (
158 |             "schema_version",
    |

TRY004 Prefer `TypeError` exception for invalid type
   --> src/aidy/bigquery_exporter.py:169:13
    |
167 |         payload = parsed.get("payload")
168 |         if not isinstance(payload, dict):
169 |             raise ValueError("R2 evidence object requires an object payload.")
    |             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
170 |         try:
171 |             schema_version = int(parsed["schema_version"])
    |

TRY004 Prefer `TypeError` exception for invalid type
   --> src/aidy/bigquery_exporter.py:220:9
    |
218 |         return None
219 |     if not isinstance(value, str):
220 |         raise ValueError("Archived timestamp must be an ISO-8601 string.")
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
221 |     try:
222 |         parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    |

FURB162 Unnecessary timezone replacement with zero offset
   --> src/aidy/bigquery_exporter.py:222:41
    |
220 |         raise ValueError("Archived timestamp must be an ISO-8601 string.")
221 |     try:
222 |         parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    |                                         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
223 |     except ValueError as exc:
224 |         raise ValueError(f"Invalid archived timestamp: {value}") from exc
    |
help: Remove `.replace()` call

TRY004 Prefer `TypeError` exception for invalid type
   --> src/aidy/bigquery_exporter.py:232:9
    |
230 | def _json_object(value: Any, *, name: str) -> dict[str, Any]:
231 |     if not isinstance(value, dict):
232 |         raise ValueError(f"{name} must be an object.")
    |         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
233 |     return value
    |

Found 7 errors.
No fixes available (1 hidden fix can be enabled with the `--unsafe-fixes` option).
```

## compile
```text
```

## pytest
```text
..............................................................           [100%]
62 passed in 0.57s
```
