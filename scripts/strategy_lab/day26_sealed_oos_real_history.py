"""Day26 real XAUUSD History -> M5 walk-forward folds -> sealed OOS audit.

AIDY uses retrospective HistData bid OHLC in BigQuery; this certifies
chronological evaluation discipline, NOT real-market predictive alpha or
broker/TradingView/MetaTrader execution parity.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aidy.strategy_lab_history_reader import ReadResult, Window, read_bigquery_window
from aidy.strategy_lab_oos_protocol import SealedOOS
from aidy.strategy_lab_oos_trial_registry import TrialRegistry

ROOT=Path(__file__).resolve().parents[2]
OUTPUT=ROOT/"artifacts/strategy_lab/day26_sealed_oos_real_history.json"


def audit(history: ReadResult) -> dict:
    study=SealedOOS(history)
    review=study.review_development()
    with tempfile.TemporaryDirectory(prefix="aidy-day26-oos-") as dirname:
        registry=TrialRegistry(Path(dirname)/"trial_ledger.sqlite3")
        register_sha=registry.register(
            trial_key="day26_prior_sign_v1",
            family="prior_mean_sign_lookahead_2_v1",
            study=study,
        )
        try:
            registry.reveal_once("day26_prior_sign_v1",study)
        except ValueError as exc:
            if "frozen" not in str(exc):
                raise
            prefreeze_rejected=True
        else:
            raise ValueError("unsafe unregistered final holdout access")
        freeze_sha=registry.freeze("day26_prior_sign_v1",study)
        # Persist and verify the pre-release chain state as a distinct step.
        before=registry.audit()
        if before["event_count"] != 2 or before["completed_holdout_reveals"]:
            raise ValueError("holdout unexpectedly exposed before freeze")
        result=registry.reveal_once("day26_prior_sign_v1",study)
        try:
            registry.reveal_once("day26_prior_sign_v1",study)
        except ValueError as exc:
            if "unspent" not in str(exc):
                raise
            second_reveal_denied=True
        else:
            raise ValueError("holdout was revealed twice")
        final=registry.audit()
        if final["completed_holdout_reveals"] != 1 or final["event_count"] != 3:
            raise ValueError("unexpected trial event chain")
    return {
        "status":"PASS",
        "schema":"aidy.day26.sealed_walkforward_oos_audit.v1",
        "source_type":"REAL_RETROSPECTIVE_HISTDATA_BID_M1",
        "source_input_sha256":history.input_digest,
        "source_archive_sha256":list(history.source_archive_hashes),
        "native_m1_count":history.native_m1_rows,
        "closed_m5_count":len(history.bars),
        "development":review.wire(),
        "one_time_reveal":result,
        "trial_register_sha256":register_sha,
        "trial_freeze_sha256":freeze_sha,
        "trial_ledger":final,
        "prefreeze_access_denied":prefreeze_rejected,
        "second_holdout_reveal_denied":second_reveal_denied,
        "holdout_is_a_protected_operational_interface_not_raw_data_security":True,
        "real_bid_ask_trade_fills_tested":False,
        "broker_costs_or_alpha_qualified":False,
    }


def main() -> int:
    from google.cloud import bigquery
    from google.oauth2 import service_account

    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    try:
        credential=json.loads(os.environ["AIDY_GCP_SERVICE_ACCOUNT_JSON"])
        client=bigquery.Client(
            project=credential["project_id"],location="EU",
            credentials=service_account.Credentials.from_service_account_info(credential),
        )
        first=datetime(2025,1,6,11,tzinfo=UTC)
        end=first+timedelta(minutes=600)
        history,job_id=read_bigquery_window(client,Window(first,end,end,5))
        proof=audit(history)
        replay,replay_job=read_bigquery_window(
            client,Window(first,end,end,5,expected_digest=history.input_digest)
        )
        if replay!=history:
            raise ValueError("real BigQuery historical source SHA/frozen replay changed")
        proof["first_bigquery_job_id"]=job_id
        proof["replay_bigquery_job_id"]=replay_job
        proof["read_only"]=True
    except Exception as exc:  # noqa: BLE001 - explicit recorded fail-closed status
        proof={"status":"BLOCKED","error_type":type(exc).__name__,
               "message":str(exc)[:400],"broker_costs_or_alpha_qualified":False}
    OUTPUT.write_text(json.dumps(proof,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(proof,sort_keys=True))
    return 0 if proof["status"]=="PASS" else 1


if __name__=="__main__":
    raise SystemExit(main())
