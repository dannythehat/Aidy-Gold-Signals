"""Generate the Oracle Hub GOLD 83-candidate multi-year AIDY research queue.

Source: immutable 15-Oct owner Drive-sourced repo snapshot; NEVER mistake
historical discovery metadata for latest audit statuses, profits, qualification,
paper-account operation or permission to place broker orders.

This is a work queue, not a backtest engine or a promotion mechanism.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "research/strategy_lab/day33_gold_edge_83_snapshot.json"
DEFAULT_OUTPUT = ROOT / "artifacts/gold_hunter/oracle_hub_research_queue.json"

# Methodology priorities from the owner Drive source-reviewed library, not
# a claim of expected profit. Earlier AIDY audit verdicts remain authoritative.
METHODOLOGY_PRIORITY = ("S040", "S032", "S050", "S052")
EVIDENCE_RECONCILIATION = ("S001", "S002", "S003", "S004", "S005", "S006", "S010")
LIFECYCLE = (
    "DISCOVERED", "SOURCE_AUDITED", "MULTIYEAR_SCREENED",
    "HISTORICALLY_QUALIFIED", "NAMED_PACKAGED",
    "PAPER_READY", "PAPER_MONTH_PASSED",
    "CENT_READY", "CENT_TRIAL_PASSED",
    "ORACLE_HUB_ELIGIBLE", "ORACLE_HUB_APPROVED",
)


def _check(candidates: list) -> None:
    if len(candidates) != 83:
        raise ValueError(f"Expected 83 source leads, found {len(candidates)}")
    ids = [x["id"] for x in candidates]
    if len(set(ids)) != len(ids) or set(ids) != {
        f"S{i:03d}" for i in range(1, 84)
    }:
        raise ValueError("Original 83 IDs missing, duplicated or changed")
    for c in candidates:
        if not isinstance(c.get("title"), str) or not c["title"].strip():
            raise ValueError(f"Missing source description: {c['id']}")
        u = urlparse(c.get("source_url") or "")
        if u.scheme != "https" or not u.netloc:
            raise ValueError(f"Missing original source URI: {c['id']}")


def create_queue(source: Path = DEFAULT_SOURCE) -> dict:
    raw = source.read_bytes()
    snapshot = json.loads(raw)
    if snapshot.get("schema") != "aidy.strategy_lab.gold_edge_frozen_catalogue.v1":
        raise ValueError("Unknown immutable AIDY candidate source schema")
    candidates = snapshot.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("Missing frozen source candidate list")
    _check(candidates)
    queue = []
    for x in candidates:
        ident = x["id"]
        if ident in EVIDENCE_RECONCILIATION:
            work = "RECONCILE_EXISTING_AIDY_SOURCE_VERDICT_FIRST"
        elif ident in METHODOLOGY_PRIORITY:
            work = "AUDIT_PUBLISHED_RULES_AND_RUN_MULTYEAR_REPLAY"
        else:
            work = "SOURCE_AUDIT_THEN_MULTYEAR_REPLAY"
        queue.append({
            "id": ident,
            "original_title": x["title"],
            "method_family_claimed": x.get("family", ""),
            "original_source_url": x["source_url"],
            "metadata_snapshot_date_utc": snapshot.get("frozen_date_utc"),
            "lifecycle": "DISCOVERED",
            "historical_source_status": "NOT_RECONCILED",
            "latest_verified_multiyear_outcome": None,
            "passed_research_gate": False,
            "unique_brand_name": None,
            "forward_paper_account_id": None,
            "real_cent_account_id": None,
            "oracle_hub_admitted": False,
            "priority_work": work,
            "must_check": [
                "original_rules_and_license",
                "pinned_source_commit_and_parity",
                "genuine_multiyear_archives_and_no_lookahead",
                "observed_bid_ask_and_realistic_trading_costs",
                "net_yearly_monthly_drawdown_and_trades",
                "held_out_regime_cost_stress_and_concentration",
                "owner_review_and_version_frozen",
            ],
        })
    queue.sort(key=lambda x: (
        0 if x["priority_work"] == "RECONCILE_EXISTING_AIDY_SOURCE_VERDICT_FIRST"
        else 1 if x["priority_work"] == "AUDIT_PUBLISHED_RULES_AND_RUN_MULTYEAR_REPLAY"
        else 2,
        x["id"],
    ))
    return {
        "schema": "oracle_hub.gold.candidate_research_queue.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_path": source.relative_to(ROOT).as_posix() if source.is_relative_to(ROOT) else str(source),
        "source_metadata_frozen_at_utc": snapshot.get("frozen_date_utc"),
        "all_83_discovery_only_until_latest_evidence_reconciled": True,
        "total": len(queue),
        "prequalified": 0,
        "paper_enabled": 0,
        "cent_enabled": 0,
        "oracle_hub_enabled": 0,
        "original_evidence_audit_candidates": len(EVIDENCE_RECONCILIATION),
        "review_priority_candidates": len(METHODOLOGY_PRIORITY),
        "bot_orders_placed": 0,
        "queue": queue,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = create_queue(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print("ORACLE_HUB_RESEARCH_QUEUE", json.dumps({
        "total": result["total"], "unqualified": result["total"] - result["prequalified"],
        "existing_aidy_evidence_review": result["original_evidence_audit_candidates"],
        "new_methodology_priorities": result["review_priority_candidates"],
        "source_sha256": result["source_sha256"], "output": str(args.output),
        "broker_orders": 0,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
