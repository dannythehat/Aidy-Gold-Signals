from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aidy.context_packet import compute_context_hash
from aidy.decision_ledger import (
    DECISION_LEDGER_VERSION,
    OUTCOME_ATTACHMENT_VERSION,
    build_ex_ante_evaluation_record,
    build_outcome_attachment,
    build_reproducibility_bundle,
    canonical_json,
    decision_ledger_manifest,
    digest,
    reconcile_ex_ante_record,
    reconcile_outcome_attachment,
    reconstruct_non_secret_decision_bundle,
    verify_ex_ante_record,
    verify_outcome_attachment,
)
from aidy.master_trader_contract import MASTER_TRADER_CONTRACT_VERSION
from aidy.master_trader_contract_v2 import (
    MACHINE_CONDITION_VERSION,
    MASTER_TRADER_CONTRACT_VERSION_V2,
    master_trader_decision_digest_versioned,
)
from aidy.safety_gates import SAFETY_GATES_VERSION, compute_safety_gate_digest
from aidy.setup_detector import SETUP_TAXONOMY_VERSION

BASE_SHA = "6a98243b798762dc2cc90d9e746a91e55c540a92"
DEFAULT_PROJECT = "aidy-signals"
DEFAULT_DATASET = "aidy_analytics_test"
DEFAULT_LOCATION = "EU"
LEDGER_TABLE = "research_day34_decision_ledger"
ATTACHMENT_TABLE = "research_day34_outcome_attachments"
SUMMARY_TABLE = "research_day34_summary"


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="day34_artifacts")
    parser.add_argument("--project", default=os.environ.get("AIDY_GCP_PROJECT_ID", DEFAULT_PROJECT))
    parser.add_argument("--dataset", default=os.environ.get("AIDY_BIGQUERY_DATASET", DEFAULT_DATASET))
    parser.add_argument("--location", default=os.environ.get("AIDY_BIGQUERY_LOCATION", DEFAULT_LOCATION))
    parser.add_argument("--as-of", default="2026-09-01T02:30:00+00:00")
    parser.add_argument("--bigquery", action="store_true")
    return parser.parse_args()


def _context(now: datetime, index: int) -> dict[str, Any]:
    value: dict[str, Any] = {
        "context_packet_version": "aidy_market_context_v7_volatility_state",
        "as_of_utc": (now + timedelta(seconds=index)).isoformat(),
        "symbol": "XAUUSD",
        "objective_only": True,
        "retrospective_history_included": False,
        "broker_follower_state_included": False,
        "source_contract_versions": {
            "pit_query": "aidy_pit_query_v1",
            "gold_features": "aidy_gold_features_v1",
            "analogue_retrieval": "aidy_analogue_retrieval_v2",
            "evidence_grading": "aidy_evidence_report_v2",
        },
        "data_quality": {
            "state": "known",
            "unknown_is_not_absent": True,
            "quote_freshness": "fresh",
            "fixture_index": index,
        },
        "gold": {"quote_context": {"mid": str(2488 + index)}},
    }
    value["context_hash"] = compute_context_hash(value)
    return value


def _gate(stage: str, *, passed: bool, context_hash: str, checked_at: datetime) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "gate_version": SAFETY_GATES_VERSION,
        "stage": stage,
        "status": "passed" if passed else "blocked",
        "context_hash": context_hash,
        "checked_at_utc": checked_at.isoformat(),
        "reason_codes": [f"day34_{stage}_{'allowed' if passed else 'blocked'}"],
        "checks": [{"gate": "day34_fixture", "passed": passed, "reason_code": "day34_fixture"}],
    }
    if stage == "pre_model":
        receipt.update(
            {
                "model_call_allowed": passed,
                "instruction_type": "market_evaluation",
                "max_context_age_seconds": 300,
            }
        )
    else:
        receipt.update(
            {
                "decision_admitted": passed,
                "actionable": False,
                "decision_action": None,
                "downstream_action": None,
            }
        )
    receipt["gate_digest"] = compute_safety_gate_digest(receipt)
    return receipt


def _base_decision(action: str, evaluated_at: datetime) -> dict[str, Any]:
    return {
        "contract_version": MASTER_TRADER_CONTRACT_VERSION,
        "action": action,
        "symbol": "XAUUSD",
        "evaluated_at_utc": evaluated_at.isoformat(),
        "valid_until_utc": (evaluated_at + timedelta(minutes=15)).isoformat(),
        "confidence": 0.74,
        "setup_taxonomy_version": SETUP_TAXONOMY_VERSION,
        "setup_codes": [],
        "reason_codes": ["evidence_supportive"],
        "decision_summary": "Bounded accepted evidence supports this recorded evaluation.",
        "target_decision_id": None,
        "direction": None,
        "entry_type": None,
        "market_reference_price": None,
        "stop_loss": None,
        "targets": [],
        "management_instruction": None,
        "new_stop_loss": None,
        "new_targets": [],
        "close_scope": None,
    }


