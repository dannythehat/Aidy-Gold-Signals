#!/usr/bin/env python3
"""AIDY Build-24 shadow learning-loop watchdog.

The learning loop can stop producing cycles silently. Two real cases:

* 2026-09-21: a 135-minute cycle gap had to be reconstructed from
  market_snapshots because the singleton health row keeps no history.
* A raised expert builder loses an entire shadow cycle; the sync boundary
  catches it so capture survives, but the error is erased by the next
  successful sync.

This watchdog reads live D1 read-only and fails loudly when the loop has
stalled, when the most recent sync recorded an error, or when cycles are
being produced with an unexpected gate count.

Read-only. Never writes to D1. Never touches execution or capture.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime

# A cycle is expected roughly every 15 minutes while Gold is open. Gold closes
# daily (maintenance) and at weekends, so the default tolerates a normal
# closure plus the post-reopen warm-up before alerting.
MAX_CYCLE_AGE_MINUTES = float(os.getenv("SHADOW_MAX_CYCLE_AGE_MINUTES", "180"))
MAX_HEALTH_AGE_MINUTES = float(os.getenv("SHADOW_MAX_HEALTH_AGE_MINUTES", "30"))
EXPECTED_GATE_N = int(os.getenv("SHADOW_EXPECTED_GATE_N", "15"))

SQL = """
SELECT
  (SELECT MAX(decided_at_utc) FROM aidy_gold_expert_shadow_cycles)
      AS latest_cycle_decided_at_utc,
  (SELECT COUNT(*) FROM aidy_gold_expert_shadow_cycles)
      AS total_cycles,
  (SELECT observed_at_utc FROM aidy_gold_expert_shadow_sync_health WHERE singleton_id=1)
      AS health_observed_at_utc,
  (SELECT status FROM aidy_gold_expert_shadow_sync_health WHERE singleton_id=1)
      AS health_status,
  (SELECT error_type FROM aidy_gold_expert_shadow_sync_health WHERE singleton_id=1)
      AS health_error_type,
  (SELECT error_message FROM aidy_gold_expert_shadow_sync_health WHERE singleton_id=1)
      AS health_error_message,
  (SELECT expected_gate_n FROM aidy_gold_expert_shadow_sync_health WHERE singleton_id=1)
      AS expected_gate_n,
  (SELECT known_gate_n FROM aidy_gold_expert_shadow_sync_health WHERE singleton_id=1)
      AS known_gate_n
"""


def _query(sql: str) -> dict:
    account = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    database = os.environ["AIDY_D1_DATABASE_ID"]
    endpoint = (
        f"https://api.cloudflare.com/client/v4/accounts/{account}"
        f"/d1/database/{database}/query"
    )
    request = urllib.request.Request(
        endpoint,
        data=json.dumps({"sql": sql}).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['CLOUDFLARE_API_TOKEN']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode())
    if not payload.get("success"):
        raise RuntimeError(f"D1 query failed: {payload.get('errors')}")
    results = payload["result"][0]["results"]
    return dict(results[0]) if results else {}


def _age_minutes(raw: object, *, now: datetime) -> float | None:
    if not raw:
        return None
    parsed = datetime.fromisoformat(str(raw))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (now - parsed.astimezone(UTC)).total_seconds() / 60.0


def main() -> int:
    now = datetime.now(UTC)
    row = _query(SQL)

    cycle_age = _age_minutes(row.get("latest_cycle_decided_at_utc"), now=now)
    health_age = _age_minutes(row.get("health_observed_at_utc"), now=now)
    failures: list[str] = []

    if cycle_age is None:
        failures.append("no shadow cycle has ever been recorded")
    elif cycle_age > MAX_CYCLE_AGE_MINUTES:
        failures.append(
            f"learning loop stalled: newest cycle is {cycle_age:.1f} min old "
            f"(limit {MAX_CYCLE_AGE_MINUTES:.0f})"
        )

    if health_age is None:
        failures.append("no shadow sync health has ever been recorded")
    elif health_age > MAX_HEALTH_AGE_MINUTES:
        failures.append(
            f"sync health stale: last observed {health_age:.1f} min ago "
            f"(limit {MAX_HEALTH_AGE_MINUTES:.0f})"
        )

    if str(row.get("health_status") or "") == "error":
        failures.append(
            "latest shadow sync recorded an error: "
            f"{row.get('health_error_type')}: "
            f"{str(row.get('health_error_message'))[:300]}"
        )

    expected = row.get("expected_gate_n")
    if expected is not None and int(expected) != EXPECTED_GATE_N:
        failures.append(
            f"expected gate count is {expected}, should be {EXPECTED_GATE_N}"
        )

    report = {
        "checked_at_utc": now.isoformat(),
        "latest_cycle_decided_at_utc": row.get("latest_cycle_decided_at_utc"),
        "latest_cycle_age_minutes": None if cycle_age is None else round(cycle_age, 1),
        "total_cycles": row.get("total_cycles"),
        "health_status": row.get("health_status"),
        "health_age_minutes": None if health_age is None else round(health_age, 1),
        "expected_gate_n": row.get("expected_gate_n"),
        "known_gate_n": row.get("known_gate_n"),
        "thresholds": {
            "max_cycle_age_minutes": MAX_CYCLE_AGE_MINUTES,
            "max_health_age_minutes": MAX_HEALTH_AGE_MINUTES,
        },
        "degraded": bool(failures),
        "failures": failures,
        "read_only": True,
        "live_money_execution_allowed": False,
    }
    print(json.dumps(report, indent=2, sort_keys=True))

    if failures:
        print("\nSHADOW_LOOP_WATCHDOG_DEGRADED", file=sys.stderr)
        for item in failures:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print("\nSHADOW_LOOP_WATCHDOG_OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.URLError as exc:
        print(f"watchdog could not reach D1: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
