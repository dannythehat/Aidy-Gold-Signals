"""Day34 acceptance: safely withhold the 83 UNTESTED candidate handoffs.

The original Gold Edge source register contains ZERO qualified strategies.
Re-run Day33 (real read-only historical source twice, 100 synthetic queue jobs)
and export an owner/Claude handoff packet containing ZERO invented winners.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from aidy.strategy_lab_goldthinker_handoff import check_handoff, prepare_private_handoff
from scripts.strategy_lab.day33_owner_dashboard_acceptance import (
    ACCEPT as DAY33_ACCEPT,
)
from scripts.strategy_lab.day33_owner_dashboard_acceptance import (
    OUT as DAY33_OUT,
)
from scripts.strategy_lab.day33_owner_dashboard_acceptance import main as day33_main

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/strategy_lab/day34"
SUMMARY = ROOT / "artifacts/strategy_lab/day34_handoff_acceptance.json"


def audit_sources(day33: dict, dashboard: dict, owner_key: bytes) -> dict:
    if (day33.get("status") != "PASS"
            or day33.get("original_drive_candidate_count") != 83
            or day33.get("independently_replayed_synthetic_queue_results") != 100
            or day33.get("real_gold_strategy_profits_demonstrated") != 0
            or day33.get("unqualified_nine_factor_scores_promoted") != 0
            or dashboard["counts"]["candidate_backlog"] != 83
            or dashboard["counts"]["independently_qualified_strategies"] != 0
            or dashboard["counts"]["actual_paper_accounts"] != 0
            or dashboard["batch"]["not_mapped_to_gold_edge_candidate_ids"] is not True
            or dashboard["research_reference"]["nine_factor_score"] is not None
            or dashboard["research_reference"]["elite20_profit"] is not None):
        raise ValueError("Day33 verified owner sources cannot establish real strategy pass")
    excluded = []
    for source in dashboard["candidates"]:
        if (source["research_stage"] != "NOT TESTED"
                or source["aidy_score_100"] is not None
                or source["paper_net_pnl_usd"] is not None
                or source["join_available"] is not False):
            raise ValueError("candidate was prematurely passed from original source")
        excluded.append({
            "strategy_id": source["id"],
            "status": "NOT_TESTED_IN_AIDY",
            "goldthinker_paper_handoff": False,
            "blockers": source["blockers"],
        })
    # Crucial: no 83-source mining, optimisation, execution or strategy backtest.
    packet = prepare_private_handoff([], owner_key)
    check_handoff(packet)
    if packet["candidate_count"] or not packet["no_broker_or_customer_side_effects"]:
        raise ValueError("unqualified candidate escaped into GoldThinker")
    return {
        "packet": packet,
        "excluded_source_candidates": excluded,
        "source_snapshot_sha256":
            dashboard["catalogue_source"]["snapshot_sha256"],
        "owner_dashboard_sha256": dashboard["snapshot_sha256"],
        "real_xauusd_source_hash":
            dashboard["research_reference"]["day29_input_source_sha256"],
        "separate_synthetic_queue_sha256":
            dashboard["batch"]["result_source_sha256"],
    }


def main() -> int:
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    try:
        if day33_main() != 0:
            raise ValueError("actual source-connected Day33 acceptance failed")
        day33 = json.loads(DAY33_ACCEPT.read_text(encoding="utf-8"))
        snapshot = json.loads((DAY33_OUT/"owner_dashboard_data.json").read_text(
            encoding="utf-8"
        ))
        key = os.urandom(32)
        checked = audit_sources(day33, snapshot, key)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT/"handoff_for_separate_owner_and_claude_review.json").write_text(
            json.dumps(checked["packet"], indent=2, sort_keys=True)+"\n",
            encoding="utf-8",
        )
        (OUT/"source_candidate_blockers.json").write_text(
            json.dumps(checked["excluded_source_candidates"],
                       indent=2, sort_keys=True)+"\n", encoding="utf-8",
        )
        (OUT/"review_checkpoint.md").write_text(
            "# Day34 GoldThinker handoff review checkpoint\n\n"
            "**NO REAL SYSTEMS HAVE QUALIFIED FOR HANDOFF.**\n\n"
            "All 83 Gold Edge candidates remain untested pending completion of "
            "the 40-day lab. The completed 100 synthetic jobs are merely "
            "research-queue engineering diagnostics.\n\n"
            "AIDY research evidence must later prove realistic bid/ask costs, "
            "fair benchmarks, chronological OOS, signed internal research "
            "source records, original strategy permissions and all nine factors.\n\n"
            "If independently qualified, AIDY may **propose** a candidate for "
            "separate Claude and owner review. That proposal CANNOT "
            "create a paper account or trade, publish, name, enrol customers, "
            "or place a strategy into GoldThinker Elite20.\n\n"
            "Owner review: NOT PERFORMED — no eligible candidates.\n"
            "Claude review: NOT PERFORMED — no eligible candidates.\n"
            "Paper production: NOT STARTED.\n"
            "Portfolio access: NOT AUTHORISED.\n",
            encoding="utf-8",
        )
        proof = {
            "status": "PASS",
            "scope": "DAY34_PRIVATE_FAIL_CLOSED_HANDOFF_POLICY_NOT_TRADING",
            "owner_and_claude_separate_review_required": True,
            "original_untested_gold_edge_sources": len(
                checked["excluded_source_candidates"]
            ),
            "real_qualifying_strategy_exports": checked["packet"]["candidate_count"],
            "real_systems_tested_for_profit": 0,
            "synthetic_queue_diagnostics_not_a_strategy_backtest": 100,
            "source_snapshot_sha256": checked["source_snapshot_sha256"],
            "owner_dashboard_sha256": checked["owner_dashboard_sha256"],
            "real_historical_bid_source_sha256": checked["real_xauusd_source_hash"],
            "unrelated_synthetic_queue_source_sha256":
                checked["separate_synthetic_queue_sha256"],
            "original_handoff_packet_sha256": checked["packet"]["packet_sha256"],
            "source_bigquery_job_ids":
                day33["independent_xauusd_real_bid_original_read_jobs"],
            "customer_join_live_trading_and_paper_execution_disabled": True,
            "owner_review_automatic_approval": False,
            "issuer_credential_was_not_persisted": True,
        }
    except Exception as exc:  # noqa: BLE001 - archived original blocker
        proof = {
            "status": "BLOCKED", "error_type": type(exc).__name__,
            "message": str(exc)[:400],
            "customer_join_live_trading_and_paper_execution_disabled": True,
        }
    SUMMARY.write_text(json.dumps(proof, indent=2, sort_keys=True)+"\n",
                       encoding="utf-8")
    print(json.dumps(proof, sort_keys=True))
    return 0 if proof["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
