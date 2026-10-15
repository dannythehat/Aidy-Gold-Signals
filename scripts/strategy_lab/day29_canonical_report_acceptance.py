"""Day29 executable reporting acceptance: source-bound canonical research result.

Read-only real BID historical XAUUSD is independent from the synthetic Day24
trade ledger and Day25 bidask quote demo. It is NEVER treated as a GoldThinker
live/paper account or a customer system with proven profits.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aidy.strategy_lab_history_reader import Window, read_bigquery_window
from aidy.strategy_lab_report_contract import build_canonical_report, verify_canonical_report
from scripts.strategy_lab.day24_ledger_metrics_acceptance import OUT as DAY24_RECEIPT
from scripts.strategy_lab.day25_baselines_cost_stress_acceptance import audit as day25_audit
from scripts.strategy_lab.day28_evidence_rating_acceptance import audit_source as day28_audit

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/strategy_lab/day29_canonical_auditable_result.json"
AS_OF = "2026-10-01T11:04:00Z"


def audit_source(history) -> dict:
    evidence = day28_audit(history)
    if evidence.get("status") != "PASS":
        raise ValueError("upstream real-source nine-factor evidence failed")
    journal = json.loads(DAY24_RECEIPT.read_text(encoding="utf-8"))
    cost = day25_audit()
    if cost.get("status") != "PASS":
        raise ValueError("source-verified cost scenarios failed")
    report = build_canonical_report(journal, cost, evidence, as_of_utc=AS_OF)
    verify_canonical_report(report)
    if (report["research"]["accounting"]["net_profit_usd"] != "13.00"
            or report["research"]["accounting"]["final_cash_usd"] != "10013.00"
            or report["research"]["periods"]["day"]["realised_net_pnl_usd"] != "9.00"
            or report["research"]["periods"]["week"]["realised_net_pnl_usd"] != "13.00"
            or report["research"]["periods"]["month"]["realised_net_pnl_usd"] != "9.00"
            or report["research"]["periods"]["year"]["realised_net_pnl_usd"] != "13.00"
            or report["research"]["periods"]["all_time"]["realised_net_pnl_usd"] != "13.00"
            or report["research"]["evidence_rating"]["score_out_of_100"] is not None
            or report["production"]["paper"]["forward_paper_pnl"] is not None
            or report["production"]["elite20"]["portfolio_pnl"] is not None
            or report["identity"]["customer_can_connect"]
            or len(report["research"]["trades"]) != 4
            or len(report["research"]["cost_stress"]) != 3):
        raise ValueError("Day29 original ledger/period/qualification acceptance changed")
    return report


def main() -> int:
    from google.cloud import bigquery
    from google.oauth2 import service_account

    OUT.parent.mkdir(parents=True, exist_ok=True)
    try:
        credentials = json.loads(os.environ["AIDY_GCP_SERVICE_ACCOUNT_JSON"])
        client = bigquery.Client(
            project=credentials["project_id"], location="EU",
            credentials=service_account.Credentials.from_service_account_info(credentials),
        )
        first = datetime(2025, 1, 6, 11, tzinfo=UTC)
        end = first + timedelta(minutes=600)
        history, first_job = read_bigquery_window(client, Window(first, end, end, 5))
        report = audit_source(history)
        replay, second_job = read_bigquery_window(
            client, Window(first, end, end, 5, expected_digest=history.input_digest)
        )
        if replay != history or audit_source(replay) != report:
            raise ValueError("Day29 original BigQuery source or report result drifted")
        proof = {
            "status": "PASS",
            "scope": "CANONICAL_AIDY_REPORT_REPLAY_NOT_GOLDTHINKER_PRODUCTION",
            "report": report,
            "independent_real_historical_query_job_ids": [first_job, second_job],
            "read_only": True,
            "future_goldthinker_named_strategy_unlocked": False,
            "paper_and_live_performance_qualified": False,
        }
    except Exception as exc:  # noqa: BLE001 - archive blocker instead of fake success
        proof = {
            "status": "BLOCKED", "error_type": type(exc).__name__,
            "message": str(exc)[:400], "paper_and_live_performance_qualified": False,
        }
    OUT.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(json.dumps({
        "status": proof["status"],
        "scope": proof.get("scope"),
        "run_id": proof.get("report", {}).get("run_id"),
        "result_sha256": proof.get("report", {}).get("canonical_result_sha256"),
        "source_job_ids": proof.get("independent_real_historical_query_job_ids"),
        "message": proof.get("message"),
    }, sort_keys=True))
    return 0 if proof["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
