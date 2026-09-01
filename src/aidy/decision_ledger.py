from __future__ import annotations

import copy
import json
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from aidy.context_packet import compute_context_hash
from aidy.master_trader_contract_v2 import (
    MASTER_TRADER_CONTRACT_VERSION_V2,
    master_trader_decision_digest_versioned,
    validate_master_trader_decision_versioned,
)
from aidy.safety_gates import SAFETY_GATES_VERSION, verify_safety_gate_digest

DECISION_LEDGER_VERSION = "aidy_immutable_decision_ledger_v1"
EX_ANTE_RECORD_VERSION = "aidy_ex_ante_evaluation_record_v1"
REPRODUCIBILITY_BUNDLE_VERSION = "aidy_decision_reproducibility_bundle_v1"
OUTCOME_ATTACHMENT_VERSION = "aidy_decision_outcome_attachment_v1"
LEDGER_MANIFEST_VERSION = "aidy_decision_ledger_manifest_v1"
DIGEST_ALGORITHM = "sha256"

CYCLE_DISPOSITIONS = (
    "pre_model_blocked",
    "model_failed",
    "post_model_blocked",
    "no_trade",
    "decision_admitted",
)
OUTCOME_ATTACHMENT_TYPES = ("trade_outcome", "shadow_outcome")

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{3,191}$")
_SECRET_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "client_secret",
        "cloudflare_api_token",
        "metaapi_token",
        "password",
        "private_key",
        "secret",
        "service_account_json",
        "telegram_bot_token",
    }
)
_HIDDEN_REASONING_KEYS = frozenset(
    {
        "analysis",
        "chain_of_thought",
        "chainofthought",
        "hidden_reasoning",
        "reasoning_trace",
        "scratchpad",
        "thoughts",
    }
)
_OUTCOME_KEYS = frozenset(
    {
        "counterfactual_digest",
        "counterfactual_version",
        "future_evaluation",
        "future_return",
        "future_returns",
        "horizon_assessments",
        "mae",
        "mfe",
        "move_bundle",
        "move_bundle_version",
        "outcome",
        "outcome_label",
        "outcome_state",
        "outcomes",
        "path_class",
        "pnl",
        "primary_classification",
        "realized_pnl",
        "shadow_outcome",
        "stop_hit",
        "target_hit",
        "trade_outcome_bundle",
        "trade_outcome_bundle_version",
    }
)
_SECRET_MARKERS = ("sk-", "bearer ", "-----begin private key-----")


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def _utc(value: Any, *, name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError(f"{name} must be timezone-aware ISO-8601 text.") from exc
    else:
        raise TypeError(f"{name} must be a timezone-aware datetime or ISO-8601 string.")
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware.")
    return parsed.astimezone(UTC)


def _text(value: Any, *, name: str, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{name} must be non-empty text.")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ValueError(f"{name} exceeds {maximum} characters.")
    return normalized


def _optional_text(value: Any, *, name: str, maximum: int = 256) -> str | None:
    if value is None:
        return None
    return _text(value, name=name, maximum=maximum)


def _safe_id(value: Any, *, name: str) -> str:
    normalized = _text(value, name=name, maximum=192)
    if not _SAFE_ID.fullmatch(normalized):
        raise ValueError(f"{name} has an unsafe identifier format.")
    return normalized


def _assert_no_secrets_or_hidden_reasoning(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _SECRET_KEYS:
                raise ValueError(f"Secret-bearing field is forbidden at {path}.{key}.")
            if normalized in _HIDDEN_REASONING_KEYS:
                raise ValueError(f"Hidden reasoning field is forbidden at {path}.{key}.")
            _assert_no_secrets_or_hidden_reasoning(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_no_secrets_or_hidden_reasoning(item, path=f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.strip().lower()
        if any(marker in lowered for marker in _SECRET_MARKERS):
            raise ValueError(f"Secret-like value is forbidden at {path}.")


def _assert_ex_ante_safe(value: Any, *, path: str = "ex_ante") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _SECRET_KEYS:
                raise ValueError(f"Secret-bearing field is forbidden at {path}.{key}.")
            if normalized in _HIDDEN_REASONING_KEYS:
                raise ValueError(f"Hidden reasoning field is forbidden at {path}.{key}.")
            if normalized in _OUTCOME_KEYS:
                raise ValueError(f"Future/outcome field is forbidden at {path}.{key}.")
            if normalized == "future_derived" and item is not False:
                raise ValueError(f"Future-derived evidence is forbidden at {path}.{key}.")
            if normalized == "evaluation_only" and item is not False:
                raise ValueError(f"Evaluation-only evidence is forbidden at {path}.{key}.")
            _assert_ex_ante_safe(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_ex_ante_safe(item, path=f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.strip().lower()
        if any(marker in lowered for marker in _SECRET_MARKERS):
            raise ValueError(f"Secret-like value is forbidden at {path}.")


def _unique_ids(values: Iterable[Any], *, name: str) -> list[str]:
    result = [_safe_id(item, name=f"{name} entry") for item in values]
    if len(result) != len(set(result)):
        raise ValueError(f"{name} cannot contain duplicates.")
    return result


def _sampling_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("sampling_metadata must be a mapping.")
    required = {"seed_supported", "seed", "temperature_supported", "temperature"}
    if set(value) != required:
        raise ValueError(
            "sampling_metadata must contain the exact supported/seed/temperature fields."
        )
    seed_supported = value["seed_supported"]
    temperature_supported = value["temperature_supported"]
    if not isinstance(seed_supported, bool) or not isinstance(temperature_supported, bool):
        raise TypeError("sampling support flags must be boolean.")
    seed = value["seed"]
    temperature = value["temperature"]
    if not seed_supported and seed is not None:
        raise ValueError("seed must be null when seed_supported is false.")
    if seed_supported and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise TypeError("seed must be an integer when seed_supported is true.")
    if not temperature_supported and temperature is not None:
        raise ValueError("temperature must be null when temperature_supported is false.")
    if temperature_supported:
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
            raise TypeError("temperature must be numeric when temperature_supported is true.")
        if not 0 <= float(temperature) <= 2:
            raise ValueError("temperature must be between 0 and 2.")
    return {
        "seed_supported": seed_supported,
        "seed": seed,
        "temperature_supported": temperature_supported,
        "temperature": temperature,
    }


def build_reproducibility_bundle(
    *,
    context: Mapping[str, Any],
    prompt_version: str | None,
    prompt_digest: str | None,
    gateway_version: str | None,
    model_id: str | None,
    strategy_version: str,
    config_version: str,
    sampling_metadata: Mapping[str, Any],
    regime_state: Mapping[str, Any] | None,
    setup_state: Mapping[str, Any] | None,
    evidence_grade: str | None,
    effective_n: int | None,
    evidence_report_digest: str | None,
    analogue_retrieval_version: str | None,
    analogue_retrieval_digest: str | None,
    analogue_case_ids: Iterable[str] = (),
    selective_layer_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(context, Mapping):
        raise TypeError("context must be a mapping.")
    context_snapshot = copy.deepcopy(dict(context))
    _assert_ex_ante_safe(context_snapshot, path="context")
    supplied_hash = str(context_snapshot.get("context_hash") or "")
    if not supplied_hash or supplied_hash != compute_context_hash(context_snapshot):
        raise ValueError("Context hash is missing or invalid.")
    context_version = _text(
        context_snapshot.get("context_packet_version"), name="context_packet_version"
    )
    if effective_n is not None and (
        isinstance(effective_n, bool)
        or not isinstance(effective_n, int)
        or effective_n < 0
    ):
        raise ValueError("effective_n must be a non-negative integer or null.")
    cases = _unique_ids(analogue_case_ids, name="analogue_case_ids")
    source_versions = context_snapshot.get("source_contract_versions")
    source_versions = dict(source_versions) if isinstance(source_versions, Mapping) else {}
    bundle: dict[str, Any] = {
        "bundle_version": REPRODUCIBILITY_BUNDLE_VERSION,
        "context_packet_version": context_version,
        "context_hash": supplied_hash,
        "source_contract_versions": source_versions,
        "prompt_version": _optional_text(prompt_version, name="prompt_version"),
        "prompt_digest": _optional_text(prompt_digest, name="prompt_digest"),
        "gateway_version": _optional_text(gateway_version, name="gateway_version"),
        "model_id": _optional_text(model_id, name="model_id"),
        "strategy_version": _text(strategy_version, name="strategy_version"),
        "config_version": _text(config_version, name="config_version"),
        "sampling_metadata": _sampling_metadata(sampling_metadata),
        "regime_state": None
        if regime_state is None
        else copy.deepcopy(dict(regime_state)),
        "setup_state": None if setup_state is None else copy.deepcopy(dict(setup_state)),
        "evidence_grade": _optional_text(evidence_grade, name="evidence_grade"),
        "effective_n": effective_n,
        "evidence_report_digest": _optional_text(
            evidence_report_digest, name="evidence_report_digest"
        ),
        "analogue_retrieval_version": _optional_text(
            analogue_retrieval_version, name="analogue_retrieval_version"
        ),
        "analogue_retrieval_digest": _optional_text(
            analogue_retrieval_digest, name="analogue_retrieval_digest"
        ),
        "analogue_case_ids": cases,
        "selective_layer_state": None
        if selective_layer_state is None
        else copy.deepcopy(dict(selective_layer_state)),
    }
    _assert_ex_ante_safe(bundle, path="reproducibility_bundle")
    bundle["bundle_digest"] = digest(bundle)
    return bundle


def verify_reproducibility_bundle(bundle: Mapping[str, Any]) -> bool:
    if not isinstance(bundle, Mapping):
        return False
    supplied = str(bundle.get("bundle_digest") or "")
    body = copy.deepcopy(dict(bundle))
    body.pop("bundle_digest", None)
    try:
        _assert_ex_ante_safe(body, path="reproducibility_bundle")
    except (TypeError, ValueError):
        return False
    return bool(supplied) and supplied == digest(body)


def _gate_receipt(
    value: Mapping[str, Any] | None,
    *,
    stage: str,
    context_hash: str,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError(f"{stage} gate receipt must be a mapping or null.")
    receipt = copy.deepcopy(dict(value))
    if receipt.get("gate_version") != SAFETY_GATES_VERSION or receipt.get("stage") != stage:
        raise ValueError(f"{stage} gate receipt version/stage mismatch.")
    if receipt.get("context_hash") != context_hash:
        raise ValueError(f"{stage} gate receipt does not bind the exact context hash.")
    if not verify_safety_gate_digest(receipt):
        raise ValueError(f"{stage} gate receipt digest is invalid.")
    _assert_ex_ante_safe(receipt, path=f"{stage}_gate_receipt")
    return receipt


def _gateway_snapshot(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError("gateway_result must be a mapping or null.")
    allowed = (
        "gateway_version",
        "status",
        "publication_allowed",
        "failure_reason",
        "decision_digest",
        "request_digest",
        "attempts",
        "latency_ms",
        "response_id",
        "provider_status",
        "provider_model",
        "usage",
        "estimated_cost_usd",
        "pricing_version",
        "prompt_version",
        "prompt_digest",
        "model_id",
        "reasoning_effort",
    )
    snapshot = {key: copy.deepcopy(value.get(key)) for key in allowed}
    _assert_ex_ante_safe(snapshot, path="gateway_snapshot")
    return snapshot


def _decision_snapshot(
    value: Mapping[str, Any] | None,
) -> tuple[dict[str, Any] | None, str | None, dict[str, Any] | None]:
    if value is None:
        return None, None, None
    normalized = validate_master_trader_decision_versioned(value)
    decision_digest = master_trader_decision_digest_versioned(normalized)
    falsifiable: dict[str, Any] | None = None
    if normalized["contract_version"] == MASTER_TRADER_CONTRACT_VERSION_V2:
        falsifiable = {
            "thesis": normalized["thesis"],
            "expected_horizon_minutes": normalized["expected_horizon_minutes"],
            "counter_argument": normalized["counter_argument"],
            "invalidation_condition": normalized["invalidation_condition"],
            "abstention_basis": normalized["abstention_basis"],
            "shadow_thesis": normalized["shadow_thesis"],
            "shadow_direction": normalized["shadow_direction"],
            "shadow_horizon_minutes": normalized["shadow_horizon_minutes"],
            "shadow_evaluation_condition": normalized["shadow_evaluation_condition"],
        }
    _assert_ex_ante_safe(normalized, path="decision")
    return normalized, decision_digest, falsifiable


def _validate_disposition(
    *,
    disposition: str,
    pre: Mapping[str, Any],
    gateway: Mapping[str, Any] | None,
    post: Mapping[str, Any] | None,
    decision: Mapping[str, Any] | None,
) -> None:
    if disposition not in CYCLE_DISPOSITIONS:
        raise ValueError("Unsupported cycle_disposition.")
    if disposition == "pre_model_blocked":
        if pre.get("status") != "blocked" or pre.get("model_call_allowed") is not False:
            raise ValueError("pre_model_blocked requires a blocked pre-model receipt.")
        if gateway is not None or post is not None or decision is not None:
            raise ValueError(
                "pre_model_blocked cannot contain gateway/post-model/decision state."
            )
        return
    if pre.get("status") != "passed" or pre.get("model_call_allowed") is not True:
        raise ValueError(f"{disposition} requires a passed pre-model receipt.")
    if gateway is None:
        raise ValueError(f"{disposition} requires gateway metadata.")
    if disposition == "model_failed":
        if gateway.get("status") == "accepted" or gateway.get("publication_allowed") is True:
            raise ValueError("model_failed requires a failed-closed gateway result.")
        if post is not None or decision is not None:
            raise ValueError("model_failed cannot contain post-model or decision state.")
        return
    if gateway.get("status") != "accepted" or gateway.get("publication_allowed") is not True:
        raise ValueError(f"{disposition} requires an accepted gateway result.")
    if post is None or decision is None:
        raise ValueError(f"{disposition} requires post-model and decision state.")
    if disposition == "post_model_blocked":
        if post.get("status") != "blocked" or post.get("decision_admitted") is not False:
            raise ValueError("post_model_blocked requires a blocked post-model receipt.")
        return
    if post.get("status") != "passed" or post.get("decision_admitted") is not True:
        raise ValueError(f"{disposition} requires an admitted post-model receipt.")
    action = str(decision.get("action") or "")
    if disposition == "no_trade" and action != "no_trade":
        raise ValueError("no_trade disposition requires a no_trade decision.")
    if disposition == "decision_admitted" and action == "no_trade":
        raise ValueError("decision_admitted requires an actionable decision.")


def _validate_cross_links(
    *,
    context: Mapping[str, Any],
    instruction_type: str,
    pre: Mapping[str, Any],
    gateway: Mapping[str, Any] | None,
    post: Mapping[str, Any] | None,
    decision: Mapping[str, Any] | None,
    decision_digest: str | None,
    repro: Mapping[str, Any],
    quality: Mapping[str, Any],
) -> None:
    context_hash = str(context["context_hash"])
    if pre.get("instruction_type") != instruction_type:
        raise ValueError("Pre-model receipt instruction_type does not match the evaluation.")
    if repro.get("context_hash") != context_hash:
        raise ValueError("Reproducibility bundle does not bind the exact context hash.")
    if repro.get("context_packet_version") != context.get("context_packet_version"):
        raise ValueError("Reproducibility bundle context version does not match the evaluation.")
    context_sources = context.get("source_contract_versions")
    context_sources = dict(context_sources) if isinstance(context_sources, Mapping) else {}
    if repro.get("source_contract_versions") != context_sources:
        raise ValueError("Reproducibility source-contract identities do not match the context.")
    context_quality = context.get("data_quality")
    context_quality = dict(context_quality) if isinstance(context_quality, Mapping) else {}
    if dict(quality) != context_quality:
        raise ValueError("data_quality_flags must exactly match context.data_quality.")
    context_as_of = _utc(context.get("as_of_utc"), name="context.as_of_utc")
    if decision is not None:
        decision_time = _utc(decision.get("evaluated_at_utc"), name="decision.evaluated_at_utc")
        if decision_time != context_as_of:
            raise ValueError("Decision evaluation time does not match the exact context as-of.")
    if gateway is None:
        if any(
            repro.get(field) is not None
            for field in ("prompt_version", "prompt_digest", "gateway_version", "model_id")
        ):
            raise ValueError("No-model evaluation cannot claim prompt/gateway/model identities.")
    else:
        for field in ("prompt_version", "prompt_digest", "gateway_version", "model_id"):
            if repro.get(field) != gateway.get(field):
                raise ValueError(
                    f"Reproducibility {field} does not match the gateway snapshot."
                )
        if decision is None:
            if gateway.get("decision_digest") is not None:
                raise ValueError("Gateway decision_digest must be null when no decision exists.")
        elif gateway.get("decision_digest") != decision_digest:
            raise ValueError("Gateway decision digest does not match the stored decision.")
    if (
        post is not None
        and decision is not None
        and post.get("decision_action") != decision.get("action")
    ):
        raise ValueError("Post-model decision_action does not match the stored decision.")


def build_ex_ante_evaluation_record(
    *,
    context: Mapping[str, Any],
    instruction_type: str,
    cycle_disposition: str,
    pre_model_receipt: Mapping[str, Any],
    gateway_result: Mapping[str, Any] | None,
    post_model_receipt: Mapping[str, Any] | None,
    decision: Mapping[str, Any] | None,
    reproducibility_bundle: Mapping[str, Any],
    data_quality_flags: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(context, Mapping):
        raise TypeError("context must be a mapping.")
    context_snapshot = copy.deepcopy(dict(context))
    _assert_ex_ante_safe(context_snapshot, path="context_snapshot")
    context_hash = str(context_snapshot.get("context_hash") or "")
    if not context_hash or context_hash != compute_context_hash(context_snapshot):
        raise ValueError("Context hash is missing or invalid.")
    evaluated_at = _utc(context_snapshot.get("as_of_utc"), name="context.as_of_utc")
    instruction = _text(instruction_type, name="instruction_type")
    pre = _gate_receipt(
        pre_model_receipt,
        stage="pre_model",
        context_hash=context_hash,
    )
    if pre is None:
        raise ValueError("pre_model_receipt is required for every evaluation.")
    post = _gate_receipt(
        post_model_receipt,
        stage="post_model",
        context_hash=context_hash,
    )
    gateway = _gateway_snapshot(gateway_result)
    decision_snapshot, decision_digest, falsifiable = _decision_snapshot(decision)
    _validate_disposition(
        disposition=cycle_disposition,
        pre=pre,
        gateway=gateway,
        post=post,
        decision=decision_snapshot,
    )
    if not isinstance(reproducibility_bundle, Mapping) or not verify_reproducibility_bundle(
        reproducibility_bundle
    ):
        raise ValueError("reproducibility_bundle is invalid.")
    repro = copy.deepcopy(dict(reproducibility_bundle))
    if not isinstance(data_quality_flags, Mapping):
        raise TypeError("data_quality_flags must be a mapping.")
    quality = copy.deepcopy(dict(data_quality_flags))
    _assert_ex_ante_safe(quality, path="data_quality_flags")
    _validate_cross_links(
        context=context_snapshot,
        instruction_type=instruction,
        pre=pre,
        gateway=gateway,
        post=post,
        decision=decision_snapshot,
        decision_digest=decision_digest,
        repro=repro,
        quality=quality,
    )
    identity_body = {
        "ledger_version": DECISION_LEDGER_VERSION,
        "context_hash": context_hash,
        "instruction_type": instruction,
        "prompt_version": repro.get("prompt_version"),
        "model_id": repro.get("model_id"),
        "strategy_version": repro.get("strategy_version"),
        "config_version": repro.get("config_version"),
    }
    identity_digest = digest(identity_body)
    evaluation_id = f"aidy_eval_{identity_digest[:32]}"
    decision_id = f"aidy_dec_{identity_digest[:32]}"
    record: dict[str, Any] = {
        "record_version": EX_ANTE_RECORD_VERSION,
        "ledger_version": DECISION_LEDGER_VERSION,
        "evaluation_id": evaluation_id,
        "decision_id": decision_id,
        "evaluated_at_utc": evaluated_at.isoformat(),
        "instruction_type": instruction,
        "cycle_disposition": cycle_disposition,
        "context_packet_version": context_snapshot.get("context_packet_version"),
        "context_hash": context_hash,
        "context_snapshot": context_snapshot,
        "reproducibility_bundle": repro,
        "reproducibility_bundle_digest": repro["bundle_digest"],
        "pre_model_receipt": pre,
        "gateway_snapshot": gateway,
        "post_model_receipt": post,
        "decision": decision_snapshot,
        "model_decision_digest": decision_digest,
        "falsifiable_thesis": falsifiable,
        "data_quality_flags": quality,
        "outcome_attachment_count": 0,
        "outcome_fields_present": False,
    }
    _assert_ex_ante_safe(record, path="ex_ante_record")
    record["ex_ante_digest"] = digest(record)
    return record


def verify_ex_ante_record(record: Mapping[str, Any]) -> bool:
    if not isinstance(record, Mapping):
        return False
    supplied = str(record.get("ex_ante_digest") or "")
    body = copy.deepcopy(dict(record))
    body.pop("ex_ante_digest", None)
    try:
        _assert_ex_ante_safe(body, path="ex_ante_record")
        context = body.get("context_snapshot")
        repro = body.get("reproducibility_bundle")
        if not isinstance(context, Mapping) or not isinstance(repro, Mapping):
            return False
        if body.get("context_hash") != context.get("context_hash"):
            return False
        if str(context.get("context_hash") or "") != compute_context_hash(context):
            return False
        if body.get("reproducibility_bundle_digest") != repro.get("bundle_digest"):
            return False
        if not verify_reproducibility_bundle(repro):
            return False
        if body.get("outcome_attachment_count") != 0:
            return False
        if body.get("outcome_fields_present") is not False:
            return False
    except (TypeError, ValueError):
        return False
    return bool(supplied) and supplied == digest(body)


def reconcile_ex_ante_record(
    existing: Mapping[str, Any] | None,
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    if not verify_ex_ante_record(candidate):
        raise ValueError("Candidate ex-ante record is invalid.")
    normalized = copy.deepcopy(dict(candidate))
    if existing is None:
        return normalized
    if not verify_ex_ante_record(existing):
        raise ValueError("Existing ex-ante record is invalid.")
    if existing.get("evaluation_id") != candidate.get("evaluation_id"):
        raise ValueError("Cannot reconcile different evaluation identities.")
    if (
        existing.get("ex_ante_digest") != candidate.get("ex_ante_digest")
        or canonical_json(existing) != canonical_json(candidate)
    ):
        raise ValueError("Immutable ex-ante record mutation detected.")
    return copy.deepcopy(dict(existing))


def build_outcome_attachment(
    *,
    ex_ante_record: Mapping[str, Any],
    attachment_type: str,
    attached_at_utc: datetime | str,
    outcome_contract_version: str,
    outcome_identity: str,
    outcome_payload: Mapping[str, Any],
) -> dict[str, Any]:
    if not verify_ex_ante_record(ex_ante_record):
        raise ValueError("Outcome attachment requires a valid immutable ex-ante record.")
    if attachment_type not in OUTCOME_ATTACHMENT_TYPES:
        raise ValueError("Unsupported attachment_type.")
    disposition = str(ex_ante_record.get("cycle_disposition") or "")
    if attachment_type == "shadow_outcome" and disposition != "no_trade":
        raise ValueError("shadow_outcome can attach only to a no_trade evaluation.")
    if attachment_type == "trade_outcome" and disposition != "decision_admitted":
        raise ValueError("trade_outcome can attach only to an admitted actionable decision.")
    attached_at = _utc(attached_at_utc, name="attached_at_utc")
    evaluated_at = _utc(ex_ante_record.get("evaluated_at_utc"), name="evaluated_at_utc")
    if attached_at <= evaluated_at:
        raise ValueError("Outcome attachment must occur after the ex-ante evaluation time.")
    contract_version = _text(outcome_contract_version, name="outcome_contract_version")
    identity = _safe_id(outcome_identity, name="outcome_identity")
    if not isinstance(outcome_payload, Mapping):
        raise TypeError("outcome_payload must be a mapping.")
    payload = copy.deepcopy(dict(outcome_payload))
    _assert_no_secrets_or_hidden_reasoning(payload, path="outcome_payload")
    attachment_identity_body = {
        "evaluation_id": ex_ante_record["evaluation_id"],
        "ex_ante_digest": ex_ante_record["ex_ante_digest"],
        "attachment_type": attachment_type,
        "outcome_contract_version": contract_version,
        "outcome_identity": identity,
    }
    attachment_id = f"aidy_out_{digest(attachment_identity_body)[:32]}"
    record: dict[str, Any] = {
        "attachment_version": OUTCOME_ATTACHMENT_VERSION,
        "attachment_id": attachment_id,
        "attachment_type": attachment_type,
        "evaluation_id": ex_ante_record["evaluation_id"],
        "decision_id": ex_ante_record["decision_id"],
        "ex_ante_digest": ex_ante_record["ex_ante_digest"],
        "evaluated_at_utc": ex_ante_record["evaluated_at_utc"],
        "attached_at_utc": attached_at.isoformat(),
        "outcome_contract_version": contract_version,
        "outcome_identity": identity,
        "outcome_payload": payload,
    }
    record["attachment_digest"] = digest(record)
    return record


def verify_outcome_attachment(attachment: Mapping[str, Any]) -> bool:
    if not isinstance(attachment, Mapping):
        return False
    supplied = str(attachment.get("attachment_digest") or "")
    body = copy.deepcopy(dict(attachment))
    body.pop("attachment_digest", None)
    try:
        _assert_no_secrets_or_hidden_reasoning(body, path="outcome_attachment")
        if body.get("attachment_version") != OUTCOME_ATTACHMENT_VERSION:
            return False
        if body.get("attachment_type") not in OUTCOME_ATTACHMENT_TYPES:
            return False
        if _utc(body.get("attached_at_utc"), name="attached_at_utc") <= _utc(
            body.get("evaluated_at_utc"), name="evaluated_at_utc"
        ):
            return False
    except (TypeError, ValueError):
        return False
    return bool(supplied) and supplied == digest(body)


def reconcile_outcome_attachment(
    existing: Mapping[str, Any] | None,
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    if not verify_outcome_attachment(candidate):
        raise ValueError("Candidate outcome attachment is invalid.")
    normalized = copy.deepcopy(dict(candidate))
    if existing is None:
        return normalized
    if not verify_outcome_attachment(existing):
        raise ValueError("Existing outcome attachment is invalid.")
    if existing.get("attachment_id") != candidate.get("attachment_id"):
        raise ValueError("Cannot reconcile different outcome attachment identities.")
    if (
        existing.get("attachment_digest") != candidate.get("attachment_digest")
        or canonical_json(existing) != canonical_json(candidate)
    ):
        raise ValueError("Conflicting immutable outcome attachment detected.")
    return copy.deepcopy(dict(existing))


def reconstruct_non_secret_decision_bundle(record: Mapping[str, Any]) -> dict[str, Any]:
    if not verify_ex_ante_record(record):
        raise ValueError("Cannot reconstruct from an invalid ex-ante record.")
    return {
        "evaluation_id": record["evaluation_id"],
        "decision_id": record["decision_id"],
        "evaluated_at_utc": record["evaluated_at_utc"],
        "cycle_disposition": record["cycle_disposition"],
        "context_snapshot": copy.deepcopy(record["context_snapshot"]),
        "reproducibility_bundle": copy.deepcopy(record["reproducibility_bundle"]),
        "pre_model_receipt": copy.deepcopy(record["pre_model_receipt"]),
        "gateway_snapshot": copy.deepcopy(record["gateway_snapshot"]),
        "post_model_receipt": copy.deepcopy(record["post_model_receipt"]),
        "decision": copy.deepcopy(record["decision"]),
        "model_decision_digest": record["model_decision_digest"],
        "falsifiable_thesis": copy.deepcopy(record["falsifiable_thesis"]),
        "data_quality_flags": copy.deepcopy(record["data_quality_flags"]),
        "ex_ante_digest": record["ex_ante_digest"],
    }


def decision_ledger_manifest() -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "manifest_version": LEDGER_MANIFEST_VERSION,
        "ledger_version": DECISION_LEDGER_VERSION,
        "ex_ante_record_version": EX_ANTE_RECORD_VERSION,
        "reproducibility_bundle_version": REPRODUCIBILITY_BUNDLE_VERSION,
        "outcome_attachment_version": OUTCOME_ATTACHMENT_VERSION,
        "digest_algorithm": DIGEST_ALGORITHM,
        "cycle_dispositions": list(CYCLE_DISPOSITIONS),
        "outcome_attachment_types": list(OUTCOME_ATTACHMENT_TYPES),
        "every_cycle_gets_stable_evaluation_id": True,
        "every_cycle_gets_stable_decision_id": True,
        "duplicate_identical_evaluation_is_idempotent": True,
        "exact_context_hash_bound_to_gate_receipts": True,
        "exact_data_quality_bound_to_context": True,
        "gateway_decision_digest_bound_to_stored_decision": True,
        "decision_time_bound_to_context_asof": True,
        "model_prompt_gateway_identities_cross_checked": True,
        "ex_ante_mutation_allowed": False,
        "outcome_attachment_mutates_ex_ante": False,
        "future_outcomes_allowed_in_ex_ante": False,
        "hidden_reasoning_stored": False,
        "secrets_stored": False,
        "v1_and_v2_decisions_readable": True,
        "gateway_promoted_by_day34": False,
        "trading_gate_created_by_day34": False,
        "super_signals_modified": False,
    }
    manifest["manifest_digest"] = digest(manifest)
    return manifest
