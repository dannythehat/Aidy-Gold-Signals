"""Post-ledger dependence diagnostics. Never alter original signals or trades."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from aidy.gold_toolbox_registry import _CATALOG
from scripts.oracle_gold.history import digest


def analyse(root):
    streams = {}
    for year in (2023, 2024, 2025):
        report = json.loads((root/str(year)/"report.json").read_text())
        expected = report.pop("sha256")
        if digest(report) != expected:
            raise ValueError("Diagnostics require frozen original reports")
        for key, model in report["models"].items():
            monthly = model["monthly"]
            values = [(m["month"], m["return_pct"]) for m in monthly]
            streams.setdefault(key, []).extend(values)
    frame = pd.DataFrame({key: pd.Series(dict(values)) for key, values in streams.items()})
    pairs = []
    for scenario in ("base", "stress"):
        names = sorted(c for c in frame if c.endswith("/"+scenario))
        for i, a in enumerate(names):
            for b in names[i+1:]:
                joint = frame[[a, b]].dropna()
                corr = joint[a].corr(joint[b]) if joint[a].std() and joint[b].std() else None
                pairs.append({"a": a, "b": b, "common_months": len(joint),
                    "monthly_marked_return_correlation": corr,
                    "joint_negative_months": int(((joint[a] < 0)&(joint[b] < 0)).sum()),
                    "joint_positive_months": int(((joint[a] > 0)&(joint[b] > 0)).sum()),
                    "high_correlation_review_flag": bool(corr is not None and abs(corr) >= .8),
                    "independence_proven": False,
                    "caveat": "Apex defective-engine diagnostic; unsealed and gap-qualified histories"})
    routes = [{"capability": c["name"], "owner": c["owner"],
               "integrated_for_this_batch": False,
               "status": "EXCLUDED_EXTERNAL_SYSTEM" if c["owner"] != "aidy" else "NOT_INTEGRATED_IN_FROZEN_ORIGINAL_REPLAY",
               "reason": "No external Super Signals data used" if c["owner"] != "aidy" else
                         "Original source signals frozen; no historical expert/runtime availability assumed. H1 price history is input, not proof this expert ran."}
              for c in _CATALOG]
    modules = [
        {"path": "scripts/strategy_lab/s010_run_12month_history.py", "status": "USED_AUTHENTICATED_BIGQUERY_M1_READ"},
        {"path": "src/aidy/strategy_lab_crossfire_tick_2021.py", "status": "USED_REAL_R2_TICK_VALIDATION_AND_DERIVATION"},
        {"path": "src/aidy/strategy_lab_s010_backtest.py", "status": "USED_ORIGINAL_SIGNAL_PARITY_AND_EXISTING_BASE_STRESS_MODELS"},
        {"path": "src/aidy/strategy_lab_broker_profile.py", "status": "BLOCKED_UNATTESTED_NATIVE_CONTRACT"},
        {"path": "src/aidy/strategy_lab_bidask_execution.py", "status": "NOT_ROUTED_FULL_EVENT_ALIGNED_ASK_TAPE_UNAVAILABLE_IN_YEAR_SNAPSHOTS"},
        {"path": "src/aidy/strategy_lab_fees_funding.py", "status": "BLOCKED_NO_VERIFIED_FUNDING_AND_COMMISSION_TERMS"},
        {"path": "src/aidy/strategy_lab_regimes.py", "status": "NOT_ROUTED_SOURCE_MODULE_IS_BOUNDED_M5_DEVELOPMENT_POLICY_NOT_H1_NATIVE_CLASSIFIER"},
        {"path": "src/aidy/strategy_lab_system_processor.py", "status": "NOT_GENERICALLY_ROUTED_ONLY_SUPPORTS_S010_AND_LAB_DONCHIAN"}]
    packet = {"schema": "oracle.gold.batch01.dependence_and_tool_routing.v1",
        "original_entries_or_exits_changed": False, "monthly_dependence": pairs,
        "toolbox_use_or_exclusion": routes, "data_and_execution_modules": modules,
        "portfolio": {"status": "BLOCKED", "missing": ["verified shared margin/stopout",
            "hedging/netting treatment", "native lot steps", "financing", "causal source execution gate"],
            "sum_of_independent_accounts_used_as_master": False},
        "regime_expert_analysis": "NOT_INTEGRATED; no invented regime labels or live-learning outputs"}
    packet["sha256"] = digest(packet)
    return packet


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    args.out.write_text(json.dumps(analyse(args.root), indent=2, sort_keys=True, allow_nan=False)+"\n")


if __name__ == "__main__":
    main()
