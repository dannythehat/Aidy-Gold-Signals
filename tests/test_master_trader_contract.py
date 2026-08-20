from __future__ import annotations

from copy import deepcopy

import pytest

from aidy.master_trader_contract import (
    MASTER_TRADER_CONTRACT_VERSION,
    SUPPORTED_ACTIONS,
    master_trader_contract_manifest,
    master_trader_decision_digest,
    master_trader_json_schema,
    master_trader_response_format,
    validate_master_trader_decision,
)
from aidy.setup_detector import SETUP_DEFINITIONS, SETUP_TAXONOMY_VERSION


def _base(action: str) -> dict[str, object]:
    return {
        "contract_version": MASTER_TRADER_CONTRACT_VERSION,
        "action": action,
        "symbol": "XAUUSD",
        "evaluated_at_utc": "2026-08-20T12:00:00+00:00",
        "valid_until_utc": "2026-08-20T12:15:00+00:00",
        "confidence": 0.75,
        "setup_taxonomy_version": SETUP_TAXONOMY_VERSION,
        "setup_codes": [],
        "reason_codes": ["evidence_supportive"],
        "decision_summary": "The accepted evidence supports this bounded decision.",
        "target_decision_id": None,
        "direction": None,
        "entry_type": None,
        "market_reference_price": None,
        "stop_loss": None,
        "targets": [],
        "management_instruction": None,
        "new_stop_loss": None,
        "new_targets": [],
        "close_scope": None,
    }


def _long_new_trade() -> dict[str, object]:
    decision = _base("new_trade")
    decision.update(
        {
            "setup_codes": ["trend_pullback_long"],
            "direction": "long",
            "entry_type": "market",
            "market_reference_price": 2500.0,
            "stop_loss": 2480.0,
            "targets": [2520.0, 2540.0],
        }
    )
    return decision


def _short_new_trade() -> dict[str, object]:
    decision = _base("new_trade")
    decision.update(
        {
            "setup_codes": ["trend_pullback_short"],
            "direction": "short",
            "entry_type": "market",
            "market_reference_price": 2500.0,
            "stop_loss": 2520.0,
            "targets": [2480.0, 2460.0],
        }
    )
    return decision


def _manage(instruction: str) -> dict[str, object]:
    decision = _base("manage_trade")
    decision["target_decision_id"] = "aidy_dec_12345678"
    decision["management_instruction"] = instruction
    if instruction == "move_stop":
        decision["new_stop_loss"] = 2505.0
    elif instruction == "replace_targets":
        decision["new_targets"] = [2550.0, 2575.0]
    elif instruction == "move_stop_and_targets":
        decision["new_stop_loss"] = 2505.0
        decision["new_targets"] = [2550.0, 2575.0]
    return decision


def _close() -> dict[str, object]:
    decision = _base("close_trade")
    decision["target_decision_id"] = "aidy_dec_12345678"
    decision["close_scope"] = "full"
    return decision


def test_schema_is_strict_all_fields_required_and_flat():
    schema = master_trader_json_schema()
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["properties"]["action"]["enum"] == list(SUPPORTED_ACTIONS)


def test_response_format_is_strict_json_schema():
    response_format = master_trader_response_format()
    assert response_format["type"] == "json_schema"
    assert response_format["strict"] is True
    assert response_format["schema"] == master_trader_json_schema()


def test_schema_contains_no_position_sizing_or_hidden_reasoning_fields():
    text = str(master_trader_json_schema()).lower()
    for forbidden in (
        "lot_size",
        "position_size",
        "risk_percent",
        "risk_pct",
        "account_balance",
        "account_equity",
        "chain_of_thought",
        "hidden_reasoning",
        "reasoning_trace",
        "scratchpad",
    ):
        assert forbidden not in text


def test_schema_uses_exact_day15_setup_taxonomy():
    schema_codes = set(
        master_trader_json_schema()["properties"]["setup_codes"]["items"]["enum"]
    )
    detector_codes = {item["setup_id"] for item in SETUP_DEFINITIONS}
    assert schema_codes == detector_codes
    assert len(schema_codes) == 20


def test_manifest_locks_safety_and_non_execution_boundaries():
    manifest = master_trader_contract_manifest()
    assert manifest["no_trade_first_class"] is True
    assert manifest["pending_orders_supported"] is False
    assert manifest["position_sizing_fields_allowed"] is False
    assert manifest["confidence_controls_position_size"] is False
    assert manifest["hidden_chain_of_thought_required"] is False
    assert manifest["gateway_implemented_by_this_contract"] is False
    assert manifest["execution_implemented_by_this_contract"] is False


def test_valid_long_new_trade():
    result = validate_master_trader_decision(_long_new_trade())
    assert result["action"] == "new_trade"
    assert result["direction"] == "long"
    assert result["entry_type"] == "market"


def test_valid_short_new_trade():
    result = validate_master_trader_decision(_short_new_trade())
    assert result["direction"] == "short"


