from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from aidy.management_contract_v2 import verify_management_action_record
from aidy.paper_simulator import _event_digest, _state_digest, verify_paper_state
from aidy.pit_reconstruction import normalize_as_of

PAPER_MANAGEMENT_RUNTIME_VERSION = "aidy_paper_management_runtime_v1"


class PaperManagementRuntimeError(ValueError):
    pass


def _decimal(value: Any, *, name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise PaperManagementRuntimeError(f"{name} is required.")
    parsed = Decimal(str(value))
    if not parsed.is_finite() or parsed <= 0:
        raise PaperManagementRuntimeError(f"{name} must be positive and finite.")
    return parsed


def apply_management_to_paper_state(
    state: Mapping[str, Any],
    management_action: Mapping[str, Any],
    *,
    observed_at_utc: datetime | str,
    current_mid: Any,
) -> dict[str, Any]:
    """Apply one Day-48 manage_trade action to the active Day-46 state.

    close_trade is deliberately terminal and returns a closure record instead
    of forging a Day-46 state whose original contract did not define
    `closed_management`.
    """

    if not verify_paper_state(state):
        raise PaperManagementRuntimeError("Verified active Day-46 paper state required.")
    if not verify_management_action_record(management_action):
        raise PaperManagementRuntimeError("Verified Day-48 management action required.")
    action = management_action["decision"]
    if management_action.get("position_id") != state.get("position_id"):
        raise PaperManagementRuntimeError("Management action targets a different paper position.")
    if management_action.get("originating_decision_id") != state.get("decision_id"):
        raise PaperManagementRuntimeError("Management action targets a different origin decision.")
    if management_action.get("paper_state_digest") != state.get("state_digest"):
        raise PaperManagementRuntimeError("Management action was evaluated on a stale paper state.")

    stamp = normalize_as_of(observed_at_utc)
    mid = _decimal(current_mid, name="current_mid")
    if action["action"] == "close_trade":
        return {
            "runtime_version": PAPER_MANAGEMENT_RUNTIME_VERSION,
            "state_type": "terminal_management_close",
            "position_id": state["position_id"],
            "originating_decision_id": state["decision_id"],
            "management_action_id": management_action["management_action_id"],
            "previous_paper_state_digest": state["state_digest"],
            "closed_at_utc": stamp.isoformat(),
            "closed_price": str(mid),
            "paper_only": True,
            "execution_allowed": False,
            "watcher_can_run_again": False,
            "formal_forward_evidence": False,
        }

    if action["action"] != "manage_trade":
        raise PaperManagementRuntimeError("Only manage_trade or close_trade is supported.")

    updated = copy.deepcopy(dict(state))
    updated.pop("state_digest", None)
    projected = management_action["projected_transition"]
    if action["management_instruction"] in {"move_stop", "move_stop_and_targets"}:
        updated["stop_loss"] = str(projected["stop_loss"])
    if action["management_instruction"] in {"replace_targets", "move_stop_and_targets"}:
        replacements = list(projected.get("replacement_targets") or [])
        remaining = list(updated["remaining_target_indices"])
        if len(replacements) != len(remaining):
            raise PaperManagementRuntimeError(
                "Runtime requires one replacement target per remaining paper leg."
            )
        for leg_index, replacement in zip(remaining, replacements, strict=True):
            updated["targets"][int(leg_index) - 1] = str(replacement)

    event: dict[str, Any] = {
        "event_type": "management_action",
        "event_index": len(updated["lifecycle_events"]),
        "as_of_utc": stamp.isoformat(),
        "observation_digest": None,
        "mid": str(mid),
        "target_hits": [],
        "stop_hit": False,
        "invalidation_result": "not_evaluated",
        "resulting_state": updated["position_state"],
        "management_action_id": management_action["management_action_id"],
        "management_action_digest": management_action["ledger_digest"],
        "runtime_version": PAPER_MANAGEMENT_RUNTIME_VERSION,
    }
    event["event_digest"] = _event_digest(event)
    updated["lifecycle_events"].append(event)
    updated["state_digest"] = _state_digest(updated)
    if not verify_paper_state(updated):
        raise PaperManagementRuntimeError("Managed paper state failed deterministic verification.")
    return updated