def _no_trade(evaluated_at: datetime) -> dict[str, Any]:
    value = _base_decision("no_trade", evaluated_at)
    value["reason_codes"] = ["evidence_insufficient"]
    return value


def _new_trade(evaluated_at: datetime) -> dict[str, Any]:
    value = _base_decision("new_trade", evaluated_at)
    value.update(
        {
            "setup_codes": ["trend_pullback_long"],
            "direction": "long",
            "entry_type": "market",
            "market_reference_price": 2492.0,
            "stop_loss": 2480.0,
            "targets": [2504.0, 2516.0],
        }
    )
    return value


def _v2_no_trade(evaluated_at: datetime) -> dict[str, Any]:
    value = _no_trade(evaluated_at)
    value["contract_version"] = MASTER_TRADER_CONTRACT_VERSION_V2
    value.update(
        {
            "thesis": None,
            "expected_horizon_minutes": None,
            "counter_argument": "A clean directional continuation could still emerge after the present uncertainty resolves.",
            "invalidation_condition": None,
            "abstention_basis": "Current evidence does not justify taking directional exposure at this decision time.",
            "shadow_thesis": "A sustained break above the reference zone would support the bullish continuation hypothesis without exposure.",
            "shadow_direction": "long",
            "shadow_horizon_minutes": 120,
            "shadow_evaluation_condition": {
                "condition_version": MACHINE_CONDITION_VERSION,
                "field_path": "$.gold.quote_context.mid",
                "operator": "gte",
                "value_type": "number",
                "value": 2510.0,
            },
        }
    )
    return value


def _repro(context: Mapping[str, Any], *, model_called: bool) -> dict[str, Any]:
    return build_reproducibility_bundle(
        context=context,
        prompt_version="aidy_master_trader_prompt_v1" if model_called else None,
        prompt_digest="a" * 64 if model_called else None,
        gateway_version="aidy_openai_reasoning_gateway_v1" if model_called else None,
        model_id="gpt-5.6-sol" if model_called else None,
        strategy_version="aidy_strategy_config_v1",
        config_version="aidy_runtime_config_v1",
        sampling_metadata={
            "seed_supported": False,
            "seed": None,
            "temperature_supported": False,
            "temperature": None,
        },
        regime_state={"trend_structure": "uptrend", "volatility_band": "normal"},
        setup_state={"candidate_setup_ids": ["trend_pullback_long"]},
        evidence_grade="exploratory",
        effective_n=7,
        evidence_report_digest="b" * 64,
        analogue_retrieval_version="aidy_analogue_retrieval_v2",
        analogue_retrieval_digest="c" * 64,
        analogue_case_ids=["case_20260801", "case_20260714"],
        selective_layer_state=None,
    )


def _gateway(decision: Mapping[str, Any] | None, *, accepted: bool) -> dict[str, Any]:
    return {
        "gateway_version": "aidy_openai_reasoning_gateway_v1",
        "status": "accepted" if accepted else "failed_closed",
        "publication_allowed": accepted,
        "failure_reason": None if accepted else "api_transport_error",
        "structured_decision": None if decision is None else dict(decision),
        "decision_digest": None if decision is None else master_trader_decision_digest_versioned(decision),
        "request_digest": "d" * 64,
        "attempts": 1,
        "latency_ms": 10,
        "response_id": "resp_day34",
        "provider_status": "completed" if accepted else None,
        "provider_model": "gpt-5.6-sol",
        "usage": {"input_tokens": 100, "output_tokens": 50},
        "estimated_cost_usd": "0.001000",
        "pricing_version": "pricing_v1",
        "prompt_version": "aidy_master_trader_prompt_v1",
        "prompt_digest": "a" * 64,
        "model_id": "gpt-5.6-sol",
        "reasoning_effort": "medium",
    }


