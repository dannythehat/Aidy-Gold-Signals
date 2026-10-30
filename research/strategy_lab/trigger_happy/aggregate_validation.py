"""Full loss-preserving TH001 historical replication summary.

Eight previously unexamined months are chronologically BEFORE discovery.
Do not call this forward OOS or broker-executable without later evidence.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


MONTHS = ("202510", "202511", "202512", "202601",
          "202602", "202603", "202604", "202605")


def combine(root: Path, frozen: Path) -> dict:
    selection = json.loads(frozen.read_text())
    docs = {}
    for p in sorted(root.rglob("validation_month.json")):
        d = json.loads(p.read_text())
        month = d["source_month"]
        if month in docs:
            raise ValueError("Duplicate validation month")
        if d["frozen_candidate_sha"] != selection["frozen_content_sha256"]:
            raise ValueError("Candidate selection changed between months")
        docs[month] = d
    if set(docs) != set(MONTHS):
        raise ValueError("Missing required historical replication month(s): "
                         + repr(sorted(set(MONTHS) - set(docs))))
    cases = []
    ids = [p["id"] for p in selection["selected"]] + ["ORIGINAL_FOLLOW_BASELINE"]
    for selected_id in ids:
        months = {}
        for m in MONTHS:
            doc = docs[m]
            choices = doc["selected_cases"] + [doc["original_baseline"]]
            matches = [c for c in choices if c["id"] == selected_id]
            if len(matches) != 1:
                raise ValueError("Missing case / duplicate case for " + m)
            months[m] = matches[0]
        records = list(months.values())
        cases.append({
            "id": selected_id,
            "n_months": len(records),
            "total_filled_bundles": sum(x["filled"] for x in records),
            "total_closed_legs": sum(x["closed_legs"] for x in records),
            "total_tp_legs": sum(x["tp_legs"] for x in records),
            "total_stop_legs": sum(x["stop_legs"] for x in records),
            "total_time_legs": sum(x["time_legs"] for x in records),
            "total_fee10_usd": round(sum(x["fee10_net_usd"] for x in records), 3),
            "total_fee10_extra_slip050_usd": round(
                sum(x["fee10_plus_extra_slip050_net_usd"] for x in records), 3),
            "positive_months_after_fee": sum(x["fee10_net_usd"] > 0 for x in records),
            "positive_months_after_extra_slip": sum(
                x["fee10_plus_extra_slip050_net_usd"] > 0 for x in records),
            "negative_months_after_fee": sum(x["fee10_net_usd"] < 0 for x in records),
            "monthly": {m: {
                "filled": x["filled"], "fee10_net_usd": x["fee10_net_usd"],
                "stress_net_usd": x["fee10_plus_extra_slip050_net_usd"],
            } for m, x in months.items()},
        })
    return {
        "study": "TH001_PREVIOUSLY_UNEXAMINED_HISTORICAL_REPLICATION",
        "frozen_selection_sha256": selection["frozen_content_sha256"],
        "discovery_period": selection["discovery_months"],
        "previously_unexamined_period": list(MONTHS),
        "source_zip_sha256_per_month": {
            m: docs[m]["source"]["original_zip_sha256"] for m in MONTHS},
        "comparison_no_data_leak_warning": (
            "These months precede discovery chronologically and are not a formal forward holdout;"
            " 540 related configurations were already explored on discovery data."
        ),
        "result": cases, "approved_for_paper": False,
        "broker_execution_verified": False,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--selection", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    report = combine(a.root, a.selection)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("TH001_HISTORICAL_REPLICATION_FINAL", json.dumps(
        {"selected_sha": report["frozen_selection_sha256"],
         "comparison_warning": report["comparison_no_data_leak_warning"],
         "cases": report["result"]}, sort_keys=True))


if __name__ == "__main__":
    main()
