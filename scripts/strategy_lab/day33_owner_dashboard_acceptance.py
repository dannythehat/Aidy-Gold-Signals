"""Day33 real owner-only dashboard acceptance.

Replays Day32 100-job synthetic scheduling twice, calls actual Day29 read-only
XAUUSD source evidence pipeline twice, and reconciles the ORIGINAL frozen
83-row Google Drive candidate snapshot. No public site or billing.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from aidy.strategy_lab_owner_dashboard import (
    build_snapshot,\n    export_dashboard,\n    verify_snapshot,
)
from scripts.strategy_lab.day29_canonical_report_acceptance import (
    OUT as DAY29_OUT,
)
from scripts.strategy_lab.day29_canonical_report_acceptance import main as day29_main
from scripts.strategy_lab.day32_100_job_acceptance import exercise

ROOT = Path(__file__).resolve().parents[2]
CATALOGUE = ROOT/"research/strategy_lab/day33_gold_edge_83_snapshot.json"
OUT = ROOT/"artifacts/strategy_lab/day33"
ACCEPT = ROOT/"artifacts/strategy_lab/day33_owner_dashboard_acceptance.json"


def produce_source(catalogue: dict, original: dict, directory: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="aidy-d33-") as temp:
        a, values = exercise(Path(temp)/"first_queue.sqlite")
        b, repeated = exercise(Path(temp)/"second_queue.sqlite")
    if a != b or values != repeated:
        raise ValueError("queue cannot independently reproduce 100 identical jobs")
    snapshot = build_snapshot(catalogue, values, a, original)
    verify_snapshot(snapshot)
    return export_dashboard(snapshot, directory)


def main() -> int:
    ACCEPT.parent.mkdir(parents=True, exist_ok=True)
    try:
        if day29_main() != 0:
            raise ValueError("real BigQuery read-only and source-checked research failed")
        original = json.loads(DAY29_OUT.read_text(encoding="utf-8"))
        catalogue = json.loads(CATALOGUE.read_text(encoding="utf-8"))
        manifest = produce_source(catalogue, original, OUT)
        snapshot = json.loads((OUT/"owner_dashboard_data.json").read_text())
        verify_snapshot(snapshot)
        page = (OUT/"owner_research_dashboard.html").read_text(encoding="utf-8")
        if (len(snapshot["candidates"]) != 83
                or len(snapshot["batch"]["experiments"]) != 100
                or snapshot["counts"]["independently_qualified_strategies"] != 0
                or "S001" not in page or "S083" not in page
                or "100" not in page or "GoldThinker" not in page
                or "NOT TESTED" not in page
                or len(manifest["files"]) != 2
                or original["report"]["research"]["evidence_rating"][
                    "score_out_of_100"
                ] is not None):
            raise ValueError("owner UI missing real source rows or invented evidence")
        proof = {
            "status": "PASS",
            "schema": "aidy.strategy_lab.day33.owner_dashboard_acceptance.v1",
            "owner_only_offline_html_created": True,
            "original_drive_candidate_count": 83,
            "source_drive_live_sync": False,
            "independent_xauusd_real_bid_original_read_jobs":
                original["independent_real_historical_query_job_ids"],
            "original_day29_source_sha256":
                original["report"]["canonical_result_sha256"],
            "original_day32_result_sha256":
                snapshot["batch"]["result_source_sha256"],
            "gold_edge_source_snapshot_sha256":
                snapshot["catalogue_source"]["snapshot_sha256"],
            "independently_replayed_synthetic_queue_results": 100,
            "unqualified_nine_factor_scores_promoted": 0,
            "real_gold_strategy_profits_demonstrated": 0,
            "customer_paper_accounts_created": 0,
            "customer_website_published": False,
            "no_billing": True,
            "dashboard_snapshot_sha256": snapshot["snapshot_sha256"],
            "manifest": manifest,
        }
    except Exception as exc:  # noqa: BLE001 - archive blocker, never false PASS
        proof = {
            "status": "BLOCKED", "error_type": type(exc).__name__,
            "message": str(exc)[:400], "customer_website_published": False,
        }
    ACCEPT.write_text(json.dumps(proof, indent=2, sort_keys=True)+"\n",
                      encoding="utf-8")
    print(json.dumps(proof, sort_keys=True))
    return 0 if proof["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
