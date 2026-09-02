from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aidy.day53_step2_preregistration import STEP2_QUALIFICATION_ID, step2_contract_digest
from aidy.day53_step2_scoring import structural_preflight_result
from aidy.market_data_semantics import QUALIFICATION_RESULT_RECORD_TYPE
from aidy.research_trials import build_record, canonical_json, verify_chain

AUDIT_RECORD_TYPE = "qualification_structural_audit"
AUDIT_VERSION = "aidy_day53_step2_structural_audit_v1"
GENESIS_DIGEST = "daa8478ee4932bb5fabd83396abc29cdc38fca2e5b913fb78a0e4e2c80458406"


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


def _qualification_result(rows: list[dict[str, Any]]) -> dict[str, Any]:
    matches = [
        row
        for row in rows
        if row["record_type"] == QUALIFICATION_RESULT_RECORD_TYPE
        and row["payload"].get("qualification_id") == STEP2_QUALIFICATION_ID
        and row["payload"].get("contract_digest") == step2_contract_digest()
    ]
    if len(matches) != 1:
        raise ValueError("structural audit requires exactly one Step 2 qualification result")
    return matches[0]


def _audit_payload(result_record: dict[str, Any]) -> dict[str, Any]:
    structural = structural_preflight_result()
    if structural.get("terminal") is not True or structural.get("outcome") != "insufficient_evidence":
        raise ValueError("Step 2 structural preflight is not terminal insufficient evidence")
    if result_record["payload"].get("outcome") != "insufficient_evidence":
        raise ValueError("qualification result outcome does not match structural preflight")
    if result_record["payload"].get("evidence_digest") != structural["evidence_digest"]:
        raise ValueError("qualification result evidence digest does not match structural proof")
    if result_record["payload"].get("inheritance_allowed") is not False:
        raise ValueError("insufficient Step 2 result cannot allow inheritance")

    capacity = structural["evidence"]["structural_retrieval_session_capacity"]
    exact = capacity["exact_session_label_upper_bounds"]
    required = capacity["registered_minimum_session_query_count_each"]
    blockers = capacity["structural_blockers"]
    if blockers.get("london") != {"maximum_possible": 48, "required": 50}:
        raise ValueError("frozen London structural blocker changed")
    if blockers.get("new_york") != {"maximum_possible": 44, "required": 50}:
        raise ValueError("frozen New York structural blocker changed")

    return {
        "audit_version": AUDIT_VERSION,
        "qualification_id": STEP2_QUALIFICATION_ID,
        "contract_digest": step2_contract_digest(),
        "qualification_result_sequence": int(result_record["sequence"]),
        "qualification_result_record_digest": result_record["record_digest"],
        "qualification_result_outcome": "insufficient_evidence",
        "qualification_evidence_digest": structural["evidence_digest"],
        "structural_proof": {
            "basis": "every_frozen_utc_hour_pairable_upper_bound_before_market_value_loading",
            "nested_selector_timestamp_count": int(capacity["nested_selector_timestamp_count"]),
            "exact_session_label_upper_bounds": {
                "asia": int(exact["asia"]),
                "london": int(exact["london"]),
                "new_york": int(exact["new_york"]),
            },
            "registered_minimum_session_query_count_each": {
                "asia": int(required["asia"]),
                "london": int(required["london"]),
                "new_york": int(required["new_york"]),
            },
            "structural_blockers": blockers,
            "proof_logic": (
                "real source-native completeness can only remove pairable timestamps from this "
                "upper bound and therefore cannot raise London above 48 or New York above 44"
            ),
        },
        "execution_decision": {
            "market_value_execution_skipped": True,
            "skip_is_consequence_not_cause": True,
            "primary_outcome_cause": "registered_coverage_shortfall_structurally_proven",
            "bounded_achievable_sample_scored": False,
            "reason_not_scored": (
                "scores from a non-qualifying achievable sample cannot change the registered "
                "outcome and would expose target performance to any successor experiment design"
            ),
            "successor_information_state_preserved": "no_market_values_observed",
            "api_credit_cost_used_as_outcome_basis": False,
        },
        "candidate_universe_loaded": False,
        "market_values_inspected": False,
        "empirical_scoring_performed": False,
        "twelve_data_vendor_calls": 0,
        "inheritance_allowed": False,
        "cross_source_retrieval_permission": False,
    }


