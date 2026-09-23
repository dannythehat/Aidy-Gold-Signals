#!/usr/bin/env python3
"""Report whether any AIDY subject beats the majority-class baseline.

Run it as evidence accumulates and watch whether the gap closes. The 2026-09-23 result
was that nothing beat its baseline and nothing was exploitably inverted either, on a
three-day sample whose directional outcomes were 57.9 per cent bearish - so the deficit
could not be separated from the sample period. That is the question this re-answers:
does the gap persist once regimes vary, or was it the drift?

Read-only. Never writes to D1. Never touches execution, capture or Super Signals. It
reports; it changes no expert's polarity, no weight and no behaviour.

Exit status is 0 whenever the queries succeed, including when a subject beats its
baseline. A finding here is evidence for a decision the owner makes, not an automatic
change - and on this data the correct decision was to change nothing.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aidy.gold_baseline_edge import (
    ALPHA,
    MIN_BASELINE_N,
    VERDICT_BEATS,
    assess,
    normal_two_sided_p,
    strategy_comparison,
    two_sided_binomial_p,
    wilson_interval,
)

#: One scope only. The ledger repeats every result across many scope keys, so mixing
#: them multiplies n by the number of scopes and invents significance that is not there.
SCOPE_TYPE = os.getenv("BASELINE_SCOPE_TYPE", "gate_global")

SUBJECT_SQL = """
SELECT subject_type,
       subject_id,
       COUNT(*) AS n,
       SUM(correct) AS correct,
       SUM(CASE WHEN realised_direction='bullish' THEN 1 ELSE 0 END) AS bullish,
       SUM(CASE WHEN realised_direction='bearish' THEN 1 ELSE 0 END) AS bearish,
       SUM(CASE WHEN realised_direction='neutral' THEN 1 ELSE 0 END) AS neutral
FROM aidy_gold_expert_outcome_ledger
WHERE scope_type = ?
  AND correct IS NOT NULL
GROUP BY subject_type, subject_id
ORDER BY COUNT(*) DESC
"""

#: What each gate actually said, against what happened. This is what separates
#: "fails to exploit a drift" from "reads the market backwards".
CONFUSION_SQL = """
SELECT s.conclusion AS said,
       l.realised_direction AS happened,
       COUNT(*) AS n
FROM aidy_gold_expert_outcome_ledger AS l
JOIN aidy_gold_expert_gate_snapshots AS s
  ON s.packet_digest = l.packet_digest
WHERE l.scope_type = ?
  AND l.subject_type = 'gate'
  AND l.correct IS NOT NULL
GROUP BY said, happened
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
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("success"):
        raise RuntimeError(f"D1 query failed: {payload.get('errors')}")
    return payload["result"][0]["results"]


