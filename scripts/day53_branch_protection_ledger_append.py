from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aidy.research_trials import build_record, canonical_json, verify_chain

RECORD_TYPE = "repository_branch_protection_enabled"
ATTESTATION_VERSION = "aidy_github_main_ruleset_attestation_v1"
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


def _write_insert(path: Path, record: dict[str, Any] | None) -> None:
    if record is None:
        path.write_text("-- no-op\n", encoding="utf-8")
        return
    values = [
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
    sql = (
        "INSERT INTO research_evidence_ledger "
        "(sequence,record_digest,previous_digest,ledger_version,record_type,recorded_at_utc,"
        "code_head_sha,initiated_by,payload_json) VALUES (" + ",".join(values) + ");\n"
    )
    path.write_text(sql, encoding="utf-8")


def _attestation(path: Path) -> tuple[dict[str, Any], str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    supplied = str(value.pop("attestation_digest", ""))
    calculated = hashlib.sha256(canonical_json(value).encode()).hexdigest()
    if supplied != calculated:
        raise ValueError("branch-protection attestation digest mismatch")
    if value.get("attestation_version") != ATTESTATION_VERSION:
        raise ValueError("unexpected branch-protection attestation version")
    required_checks = value.get("required_status_checks")
    if required_checks != [
        "Evidence Semantic Change Gate / classify-protected-diff",
        "AIDY Day 53 Twelve Data OHLC Adapter / acceptance",
    ]:
        raise ValueError("required status-check set changed")
    if value.get("default_branch") != "main" or value.get("enforcement") != "active":
        raise ValueError("main protection is not attested active")
    if value.get("target_condition") != {"include": ["~DEFAULT_BRANCH"], "exclude": []}:
        raise ValueError("ruleset does not target only the default branch selector")
    if value.get("required_pull_request") != {"enabled": True, "required_approving_review_count": 0}:
        raise ValueError("pull-request rule differs from registered governance state")
    if value.get("restrict_deletions") is not True:
        raise ValueError("deletion protection missing")
    if value.get("block_force_pushes_non_fast_forward") is not True:
        raise ValueError("non-fast-forward protection missing")
    if value.get("bypass_actors") != [] or value.get("current_user_can_bypass") != "never":
        raise ValueError("branch-protection bypass exists")
    if value.get("observed_before_pr60_merge") is not True or value.get("pr60_merged_at_observation") is not False:
        raise ValueError("pre-merge ordering attestation missing")
    return value, supplied


def _payload(attestation: dict[str, Any], attestation_digest: str) -> dict[str, Any]:
    return {
        "governance_event_version": "aidy_repository_protection_event_v1",
        "event": "main_branch_protection_enabled",
        "repository": attestation["repository"],
        "default_branch": attestation["default_branch"],
        "ruleset_id": attestation["ruleset_id"],
        "ruleset_name": attestation["ruleset_name"],
        "enforcement": attestation["enforcement"],
        "target_condition": attestation["target_condition"],
        "required_pull_request": attestation["required_pull_request"],
        "required_status_checks": attestation["required_status_checks"],
        "strict_required_status_checks_policy": attestation["strict_required_status_checks_policy"],
        "restrict_deletions": attestation["restrict_deletions"],
        "block_force_pushes_non_fast_forward": attestation["block_force_pushes_non_fast_forward"],
        "bypass_actors": attestation["bypass_actors"],
        "current_user_can_bypass": attestation["current_user_can_bypass"],
        "github_ruleset_enabled_at": attestation["github_ruleset_created_at"],
        "github_ruleset_updated_at": attestation["github_ruleset_updated_at"],
        "github_observed_source": attestation["github_observed_source"],
        "observed_before_pr60_merge": True,
        "pr60_merged_at_observation": False,
        "attestation_digest": attestation_digest,
    }


def prepare(*, ledger: Path, attestation_path: Path, accepted_head: str, sql: Path, output: Path) -> None:
    rows = _ledger_rows(ledger)
    attestation, attestation_digest = _attestation(attestation_path)
    payload = _payload(attestation, attestation_digest)
    matches = [
        row
        for row in rows
        if row["record_type"] == RECORD_TYPE
        and row["payload"].get("ruleset_id") == attestation["ruleset_id"]
    ]
    if len(matches) > 1:
        raise ValueError("duplicate branch-protection governance records")
    if matches:
        if matches[0]["payload"] != payload:
            raise ValueError("existing branch-protection record differs from attestation")
        _write_insert(sql, None)
        record = matches[0]
        action = "verified_existing"
    else:
        latest = rows[-1]
        recorded_at = max(
            datetime.now(UTC),
            datetime.fromisoformat(str(latest["recorded_at_utc"])).astimezone(UTC),
        )
        record = build_record(
            sequence=int(latest["sequence"]) + 1,
            previous_digest=str(latest["record_digest"]),
            record_type=RECORD_TYPE,
            recorded_at=recorded_at,
            code_head_sha=accepted_head,
            initiated_by="scheduled_system",
            payload=payload,
        )
        _write_insert(sql, record)
        action = "append"
    output.write_text(
        json.dumps({"action": action, "record": record}, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def verify(*, ledger: Path, attestation_path: Path, output: Path) -> None:
    rows = _ledger_rows(ledger)
    attestation, attestation_digest = _attestation(attestation_path)
    expected = _payload(attestation, attestation_digest)
    matches = [
        row
        for row in rows
        if row["record_type"] == RECORD_TYPE
        and row["payload"].get("ruleset_id") == attestation["ruleset_id"]
    ]
    if len(matches) != 1 or matches[0]["payload"] != expected:
        raise ValueError("branch-protection governance record verification failed")
    result = {
        "state": "main_branch_protection_ledgered",
        "record_sequence": int(matches[0]["sequence"]),
        "record_digest": matches[0]["record_digest"],
        "ledger_head_sequence": int(rows[-1]["sequence"]),
        "ledger_head_digest": rows[-1]["record_digest"],
        "attestation_digest": attestation_digest,
    }
    output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "verify"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--ledger", type=Path, required=True)
        cmd.add_argument("--attestation", type=Path, required=True)
        cmd.add_argument("--output", type=Path, required=True)
        if name == "prepare":
            cmd.add_argument("--accepted-head", required=True)
            cmd.add_argument("--sql", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(
            ledger=args.ledger,
            attestation_path=args.attestation,
            accepted_head=args.accepted_head,
            sql=args.sql,
            output=args.output,
        )
    else:
        verify(ledger=args.ledger, attestation_path=args.attestation, output=args.output)


if __name__ == "__main__":
    main()
