from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aidy.day53_step2_preregistration import (
    COMPARISON_POPULATION,
    PARAMETER_SPACE_DIGEST,
    STEP2_QUALIFICATION_ID,
    STEP2_RESEARCH_FAMILY_ID,
    step2_contract_digest,
)
from aidy.day53_step2_qualification_guard import assert_step2_scoring_prerequisites
from aidy.day53_step2_scoring import (
    QUALIFICATION_SELECTOR_PREFIX,
    RETRIEVAL_SELECTOR_PREFIX,
    SCORER_VERSION,
    structural_preflight_result,
)
from aidy.feature_engine import FEATURE_DEFINITION_VERSION
from aidy.market_data_semantics import (
    QUALIFICATION_RESULT_RECORD_TYPE,
    histdata_semantic_identity,
    twelve_data_semantic_identity,
)
from aidy.research_ledger_anchor import verify_ledger_against_anchor
from aidy.research_trials import (
    build_record,
    canonical_json,
    digest,
    qualification_result_payload,
    trial_started_payload,
    trial_state_payload,
    verify_chain,
)

TRIAL_STARTED_RECORD_TYPE = "trial_started"
TRIAL_STATE_RECORD_TYPE = "trial_state"
GENESIS_DIGEST = "daa8478ee4932bb5fabd83396abc29cdc38fca2e5b913fb78a0e4e2c80458406"
RUN_PROTOCOL_VERSION = "aidy_day53_step2_formal_run_v1"


def _ledger_rows(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for batch in raw:
        rows.extend(batch.get("results") or [])
    normalized: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: int(item["sequence"])):
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        normalized.append(item)
    if not normalized or not verify_chain(normalized):
        raise ValueError("research ledger chain is invalid")
    if normalized[0]["record_digest"] != GENESIS_DIGEST:
        raise ValueError("research ledger genesis digest mismatch")
    return normalized