def test_new_trade_requires_xauusd():
    decision = _long_new_trade()
    decision["symbol"] = "EURUSD"
    with pytest.raises(ValueError, match="XAUUSD"):
        validate_master_trader_decision(decision)


def test_new_trade_rejects_pending_entry_type():
    decision = _long_new_trade()
    decision["entry_type"] = "limit"
    with pytest.raises(ValueError, match="market entries only"):
        validate_master_trader_decision(decision)


def test_new_trade_requires_setup_code():
    decision = _long_new_trade()
    decision["setup_codes"] = []
    with pytest.raises(ValueError, match="at least one"):
        validate_master_trader_decision(decision)


def test_new_trade_rejects_unknown_setup_code():
    decision = _long_new_trade()
    decision["setup_codes"] = ["future_magic_setup"]
    with pytest.raises(ValueError, match="unsupported code"):
        validate_master_trader_decision(decision)


@pytest.mark.parametrize("stop", [2500.0, 2510.0])
def test_long_stop_must_be_below_reference(stop: float):
    decision = _long_new_trade()
    decision["stop_loss"] = stop
    with pytest.raises(ValueError, match="below"):
        validate_master_trader_decision(decision)


@pytest.mark.parametrize("stop", [2500.0, 2490.0])
def test_short_stop_must_be_above_reference(stop: float):
    decision = _short_new_trade()
    decision["stop_loss"] = stop
    with pytest.raises(ValueError, match="above"):
        validate_master_trader_decision(decision)


def test_new_trade_requires_one_to_three_targets():
    decision = _long_new_trade()
    decision["targets"] = []
    with pytest.raises(ValueError, match="between 1 and 3"):
        validate_master_trader_decision(decision)
    decision["targets"] = [2510.0, 2520.0, 2530.0, 2540.0]
    with pytest.raises(ValueError, match="between 1 and 3"):
        validate_master_trader_decision(decision)


def test_long_targets_must_be_above_and_increasing():
    decision = _long_new_trade()
    decision["targets"] = [2540.0, 2520.0]
    with pytest.raises(ValueError, match="increasing"):
        validate_master_trader_decision(decision)
    decision["targets"] = [2490.0]
    with pytest.raises(ValueError, match="above"):
        validate_master_trader_decision(decision)


def test_short_targets_must_be_below_and_decreasing():
    decision = _short_new_trade()
    decision["targets"] = [2460.0, 2480.0]
    with pytest.raises(ValueError, match="decreasing"):
        validate_master_trader_decision(decision)
    decision["targets"] = [2510.0]
    with pytest.raises(ValueError, match="below"):
        validate_master_trader_decision(decision)


def test_new_trade_rejects_management_fields():
    decision = _long_new_trade()
    decision["new_stop_loss"] = 2501.0
    with pytest.raises(ValueError, match="new_stop_loss"):
        validate_master_trader_decision(decision)


def test_no_trade_is_valid_first_class_with_no_setup():
    decision = _base("no_trade")
    decision["reason_codes"] = ["setup_absent"]
    result = validate_master_trader_decision(decision)
    assert result["action"] == "no_trade"
    assert result["setup_codes"] == []


def test_no_trade_may_record_observed_setup_without_creating_trade():
    decision = _base("no_trade")
    decision["setup_codes"] = ["trend_pullback_long"]
    decision["reason_codes"] = ["evidence_insufficient"]
    result = validate_master_trader_decision(decision)
    assert result["action"] == "no_trade"
    assert result["setup_codes"] == ["trend_pullback_long"]


def test_no_trade_rejects_trade_geometry():
    decision = _base("no_trade")
    decision["stop_loss"] = 2490.0
    with pytest.raises(ValueError, match="stop_loss"):
        validate_master_trader_decision(decision)


@pytest.mark.parametrize(
    "instruction",
    ["move_stop", "replace_targets", "move_stop_and_targets"],
)
def test_valid_manage_trade_variants(instruction: str):
    result = validate_master_trader_decision(_manage(instruction))
    assert result["action"] == "manage_trade"
    assert result["management_instruction"] == instruction
    assert result["target_decision_id"] == "aidy_dec_12345678"


def test_manage_trade_requires_explicit_target_decision_id():
    decision = _manage("move_stop")
    decision["target_decision_id"] = None
    with pytest.raises(ValueError, match="required"):
        validate_master_trader_decision(decision)


def test_manage_trade_rejects_malformed_instruction_payloads():
    decision = _manage("move_stop")
    decision["new_targets"] = [2550.0]
    with pytest.raises(ValueError, match="move_stop requires"):
        validate_master_trader_decision(decision)

    decision = _manage("replace_targets")
    decision["new_targets"] = []
    with pytest.raises(ValueError, match="replace_targets requires"):
        validate_master_trader_decision(decision)

    decision = _manage("move_stop_and_targets")
    decision["new_stop_loss"] = None
    with pytest.raises(ValueError, match="requires"):
        validate_master_trader_decision(decision)


def test_manage_trade_rejects_new_trade_geometry():
    decision = _manage("move_stop")
    decision["market_reference_price"] = 2500.0
    with pytest.raises(ValueError, match="market_reference_price"):
        validate_master_trader_decision(decision)