def _cycle(now: datetime, index: int, disposition: str) -> dict[str, Any]:
    context = _context(now, index)
    evaluated_at = datetime.fromisoformat(str(context["as_of_utc"]))
    pre = _gate(
        "pre_model",
        passed=disposition != "pre_model_blocked",
        context_hash=str(context["context_hash"]),
        checked_at=evaluated_at,
    )
    decision: dict[str, Any] | None = None
    gateway: dict[str, Any] | None = None
    post: dict[str, Any] | None = None
    model_called = disposition != "pre_model_blocked"
    if disposition == "model_failed":
        gateway = _gateway(None, accepted=False)
    elif disposition not in {"pre_model_blocked"}:
        if disposition == "post_model_blocked":
            decision = _v2_no_trade(evaluated_at)
        elif disposition == "no_trade":
            decision = _no_trade(evaluated_at)
        else:
            decision = _new_trade(evaluated_at)
        gateway = _gateway(decision, accepted=True)
        post = _gate(
            "post_model",
            passed=disposition in {"no_trade", "decision_admitted"},
            context_hash=str(context["context_hash"]),
            checked_at=evaluated_at + timedelta(seconds=1),
        )
        post["decision_action"] = decision["action"]
        post["actionable"] = disposition == "decision_admitted"
        post["downstream_action"] = (
            "no_action"
            if disposition == "no_trade"
            else decision["action"]
            if disposition == "decision_admitted"
            else None
        )
        post["gate_digest"] = compute_safety_gate_digest(post)
    return build_ex_ante_evaluation_record(
        context=context,
        instruction_type="market_evaluation",
        cycle_disposition=disposition,
        pre_model_receipt=pre,
        gateway_result=gateway,
        post_model_receipt=post,
        decision=decision,
        reproducibility_bundle=_repro(context, model_called=model_called),
        data_quality_flags=context["data_quality"],
    )


def build_artifacts(now: datetime, head_sha: str) -> dict[str, Any]:
    dispositions = (
        "pre_model_blocked",
        "model_failed",
        "post_model_blocked",
        "no_trade",
        "decision_admitted",
    )
    records = [_cycle(now, index, disposition) for index, disposition in enumerate(dispositions)]
    if not all(verify_ex_ante_record(row) for row in records):
        raise RuntimeError("Day 34 ex-ante record verification failed")
    by_disposition = {str(row["cycle_disposition"]): row for row in records}

    no_trade = by_disposition["no_trade"]
    actionable = by_disposition["decision_admitted"]
    attachments = [
        build_outcome_attachment(
            ex_ante_record=no_trade,
            attachment_type="shadow_outcome",
            attached_at_utc=now + timedelta(hours=3),
            outcome_contract_version="aidy_no_trade_shadow_outcome_v1",
            outcome_identity="day34_shadow_fixture",
            outcome_payload={
                "horizon_minutes": 120,
                "path_class": "up",
                "mfe": "11.4",
                "mae": "3.2",
                "outcome_state": "shadow_hypothesis_supported",
            },
        ),
        build_outcome_attachment(
            ex_ante_record=actionable,
            attachment_type="trade_outcome",
            attached_at_utc=now + timedelta(hours=4),
            outcome_contract_version="aidy_trade_outcome_v1",
            outcome_identity="day34_trade_fixture",
            outcome_payload={
                "horizon_minutes": 240,
                "outcome_state": "target_hit",
                "realized_pnl": "1.0R",
                "mfe": "19.0",
                "mae": "4.0",
            },
        ),
    ]
    if not all(verify_outcome_attachment(row) for row in attachments):
        raise RuntimeError("Day 34 outcome attachment verification failed")

    identical_rerun = reconcile_ex_ante_record(records[0], copy.deepcopy(records[0]))
    if identical_rerun != records[0]:
        raise RuntimeError("Day 34 identical evaluation reconciliation failed")
    mutation_detected = False
    mutated = copy.deepcopy(records[0])
    mutated["data_quality_flags"]["state"] = "mutated"
    mutated.pop("ex_ante_digest")
    mutated["ex_ante_digest"] = digest(mutated)
    try:
        reconcile_ex_ante_record(records[0], mutated)
    except ValueError:
        mutation_detected = True
    if not mutation_detected:
        raise RuntimeError("Day 34 ex-ante mutation was not detected")

    attachment_conflict_detected = False
    changed_attachment = copy.deepcopy(attachments[0])
    changed_attachment["outcome_payload"]["outcome_state"] = "conflicting_result"
    changed_attachment.pop("attachment_digest")
    changed_attachment["attachment_digest"] = digest(changed_attachment)
    try:
        reconcile_outcome_attachment(attachments[0], changed_attachment)
    except ValueError:
        attachment_conflict_detected = True
    if not attachment_conflict_detected:
        raise RuntimeError("Day 34 conflicting attachment was not detected")

    reconstructed = reconstruct_non_secret_decision_bundle(no_trade)
    if reconstructed["context_snapshot"] != no_trade["context_snapshot"]:
        raise RuntimeError("Day 34 reproducibility reconstruction lost context")
    if reconstructed["reproducibility_bundle"] != no_trade["reproducibility_bundle"]:
        raise RuntimeError("Day 34 reproducibility reconstruction lost identities")

    manifest = decision_ledger_manifest()
    experiment_id = f"day34-ledger-{head_sha[:12]}-{manifest['manifest_digest'][:8]}"
    summary: dict[str, Any] = {
        "ok": True,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "experiment_id": experiment_id,
        "ledger_version": DECISION_LEDGER_VERSION,
        "manifest_digest": manifest["manifest_digest"],
        "evaluation_count": len(records),
        "cycle_dispositions": [row["cycle_disposition"] for row in records],
        "all_cycles_first_class": set(dispositions) == {row["cycle_disposition"] for row in records},
        "all_ex_ante_digests_valid": all(verify_ex_ante_record(row) for row in records),
        "stable_decision_id_for_blocked_cycles": all(bool(row["decision_id"]) for row in records),
        "exact_context_snapshot_retained": True,
        "exact_ranked_analogue_ids_retained": no_trade["reproducibility_bundle"]["analogue_case_ids"] == ["case_20260801", "case_20260714"],
        "effective_n_retained": no_trade["reproducibility_bundle"]["effective_n"] == 7,
        "v2_falsifiable_metadata_retained": bool(by_disposition["post_model_blocked"]["falsifiable_thesis"]),
        "identical_evaluation_idempotent": True,
        "ex_ante_mutation_detected": mutation_detected,
        "outcome_attachment_count": len(attachments),
        "outcomes_structurally_separate": all(row["outcome_fields_present"] is False for row in records),
        "outcome_attachments_valid": all(verify_outcome_attachment(row) for row in attachments),
        "conflicting_attachment_detected": attachment_conflict_detected,
        "one_bundle_reconstruction_proven": True,
        "bigquery_write_contract": "insert_only_idempotent_reconciliation",
        "gateway_promoted_by_day34": False,
        "predictive_edge_claimed": False,
        "trading_gate_created": False,
        "accepted_prior_modules_modified": False,
        "super_signals_modified": False,
    }
    summary["summary_digest"] = digest(summary)
    return {
        "records": records,
        "attachments": attachments,
        "reconstructed": reconstructed,
        "manifest": manifest,
        "summary": summary,
    }


