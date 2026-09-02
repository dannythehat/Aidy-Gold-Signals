from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aidy.day53_step2_preregistration import (
    STEP2_QUALIFICATION_ID,
    STEP2_RESEARCH_FAMILY_ID,
    build_step2_equivalence_contract_payload,
    build_step2_research_family_payload,
)
from aidy.day53_step2_qualification_guard import (
    assert_repository_preregistration_manifest,
    assert_step2_scoring_prerequisites,
)
from aidy.market_data_semantics import EQUIVALENCE_CONTRACT_RECORD_TYPE
from aidy.research_trials import build_record, canonical_json, verify_chain

FAMILY_RECORD_TYPE = "research_family_registered"
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


def _matches(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    families = [
        row
        for row in rows
        if row["record_type"] == FAMILY_RECORD_TYPE
        and row["payload"].get("research_family_id") == STEP2_RESEARCH_FAMILY_ID
    ]
    contracts = [
        row
        for row in rows
        if row["record_type"] == EQUIVALENCE_CONTRACT_RECORD_TYPE
        and row["payload"].get("qualification_id") == STEP2_QUALIFICATION_ID
    ]
    return families, contracts


def _sql_quote(value: object) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def prepare(*, ledger_path: Path, manifest_path: Path, accepted_head: str, sql_path: Path, audit_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    repository = assert_repository_preregistration_manifest(manifest)
    rows = _ledger_rows(ledger_path)
    families, contracts = _matches(rows)

    if bool(families) != bool(contracts):
        raise ValueError("partial Step 2 preregistration exists in D1; refusing repair by guess")
    if len(families) > 1 or len(contracts) > 1:
        raise ValueError("duplicate Step 2 preregistration records exist in D1")

    prepared_records: list[dict[str, Any]] = []
    if families:
        for record in (families[0], contracts[0]):
            if record["code_head_sha"] != accepted_head:
                raise ValueError("existing Step 2 preregistration is bound to the wrong code head")
        guard = assert_step2_scoring_prerequisites(
            manifest=manifest,
            research_ledger_records=rows,
        )
        sql_path.write_text("-- exact Step 2 preregistration already present; no-op\n", encoding="utf-8")
        action = "verified_existing_exact_records"
    else:
        latest = rows[-1]
        now = datetime.now(UTC)
        latest_time = datetime.fromisoformat(str(latest["recorded_at_utc"]))
        if now < latest_time:
            now = latest_time
        family = build_record(
            sequence=int(latest["sequence"]) + 1,
            previous_digest=str(latest["record_digest"]),
            record_type=FAMILY_RECORD_TYPE,
            recorded_at=now,
            code_head_sha=accepted_head,
            initiated_by="human",
            payload=build_step2_research_family_payload(),
        )
        contract = build_record(
            sequence=int(family["sequence"]) + 1,
            previous_digest=str(family["record_digest"]),
            record_type=EQUIVALENCE_CONTRACT_RECORD_TYPE,
            recorded_at=now + timedelta(seconds=1),
            code_head_sha=accepted_head,
            initiated_by="human",
            payload=build_step2_equivalence_contract_payload(),
        )
        prepared_records = [family, contract]
        statements = ["BEGIN TRANSACTION;"]
        for record in prepared_records:
            statements.append(
                "INSERT INTO research_evidence_ledger "
                "(sequence,record_digest,previous_digest,ledger_version,record_type,"
                "recorded_at_utc,code_head_sha,initiated_by,payload_json) VALUES ("
                + ",".join(
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
                )
                + ");"
            )
        statements.append("COMMIT;")
        sql_path.write_text("\n".join(statements) + "\n", encoding="utf-8")
        guard = {
            "state": "prepared_exact_append",
            "contract_digest": repository["contract_digest"],
            "research_family_digest": repository["research_family_digest"],
        }
        action = "append_exact_records"

    audit = {
        "action": action,
        "accepted_step2_head": accepted_head,
        "repository_contract_digest": repository["contract_digest"],
        "repository_research_family_digest": repository["research_family_digest"],
        "ledger_sequence_before": int(rows[-1]["sequence"]),
        "ledger_head_digest_before": rows[-1]["record_digest"],
        "prepared_records": prepared_records,
        "pre_append_guard_state": guard,
        "empirical_scoring_performed": False,
        "twelve_data_vendor_calls": 0,
    }
    audit_path.write_text(json.dumps(audit, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, sort_keys=True))


def verify(*, ledger_path: Path, manifest_path: Path, accepted_head: str, output_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = _ledger_rows(ledger_path)
    guard = assert_step2_scoring_prerequisites(
        manifest=manifest,
        research_ledger_records=rows,
    )
    families, contracts = _matches(rows)
    if len(families) != 1 or len(contracts) != 1:
        raise ValueError("Step 2 D1 verification requires exactly one family and contract record")
    family, contract = families[0], contracts[0]
    if family["code_head_sha"] != accepted_head or contract["code_head_sha"] != accepted_head:
        raise ValueError("Step 2 D1 records are not bound to the accepted scientific head")
    raw_trials = sum(1 for row in rows if row["record_type"] == "trial_started")
    result = {
        "state": "step2_d1_preregistration_verified",
        "accepted_step2_head": accepted_head,
        "research_family_sequence": int(family["sequence"]),
        "research_family_record_digest": family["record_digest"],
        "equivalence_contract_sequence": int(contract["sequence"]),
        "equivalence_contract_record_digest": contract["record_digest"],
        "contract_digest": guard["contract_digest"],
        "research_family_digest": guard["research_family_digest"],
        "ledger_head_sequence": int(rows[-1]["sequence"]),
        "ledger_head_digest": rows[-1]["record_digest"],
        "raw_attempted_trials": raw_trials,
        "empirical_scoring_performed": False,
        "twelve_data_vendor_calls": 0,
    }
    output_path.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "verify"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--ledger", type=Path, required=True)
        cmd.add_argument("--manifest", type=Path, required=True)
        cmd.add_argument("--accepted-head", required=True)
        if name == "prepare":
            cmd.add_argument("--sql", type=Path, required=True)
            cmd.add_argument("--audit", type=Path, required=True)
        else:
            cmd.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(
            ledger_path=args.ledger,
            manifest_path=args.manifest,
            accepted_head=args.accepted_head,
            sql_path=args.sql,
            audit_path=args.audit,
        )
    else:
        verify(
            ledger_path=args.ledger,
            manifest_path=args.manifest,
            accepted_head=args.accepted_head,
            output_path=args.output,
        )


if __name__ == "__main__":
    main()
