from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Literal, TypedDict

ATTESTATION_VERSION = "aidy_pit_field_attestation_v1"
ATTESTATION_MANIFEST_VERSION = "aidy_pit_attestation_manifest_v1"
LEAK_AUDIT_VERSION = "aidy_deliberate_leak_audit_v1"
TRIAL_REGISTRY_VERSION = "aidy_experiment_trial_registry_v1"

PITState = Literal["true", "false", "partial"]
RESULT_STATES = {"preregistered", "passed", "null", "insufficient", "failed"}
BLOCKING_LEAK_CATEGORIES = {
    "revision_after_decision",
    "overwritten_vendor_file",
    "publication_lag",
    "missing_historical_release_timestamp",
    "retrospective_before_first_observation",
    "timezone_date_dst_ambiguity",
    "future_outcome_in_decision",
    "unknown_converted_to_absent",
    "context_hash_coverage_gap",
    "attestation_contract_mismatch",
}


class FieldPolicy(TypedDict):
    field_contract: str
    contract_version: str
    source: str
    evidence_family: str
    provenance_class: str
    pit_reconstructable: PITState
    reconstruction_method: str
    reconstruction_version: str
    retrospective_eligible: bool
    evaluation_eligible: bool
    decision_input_eligible: bool
    staleness_rule: str


class IntegrityError(ValueError):
    pass


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str, *, name: str) -> str:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise IntegrityError(f"{name} must be timezone-aware")
    return parsed.astimezone(UTC).isoformat()


def _leaf_paths(value: object, prefix: str = "$") -> list[str]:
    if isinstance(value, Mapping):
        paths: list[str] = []
        for key in sorted(value, key=str):
            path = f"{prefix}.{key}"
            paths.extend(_leaf_paths(value[key], path))
        return paths or [prefix]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        paths = []
        for index, item in enumerate(value):
            paths.extend(_leaf_paths(item, f"{prefix}[{index}]"))
        return paths or [prefix]
    return [prefix]


def _policy_for(path: str, policies: Mapping[str, FieldPolicy]) -> FieldPolicy:
    matches = [
        (prefix, policy)
        for prefix, policy in policies.items()
        if path == prefix or path.startswith((prefix + ".", prefix + "["))
    ]
    if not matches:
        raise IntegrityError(f"active model-facing field lacks a policy: {path}")
    return max(matches, key=lambda item: len(item[0]))[1]


def build_field_attestation_manifest(
    packet: Mapping[str, Any],
    *,
    policies: Mapping[str, FieldPolicy],
    observed_at: datetime | str,
    published_at: datetime | str | None,
    first_observed_at: datetime | str,
    staleness_state: str,
    quality_state: str,
) -> dict[str, Any]:
    if not packet or "context_hash" not in packet:
        raise IntegrityError("a hashed model-facing context packet is required")
    observation = _utc(observed_at, name="observed_at")
    first_observed = _utc(first_observed_at, name="first_observed_at")
    publication = _utc(published_at, name="published_at") if published_at else None
    if first_observed < observation:
        raise IntegrityError("first_observed_at cannot precede observation timestamp")
    rows: list[dict[str, Any]] = []
    for path in _leaf_paths(packet):
        if path == "$.context_hash":
            continue
        policy = dict(_policy_for(path, policies))
        pit_state = policy["pit_reconstructable"]
        if pit_state not in {"true", "false", "partial"}:
            raise IntegrityError(f"invalid PIT state for {path}")
        if policy["decision_input_eligible"] and pit_state != "true":
            raise IntegrityError(f"false/partial PIT field cannot be decision eligible: {path}")
        row: dict[str, Any] = {
            "attestation_version": ATTESTATION_VERSION,
            "field_identity": f"{policy['field_contract']}:{path}",
            "json_path": path,
            **policy,
            "observation_timestamp": observation,
            "publication_timestamp": publication,
            "first_observed_timestamp": first_observed,
            "staleness_state": staleness_state,
            "quality_state": quality_state,
            "context_hash_covered": True,
            "context_hash": str(packet["context_hash"]),
        }
        row["attestation_digest"] = digest(row)
        rows.append(row)
    identities = [row["field_identity"] for row in rows]
    if len(identities) != len(set(identities)):
        raise IntegrityError("duplicate field identity")
    manifest: dict[str, Any] = {
        "manifest_version": ATTESTATION_MANIFEST_VERSION,
        "context_hash": str(packet["context_hash"]),
        "active_field_count": len(rows),
        "attestations": rows,
    }
    manifest["manifest_digest"] = digest(manifest)
    return manifest


def verify_field_attestation_manifest(manifest: Mapping[str, Any]) -> bool:
    try:
        body = dict(manifest)
        supplied = str(body.pop("manifest_digest", ""))
        rows = list(body["attestations"])
        if supplied != digest(body) or body["manifest_version"] != ATTESTATION_MANIFEST_VERSION:
            return False
        if body["active_field_count"] != len(rows) or not rows:
            return False
        identities = set()
        for raw in rows:
            row = dict(raw)
            row_digest = str(row.pop("attestation_digest", ""))
            if row_digest != digest(row) or row["attestation_version"] != ATTESTATION_VERSION:
                return False
            if row["context_hash"] != body["context_hash"] or row["context_hash_covered"] is not True:
                return False
            if row["decision_input_eligible"] and row["pit_reconstructable"] != "true":
                return False
            if row["field_identity"] in identities:
                return False
            identities.add(row["field_identity"])
        return True
    except (KeyError, TypeError, ValueError):
        return False