def _write(path: Path, value: object) -> None:
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def _expected_records(values: Iterable[tuple[str, Mapping[str, Any]]]) -> dict[str, dict[str, str]]:
    expected: dict[str, dict[str, str]] = {}
    for identity, record in values:
        if identity in expected:
            raise RuntimeError(f"Day 34 duplicate analytical identity: {identity}")
        expected[identity] = {
            "record_digest": digest(record),
            "record_json": canonical_json(record),
        }
    return expected


def _reconcile_existing_records(
    *,
    existing: Iterable[Mapping[str, Any]],
    expected: Mapping[str, Mapping[str, str]],
) -> bool:
    rows = list(existing)
    identities = [str(row["identity"]) for row in rows]
    if len(identities) != len(set(identities)):
        raise RuntimeError("Day 34 BigQuery contains duplicate immutable identities")
    if not rows:
        return False
    if set(identities) != set(expected):
        raise RuntimeError("Day 34 BigQuery immutable identity set drift")
    for row in rows:
        identity = str(row["identity"])
        wanted = expected[identity]
        if str(row["record_digest"]) != wanted["record_digest"]:
            raise RuntimeError(f"Day 34 immutable digest mismatch for {identity}")
        if str(row["record_json"]) != wanted["record_json"]:
            raise RuntimeError(f"Day 34 immutable payload mismatch for {identity}")
    return True


