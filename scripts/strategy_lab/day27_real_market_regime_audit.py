"""Day27: genuine read-only HistData XAUUSD BID M1 regime diagnostic.

Two source-pinned BigQuery reads; 120 fully closed M5, Day26 walk-forward
development predictions only, as-of regimes and insufficient-sample abstention.
No external economic calendar = UNKNOWN; no qualified trading alpha.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aidy.strategy_lab_history_reader import Window, read_bigquery_window
from aidy.strategy_lab_oos_protocol import SealedOOS
from aidy.strategy_lab_regimes import analyze_day26_development_regimes

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "artifacts/strategy_lab/day27_real_market_regime_audit.json"


def audit_source(history) -> dict:
    study = SealedOOS(history)
    audit = analyze_day26_development_regimes(history, study=study)
    result = audit.to_wire()
    if result["evaluated_walkforward_predictions"] != 48:
        raise ValueError("exact registered Day26 fold sizes are not preserved")
    if result["sealed_holdout_decisions_consumed"] != 0:
        raise ValueError("Day27 reopened Day26 sealed holdout")
    for dimension in ("trend", "volatility", "session", "news"):
        found = [r for r in result["breakdowns"] if r["dimension"] == dimension]
        if sum(r["validation_signals"] for r in found) != 48:
            raise ValueError("missing or duplicate as-of regime validation labels")
    news = [r for r in result["breakdowns"] if r["dimension"] == "news"]
    if (len(news) != 1 or news[0]["state"] != "SOURCE_UNAVAILABLE_NO_NEWS_CONCLUSIONS"
            or any(r["model_direction_hit_rate_percent"] is not None for r in news)):
        raise ValueError("unqualified calendar was advertised as news-free data")
    return {
        "status": "PASS",
        "acceptance": "REGIME_ASOF_REAL_HISTDATA_BID_M5_DAY26_DEV_FOLDS",
        "report": result,
        "independent_real_market_strategy_alpha_qualified": False,
        "news_calendar_source_qualified": False,
        "native_broker_fills_and_costs_verified": False,
    }


def main() -> int:
    from google.cloud import bigquery
    from google.oauth2 import service_account

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    try:
        credentials = json.loads(os.environ["AIDY_GCP_SERVICE_ACCOUNT_JSON"])
        client = bigquery.Client(
            project=credentials["project_id"], location="EU",
            credentials=service_account.Credentials.from_service_account_info(credentials),
        )
        first = datetime(2025, 1, 6, 11, tzinfo=UTC)
        end = first + timedelta(minutes=600)
        history, first_job = read_bigquery_window(
            client, Window(first, end, end, 5)
        )
        evidence = audit_source(history)
        replay, second_job = read_bigquery_window(
            client, Window(first, end, end, 5, expected_digest=history.input_digest)
        )
        if replay != history or audit_source(replay) != evidence:
            raise ValueError("real historical source or exact as-of regime replay drift")
        evidence["bigquery_original_job_id"] = first_job
        evidence["bigquery_source_replay_job_id"] = second_job
        evidence["read_only"] = True
    except Exception as exc:  # noqa: BLE001 - an explicit stored BLOCKED state
        evidence = {
            "status": "BLOCKED", "error_type": type(exc).__name__,
            "message": str(exc)[:400],
            "independent_real_market_strategy_alpha_qualified": False,
            "news_calendar_source_qualified": False,
        }
    OUTPUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    print(json.dumps(evidence, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
