from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from aidy.master_trader_contract import (
    master_trader_decision_digest,
    validate_master_trader_decision,
)
from aidy.self_consistency import (
    canonical_json,
    digest,
    self_consistency_ledger_state,
    verify_self_consistency_result,
)

SELF_CONSISTENCY_LEDGER_PROJECTION_VERSION = "aidy_self_consistency_ledger_projection_v1"


def build_self_consistency_selective_layer_state(
    result: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the Day-34-compatible ledger projection with all three sample decisions."""

    if not verify_self_consistency_result(result):
        raise ValueError("Self-consistency result is invalid.")
    receipts = result.get("sample_receipts")
    if not isinstance(receipts, list) or len(receipts) != 3:
        raise ValueError("Self-consistency result must contain exactly three sample receipts.")

    sample_decisions: list[dict[str, Any] | None] = []
    for index, receipt in enumerate(receipts, start=1):
        if not isinstance(receipt, Mapping):
            raise TypeError(f"sample_receipts[{index - 1}] must be a mapping.")
        raw = receipt.get("decision")
        if raw is None:
            sample_decisions.append(None)
            continue
        if not isinstance(raw, Mapping):
            raise TypeError(f"sample_receipts[{index - 1}].decision must be a mapping or null.")
        decision = validate_master_trader_decision(raw)
        expected_digest = master_trader_decision_digest(decision)
        if receipt.get("decision_digest") != expected_digest:
            raise ValueError(f"sample {index} decision digest does not match its validated decision.")
        sample_decisions.append(copy.deepcopy(decision))

    state = self_consistency_ledger_state(result)
    state["ledger_projection_version"] = SELF_CONSISTENCY_LEDGER_PROJECTION_VERSION
    state["sample_decisions"] = sample_decisions
    state["all_three_sample_slots_ledgered"] = len(sample_decisions) == 3
    state["sample_decision_count"] = sum(item is not None for item in sample_decisions)
    state["ledger_projection_digest"] = digest(state)
    return state


def verify_self_consistency_selective_layer_state(state: Mapping[str, Any]) -> bool:
    if not isinstance(state, Mapping):
        return False
    if state.get("ledger_projection_version") != SELF_CONSISTENCY_LEDGER_PROJECTION_VERSION:
        return False
    decisions = state.get("sample_decisions")
    if not isinstance(decisions, list) or len(decisions) != 3:
        return False
    if state.get("all_three_sample_slots_ledgered") is not True:
        return False
    supplied = str(state.get("ledger_projection_digest") or "")
    body = copy.deepcopy(dict(state))
    body.pop("ledger_projection_digest", None)
    try:
        for decision in decisions:
            if decision is not None:
                validate_master_trader_decision(decision)
        canonical_json(body)
    except (TypeError, ValueError):
        return False
    return bool(supplied) and supplied == digest(body)
