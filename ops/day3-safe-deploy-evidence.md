# Day 3 safe-deploy evidence

- Trigger commit: cc800fb38736ecd4fcab22addb70d77caca3a103
- Observed at UTC: 2026-08-19T08:54:35Z
- Dependencies: PASS
- Cloudflare credentials present: PASS
- Ruff/compile/tests: PASS
- Code gate status: ruff=0 compile=0 pytest=0
- Safe-off config built: PASS
- D1 migrations: PASS
- Worker safe-off deploy: PASS
- Scheduler safe-off deploy: PASS
- Health + continuity fail-closed proof: NOT_REACHED_OR_FAILED

## ruff output
```text
All checks passed!
```

## compile output
```text
```

## pytest output
```text
...............................................                          [100%]
47 passed in 0.37s
```

## Health
```json
{"service": "aidy-signals", "status": "ok", "runtime": "cloudflare-workers", "environment": "test", "capture_enabled": false, "scheduler": "queue-consumer"}
```

## Safe-off continuity response
HTTP 404
```json
Not found
```

## Remaining live gate
Enable capture only with an independently owned AIDY market-data source, restore the one-minute Cloudflare scheduler, then require a clean 5+ minute /day3/continuity window with D1/R2 reconciliation.
