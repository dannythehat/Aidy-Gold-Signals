#!/usr/bin/env python3
"""Report whether any AIDY expert's directional calls carry information.

Raw accuracy cannot answer that. An expert answering into a window that resolved
bearish 48.5 per cent of the time scores 48.5 per cent knowing nothing, and an expert
that is reliably *wrong* carries just as much information as one reliably right while
raw accuracy files it next to the noise.

This joins the immutable outcome ledger to the gate snapshot that made each call
(on packet_digest) and reports, per expert, the agreement rate over cycles where the
expert committed to a direction and the market resolved to one - with a Wilson interval
and a Bonferroni correction for the number of experts examined.

Read-only. Never writes to D1. Never touches execution, capture or Super Signals.
It reports; it changes no expert's polarity and no trading behaviour.

Exit status is 0 whenever the query succeeds, including when a polarity verdict is
reached. This is a reporting job, not a gate: a finding here is evidence for a decision
the owner makes, not an automatic change.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aidy.gold_expert_directional_skill import (
    MIN_DIRECTIONAL_N,
    assess,
)
from aidy.gold_expert_momentum_stance import assess as assess_stance

#: Only aggregate at one scope. gate_global is the scope every subject actually falls
#: back to in production, and mixing scopes would double-count the same cycle.
SCOPE_TYPE = os.getenv("SKILL_SCOPE_TYPE", "gate_global")

#: decided_at orders each subject's own history, which is what the momentum stance
#: needs to know what the expert could have been extrapolating from.
SQL = """
SELECT s.gate_id AS subject_id,
       c.decided_at_utc AS decided_at,
       s.conclusion,
       l.realised_direction
FROM aidy_gold_expert_outcome_ledger AS l
JOIN aidy_gold_expert_gate_snapshots AS s
  ON s.packet_digest = l.packet_digest
JOIN aidy_gold_expert_shadow_cycles AS c
  ON c.cycle_view_id = s.cycle_view_id
WHERE l.subject_type = 'gate'
  AND l.scope_type = ?
  AND l.correct IS NOT NULL
  AND s.conclusion IN ('bullish','bearish')
  AND l.realised_direction IN ('bullish','bearish')
ORDER BY s.gate_id, c.decided_at_utc
"""


def _query(sql: str, params: list[str]) -> list[dict]:
    account = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    database = os.environ["AIDY_D1_DATABASE_ID"]
    endpoint = (
        f"https://api.cloudflare.com/client/v4/accounts/{account}"
        f"/d1/database/{database}/query"
    )
    request = urllib.request.Request(
        endpoint,
        data=json.dumps({"sql": sql, "params": params}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {os.environ['CLOUDFLARE_API_TOKEN']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("success"):
        raise RuntimeError(f"D1 query failed: {payload.get('errors')}")
    return payload["result"][0]["results"]


def main() -> int:
    try:
        rows = _query(SQL, [SCOPE_TYPE])
    except (KeyError, urllib.error.URLError, RuntimeError) as exc:
        print(f"directional skill report unavailable: {type(exc).__name__}: {exc}")
        return 1

    results = assess(rows)
    stances = assess_stance(rows)
    report = {
        "scope_type": SCOPE_TYPE,
        "subjects_examined": len(results),
        "minimum_directional_n": MIN_DIRECTIONAL_N,
        "total_directional_resolutions": sum(item.directional_n for item in results),
        "momentum_stance": [
            {
                "subject_id": item.subject_id,
                "n": item.n,
                "momentum_alignment": item.momentum_alignment,
                "market_continuation": item.market_continuation,
                "followed_n": item.followed_n,
                "followed_accuracy": item.followed_accuracy,
                "faded_n": item.faded_n,
                "faded_accuracy": item.faded_accuracy,
                "stance": item.stance,
                "alignment_interval": item.alignment_interval,
            }
            for item in stances
        ],
        "subjects": [
            {
                "subject_id": item.subject_id,
                "directional_n": item.directional_n,
                "agreed": item.agreed,
                "opposed": item.opposed,
                "agreement_rate": item.agreement_rate,
                "nominal_interval": item.nominal_interval,
                "family_interval": item.family_interval,
                "nominal_polarity": item.nominal_polarity,
                "polarity": item.polarity,
                "actionable": item.actionable,
                "reason": item.reason,
            }
            for item in results
        ],
    }

    out = Path(os.getenv("SKILL_REPORT_PATH", "artifacts/aidy-directional-skill.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True))

    print(f"AIDY directional skill @ {SCOPE_TYPE}")
    print(f"  subjects examined: {len(results)} (family-wise correction divides by this)")
    for item in results:
        rate = item.agreement_rate or "n/a"
        interval = (
            f" family95={item.family_interval}" if item.family_interval else ""
        )
        print(
            f"  {item.subject_id}: n={item.directional_n} "
            f"agree={item.agreed} oppose={item.opposed} rate={rate} "
            f"-> {item.polarity}{interval}"
        )

    print()
    print("  momentum stance (is the expert extrapolating, and does it pay?)")
    for item in stances:
        print(
            f"    {item.subject_id}: n={item.n} "
            f"follows={item.momentum_alignment} market_continues={item.market_continuation} "
            f"followed_acc={item.followed_accuracy} faded_acc={item.faded_accuracy} "
            f"-> {item.stance}"
        )

    actionable = [item for item in results if item.actionable]
    if actionable:
        print()
        print("POLARITY VERDICT REACHED - evidence for an owner decision, not a change:")
        for item in actionable:
            print(
                f"  {item.subject_id} is {item.polarity} "
                f"(n={item.directional_n}, family95={item.family_interval})"
            )
    else:
        print()
        print("No expert has earned a polarity verdict. Nothing to act on.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