def _persist_bigquery(
    artifacts: Mapping[str, Any],
    *,
    project: str,
    dataset: str,
    location: str,
) -> dict[str, int]:
    from google.cloud import bigquery
    from google.oauth2 import service_account

    raw = os.environ.get("AIDY_GCP_SERVICE_ACCOUNT_JSON")
    credentials = service_account.Credentials.from_service_account_info(json.loads(raw)) if raw else None
    client = bigquery.Client(project=project, credentials=credentials, location=location)
    experiment_id = str(artifacts["summary"]["experiment_id"])
    groups = {
        LEDGER_TABLE: [(str(row["evaluation_id"]), row) for row in artifacts["records"]],
        ATTACHMENT_TABLE: [(str(row["attachment_id"]), row) for row in artifacts["attachments"]],
        SUMMARY_TABLE: [("summary", artifacts["summary"])],
    }
    schema = [
        bigquery.SchemaField("experiment_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("identity", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("recorded_at_utc", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("record_digest", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("record_json", "STRING", mode="REQUIRED"),
    ]
    counts: dict[str, int] = {}
    for table_name, values in groups.items():
        table_id = f"{project}.{dataset}.{table_name}"
        try:
            table = client.get_table(table_id)
            actual = [(field.name, field.field_type, field.mode) for field in table.schema]
            wanted_schema = [(field.name, field.field_type, field.mode) for field in schema]
            if actual != wanted_schema:
                raise RuntimeError(f"Day 34 schema drift for {table_id}")
        except Exception as error:
            if error.__class__.__name__ != "NotFound":
                raise
            table = client.create_table(bigquery.Table(table_id, schema=schema))

        expected = _expected_records(values)
        query = client.query(
            f"SELECT identity, record_digest, record_json FROM `{table_id}` WHERE experiment_id=@experiment_id",
            job_config=bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("experiment_id", "STRING", experiment_id)]
            ),
        )
        existing = [dict(row.items()) for row in query.result()]
        already_present = _reconcile_existing_records(existing=existing, expected=expected)
        if not already_present:
            recorded_at = datetime.now(UTC).isoformat()
            rows = [
                {
                    "experiment_id": experiment_id,
                    "identity": identity,
                    "recorded_at_utc": recorded_at,
                    **payload,
                }
                for identity, payload in sorted(expected.items())
            ]
            errors = client.insert_rows_json(table, rows)
            if errors:
                raise RuntimeError(f"Day 34 BigQuery insert failed: {errors}")
            verify_query = client.query(
                f"SELECT identity, record_digest, record_json FROM `{table_id}` WHERE experiment_id=@experiment_id",
                job_config=bigquery.QueryJobConfig(
                    query_parameters=[bigquery.ScalarQueryParameter("experiment_id", "STRING", experiment_id)]
                ),
            )
            verified = [dict(row.items()) for row in verify_query.result()]
            if not _reconcile_existing_records(existing=verified, expected=expected):
                raise RuntimeError(f"Day 34 BigQuery reconciliation failed for {table_id}")
        counts[table_name] = len(expected)

    ledger_id = f"{project}.{dataset}.{LEDGER_TABLE}"
    target_evaluation = str(artifacts["records"][3]["evaluation_id"])
    one_query = client.query(
        f"SELECT record_json FROM `{ledger_id}` WHERE experiment_id=@experiment_id AND identity=@identity",
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("experiment_id", "STRING", experiment_id),
                bigquery.ScalarQueryParameter("identity", "STRING", target_evaluation),
            ]
        ),
    )
    rows = list(one_query.result())
    if len(rows) != 1:
        raise RuntimeError("Day 34 one-query reproducibility lookup did not return exactly one row")
    restored_record = json.loads(str(rows[0]["record_json"]))
    restored_bundle = reconstruct_non_secret_decision_bundle(restored_record)
    if restored_bundle != artifacts["reconstructed"]:
        raise RuntimeError("Day 34 one-query reproducibility bundle mismatch")
    return counts


def main() -> None:
    args = _args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    as_of = datetime.fromisoformat(args.as_of)
    if as_of.tzinfo is None:
        raise RuntimeError("Day 34 --as-of must be timezone-aware")
    artifacts = build_artifacts(as_of.astimezone(UTC), head_sha)
    if args.bigquery:
        artifacts["summary"]["bigquery_rows"] = _persist_bigquery(
            artifacts,
            project=args.project,
            dataset=args.dataset,
            location=args.location,
        )
        artifacts["summary"].pop("summary_digest")
        artifacts["summary"]["summary_digest"] = digest(artifacts["summary"])
    _write(output / "decision_ledger.json", artifacts["records"])
    _write(output / "outcome_attachments.json", artifacts["attachments"])
    _write(output / "reconstructed_bundle.json", artifacts["reconstructed"])
    _write(output / "ledger_manifest.json", artifacts["manifest"])
    _write(output / "summary.json", artifacts["summary"])
    print(canonical_json(artifacts["summary"]))


if __name__ == "__main__":
    main()
