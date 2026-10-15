"""Day30 live CI acceptance: ACTUAL PDF, CSV, chart and JSON downloads.

Reuses the complete original Day29 2x read-only BigQuery XAUUSD source
reproduction and emits ALL artefacts under an immutable report run identity.
These are internal synthetic trade/fee results, not a profitable gold system.
"""
from __future__ import annotations

import json
from pathlib import Path

from aidy.strategy_lab_report_exports import build_export_bundle, verify_export_bundle
from scripts.strategy_lab.day29_canonical_report_acceptance import OUT as DAY29_OUT
from scripts.strategy_lab.day29_canonical_report_acceptance import main as day29_main

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/strategy_lab/day30"
RECEIPT = ROOT / "artifacts/strategy_lab/day30_exports_acceptance.json"
EXPECTED_INPUT_SOURCE_SHA = (
    "50d0bc064f9a2dd91f93a38abc3ab9270d1f1f5082c9e85f936d276b5593207b"
)


def main() -> int:
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    try:
        if day29_main() != 0:
            raise ValueError("Day29 real historical source full replay failed")
        original = json.loads(DAY29_OUT.read_text(encoding="utf-8"))
        if (original.get("status") != "PASS"
                or original["report"]["provenance"]["source_sha256"][
                    "day26_real_historical_bid"
                ] != EXPECTED_INPUT_SOURCE_SHA
                or len(original["independent_real_historical_query_job_ids"]) != 2):
            raise ValueError("original source history digest or two queries absent")
        checks = build_export_bundle(original, OUT)
        independently_rechecked = verify_export_bundle(OUT, original)
        if checks != independently_rechecked:
            raise ValueError("independent PDF/CSV/JSON/manifest replay disagrees")
        proof = {
            "status": "PASS",
            "schema": "aidy.strategy_lab.day30.exports_acceptance.v1",
            "source_type": "real_bid_history_plus_separate_synthetic_accounting",
            "source_historical_xauusd_bid_m1_sha256": EXPECTED_INPUT_SOURCE_SHA,
            "real_bigquery_read_only_jobs": original[
                "independent_real_historical_query_job_ids"
            ],
            "output": checks,
            "file_count": len(checks["file_shas"]),
            "real_broker_paper_account_tested": False,
            "named_goldthinker_strategy_created": False,
            "elite20_portfolio_realised_pnl_verified": False,
            "real_strategy_alpha_qualified": False,
            "downloadable_report_files_actually_created": True,
        }
        if (proof["file_count"] != 7
                or checks["verified_complete_trades"] != 4
                or checks["verified_cost_stress_scenarios"] != 3
                or checks["pdf_csv_json_net_profit_usd"] != "13.00"
                or checks["actual_forward_paper_pnl_available"]
                or checks["goldthinker_master_portfolio_pnl_available"]):
            raise ValueError("Day30 source case and scientific assertions differ")
    except Exception as exc:  # noqa: BLE001 - fail closed with on-disk blocker
        proof = {
            "status": "BLOCKED",
            "error_type": type(exc).__name__,
            "message": str(exc)[:400],
            "downloadable_report_files_actually_created": False,
            "real_strategy_alpha_qualified": False,
        }
    RECEIPT.write_text(json.dumps(proof, indent=2, sort_keys=True)+"\n",
                       encoding="utf-8")
    print(json.dumps(proof, sort_keys=True))
    return 0 if proof["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
