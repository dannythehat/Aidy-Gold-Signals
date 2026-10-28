"""Verify genuine CI reports and preserve every model, loss and ledger in Git."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path

from scripts.oracle_gold.history import digest

ROOT = Path(__file__).resolve().parents[2]
RUN = "https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/40684602595"
COMMIT = "ccc859c042453c7275217285ab187c93f52b3e92"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ci-results", required=True, type=Path)
    args = p.parse_args()
    out = ROOT / "reports/gold_oracle"
    summaries, hashes, reports = [], {}, []
    for year in (2023, 2024, 2025):
        folder = args.ci_results / str(year)
        report = json.loads((folder/"report.json").read_text())
        expected = report.pop("sha256")
        if digest(report) != expected or report["year"] != year:
            raise ValueError("CI report identity changed")
        report["sha256"] = expected
        reports.append(report)
        dest = out / "batch01" / str(year)
        dest.mkdir(parents=True, exist_ok=True)
        for f in folder.iterdir():
            if f.name == "report.json" or f.name.endswith(("_trades.csv", "_monthly.csv")) or f.name == "signal_events.csv":
                target = dest/f.name
                if target.exists() and target.read_bytes() != f.read_bytes():
                    raise ValueError("Refusing to overwrite immutable result " + str(target))
                shutil.copyfile(f, target)
                hashes[str(target.relative_to(ROOT))] = hashlib.sha256(target.read_bytes()).hexdigest()
        for key, m in report["models"].items():
            ident, scenario = key.split("/")
            net = m.get("net_usd", m.get("net_marked_pnl_usd"))
            summaries.append({"strategy_id": ident, "year": year, "scenario": scenario,
                "status": m["status"], "diagnostic_only": ident != "S010",
                "initial_usd": 10000., "closed_trades": m["closed_trades"],
                "long_trades": m.get("long_trades", m["closed_trades"] if ident == "S010" else None),
                "short_trades": m.get("short_trades", 0 if ident == "S010" else None),
                "net_marked_usd": net, "net_closed_usd": m.get("net_closed_trade_usd", net),
                "net_sign": "NEGATIVE" if net < 0 else "POSITIVE" if net > 0 else "ZERO",
                "h1_close_marked_dd_pct": m.get("max_h1_close_marked_dd_pct", m.get("max_marked_drawdown_pct")),
                "profit_factor": m["profit_factor"], "win_rate_pct": m["win_rate_pct"],
                "source_snapshot_sha256": report["manifest"]["rows_sha256"],
                "report_sha256": expected, "code_commit": COMMIT, "ci_url": RUN,
                "native_broker_parity": False, "sealed_oos": False,
                "ledger": str((dest/f"{ident}_{scenario}_trades.csv").relative_to(ROOT))})
    with (out/"strategy_results_register.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    result = {"schema": "oracle.gold.strategy_results.v1", "ci_run": RUN, "code_commit": COMMIT,
        "artifact_id": 12813599468,
        "artifact_sha256": "4bfa62a353e8df88a4507b96a5b98c33a2f5445856efc7eac90d547ccb998fcb",
        "experiments": summaries, "ledger_file_sha256": hashes,
        "negative_scenario_results_retained": sum(s["net_sign"] == "NEGATIVE" for s in summaries),
        "tested_original_ids": sorted({s["strategy_id"] for s in summaries}),
        "execution_qualified_ids": [], "full_source_calendar_years_certified": 0,
        "all83_tested": False, "portfolio_status": "BLOCKED_SOURCE_CAUSALITY_AND_SHARED_MARGIN",
        "failed_attempts": [{"ci_run": "https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/40684079400",
            "status": "FAILED_BIGQUERY_QUERY", "cause": "New numeric predicate compared warehouse STRING price with INT64; corrected with SAFE_CAST; regex braces escaped", "source_r2_jobs": "ALL_12_PASSED_AND_REUSED"}],
        "scope_limits": ["2023 R2 and 2024/25 BigQuery are different history sources; not parity-equivalent tapes",
            "All source months checked, not complete broker trading calendars; partial H1 excluded",
            "Apex warmup250 consumes start of each year; compare with prior reports only at identical scope",
            "S010 original signals parity checked; original native accounting differs from AIDY next-open model",
            "Apex native engine has demonstrated future-close sizing defect; P&L is diagnostic only",
            "No original ZIPs or complete quote histories committed; artifacts retain detailed evidence90days",
            "No original IDs deleted, no numeric nine-factor scores, no independent family or bot approved"]}
    result["sha256"] = digest(result)
    (out/"strategy_results_register.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    # Attach results without turning diagnostic engine defects into negative edge verdicts.
    path = out/"83_source_and_duplicate_audit.json"
    register = json.loads(path.read_text())
    for row in register["rows"]:
        row["batch01_results"] = [s for s in summaries if s["strategy_id"] == row["id"]]
    register.pop("sha256", None)
    register["sha256"] = digest(register)
    path.write_text(json.dumps(register, indent=2, sort_keys=True)+"\n")
    print(json.dumps({"scenarios": len(summaries), "negative": result["negative_scenario_results_retained"],
                      "result_sha256": result["sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
