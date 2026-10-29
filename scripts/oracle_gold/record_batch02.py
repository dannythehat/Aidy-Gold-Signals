"""Reconcile native R-scorecard CI artifacts and retain every scenario and setup."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path

from scripts.oracle_gold.batch02 import outcome_summary
from scripts.oracle_gold.build_register import write_register_csv
from scripts.oracle_gold.history import digest

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/"reports/gold_oracle"
RUN = "https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/40696344939"
CODE = "63e69bf0f32f3fb0aeb7f6991688dd607e334c57"
ARTIFACTS = {
    2023: (12819123078, "28b961642457571d606e99afdcfd5c414bc79e980ef15c3a2c295df7b6965655"),
    2024: (12819307657, "db6196a08626a58a60e5b215916834a5dc51fac286f0b18958087bb1c153d1e5"),
    2025: (12819970709, "a10d34711dc0d9b8a35fe5f2449fd756e8434162bb6171d5eae72622af5e9532"),
}


def decode_ledger(path):
    with path.open() as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        for key in ("setup_id",):
            row[key] = int(row[key])
        for key in ("native_entry_price", "stop", "target", "risk_distance", "native_r"):
            row[key] = float(row[key])
        row["native_exit_price"] = float(row["native_exit_price"]) if row["native_exit_price"] else None
        row["exit_bar_open_utc"] = row["exit_bar_open_utc"] or None
        row["trend_filter_kept"] = row["trend_filter_kept"] == "True"
    return rows


def record(ci_results):
    summaries, hashes, model_years = [], {}, []
    prior = json.loads((OUT/"common_cost_results_register.json").read_text())
    by_year = {r["year"]: r["source_snapshot_sha256"] for r in prior["experiments"]}
    for year in (2023, 2024, 2025):
        folder = ci_results/str(year)
        report = json.loads((folder/"report.json").read_text())
        sha = report.pop("sha256")
        if digest(report) != sha or report["year"] != year or report["source_snapshot_sha256"] != by_year[year]:
            raise ValueError("Batch02 report or historical snapshot identity changed")
        report["sha256"] = sha
        if set(report["models"]) != {f"S{i:03}" for i in range(20, 32)}:
            raise ValueError("Incomplete original module coverage")
        for ident, model in report["models"].items():
            rows = decode_ledger(folder/f"{ident}_native_setups.csv")
            if len(rows) != model["setup_count"] or digest(rows) != model["ledger_sha256"]:
                raise ValueError("Native setup ledger changed")
            for scenario, result in model["scenarios"].items():
                kept = scenario.startswith("source_EMA_filter_on/")
                replay = outcome_summary(rows, result["illustrative_cost_per_oz_round_trip"], kept)
                if replay != result:
                    raise ValueError("Native R scenario fails ledger reconciliation")
                summaries.append({"strategy_id": ident, "year": year, "scenario": scenario,
                    **result, "net_R_sign": "NEGATIVE" if result["cost_adjusted_total_R"] < 0 else
                    "POSITIVE" if result["cost_adjusted_total_R"] > 0 else "ZERO",
                    "prefix_stable_at_tested_cuts": model["prefix_geometry_stable_on_tested_cuts"],
                    "setups_with_execution_flags": model["setups_with_execution_flags"],
                    "source_snapshot_sha256": report["source_snapshot_sha256"],
                    "ledger": f"reports/gold_oracle/batch02/{year}/{ident}_native_setups.csv",
                    "ci_url": RUN, "code_commit": CODE, "execution_qualified": False,
                    "sealed_oos": False})
            model_years.append({"strategy_id": ident, "year": year,
                "setup_count": len(rows), "prefix_tests": model["prefix_tests"],
                "prefix_stable_at_tested_cuts": model["prefix_geometry_stable_on_tested_cuts"],
                "execution_flags": model["setups_with_execution_flags"]})
        dest = OUT/"batch02"/str(year)
        dest.mkdir(parents=True, exist_ok=True)
        for path in folder.iterdir():
            target = dest/path.name
            if target.exists() and target.read_bytes() != path.read_bytes():
                raise ValueError("Refusing to overwrite original batch02 evidence")
            shutil.copyfile(path, target)
            hashes[str(target.relative_to(ROOT))] = hashlib.sha256(target.read_bytes()).hexdigest()
    packet = {"schema": "oracle.gold.batch02.results.v1", "ci_url": RUN, "code_commit": CODE,
        "artifacts": {str(y): {"id": v[0], "zip_sha256": v[1]} for y, v in ARTIFACTS.items()},
        "experiments": summaries, "model_years": model_years, "ledger_file_sha256": hashes,
        "negative_R_scenario_results_retained": sum(s["net_R_sign"] == "NEGATIVE" for s in summaries),
        "setup_ledger_rows": sum(m["setup_count"] for m in model_years),
        "USD_accounts_simulated": 0, "execution_qualified_ids": [], "all83_tested": False,
        "limits": ["Twelve unchanged source methods with native H1 preset, not twelve certified independent systems",
            "Original overlapping per-setup R scorecard; no equity-sizing, margin, netting, financing or account drawdown",
            "EMA filter off/on and cost sensitivities reuse the same setups; not independent experiments",
            "Prefix stability is bounded to tested cuts, never a global proof of causality",
            "S024 changes historic zones; S022 fallback-before-market-open also fails a tested prefix",
            "Missing quote chronology and native fill defects remain; costs are illustrative R overlays",
            "Unknown rules and simulator defects are not fabricated negative economic grades"]}
    packet["sha256"] = digest(packet)
    (OUT/"batch02_results_register.json").write_text(json.dumps(packet, indent=2, sort_keys=True)+"\n")
    with (OUT/"batch02_results_register.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summaries[0]))
        w.writeheader()
        w.writerows(summaries)
    path = OUT/"83_source_and_duplicate_audit.json"
    register = json.loads(path.read_text())
    for row in register["rows"]:
        row["batch02_results"] = [s for s in summaries if s["strategy_id"] == row["id"]]
    register.pop("sha256", None)
    register["sha256"] = digest(register)
    path.write_text(json.dumps(register, indent=2, sort_keys=True)+"\n")
    write_register_csv(register["rows"])
    print("BATCH02_RECONCILED", len(summaries), "scenarios", packet["negative_R_scenario_results_retained"],
          "negative R scenarios", packet["setup_ledger_rows"], "native setups")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ci-results", required=True, type=Path)
    record(p.parse_args().ci_results)


if __name__ == "__main__":
    main()