def main() -> int:
    try:
        subject_rows = _query(SUBJECT_SQL, [SCOPE_TYPE])
        confusion = _query(CONFUSION_SQL, [SCOPE_TYPE])
    except (KeyError, urllib.error.URLError, RuntimeError) as exc:
        print(f"baseline edge report unavailable: {type(exc).__name__}: {exc}")
        return 1

    rows = [
        {
            "subject_type": row["subject_type"],
            "subject_id": row["subject_id"],
            "n": int(row["n"] or 0),
            "correct": int(row["correct"] or 0),
            "class_counts": {
                "bullish": int(row["bullish"] or 0),
                "bearish": int(row["bearish"] or 0),
                "neutral": int(row["neutral"] or 0),
            },
        }
        for row in subject_rows
    ]
    results = assess(rows)
    tested = [item for item in results if item.n >= MIN_BASELINE_N]
    winners = [item for item in tested if item.verdict == VERDICT_BEATS]
    strategies = strategy_comparison(confusion)

    print(f"AIDY baseline edge @ scope_type={SCOPE_TYPE}")
    print(f"  subjects tested: {len(tested)} (n >= {MIN_BASELINE_N}); correction divides by this")
    print(f"  scored observations: {sum(item.n for item in tested)}")
    print()
    print(f"  {'subject':<44}{'n':>5}{'acc':>8}{'base':>8}{'edge':>8}{'p':>11}  verdict")
    print("  " + "-" * 96)
    for item in tested:
        print(
            f"  {item.subject_id[:43]:<44}{item.n:>5}{item.accuracy:>8.3f}"
            f"{item.baseline:>8.3f}{item.edge:>+8.3f}{item.p_value:>11.5f}  {item.verdict}"
        )

    print()
    print("  strategy comparison over directional gate outcomes")
    print(f"    n={strategies.n}  majority class={strategies.majority_class}")
    print(f"    follow the experts   {strategies.follow_accuracy:.3f}")
    print(f"    always {strategies.majority_class:<14}{strategies.majority_accuracy:.3f}   <- the bar")
    print(f"    invert the experts   {strategies.invert_accuracy:.3f}")
    print(f"    random 50/50 calling {strategies.random_accuracy:.3f}")
    print(f"    p vs majority = {strategies.p_vs_majority:.2e}    p vs random = {strategies.p_vs_random:.3f}")
    print(f"    inverting beats the constant answer? {strategies.inversion_is_exploitable}")

    pooled_n = sum(item.n for item in tested)
    pooled_k = sum(item.correct for item in tested)
    pooled_classes = [
        sum(dict(item.class_counts).get(name, 0) for item in tested)
        for name in ("bullish", "bearish", "neutral")
    ]
    if pooled_n:
        pooled_base = max(pooled_classes) / pooled_n
        low, high = wilson_interval(pooled_k, pooled_n)
        print()
        print("  pooled (subjects share cycles, so indicative only - not independent tests)")
        print(f"    n={pooled_n} accuracy={pooled_k/pooled_n:.4f} baseline={pooled_base:.4f}")
        print(f"    exact p={two_sided_binomial_p(pooled_k, pooled_n, pooled_base):.3e}"
              f"  normal p={normal_two_sided_p(pooled_k, pooled_n, pooled_base):.3e}")
        print(f"    accuracy 95% Wilson [{low:.4f}, {high:.4f}]"
              f"  baseline inside? {low <= pooled_base <= high}")

    out = Path(os.getenv("BASELINE_REPORT_PATH", "artifacts/aidy-baseline-edge.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "scope_type": SCOPE_TYPE,
                "alpha": ALPHA,
                "minimum_n": MIN_BASELINE_N,
                "subjects_tested": len(tested),
                "subjects_beating_baseline": len(winners),
                "strategies": {
                    "n": strategies.n,
                    "majority_class": strategies.majority_class,
                    "follow_accuracy": strategies.follow_accuracy,
                    "invert_accuracy": strategies.invert_accuracy,
                    "majority_accuracy": strategies.majority_accuracy,
                    "p_vs_majority": strategies.p_vs_majority,
                    "p_vs_random": strategies.p_vs_random,
                    "inversion_is_exploitable": strategies.inversion_is_exploitable,
                },
                "subjects": [
                    {
                        "subject_type": item.subject_type,
                        "subject_id": item.subject_id,
                        "n": item.n,
                        "correct": item.correct,
                        "accuracy": item.accuracy,
                        "baseline": item.baseline,
                        "edge": item.edge,
                        "p_value": item.p_value,
                        "verdict": item.verdict,
                    }
                    for item in tested
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )

    print()
    if winners:
        print("A SUBJECT BEATS ITS BASELINE - evidence for an owner decision, not a change:")
        for item in winners:
            print(f"  {item.subject_id} n={item.n} acc={item.accuracy:.3f} vs {item.baseline:.3f}")
    else:
        print("No subject beats its baseline. Nothing to act on, and nothing to invert:")
        print("  a deficit against the majority baseline that is NOT a deficit against")
        print("  random means the ensemble fails to exploit a drift, not that it is")
        print("  backwards - and inverting is only meaningful if it beats the constant")
        print("  answer, which it does not.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