def _protocol(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    supplied = str(payload.get("run_protocol_digest") or "")
    body = dict(payload)
    body.pop("run_protocol_digest", None)
    if supplied != digest(body):
        raise ValueError("formal run protocol digest mismatch")
    if payload.get("run_protocol_version") != RUN_PROTOCOL_VERSION:
        raise ValueError("unexpected formal run protocol version")
    if payload.get("qualification_id") != STEP2_QUALIFICATION_ID:
        raise ValueError("formal run protocol qualification id mismatch")
    if payload.get("research_family_id") != STEP2_RESEARCH_FAMILY_ID:
        raise ValueError("formal run protocol research family mismatch")
    if payload.get("equivalence_contract_digest_sha256") != step2_contract_digest():
        raise ValueError("formal run protocol contract digest mismatch")
    if payload.get("scorer_version") != SCORER_VERSION:
        raise ValueError("formal run protocol scorer version mismatch")
    interruption = payload.get("interruption_policy")
    if not isinstance(interruption, dict):
        raise ValueError("formal run protocol interruption policy missing")
    required = {
        "policy": "restart_from_zero",
        "resume_partial_scores_allowed": False,
        "next_attempt_requires_new_trial_id": True,
        "next_attempt_recomputes_from_first_observation": True,
    }
    for key, expected in required.items():
        if interruption.get(key) != expected:
            raise ValueError(f"formal run interruption policy drifted: {key}")
    return payload


def _manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("equivalence_contract_digest_sha256") != step2_contract_digest():
        raise ValueError("repository preregistration manifest contract digest mismatch")
    return payload


def _sql_quote(value: object) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def _value_tuple(record: dict[str, Any]) -> str:
    return "(" + ",".join(
        [
            str(record["sequence"]),
            _sql_quote(record["record_digest"]),
            _sql_quote(record["previous_digest"]),
            _sql_quote(record["ledger_version"]),
            _sql_quote(record["record_type"]),
            _sql_quote(record["recorded_at_utc"]),
            _sql_quote(record["code_head_sha"]),
            _sql_quote(record["initiated_by"]),
            _sql_quote(canonical_json(record["payload"])),
        ]
    ) + ")"


def _write_insert(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        path.write_text("-- no-op\n", encoding="utf-8")
        return
    sql = (
        "INSERT INTO research_evidence_ledger "
        "(sequence,record_digest,previous_digest,ledger_version,record_type,"
        "recorded_at_utc,code_head_sha,initiated_by,payload_json) VALUES\n"
        + ",\n".join(_value_tuple(record) for record in records)
        + ";\n"
    )
    path.write_text(sql, encoding="utf-8")


def _now_after(rows: list[dict[str, Any]]) -> datetime:
    now = datetime.now(UTC)
    latest = datetime.fromisoformat(str(rows[-1]["recorded_at_utc"])).astimezone(UTC)
    return max(now, latest)


def _trial_records(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    starts = [
        row
        for row in rows
        if row["record_type"] == TRIAL_STARTED_RECORD_TYPE
        and row["payload"].get("research_family_id") == STEP2_RESEARCH_FAMILY_ID
    ]
    terminals = {
        str(row["payload"].get("trial_id")): row
        for row in rows
        if row["record_type"] == TRIAL_STATE_RECORD_TYPE
        and row["payload"].get("research_family_id") == STEP2_RESEARCH_FAMILY_ID
        and row["payload"].get("state") in {"completed", "failed", "aborted"}
    }
    return starts, terminals


def _qualification_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row["record_type"] == QUALIFICATION_RESULT_RECORD_TYPE
        and row["payload"].get("qualification_id") == STEP2_QUALIFICATION_ID
        and row["payload"].get("contract_digest") == step2_contract_digest()
    ]


def _run_digests(protocol: dict[str, Any]) -> dict[str, str]:
    protocol_digest = str(protocol["run_protocol_digest"])
    semantic_pair = {
        "histdata": histdata_semantic_identity()["semantic_identity_digest"],
        "twelve_data": twelve_data_semantic_identity()["semantic_identity_digest"],
    }
    return {
        "configuration_digest": digest(
            {
                "parameter_space_digest": PARAMETER_SPACE_DIGEST,
                "scorer_version": SCORER_VERSION,
                "run_protocol_digest": protocol_digest,
            }
        ),
        "dataset_boundary_digest": digest(
            {
                "comparison_population": COMPARISON_POPULATION,
                "qualification_selector_prefix": QUALIFICATION_SELECTOR_PREFIX,
                "retrieval_selector_prefix": RETRIEVAL_SELECTOR_PREFIX,
                "candidate_universe_loading": "deferred_until_structural_preflight_nonterminal",
            }
        ),
        "feature_definition_digest": digest(
            {
                "feature_definition_version": FEATURE_DEFINITION_VERSION,
                "target_feature": "H1_ATR_14_bps",
                "source_native_construction_before_pairing": True,
            }
        ),
        "label_definition_digest": digest(
            {
                "qualification_outcomes": ["pass", "fail", "insufficient_evidence"],
                "decision_rule": "logical_conjunction_all_mandatory_criteria",
            }
        ),
        "validation_contract_digest": protocol_digest,
        "cost_model_digest": digest(
            {"cost_model": "not_applicable_equivalence_qualification_no_pnl"}
        ),
        "market_data_semantic_identity_digest": digest(semantic_pair),
    }


def _verify_prerequisites(
    *, rows: list[dict[str, Any]], manifest: dict[str, Any], anchor: dict[str, Any]
) -> dict[str, Any]:
    verify_ledger_against_anchor(rows, anchor=anchor)
    return assert_step2_scoring_prerequisites(
        manifest=manifest,
        research_ledger_records=rows,
    )


def prepare_start(
    *,
    ledger_path: Path,
    manifest_path: Path,
    protocol_path: Path,
    anchor_path: Path,
    accepted_head: str,
    sql_path: Path,
    audit_path: Path,
) -> None:
    rows = _ledger_rows(ledger_path)
    manifest = _manifest(manifest_path)
    protocol = _protocol(protocol_path)
    anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    guard = _verify_prerequisites(rows=rows, manifest=manifest, anchor=anchor)

    existing_results = _qualification_results(rows)
    if len(existing_results) > 1:
        raise ValueError("duplicate Step 2 qualification results exist")
    if existing_results:
        _write_insert(sql_path, [])
        audit = {
            "action": "final_result_already_present",
            "ledger_head_sequence": rows[-1]["sequence"],
            "ledger_head_digest": rows[-1]["record_digest"],
            "raw_attempted_trials": sum(
                row["record_type"] == TRIAL_STARTED_RECORD_TYPE for row in rows
            ),
            "twelve_data_vendor_calls": 0,
            "market_values_inspected": False,
        }
        audit_path.write_text(json.dumps(audit, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(audit, sort_keys=True))
        return

    starts, terminals = _trial_records(rows)
    records: list[dict[str, Any]] = []
    latest = rows[-1]
    now = _now_after(rows)
    open_trials = [row for row in starts if str(row["payload"]["trial_id"]) not in terminals]
    if len(open_trials) > 1:
        raise ValueError("multiple open Step 2 trials violate restart-from-zero policy")
    if open_trials:
        old = open_trials[0]
        abort_payload = trial_state_payload(
            trial_id=str(old["payload"]["trial_id"]),
            research_family_id=STEP2_RESEARCH_FAMILY_ID,
            state="aborted",
            result_digest=None,
            reason="restart_from_zero_after_interrupted_attempt",
        )
        aborted = build_record(
            sequence=int(latest["sequence"]) + 1,
            previous_digest=str(latest["record_digest"]),
            record_type=TRIAL_STATE_RECORD_TYPE,
            recorded_at=now,
            code_head_sha=accepted_head,
            initiated_by="scheduled_system",
            payload=abort_payload,
        )
        records.append(aborted)
        latest = aborted
        now += timedelta(seconds=1)

    attempt = len(starts) + 1
    trial_id = f"day53-step2-equivalence-attempt-{attempt:03d}"
    digests = _run_digests(protocol)
    started_payload = trial_started_payload(
        trial_id=trial_id,
        research_family_id=STEP2_RESEARCH_FAMILY_ID,
        parent_trial_id=None,
        selection_origin="preregistered_explicit",
        parameter_space_digest=PARAMETER_SPACE_DIGEST,
        configuration_digest=digests["configuration_digest"],
        dataset_boundary_digest=digests["dataset_boundary_digest"],
        feature_definition_digest=digests["feature_definition_digest"],
        label_definition_digest=digests["label_definition_digest"],
        validation_contract_digest=digests["validation_contract_digest"],
        cost_model_digest=digests["cost_model_digest"],
        market_data_semantic_identity_digest=digests["market_data_semantic_identity_digest"],
    )
    started = build_record(
        sequence=int(latest["sequence"]) + 1,
        previous_digest=str(latest["record_digest"]),
        record_type=TRIAL_STARTED_RECORD_TYPE,
        recorded_at=now,
        code_head_sha=accepted_head,
        initiated_by="human",
        payload=started_payload,
    )
    records.append(started)
    _write_insert(sql_path, records)
    audit = {
        "action": "append_new_trial_start",
        "accepted_formal_run_head": accepted_head,
        "trial_id": trial_id,
        "attempt_number": attempt,
        "run_protocol_digest": protocol["run_protocol_digest"],
        "pre_append_guard": guard,
        "records": records,
        "restart_from_zero_policy": protocol["interruption_policy"],
        "market_values_inspected": False,
        "empirical_scoring_performed": False,
        "twelve_data_vendor_calls": 0,
    }
    audit_path.write_text(json.dumps(audit, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, sort_keys=True))


def prepare_result(
    *,
    ledger_path: Path,
    manifest_path: Path,
    protocol_path: Path,
    anchor_path: Path,
    accepted_head: str,
    sql_path: Path,
    result_path: Path,
) -> None:
    rows = _ledger_rows(ledger_path)
    manifest = _manifest(manifest_path)
    protocol = _protocol(protocol_path)
    anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    _verify_prerequisites(rows=rows, manifest=manifest, anchor=anchor)

    existing_results = _qualification_results(rows)
    if len(existing_results) > 1:
        raise ValueError("duplicate Step 2 qualification results exist")
    structural = structural_preflight_result()
    if structural.get("terminal") is not True:
        raise ValueError("formal run expected a terminal structural preflight")
    if structural.get("outcome") != "insufficient_evidence":
        raise ValueError("structural preflight terminal outcome drifted")
    evidence = structural["evidence"]
    if (
        evidence.get("market_values_inspected") is not False
        or evidence.get("empirical_scoring_performed") is not False
    ):
        raise ValueError("structural preflight illegally inspected market values")

    if existing_results:
        existing = existing_results[0]
        if existing["payload"].get("evidence_digest") != structural["evidence_digest"]:
            raise ValueError("existing qualification result evidence digest mismatch")
        _write_insert(sql_path, [])
        output = {
            "action": "verified_existing_final_result",
            "qualification_result_record": existing,
            "result": structural,
            "ledger_head_sequence": rows[-1]["sequence"],
            "ledger_head_digest": rows[-1]["record_digest"],
            "twelve_data_vendor_calls": 0,
        }
        result_path.write_text(
            json.dumps(output, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(output, sort_keys=True))
        return

    starts, terminals = _trial_records(rows)
    open_trials = [row for row in starts if str(row["payload"]["trial_id"]) not in terminals]
    if len(open_trials) != 1:
        raise ValueError("formal result requires exactly one open Step 2 trial")
    started = open_trials[0]
    if started["code_head_sha"] != accepted_head:
        raise ValueError("open Step 2 trial is bound to the wrong formal-run code head")
    if started["payload"].get("validation_contract_digest") != protocol["run_protocol_digest"]:
        raise ValueError("open Step 2 trial run-protocol digest mismatch")

    latest = rows[-1]
    now = _now_after(rows)
    completed_payload = trial_state_payload(
        trial_id=str(started["payload"]["trial_id"]),
        research_family_id=STEP2_RESEARCH_FAMILY_ID,
        state="completed",
        result_digest=str(structural["result_digest"]),
        reason="terminal_structural_preflight_before_market_value_loading",
    )
    completed = build_record(
        sequence=int(latest["sequence"]) + 1,
        previous_digest=str(latest["record_digest"]),
        record_type=TRIAL_STATE_RECORD_TYPE,
        recorded_at=now,
        code_head_sha=accepted_head,
        initiated_by="scheduled_system",
        payload=completed_payload,
    )
    qualification_payload = qualification_result_payload(
        qualification_id=STEP2_QUALIFICATION_ID,
        contract_digest=step2_contract_digest(),
        outcome="insufficient_evidence",
        evidence_digest=str(structural["evidence_digest"]),
    )
    qualification = build_record(
        sequence=int(completed["sequence"]) + 1,
        previous_digest=str(completed["record_digest"]),
        record_type=QUALIFICATION_RESULT_RECORD_TYPE,
        recorded_at=now + timedelta(seconds=1),
        code_head_sha=accepted_head,
        initiated_by="scheduled_system",
        payload=qualification_payload,
    )
    records = [completed, qualification]
    _write_insert(sql_path, records)
    output = {
        "action": "append_terminal_structural_result",
        "accepted_formal_run_head": accepted_head,
        "trial_id": started["payload"]["trial_id"],
        "run_protocol_digest": protocol["run_protocol_digest"],
        "records": records,
        "result": structural,
        "market_values_inspected": False,
        "candidate_universe_loaded": False,
        "empirical_scoring_performed": False,
        "twelve_data_vendor_calls": 0,
    }
    result_path.write_text(json.dumps(output, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, sort_keys=True))


def verify_final(
    *,
    ledger_path: Path,
    manifest_path: Path,
    protocol_path: Path,
    anchor_path: Path,
    accepted_head: str,
    output_path: Path,
) -> None:
    rows = _ledger_rows(ledger_path)
    manifest = _manifest(manifest_path)
    protocol = _protocol(protocol_path)
    anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    _verify_prerequisites(rows=rows, manifest=manifest, anchor=anchor)

    results = _qualification_results(rows)
    if len(results) != 1:
        raise ValueError("final verification requires exactly one Step 2 qualification result")
    structural = structural_preflight_result()
    result_record = results[0]
    if result_record["payload"].get("outcome") != "insufficient_evidence":
        raise ValueError("final Step 2 outcome is not the frozen structural result")
    if result_record["payload"].get("evidence_digest") != structural["evidence_digest"]:
        raise ValueError("final Step 2 evidence digest mismatch")
    if result_record["payload"].get("inheritance_allowed") is not False:
        raise ValueError("INSUFFICIENT Step 2 result cannot allow inheritance")
    starts, terminals = _trial_records(rows)
    completed = [
        terminal
        for terminal in terminals.values()
        if terminal["payload"].get("state") == "completed"
    ]
    if len(starts) < 1 or len(completed) != 1:
        raise ValueError("final Step 2 ledger must contain one completed formal attempt")
    output = {
        "state": "step2_formal_result_verified",
        "accepted_formal_run_head": accepted_head,
        "run_protocol_digest": protocol["run_protocol_digest"],
        "outcome": "insufficient_evidence",
        "inheritance_allowed": False,
        "cross_source_retrieval_permission": False,
        "structural_capacity": structural["evidence"][
            "structural_retrieval_session_capacity"
        ],
        "result_evidence_digest": structural["evidence_digest"],
        "result_digest": structural["result_digest"],
        "qualification_result_sequence": result_record["sequence"],
        "qualification_result_record_digest": result_record["record_digest"],
        "ledger_head_sequence": rows[-1]["sequence"],
        "ledger_head_digest": rows[-1]["record_digest"],
        "raw_attempted_trials": len(starts),
        "market_values_inspected": False,
        "candidate_universe_loaded": False,
        "empirical_scoring_performed": False,
        "twelve_data_vendor_calls": 0,
    }
    output_path.write_text(json.dumps(output, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare-start", "prepare-result", "verify-final"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--ledger", type=Path, required=True)
        cmd.add_argument("--manifest", type=Path, required=True)
        cmd.add_argument("--protocol", type=Path, required=True)
        cmd.add_argument("--anchor", type=Path, required=True)
        cmd.add_argument("--accepted-head", required=True)
        if name == "prepare-start":
            cmd.add_argument("--sql", type=Path, required=True)
            cmd.add_argument("--audit", type=Path, required=True)
        elif name == "prepare-result":
            cmd.add_argument("--sql", type=Path, required=True)
            cmd.add_argument("--result", type=Path, required=True)
        else:
            cmd.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    common = {
        "ledger_path": args.ledger,
        "manifest_path": args.manifest,
        "protocol_path": args.protocol,
        "anchor_path": args.anchor,
        "accepted_head": args.accepted_head,
    }
    if args.command == "prepare-start":
        prepare_start(**common, sql_path=args.sql, audit_path=args.audit)
    elif args.command == "prepare-result":
        prepare_result(**common, sql_path=args.sql, result_path=args.result)
    else:
        verify_final(**common, output_path=args.output)


if __name__ == "__main__":
    main()