def test_valid_close_trade_requires_exact_target_and_full_scope():
    result = validate_master_trader_decision(_close())
    assert result["action"] == "close_trade"
    assert result["target_decision_id"] == "aidy_dec_12345678"
    assert result["close_scope"] == "full"


def test_close_trade_requires_target_decision_id():
    decision = _close()
    decision["target_decision_id"] = None
    with pytest.raises(ValueError, match="required"):
        validate_master_trader_decision(decision)


def test_close_trade_rejects_partial_close():
    decision = _close()
    decision["close_scope"] = "partial"
    with pytest.raises(ValueError, match="full close only"):
        validate_master_trader_decision(decision)


def test_new_trade_and_no_trade_reject_target_decision_id():
    for decision in (_long_new_trade(), _base("no_trade")):
        decision["target_decision_id"] = "aidy_dec_12345678"
        with pytest.raises(ValueError, match="must be null"):
            validate_master_trader_decision(decision)


@pytest.mark.parametrize("confidence", [-0.01, 1.01, "0.8", True])
def test_confidence_must_be_numeric_zero_to_one(confidence: object):
    decision = _base("no_trade")
    decision["confidence"] = confidence
    with pytest.raises((TypeError, ValueError), match="confidence"):
        validate_master_trader_decision(decision)


def test_confidence_does_not_unlock_position_sizing_fields():
    decision = _long_new_trade()
    decision["confidence"] = 1.0
    decision["lot_size"] = 10
    with pytest.raises(ValueError, match="Position-sizing"):
        validate_master_trader_decision(decision)


@pytest.mark.parametrize("field", ["analysis", "chain_of_thought", "reasoning_trace"])
def test_hidden_reasoning_trace_fields_are_rejected(field: str):
    decision = _base("no_trade")
    decision[field] = "private reasoning"
    with pytest.raises(ValueError, match="Hidden reasoning-trace"):
        validate_master_trader_decision(decision)


def test_unknown_extra_field_is_rejected():
    decision = _base("no_trade")
    decision["temperature"] = 0.2
    with pytest.raises(ValueError, match="unsupported fields"):
        validate_master_trader_decision(decision)


def test_missing_required_field_is_rejected():
    decision = _base("no_trade")
    del decision["decision_summary"]
    with pytest.raises(ValueError, match="missing fields"):
        validate_master_trader_decision(decision)


def test_reason_codes_are_required_stable_unique_slugs():
    decision = _base("no_trade")
    decision["reason_codes"] = []
    with pytest.raises(ValueError, match="between 1 and 8"):
        validate_master_trader_decision(decision)
    decision["reason_codes"] = ["same_reason", "same_reason"]
    with pytest.raises(ValueError, match="duplicates"):
        validate_master_trader_decision(decision)
    decision["reason_codes"] = ["Not-A-Slug"]
    with pytest.raises(ValueError, match="invalid code"):
        validate_master_trader_decision(decision)


def test_validity_must_expire_after_evaluation():
    decision = _base("no_trade")
    decision["valid_until_utc"] = decision["evaluated_at_utc"]
    with pytest.raises(ValueError, match="after"):
        validate_master_trader_decision(decision)


def test_timestamps_must_be_timezone_aware():
    decision = _base("no_trade")
    decision["evaluated_at_utc"] = "2026-08-20T12:00:00"
    with pytest.raises(ValueError, match="timezone-aware"):
        validate_master_trader_decision(decision)


def test_target_decision_id_format_is_bounded_and_safe():
    decision = _close()
    decision["target_decision_id"] = "bad id with spaces"
    with pytest.raises(ValueError, match="unsafe"):
        validate_master_trader_decision(decision)


def test_decision_summary_is_final_summary_not_unbounded_reasoning():
    decision = _base("no_trade")
    decision["decision_summary"] = "x" * 501
    with pytest.raises(ValueError, match="1-500"):
        validate_master_trader_decision(decision)


def test_prices_must_be_json_numbers_not_numeric_strings():
    decision = _long_new_trade()
    decision["market_reference_price"] = "2500.0"
    with pytest.raises(TypeError, match="JSON number"):
        validate_master_trader_decision(decision)


def test_digest_is_deterministic_and_decision_sensitive():
    first = _base("no_trade")
    second = deepcopy(first)
    assert master_trader_decision_digest(first) == master_trader_decision_digest(second)

    second["confidence"] = 0.76
    assert master_trader_decision_digest(first) != master_trader_decision_digest(second)


def test_validator_normalizes_utc_timestamps_without_changing_action():
    decision = _base("no_trade")
    decision["evaluated_at_utc"] = "2026-08-20T15:00:00+03:00"
    decision["valid_until_utc"] = "2026-08-20T15:15:00+03:00"
    result = validate_master_trader_decision(decision)
    assert result["evaluated_at_utc"] == "2026-08-20T12:00:00+00:00"
    assert result["valid_until_utc"] == "2026-08-20T12:15:00+00:00"
