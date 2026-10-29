"""Assign all original IDs to efficient cache-sharing batches or explicit gates."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.oracle_gold.history import digest

OUT = Path(__file__).resolve().parents[2]/"reports/gold_oracle"

ROUTES = {
    "S011": ("Q04_MACRO_DAILY", "BLOCKED_PIT_MACRO_DATA", "Daily authentic gold plus publication-vintage DXY/TNX; do not strip macro gates"),
    "S012": ("GATE_SOURCE_ONLY", "BLOCKED_PROVEN_LOOKAHEAD", "No economic qualification of current original; clarification or separately labelled correction required"),
    "S013": ("Q05_PENDING_M5", "BLOCKED_ENTRY_TRIGGER_AND_DUAL_TOUCH", "Reuse M1/tick cache; native pending trigger first; original200USD/50k, no invented10k account"),
    "S014": ("GATE_IMPLEMENTATION_SELECTION", "BLOCKED_DIVERGENT_IMPLEMENTATIONS", "Pine chart/session/BE versus contradictory Python signal code; select original before replay"),
    "S015": ("Q06_FVG_SCORECARD", "BLOCKED_FILL_AND_UNRESOLVED_ACCOUNT", "Native R diagnostic possible; target-first incomplete outcomes cannot qualify as account performance"),
    "S016": ("Q07_DAILY_DONCHIAN_FAMILY", "BLOCKED_AUTHENTIC_DAILY_INPUT_ADAPTATION", "One source family with20/20/1% and95/20/2% variants; no synthetic publisher OHLC copied"),
    "S017": ("GATE_MANUAL_ASOF", "BLOCKED_HUMAN_WAVE_TIMESTAMPS", "March2026 fixed-level scenario; generic multi-year wave labels must not be invented"),
    "S018": ("GATE_MQL_DEPENDENCIES", "BLOCKED_MISSING_ORIGINAL_HELPERS", "Need native compiler, original pending/OCO helpers and broker point/digits; no broker launch"),
    "S019": ("Q08_NATIVE_M1_ACCOUNT", "BLOCKED_FULL_SETUP_POSITION_AUDIT", "Reuse authenticated M1; native account/cost engine after full parity, not H1 approximation"),
    "S082": ("GATE_LOGICAL_ZERO", "BLOCKED_PROVEN_ZERO_SIGNAL", "Original OR tautology tested; no author rule repair disguised as original"),
    "S083": ("Q09_NATIVE_BIDASK_M1", "BLOCKED_001B_BIDASK_AND_GAP_PARITY", "Authentic bid/ask M1 cache -> known_at D1/H4/M15;001A preregistration cannot certify001B"),
}


def assign(register):
    routes = dict(ROUTES)
    for i in range(1, 5):
        routes[f"S{i:03}"] = ("Q03_NATIVE_INTRADAY", "BLOCKED_NATIVE_RULE_FILL_PARITY",
            "One authenticated M1/tick cache; derive each frozen source timeframe separately; preserve all prior failures")
    for i in range(5, 11):
        routes[f"S{i:03}"] = ("B01_RETAINED", "DONE_CONDITIONAL_MODELS",
            "H1 immutable snapshots; existing account models and common-cost sensitivities")
    for i in range(20, 32):
        routes[f"S{i:03}"] = ("B02_RETAINED", "DONE_NATIVE_R_DIAGNOSTIC",
            "Same H1 snapshots reused;12 native modules; no dollar account")
    rows = []
    for source in register["rows"]:
        batch, status, reuse = routes.get(source["id"], ("WAIT_EXECUTABLE_SOURCE",
            "BLOCKED_ORIGINAL_SOURCE_NOT_VERIFIED", "Page/title or inaccessible download cannot specify a faithful backtest"))
        rows.append({"id": source["id"], "title": source["original_title"],
            "source_access": source["source_access"], "batch_or_gate": batch,
            "status": status, "reuse_and_admission": reuse, "canonical_id": source["canonical_id"],
            "native_rules_and_execution_verified": False, "execution_qualified": False,
            "independence_proven": False, "existing_negative_evidence": source.get("historical_reports", [])})
    if {r["id"] for r in rows} != {f"S{i:03}" for i in range(1, 84)} or len(rows) != 83:
        raise ValueError("Original83 ID coverage changed")
    packet = {"schema": "oracle.gold.original83.batch_assignment.v1", "rows": rows,
        "original_ids": 83, "unverified_source_waiting_ids": sum(r["batch_or_gate"] == "WAIT_EXECUTABLE_SOURCE" for r in rows),
        "source_years": [2023, 2024, 2025], "full_market_calendar_certified": False,
        "limits": ["Assignment is not a claim of distinct economic edges or permission to invent source rules",
            "Run unmodified originals before any separately labelled remediation/derived variant",
            "Shared cache does not imply common account/risk; no sum of standalone accounts called portfolio",
            "All original negative results and source failures retained; no winner-only reruns"]}
    packet["sha256"] = digest(packet)
    return packet


def main():
    register = json.loads((OUT/"83_source_and_duplicate_audit.json").read_text())
    packet = assign(register)
    (OUT/"83_batch_assignment_register.json").write_text(json.dumps(packet, indent=2, sort_keys=True)+"\n")
    print("ALL83_ASSIGNED", packet["original_ids"], "SOURCE_WAIT", packet["unverified_source_waiting_ids"])


if __name__ == "__main__":
    main()
