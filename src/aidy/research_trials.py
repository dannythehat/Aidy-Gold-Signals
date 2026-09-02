"""Append-only research-governance and trial-ledger contracts.

Step 0 exists to make empirical search observable before any Twelve Data
requalification begins. Records are content-addressed, code-head-bound and
hash-chained. Persistence adapters may append only.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

LEDGER_VERSION = "aidy_research_ledger_v1"
NO_EDGE_RULE = (
    "AIDY is permitted to conclude that no actionable edge exists. "
    "No research, qualification, accumulation or promotion rule may be changed "
    "solely because the evidence is approaching or has reached an unfavourable conclusion."
)

INITIATORS = {"human", "agent", "scheduled_system", "registered_search_engine"}
SELECTION_ORIGINS = {
    "preregistered_explicit",
    "preregistered_enumerated",
    "adaptive_algorithm_registered_ex_ante",
    "post_result_human",
    "post_result_agent",
    "post_result_unknown",
}
MECHANICAL_ORIGINS = {
    "preregistered_enumerated",
    "adaptive_algorithm_registered_ex_ante",
}
TRIAL_STATES = {"started", "completed", "failed", "aborted"}
QUALIFICATION_OUTCOMES = {"pass", "fail", "insufficient_evidence"}


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Research-ledger timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _sha(value: object, *, field: str) -> str:
    text = str(value or "")
    if len(text) != 40 or any(ch not in "0123456789abcdef" for ch in text.lower()):
        raise ValueError(f"{field} must be a 40-character git SHA.")
    return text.lower()


def _digest64(value: object, *, field: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text.lower()):
        raise ValueError(f"{field} must be a 64-character SHA-256 digest.")
    return text.lower()


def build_record(
    *,
    sequence: int,
    previous_digest: str | None,
    record_type: str,
    recorded_at: datetime | str,
    code_head_sha: str,
    initiated_by: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    if sequence < 0:
        raise ValueError("Ledger sequence cannot be negative.")
    if sequence == 0 and previous_digest is not None:
        raise ValueError("Genesis record cannot have a previous digest.")
    if sequence > 0:
        _digest64(previous_digest, field="previous_digest")
    if initiated_by not in INITIATORS:
        raise ValueError("Unknown research-ledger initiator.")
    if not record_type.strip():
        raise ValueError("record_type is required.")
    body: dict[str, Any] = {
        "ledger_version": LEDGER_VERSION,
        "sequence": int(sequence),
        "previous_digest": previous_digest,
        "record_type": record_type.strip(),
        "recorded_at_utc": _utc(recorded_at).isoformat(),
        "code_head_sha": _sha(code_head_sha, field="code_head_sha"),
        "initiated_by": initiated_by,
        "payload": dict(payload),
    }
    body["record_digest"] = digest(body)
    return body


def verify_record(record: Mapping[str, Any]) -> bool:
    body = dict(record)
    supplied = str(body.pop("record_digest", ""))
    if not supplied or supplied != digest(body):
        return False
    if body.get("ledger_version") != LEDGER_VERSION:
        return False
    try:
        sequence = int(body["sequence"])
        previous = body.get("previous_digest")
        if sequence == 0 and previous is not None:
            return False
        if sequence > 0:
            _digest64(previous, field="previous_digest")
        _utc(str(body["recorded_at_utc"]))
        _sha(body["code_head_sha"], field="code_head_sha")
    except (KeyError, TypeError, ValueError):
        return False
    return body.get("initiated_by") in INITIATORS


def verify_chain(records: Iterable[Mapping[str, Any]]) -> bool:
    previous: str | None = None
    previous_time: datetime | None = None
    count = 0
    for expected_sequence, value in enumerate(records):
        record = dict(value)
        if not verify_record(record):
            return False
        if int(record["sequence"]) != expected_sequence:
            return False
        if record.get("previous_digest") != previous:
            return False
        observed = _utc(str(record["recorded_at_utc"]))
        if previous_time is not None and observed < previous_time:
            return False
        previous = str(record["record_digest"])
        previous_time = observed
        count += 1
    return count > 0


def governance_genesis_payload() -> dict[str, Any]:
    return {
        "governance_version": "aidy_research_governance_v1",
        "no_edge_rule": NO_EDGE_RULE,
        "permitted_final_states": [
            "positive_edge",
            "no_economically_useful_edge",
            "harm",
            "insufficient_evidence",
        ],
        "mutation_policy": {
            "update_allowed": False,
            "delete_allowed": False,
            "amendment_requires_new_record": True,
            "amendment_must_reference_superseded_digest": True,
        },
        "selection_policy": {
            "mechanical_origin_requires_ex_ante_parameter_space_proof": True,
            "unknown_origin_defaults_to": "post_result_unknown",
            "agent_self_report_is_not_proof": True,
        },
        "trial_count_policy": {
            "raw_attempted_trials_can_decrease": False,
            "effective_trial_count_requires_preregistered_versioned_method": True,
            "reports_must_expose_raw_and_effective_counts": True,
        },
        "qualification_policy": {
            "default_state": "insufficient_evidence",
            "fail_allows_inheritance": False,
            "insufficient_evidence_allows_inheritance": False,
            "pass_requires_affirmative_preregistered_acceptance": True,
        },
    }


def research_family_payload(
    *,
    research_family_id: str,
    research_question: str,
    hypothesis: str,
    parameter_space_digest: str | None,
    first_result_visible: bool = False,
) -> dict[str, Any]:
    if not research_family_id.strip() or not research_question.strip() or not hypothesis.strip():
        raise ValueError("Research family id, question and hypothesis are required.")
    if first_result_visible:
        raise ValueError("Research families must be registered before any result is visible.")
    if parameter_space_digest is not None:
        parameter_space_digest = _digest64(
            parameter_space_digest, field="parameter_space_digest"
        )
    return {
        "research_family_id": research_family_id.strip(),
        "research_question": research_question.strip(),
        "hypothesis": hypothesis.strip(),
        "parameter_space_digest": parameter_space_digest,
        "registered_before_first_result": True,
    }


def trial_started_payload(
    *,
    trial_id: str,
    research_family_id: str,
    parent_trial_id: str | None,
    selection_origin: str,
    parameter_space_digest: str | None,
    configuration_digest: str,
    dataset_boundary_digest: str,
    feature_definition_digest: str,
    label_definition_digest: str,
    validation_contract_digest: str,
    cost_model_digest: str,
    market_data_semantic_identity_digest: str,
) -> dict[str, Any]:
    if selection_origin not in SELECTION_ORIGINS:
        raise ValueError("Unknown trial selection origin.")
    if not trial_id.strip() or not research_family_id.strip():
        raise ValueError("trial_id and research_family_id are required.")
    if selection_origin in MECHANICAL_ORIGINS and parameter_space_digest is None:
        raise ValueError("Mechanical selection requires ex-ante parameter-space proof.")
    if parameter_space_digest is not None:
        parameter_space_digest = _digest64(
            parameter_space_digest, field="parameter_space_digest"
        )
    return {
        "trial_id": trial_id.strip(),
        "research_family_id": research_family_id.strip(),
        "parent_trial_id": None if parent_trial_id is None else parent_trial_id.strip(),
        "selection_origin": selection_origin,
        "parameter_space_digest": parameter_space_digest,
        "configuration_digest": _digest64(configuration_digest, field="configuration_digest"),
        "dataset_boundary_digest": _digest64(
            dataset_boundary_digest, field="dataset_boundary_digest"
        ),
        "feature_definition_digest": _digest64(
            feature_definition_digest, field="feature_definition_digest"
        ),
        "label_definition_digest": _digest64(
            label_definition_digest, field="label_definition_digest"
        ),
        "validation_contract_digest": _digest64(
            validation_contract_digest, field="validation_contract_digest"
        ),
        "cost_model_digest": _digest64(cost_model_digest, field="cost_model_digest"),
        "market_data_semantic_identity_digest": _digest64(
            market_data_semantic_identity_digest,
            field="market_data_semantic_identity_digest",
        ),
        "state": "started",
    }


def validate_trial_against_family(
    trial: Mapping[str, Any], family: Mapping[str, Any]
) -> None:
    if trial.get("research_family_id") != family.get("research_family_id"):
        raise ValueError("Trial does not belong to the supplied research family.")
    origin = str(trial.get("selection_origin") or "")
    if origin in MECHANICAL_ORIGINS:
        registered = family.get("parameter_space_digest")
        if registered is None or trial.get("parameter_space_digest") != registered:
            raise ValueError(
                "Mechanical trial must prove membership in the ex-ante registered parameter space."
            )
        if family.get("registered_before_first_result") is not True:
            raise ValueError("Mechanical provenance was not registered before result visibility.")


def trial_state_payload(
    *,
    trial_id: str,
    research_family_id: str,
    state: str,
    result_digest: str | None,
    reason: str | None = None,
) -> dict[str, Any]:
    if state not in TRIAL_STATES - {"started"}:
        raise ValueError("Terminal trial state must be completed, failed or aborted.")
    if state == "completed" and result_digest is None:
        raise ValueError("Completed trial requires result_digest.")
    return {
        "trial_id": trial_id,
        "research_family_id": research_family_id,
        "state": state,
        "result_digest": (
            None if result_digest is None else _digest64(result_digest, field="result_digest")
        ),
        "reason": reason,
        "raw_trial_count_effect": 0,
    }


def equivalence_contract_payload(
    *,
    qualification_id: str,
    affected_surface: str,
    source_identity_a_digest: str,
    source_identity_b_digest: str,
    comparison_population_digest: str,
    minimum_paired_sample: int,
    coverage_requirements: Mapping[str, Any],
    distribution_metrics: list[Mapping[str, Any]],
    decision_surface_metrics: list[Mapping[str, Any]],
    pass_criteria: Mapping[str, Any],
    fail_criteria: Mapping[str, Any],
    insufficient_evidence_criteria: Mapping[str, Any],
) -> dict[str, Any]:
    if minimum_paired_sample <= 0:
        raise ValueError("Equivalence contract requires a positive paired-sample minimum.")
    if not distribution_metrics or not decision_surface_metrics:
        raise ValueError(
            "Equivalence must test both feature distribution and resulting decision surface."
        )
    if not pass_criteria or not fail_criteria or not insufficient_evidence_criteria:
        raise ValueError("PASS, FAIL and INSUFFICIENT criteria must all be explicit.")
    return {
        "qualification_id": qualification_id,
        "affected_surface": affected_surface,
        "source_identity_a_digest": _digest64(
            source_identity_a_digest, field="source_identity_a_digest"
        ),
        "source_identity_b_digest": _digest64(
            source_identity_b_digest, field="source_identity_b_digest"
        ),
        "comparison_population_digest": _digest64(
            comparison_population_digest, field="comparison_population_digest"
        ),
        "minimum_paired_sample": int(minimum_paired_sample),
        "coverage_requirements": dict(coverage_requirements),
        "distribution_metrics": [dict(item) for item in distribution_metrics],
        "decision_surface_metrics": [dict(item) for item in decision_surface_metrics],
        "pass_criteria": dict(pass_criteria),
        "fail_criteria": dict(fail_criteria),
        "insufficient_evidence_criteria": dict(insufficient_evidence_criteria),
        "default_outcome": "insufficient_evidence",
        "inheritance_requires": "pass",
    }


def qualification_result_payload(
    *,
    qualification_id: str,
    contract_digest: str,
    outcome: str,
    evidence_digest: str,
) -> dict[str, Any]:
    if outcome not in QUALIFICATION_OUTCOMES:
        raise ValueError("Unknown qualification outcome.")
    return {
        "qualification_id": qualification_id,
        "contract_digest": _digest64(contract_digest, field="contract_digest"),
        "outcome": outcome,
        "evidence_digest": _digest64(evidence_digest, field="evidence_digest"),
        "inheritance_allowed": outcome == "pass",
    }


def governance_amendment_payload(
    *,
    superseded_record_digest: str,
    amendment_reason: str,
    new_rule_set: Mapping[str, Any],
    evidence_digest: str,
) -> dict[str, Any]:
    if not amendment_reason.strip():
        raise ValueError("Governance amendment reason is required.")
    return {
        "superseded_record_digest": _digest64(
            superseded_record_digest, field="superseded_record_digest"
        ),
        "amendment_reason": amendment_reason.strip(),
        "new_rule_set": dict(new_rule_set),
        "evidence_digest": _digest64(evidence_digest, field="evidence_digest"),
        "mutation_of_prior_record": False,
    }


class D1ResearchLedger:
    """Append-only D1 adapter. The schema independently vetoes UPDATE and DELETE."""

    def __init__(self, d1: Any) -> None:
        self._d1 = d1

    async def latest(self) -> dict[str, Any] | None:
        row = await self._d1.prepare(
            """
            SELECT sequence,record_digest,previous_digest,ledger_version,record_type,
                   recorded_at_utc,code_head_sha,initiated_by,payload_json
            FROM research_evidence_ledger ORDER BY sequence DESC LIMIT 1
            """
        ).first()
        if row is None:
            return None
        value = dict(row)
        value["payload"] = json.loads(value.pop("payload_json"))
        return value

    async def append(self, record: Mapping[str, Any]) -> None:
        if not verify_record(record):
            raise ValueError("Invalid research-ledger record.")
        latest = await self.latest()
        expected_sequence = 0 if latest is None else int(latest["sequence"]) + 1
        expected_previous = None if latest is None else str(latest["record_digest"])
        if int(record["sequence"]) != expected_sequence:
            raise ValueError("Research-ledger sequence is not append-only.")
        if record.get("previous_digest") != expected_previous:
            raise ValueError("Research-ledger previous digest does not match current head.")
        await self._d1.prepare(
            """
            INSERT INTO research_evidence_ledger (
              sequence,record_digest,previous_digest,ledger_version,record_type,
              recorded_at_utc,code_head_sha,initiated_by,payload_json
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """
        ).bind(
            int(record["sequence"]),
            str(record["record_digest"]),
            record.get("previous_digest"),
            str(record["ledger_version"]),
            str(record["record_type"]),
            str(record["recorded_at_utc"]),
            str(record["code_head_sha"]),
            str(record["initiated_by"]),
            canonical_json(record["payload"]),
        ).run()