def prepare(*, ledger_path: Path, accepted_head: str, sql_path: Path, output_path: Path) -> None:
    rows = _ledger_rows(ledger_path)
    result_record = _qualification_result(rows)
    payload = _audit_payload(result_record)
    existing = [
        row
        for row in rows
        if row["record_type"] == AUDIT_RECORD_TYPE
        and row["payload"].get("qualification_id") == STEP2_QUALIFICATION_ID
    ]
    if len(existing) > 1:
        raise ValueError("duplicate Step 2 structural audit records exist")
    if existing:
        if existing[0]["payload"] != payload:
            raise ValueError("existing structural audit record differs from frozen proof")
        _write_insert(sql_path, [])
        output = {
            "action": "verified_existing_structural_audit",
            "audit_record": existing[0],
            "ledger_head_sequence": int(rows[-1]["sequence"]),
            "ledger_head_digest": rows[-1]["record_digest"],
        }
    else:
        latest = rows[-1]
        record = build_record(
            sequence=int(latest["sequence"]) + 1,
            previous_digest=str(latest["record_digest"]),
            record_type=AUDIT_RECORD_TYPE,
            recorded_at=_now_after(rows),
            code_head_sha=accepted_head,
            initiated_by="scheduled_system",
            payload=payload,
        )
        _write_insert(sql_path, [record])
        output = {
            "action": "append_structural_audit",
            "audit_record": record,
            "ledger_head_sequence_before": int(latest["sequence"]),
            "ledger_head_digest_before": latest["record_digest"],
        }
    output_path.write_text(json.dumps(output, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, sort_keys=True))


def verify(*, ledger_path: Path, accepted_head: str, output_path: Path) -> None:
    rows = _ledger_rows(ledger_path)
    result_record = _qualification_result(rows)
    expected_payload = _audit_payload(result_record)
    audits = [
        row
        for row in rows
        if row["record_type"] == AUDIT_RECORD_TYPE
        and row["payload"].get("qualification_id") == STEP2_QUALIFICATION_ID
    ]
    if len(audits) != 1:
        raise ValueError("final ledger requires exactly one Step 2 structural audit record")
    audit = audits[0]
    if audit["payload"] != expected_payload:
        raise ValueError("final structural audit payload mismatch")
    if audit["code_head_sha"] != accepted_head:
        raise ValueError("structural audit is bound to the wrong formal-run code head")
    output = {
        "state": "step2_structural_audit_verified",
        "qualification_result_sequence": int(result_record["sequence"]),
        "qualification_result_record_digest": result_record["record_digest"],
        "audit_sequence": int(audit["sequence"]),
        "audit_record_digest": audit["record_digest"],
        "ledger_head_sequence": int(rows[-1]["sequence"]),
        "ledger_head_digest": rows[-1]["record_digest"],
        "structural_proof": expected_payload["structural_proof"],
        "execution_decision": expected_payload["execution_decision"],
        "market_values_inspected": False,
        "twelve_data_vendor_calls": 0,
    }
    output_path.write_text(json.dumps(output, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "verify"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--ledger", type=Path, required=True)
        cmd.add_argument("--accepted-head", required=True)
        cmd.add_argument("--output", type=Path, required=True)
        if name == "prepare":
            cmd.add_argument("--sql", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(
            ledger_path=args.ledger,
            accepted_head=args.accepted_head,
            sql_path=args.sql,
            output_path=args.output,
        )
    else:
        verify(
            ledger_path=args.ledger,
            accepted_head=args.accepted_head,
            output_path=args.output,
        )


if __name__ == "__main__":
    main()