def build_leak_finding(
    *,
    field_identity: str,
    category: str,
    detected_at: datetime | str,
    evidence: Mapping[str, Any],
    resolved: bool = False,
) -> dict[str, Any]:
    if category not in BLOCKING_LEAK_CATEGORIES:
        raise IntegrityError(f"unknown leak category: {category}")
    finding: dict[str, Any] = {
        "audit_version": LEAK_AUDIT_VERSION,
        "field_identity": field_identity,
        "category": category,
        "severity": "blocking",
        "detected_at": _utc(detected_at, name="detected_at"),
        "resolved": resolved,
        "evidence": dict(evidence),
    }
    finding["finding_digest"] = digest(finding)
    return finding


def audit_decision_eligibility(manifest: Mapping[str, Any], findings: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    if not verify_field_attestation_manifest(manifest):
        raise IntegrityError("invalid attestation manifest")
    verified: list[dict[str, Any]] = []
    unresolved = 0
    for raw in findings:
        finding = dict(raw)
        supplied = str(finding.pop("finding_digest", ""))
        if supplied != digest(finding) or finding.get("audit_version") != LEAK_AUDIT_VERSION:
            raise IntegrityError("invalid leak finding digest or version")
        finding["finding_digest"] = supplied
        unresolved += int(finding.get("severity") == "blocking" and finding.get("resolved") is not True)
        verified.append(finding)
    result: dict[str, Any] = {
        "audit_version": LEAK_AUDIT_VERSION,
        "manifest_digest": manifest["manifest_digest"],
        "finding_count": len(verified),
        "unresolved_blocking_count": unresolved,
        "decision_input_allowed": unresolved == 0,
        "findings": verified,
    }
    result["audit_digest"] = digest(result)
    return result


def preregister_trial(
    prior_records: Sequence[Mapping[str, Any]],
    *,
    trial_number: int,
    hypothesis: str,
    null_hypothesis: str,
    dataset_version: str,
    feature_context_version: str,
    frozen_parameters: Mapping[str, Any],
    chronological_split: Mapping[str, Any],
    purge: str,
    embargo: str,
    evaluation_identity: str,
    holdout_identity: str,
    preregistered_at: datetime | str,
    code_head: str,
    evidence_digest: str,
    purpose: Literal["tuning", "evaluation"],
) -> dict[str, Any]:
    verify_trial_registry(prior_records)
    expected = len(prior_records) + 1
    if trial_number != expected:
        raise IntegrityError(f"trial number must be monotonic: expected {expected}")
    if not hypothesis.strip() or not null_hypothesis.strip():
        raise IntegrityError("hypothesis and null hypothesis are required")
    for previous in prior_records:
        if previous["holdout_identity"] == holdout_identity and purpose == "tuning":
            raise IntegrityError("holdout reuse for tuning is forbidden")
    record: dict[str, Any] = {
        "registry_version": TRIAL_REGISTRY_VERSION,
        "trial_number": trial_number,
        "trial_identity": f"trial-{trial_number:06d}",
        "hypothesis": hypothesis,
        "null_hypothesis": null_hypothesis,
        "dataset_version": dataset_version,
        "feature_context_version": feature_context_version,
        "frozen_parameters": dict(frozen_parameters),
        "chronological_split": dict(chronological_split),
        "purge": purge,
        "embargo": embargo,
        "evaluation_identity": evaluation_identity,
        "holdout_identity": holdout_identity,
        "preregistered_at": _utc(preregistered_at, name="preregistered_at"),
        "executed_at": None,
        "purpose": purpose,
        "result_state": "preregistered",
        "result": None,
        "code_head": code_head,
        "evidence_digest": evidence_digest,
        "previous_trial_digest": prior_records[-1]["trial_digest"] if prior_records else None,
    }
    record["trial_digest"] = digest(record)
    return record


def finalize_trial(record: Mapping[str, Any], *, executed_at: datetime | str, result_state: str, result: Mapping[str, Any]) -> dict[str, Any]:
    if not verify_trial_record(record) or record["result_state"] != "preregistered":
        raise IntegrityError("only a valid preregistered trial can be finalized")
    executed = _utc(executed_at, name="executed_at")
    if executed < str(record["preregistered_at"]):
        raise IntegrityError("trial execution cannot precede preregistration")
    if result_state not in RESULT_STATES - {"preregistered"}:
        raise IntegrityError("invalid terminal trial result")
    final = dict(record)
    final.pop("trial_digest")
    final["executed_at"] = executed
    final["result_state"] = result_state
    final["result"] = dict(result)
    final["preregistration_digest"] = record["trial_digest"]
    final["trial_digest"] = digest(final)
    return final


def verify_trial_record(record: Mapping[str, Any]) -> bool:
    try:
        body = dict(record)
        supplied = str(body.pop("trial_digest", ""))
        return bool(supplied) and supplied == digest(body) and record["registry_version"] == TRIAL_REGISTRY_VERSION and record["result_state"] in RESULT_STATES
    except (KeyError, TypeError, ValueError):
        return False


def verify_trial_registry(records: Sequence[Mapping[str, Any]]) -> bool:
    previous = None
    holdouts: set[str] = set()
    for index, record in enumerate(records, start=1):
        if not verify_trial_record(record) or record["trial_number"] != index:
            if records:
                raise IntegrityError("trial registry is non-monotonic or mutated")
            return True
        if record["previous_trial_digest"] != previous:
            raise IntegrityError("trial digest chain is broken")
        if record["purpose"] == "tuning" and record["holdout_identity"] in holdouts:
            raise IntegrityError("holdout reuse for tuning is forbidden")
        holdouts.add(str(record["holdout_identity"]))
        previous = record["trial_digest"]
    return True
