from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy.context_packet import compute_context_hash
from aidy.decision_ledger import verify_ex_ante_record
from aidy.master_trader_contract_v2 import (
    MASTER_TRADER_CONTRACT_VERSION_V2,
    master_trader_decision_digest_versioned,
    validate_master_trader_decision_versioned,
)
from aidy.master_watcher import verify_watcher_receipt
from aidy.paper_simulator import verify_paper_state

MANAGEMENT_CONTRACT_VERSION = "aidy_management_action_contract_v2_thesis_aware"
MANAGEMENT_LEDGER_VERSION = "aidy_management_action_ledger_v1"
MANAGEMENT_MANIFEST_VERSION = "aidy_day48_management_manifest_v1"
ACTIVE_STATES = frozenset({"open", "partial"})
THESIS_CODES = {
    "intact": "thesis_intact",
    "weakened": "thesis_weakened",
    "invalidated": "thesis_invalidated",
    "unknown": "thesis_unknown",
}


class ManagementContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def _decimal(value: Any, *, name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ManagementContractError("management_geometry_invalid", f"{name} is required.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ManagementContractError(
            "management_geometry_invalid", f"{name} must be a finite number."
        ) from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ManagementContractError(
            "management_geometry_invalid", f"{name} must be positive and finite."
        )
    return parsed


def _original_binding(
    ex_ante_record: Mapping[str, Any], paper_state: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not isinstance(ex_ante_record, Mapping) or not verify_ex_ante_record(ex_ante_record):
        raise ManagementContractError("management_ex_ante_invalid", "Valid ex-ante record required.")
    raw = ex_ante_record.get("decision")
    if not isinstance(raw, Mapping):
        raise ManagementContractError("management_origin_missing", "Originating decision is missing.")
    origin = validate_master_trader_decision_versioned(raw)
    if origin.get("contract_version") != MASTER_TRADER_CONTRACT_VERSION_V2:
        raise ManagementContractError("management_v2_required", "Originating decision must be V2.")
    if origin.get("action") != "new_trade":
        raise ManagementContractError(
            "management_origin_not_new_trade", "Management must target a new_trade origin."
        )
    if not isinstance(paper_state, Mapping) or not verify_paper_state(paper_state):
        raise ManagementContractError("management_paper_state_invalid", "Verified paper state required.")
    state = copy.deepcopy(dict(paper_state))
    if state.get("position_state") not in ACTIVE_STATES:
        raise ManagementContractError("management_position_inactive", "Only active paper states may be managed.")
    if state.get("decision_id") != ex_ante_record.get("decision_id"):
        raise ManagementContractError(
            "management_origin_id_mismatch", "Paper state and ex-ante decision IDs differ."
        )
    if state.get("ex_ante_digest") != ex_ante_record.get("ex_ante_digest"):
        raise ManagementContractError(
            "management_ex_ante_binding_mismatch", "Paper state ex-ante binding differs."
        )
    thesis = {
        "thesis": origin["thesis"],
        "expected_horizon_minutes": origin["expected_horizon_minutes"],
        "counter_argument": origin["counter_argument"],
        "invalidation_condition": copy.deepcopy(origin["invalidation_condition"]),
    }
    if canonical_json(state.get("thesis_snapshot")) != canonical_json(thesis):
        raise ManagementContractError(
            "management_original_thesis_mutated", "Paper state original thesis was mutated."
        )
    return copy.deepcopy(dict(ex_ante_record)), origin, state


def _watcher_binding(
    watcher_receipt: Mapping[str, Any], *, ex_ante: Mapping[str, Any], state: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(watcher_receipt, Mapping) or not verify_watcher_receipt(watcher_receipt):
        raise ManagementContractError("management_watcher_invalid", "Verified watcher receipt required.")
    receipt = copy.deepcopy(dict(watcher_receipt))
    if receipt.get("status") != "observed":
        raise ManagementContractError(
            "management_watcher_not_observed", "Only an observed watcher cycle can support action."
        )
    observation = receipt.get("observation")
    if not isinstance(observation, Mapping):
        raise ManagementContractError("management_watcher_invalid", "Watcher observation is missing.")
    if observation.get("position_id") != state.get("position_id"):
        raise ManagementContractError(
            "management_position_id_mismatch", "Watcher targeted a different paper position."
        )
    if observation.get("originating_decision_id") != ex_ante.get("decision_id"):
        raise ManagementContractError(
            "management_origin_id_mismatch", "Watcher targeted a different originating decision."
        )
    if observation.get("paper_state_digest") != state.get("state_digest"):
        raise ManagementContractError(
            "management_paper_state_stale", "Watcher paper-state digest is stale or mismatched."
        )
    thesis_digest = digest(state["thesis_snapshot"])
    if observation.get("original_thesis_digest") != thesis_digest:
        raise ManagementContractError(
            "management_thesis_digest_mismatch", "Watcher thesis binding does not match origin."
        )
    return receipt, copy.deepcopy(dict(observation))


def _context_binding(context: Mapping[str, Any], observation: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(context, Mapping):
        raise ManagementContractError("management_context_missing", "Current PIT context required.")
    snapshot = copy.deepcopy(dict(context))
    supplied = str(snapshot.get("context_hash") or "")
    if not supplied or supplied != compute_context_hash(snapshot):
        raise ManagementContractError("management_context_hash_invalid", "Context hash failed verification.")
    if snapshot.get("symbol") != "XAUUSD":
        raise ManagementContractError("management_symbol_invalid", "Management supports XAUUSD only.")
    if snapshot.get("objective_only") is not True:
        raise ManagementContractError(
            "management_context_boundary_invalid", "Management context must be objective-only."
        )
    if snapshot.get("retrospective_history_included") is not False:
        raise ManagementContractError(
            "management_context_boundary_invalid", "Retrospective history is forbidden."
        )
    if snapshot.get("broker_follower_state_included") is not False:
        raise ManagementContractError(
            "management_context_boundary_invalid", "Broker/follower state is forbidden."
        )
    if supplied != observation.get("context_hash"):
        raise ManagementContractError(
            "management_context_watcher_mismatch", "Watcher and action context hashes differ."
        )
    quote = snapshot.get("gold")
    quote = quote.get("quote_context") if isinstance(quote, Mapping) else None
    if not isinstance(quote, Mapping) or quote.get("mid") is None:
        raise ManagementContractError("management_quote_missing", "Current XAUUSD mid is required.")
    _decimal(quote["mid"], name="gold.quote_context.mid")
    return snapshot


def _validate_thesis_link(
    decision: Mapping[str, Any], origin: Mapping[str, Any], observation: Mapping[str, Any]
) -> None:
    for field in (
        "thesis",
        "expected_horizon_minutes",
        "counter_argument",
        "invalidation_condition",
    ):
        if canonical_json(decision.get(field)) != canonical_json(origin.get(field)):
            raise ManagementContractError(
                "management_thesis_rewrite_forbidden",
                f"Management cannot rewrite original {field}.",
            )
    required = THESIS_CODES[str(observation["thesis_assessment"])]
    reasons = decision.get("reason_codes")
    if not isinstance(reasons, list) or required not in reasons:
        raise ManagementContractError(
            "management_thesis_relationship_missing",
            f"Management reason_codes must include {required}.",
        )
    watcher_codes = observation.get("reason_codes")
    if isinstance(watcher_codes, list) and not set(map(str, watcher_codes)).intersection(map(str, reasons)):
        raise ManagementContractError(
            "management_watcher_reason_missing",
            "Management must preserve at least one current watcher reason code.",
        )


def _validate_targets(direction: str, values: list[Any], *, mid: Decimal) -> list[Decimal]:
    targets = [_decimal(item, name="new_target") for item in values]
    if len(set(targets)) != len(targets):
        raise ManagementContractError("management_geometry_invalid", "New targets must be unique.")
    if direction == "long":
        if targets != sorted(targets) or any(item <= mid for item in targets):
            raise ManagementContractError(
                "management_geometry_invalid", "Long replacement targets must increase above current mid."
            )
    else:
        if targets != sorted(targets, reverse=True) or any(item >= mid for item in targets):
            raise ManagementContractError(
                "management_geometry_invalid", "Short replacement targets must decrease below current mid."
            )
    return targets


def _project_action(
    decision: Mapping[str, Any], state: Mapping[str, Any], context: Mapping[str, Any]
) -> dict[str, Any]:
    direction = str(state["direction"])
    current_stop = _decimal(state["stop_loss"], name="current_stop")
    mid = _decimal(context["gold"]["quote_context"]["mid"], name="current_mid")
    action = decision["action"]
    projected: dict[str, Any] = {
        "position_id": state["position_id"],
        "originating_decision_id": state["decision_id"],
        "before_state": state["position_state"],
        "after_state": state["position_state"],
        "direction": direction,
        "stop_loss": str(state["stop_loss"]),
        "targets": copy.deepcopy(list(state["targets"])),
        "remaining_target_indices": copy.deepcopy(list(state["remaining_target_indices"])),
    }
    if action == "close_trade":
        projected["after_state"] = "closed_management"
        projected["close_scope"] = "full"
        return projected

    instruction = str(decision["management_instruction"])
    if instruction in {"move_stop", "move_stop_and_targets"}:
        new_stop = _decimal(decision["new_stop_loss"], name="new_stop_loss")
        if direction == "long":
            valid = current_stop <= new_stop < mid
        else:
            valid = current_stop >= new_stop > mid
        if not valid:
            raise ManagementContractError(
                "management_geometry_invalid",
                "Stop management may reduce risk but cannot worsen the stop or cross current mid.",
            )
        projected["stop_loss"] = str(decision["new_stop_loss"])

    if instruction in {"replace_targets", "move_stop_and_targets"}:
        raw_targets = list(decision["new_targets"])
        remaining = len(state["remaining_target_indices"])
        if not raw_targets or len(raw_targets) > remaining:
            raise ManagementContractError(
                "management_geometry_invalid",
                "Replacement targets cannot create more remaining legs than the paper state has.",
            )
        _validate_targets(direction, raw_targets, mid=mid)
        projected["replacement_targets"] = copy.deepcopy(raw_targets)
    return projected


def build_management_action_record(
    *,
    decision: Mapping[str, Any],
    watcher_receipt: Mapping[str, Any],
    ex_ante_record: Mapping[str, Any],
    paper_state: Mapping[str, Any],
    current_context: Mapping[str, Any],
) -> dict[str, Any]:
    ex_ante, origin, state = _original_binding(ex_ante_record, paper_state)
    receipt, observation = _watcher_binding(watcher_receipt, ex_ante=ex_ante, state=state)
    context = _context_binding(current_context, observation)
    normalized = validate_master_trader_decision_versioned(decision)
    if normalized.get("contract_version") != MASTER_TRADER_CONTRACT_VERSION_V2:
        raise ManagementContractError("management_v2_required", "Management decision must be V2.")
    if normalized.get("action") not in {"manage_trade", "close_trade"}:
        raise ManagementContractError(
            "management_action_invalid", "Day 48 accepts manage_trade or close_trade only."
        )
    if normalized.get("target_decision_id") != ex_ante.get("decision_id"):
        raise ManagementContractError(
            "management_target_id_mismatch", "target_decision_id must equal the exact origin decision ID."
        )
    assessment = observation["assessment"]
    if normalized["action"] == "manage_trade" and assessment != "management_review":
        raise ManagementContractError(
            "management_watcher_assessment_mismatch", "manage_trade requires management_review."
        )
    if normalized["action"] == "close_trade" and assessment != "close_review":
        raise ManagementContractError(
            "management_watcher_assessment_mismatch", "close_trade requires close_review."
        )
    _validate_thesis_link(normalized, origin, observation)
    projected = _project_action(normalized, state, context)
    decision_digest = master_trader_decision_digest_versioned(normalized)
    record: dict[str, Any] = {
        "ledger_version": MANAGEMENT_LEDGER_VERSION,
        "contract_version": MANAGEMENT_CONTRACT_VERSION,
        "management_action_id": f"aidy_mgmt_{digest([decision_digest, receipt['receipt_digest']])[:24]}",
        "originating_decision_id": ex_ante["decision_id"],
        "originating_ex_ante_digest": ex_ante["ex_ante_digest"],
        "position_id": state["position_id"],
        "paper_state_digest": state["state_digest"],
        "watcher_receipt_digest": receipt["receipt_digest"],
        "watcher_observation_digest": receipt["observation_digest"],
        "context_hash": context["context_hash"],
        "original_thesis_digest": digest(state["thesis_snapshot"]),
        "thesis_assessment": observation["thesis_assessment"],
        "watcher_assessment": observation["assessment"],
        "decision": normalized,
        "decision_digest": decision_digest,
        "projected_transition": projected,
        "paper_only": True,
        "publication_allowed": False,
        "execution_allowed": False,
        "account_sizing_allowed": False,
        "broker_state_used": False,
        "follower_state_used": False,
    }
    record["ledger_digest"] = digest(record)
    return record


def verify_management_action_record(record: Mapping[str, Any]) -> bool:
    if not isinstance(record, Mapping):
        return False
    supplied = str(record.get("ledger_digest") or "")
    body = copy.deepcopy(dict(record))
    body.pop("ledger_digest", None)
    try:
        if body.get("ledger_version") != MANAGEMENT_LEDGER_VERSION:
            return False
        if body.get("contract_version") != MANAGEMENT_CONTRACT_VERSION:
            return False
        if body.get("paper_only") is not True:
            return False
        for key in (
            "publication_allowed",
            "execution_allowed",
            "account_sizing_allowed",
            "broker_state_used",
            "follower_state_used",
        ):
            if body.get(key) is not False:
                return False
        normalized = validate_master_trader_decision_versioned(body["decision"])
        if body.get("decision_digest") != master_trader_decision_digest_versioned(normalized):
            return False
    except (TypeError, ValueError, KeyError):
        return False
    return bool(supplied) and supplied == digest(body)


def reconcile_management_action_record(
    existing: Mapping[str, Any], incoming: Mapping[str, Any]
) -> dict[str, Any]:
    if not verify_management_action_record(existing) or not verify_management_action_record(incoming):
        raise ManagementContractError("management_ledger_invalid", "Cannot reconcile invalid records.")
    if existing["management_action_id"] != incoming["management_action_id"]:
        raise ManagementContractError("management_ledger_identity_mismatch", "Action IDs differ.")
    if existing["ledger_digest"] != incoming["ledger_digest"]:
        raise ManagementContractError("management_ledger_conflict", "Action payloads conflict.")
    return copy.deepcopy(dict(existing))


def day48_manifest() -> dict[str, Any]:
    value: dict[str, Any] = {
        "manifest_version": MANAGEMENT_MANIFEST_VERSION,
        "management_contract_version": MANAGEMENT_CONTRACT_VERSION,
        "management_ledger_version": MANAGEMENT_LEDGER_VERSION,
        "exact_originating_decision_id_required": True,
        "active_paper_state_required": True,
        "watcher_observation_required": True,
        "original_thesis_invalidation_immutable": True,
        "management_must_cite_watcher_reason": True,
        "risk_reducing_stop_geometry_only": True,
        "ambiguous_action_fails_closed": True,
        "every_admitted_action_ledgered": True,
        "paper_only": True,
        "publication_allowed": False,
        "execution_allowed": False,
        "account_sizing_allowed": False,
        "broker_or_follower_state_allowed": False,
        "super_signals_modified": False,
    }
    value["manifest_digest"] = digest(value)
    return value
