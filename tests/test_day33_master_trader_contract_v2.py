from __future__ import annotations

from copy import deepcopy

import pytest

from aidy import master_trader_contract as v1
from aidy.master_trader_contract_v2 import (
    MACHINE_CONDITION_VERSION,
    MASTER_TRADER_CONTRACT_VERSION_V2,
    SUPPORTED_SHADOW_DIRECTIONS,
    evaluate_machine_condition,
    master_trader_contract_manifest_v2,
    master_trader_decision_digest_v2,
    master_trader_decision_digest_versioned,
    master_trader_json_schema_v2,
    master_trader_response_format_v2,
    validate_machine_condition,
    validate_master_trader_decision_v2,
    validate_master_trader_decision_versioned,
)
from aidy.setup_detector import SETUP_TAXONOMY_VERSION


def _condition(
    path: str = "$.gold.quote_context.mid",
    operator: str = "lt",
    value_type: str = "number",
    value: object = 2490.0,
) -> dict[str, object]:
    return {
        "condition_version": MACHINE_CONDITION_VERSION,
        "field_path": path,
        "operator": operator,
        "value_type": value_type,
        "value": value,
    }


def _v1_base(action: str = "no_trade") -> dict[str, object]:
    return {
        "contract_version": v1.MASTER_TRADER_CONTRACT_VERSION,
        "action": action,
        "symbol": "XAUUSD",
        "evaluated_at_utc": "2026-09-01T01:00:00+00:00",
        "valid_until_utc": "2026-09-01T01:15:00+00:00",
        "confidence": 0.72,
        "setup_taxonomy_version": SETUP_TAXONOMY_VERSION,
        "setup_codes": [],
        "reason_codes": ["evidence_insufficient"],
        "decision_summary": "The bounded evidence does not currently justify an actionable trade.",
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


def _v2_base(action: str) -> dict[str, object]:
    base = _v1_base(action)
    base.update(
        {
            "contract_version": MASTER_TRADER_CONTRACT_VERSION_V2,
            "thesis": None,
            "expected_horizon_minutes": None,
            "counter_argument": "Fresh contrary evidence could invalidate the selected action before expiry.",
            "invalidation_condition": None,
            "abstention_basis": None,
            "shadow_thesis": None,
            "shadow_direction": None,
            "shadow_horizon_minutes": None,
            "shadow_evaluation_condition": None,
        }
    )
    return base


def _new_trade() -> dict[str, object]:
    decision = _v2_base("new_trade")
    decision.update(
        {
            "setup_codes": ["trend_pullback_long"],
            "reason_codes": ["trend_pullback_confirmed"],
            "decision_summary": "A confirmed long pullback setup supports a bounded market-entry decision.",
            "direction": "long",
            "entry_type": "market",
            "market_reference_price": 2500.0,
            "stop_loss": 2480.0,
            "targets": [2520.0, 2540.0],
            "thesis": "The accepted pullback should resume the higher-timeframe uptrend over the next session.",
            "expected_horizon_minutes": 240,
            "counter_argument": "A failure back through the pullback low would show sellers regained control instead.",
            "invalidation_condition": _condition(),
        }
    )
    return decision


def _manage_trade() -> dict[str, object]:
    decision = _v2_base("manage_trade")
    decision.update(
        {
            "reason_codes": ["structure_advanced"],
            "decision_summary": "Price structure has advanced enough to justify a defensive stop adjustment.",
            "target_decision_id": "aidy_dec_12345678",
            "management_instruction": "move_stop",
            "new_stop_loss": 2505.0,
            "thesis": "Holding above the reclaimed structure should preserve the original long thesis while reducing downside.",
            "expected_horizon_minutes": 120,
            "counter_argument": "A volatility expansion could revisit the old stop region without invalidating the broader move.",
            "invalidation_condition": _condition(
                path="$.gold.quote_context.mid", operator="lt", value=2500.0
            ),
        }
    )
    return decision


def _close_trade() -> dict[str, object]:
    decision = _v2_base("close_trade")
    decision.update(
        {
            "reason_codes": ["thesis_invalidated"],
            "decision_summary": "The pre-registered thesis invalidation has occurred and the position should be closed.",
            "target_decision_id": "aidy_dec_12345678",
            "close_scope": "full",
            "thesis": "The original directional mechanism has failed and should not be given additional time to recover.",
            "expected_horizon_minutes": 30,
            "counter_argument": "The break could be a temporary liquidity sweep that reverses immediately after closure.",
            "invalidation_condition": _condition(
                path="$.price_structure_context.reclaim_state",
                operator="eq",
                value_type="text",
                value="reclaimed",
            ),
        }
    )
    return decision


def _no_trade() -> dict[str, object]:
    decision = _v2_base("no_trade")
    decision.update(
        {
            "reason_codes": ["evidence_conflicted"],
            "decision_summary": "Conflicting evidence does not justify paying for directional exposure yet.",
            "counter_argument": "The long setup could resolve before all conflicting evidence clears and leave value behind.",
            "abstention_basis": "Trend evidence is constructive but the current volatility and structure state remain conflicted.",
            "shadow_thesis": "If price reclaims the nearby structure, the long continuation hypothesis becomes testable without entry.",
            "shadow_direction": "long",
            "shadow_horizon_minutes": 240,
            "shadow_evaluation_condition": _condition(
                path="$.price_structure_context.reclaim_state",
                operator="eq",
                value_type="text",
                value="reclaimed",
            ),
        }
    )
    return decision


def test_v2_schema_is_strict_and_requires_every_field() -> None:
    schema = master_trader_json_schema_v2()
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["properties"]["contract_version"]["enum"] == [
        MASTER_TRADER_CONTRACT_VERSION_V2
    ]
    assert schema["properties"]["shadow_direction"]["enum"] == [
        *SUPPORTED_SHADOW_DIRECTIONS,
        None,
    ]


def test_v2_response_format_is_strict_json_schema() -> None:
    response_format = master_trader_response_format_v2()
    assert response_format["type"] == "json_schema"
    assert response_format["strict"] is True
    assert response_format["schema"] == master_trader_json_schema_v2()


def test_manifest_preserves_v1_safety_and_defers_gateway_promotion() -> None:
    manifest = master_trader_contract_manifest_v2()
    assert manifest["v1_records_version_readable"] is True
    assert manifest["v1_silent_upgrade_allowed"] is False
    assert manifest["v1_trade_geometry_delegated"] is True
    assert manifest["counter_argument_required_for_all_actions"] is True
    assert manifest["actionable_invalidation_required"] is True
    assert manifest["no_trade_shadow_evaluation_required"] is True
    assert manifest["position_sizing_fields_allowed"] is False
    assert manifest["confidence_controls_position_size"] is False
    assert manifest["hidden_chain_of_thought_required"] is False
    assert manifest["hidden_reasoning_trace_stored"] is False
    assert manifest["gateway_promoted_by_day33"] is False


@pytest.mark.parametrize("factory", [_new_trade, _manage_trade, _close_trade])
def test_actionable_v2_decisions_are_valid_and_falsifiable(factory) -> None:
    result = validate_master_trader_decision_v2(factory())
    assert result["action"] in {"new_trade", "manage_trade", "close_trade"}
    assert result["thesis"]
    assert result["expected_horizon_minutes"] > 0
    assert result["counter_argument"]
    assert result["invalidation_condition"]["condition_version"] == MACHINE_CONDITION_VERSION
    assert result["abstention_basis"] is None
    assert result["shadow_thesis"] is None


def test_no_trade_requires_explicit_abstention_and_shadow_target() -> None:
    result = validate_master_trader_decision_v2(_no_trade())
    assert result["action"] == "no_trade"
    assert result["thesis"] is None
    assert result["expected_horizon_minutes"] is None
    assert result["abstention_basis"]
    assert result["shadow_thesis"]
    assert result["shadow_direction"] == "long"
    assert result["shadow_horizon_minutes"] == 240
    assert result["shadow_evaluation_condition"]


@pytest.mark.parametrize("field", ["thesis", "counter_argument"])
def test_actionable_rejects_missing_or_vague_reasoning_outputs(field: str) -> None:
    decision = _new_trade()
    decision[field] = "bullish"
    with pytest.raises(ValueError, match="vague|characters"):
        validate_master_trader_decision_v2(decision)


def test_actionable_requires_expected_horizon_and_invalidation() -> None:
    decision = _new_trade()
    decision["expected_horizon_minutes"] = None
    with pytest.raises(ValueError, match="expected_horizon_minutes is required"):
        validate_master_trader_decision_v2(decision)
    decision = _new_trade()
    decision["invalidation_condition"] = None
    with pytest.raises(ValueError, match="invalidation_condition is required"):
        validate_master_trader_decision_v2(decision)


@pytest.mark.parametrize("horizon", [0, 10_081, 2.5, True])
def test_horizon_is_bounded_integer_minutes(horizon: object) -> None:
    decision = _new_trade()
    decision["expected_horizon_minutes"] = horizon
    with pytest.raises((TypeError, ValueError), match="expected_horizon_minutes"):
        validate_master_trader_decision_v2(decision)


def test_actionable_rejects_no_trade_shadow_fields() -> None:
    decision = _new_trade()
    decision["shadow_thesis"] = "A conflicting short thesis is being stored in the wrong action surface."
    with pytest.raises(ValueError, match="shadow_thesis must be null"):
        validate_master_trader_decision_v2(decision)


def test_no_trade_rejects_actionable_thesis_or_invalidation() -> None:
    decision = _no_trade()
    decision["thesis"] = "This should not be populated on a no-trade abstention record."
    with pytest.raises(ValueError, match="thesis must be null"):
        validate_master_trader_decision_v2(decision)
    decision = _no_trade()
    decision["invalidation_condition"] = _condition()
    with pytest.raises(ValueError, match="invalidation_condition must be null"):
        validate_master_trader_decision_v2(decision)


def test_no_trade_rejects_missing_or_vague_abstention_shadow_and_counterargument() -> None:
    for field in ("abstention_basis", "shadow_thesis", "counter_argument"):
        decision = _no_trade()
        decision[field] = "maybe"
        with pytest.raises(ValueError, match="vague|characters"):
            validate_master_trader_decision_v2(decision)
    decision = _no_trade()
    decision["shadow_evaluation_condition"] = None
    with pytest.raises(ValueError, match="shadow_evaluation_condition is required"):
        validate_master_trader_decision_v2(decision)


def test_machine_condition_rejects_unsafe_path_unknown_fields_and_type_mismatch() -> None:
    with pytest.raises(ValueError, match="safe absolute JSON path"):
        validate_machine_condition(
            _condition(path="$.gold.*.mid"), name="invalidation_condition"
        )
    malformed = _condition()
    malformed["python_expression"] = "do_something()"
    with pytest.raises(ValueError, match="fields mismatch"):
        validate_machine_condition(malformed, name="invalidation_condition")
    with pytest.raises(ValueError, match="ordering operators require"):
        validate_machine_condition(
            _condition(operator="gt", value_type="text", value="high"),
            name="invalidation_condition",
        )


@pytest.mark.parametrize(
    ("operator", "observed", "expected", "result"),
    [
        ("lt", 2490.0, 2500.0, True),
        ("gte", 2500.0, 2500.0, True),
        ("gt", 2490.0, 2500.0, False),
        ("eq", 2500.0, 2500.0, True),
        ("neq", 2500.0, 2501.0, True),
    ],
)
def test_numeric_machine_conditions_are_deterministically_evaluable(
    operator: str, observed: float, expected: float, result: bool
) -> None:
    context = {"gold": {"quote_context": {"mid": observed}}}
    condition = _condition(operator=operator, value=expected)
    assert evaluate_machine_condition(condition, context) is result


def test_text_boolean_and_indexed_machine_conditions_are_evaluable() -> None:
    context = {
        "regime": {"state": "trending"},
        "flags": {"safe": True},
        "events": [{"tier": "one"}],
    }
    assert evaluate_machine_condition(
        _condition("$.regime.state", "eq", "text", "trending"), context
    ) is True
    assert evaluate_machine_condition(
        _condition("$.flags.safe", "eq", "boolean", True), context
    ) is True
    assert evaluate_machine_condition(
        _condition("$.events[0].tier", "eq", "text", "one"), context
    ) is True


def test_machine_condition_unknown_or_type_mismatch_propagates_unknown() -> None:
    condition = _condition()
    assert evaluate_machine_condition(condition, {"gold": {}}) is None
    assert evaluate_machine_condition(
        condition, {"gold": {"quote_context": {"mid": "2490"}}}
    ) is None


def test_v1_trade_geometry_remains_authoritative_for_v2() -> None:
    decision = _new_trade()
    decision["stop_loss"] = 2510.0
    with pytest.raises(ValueError, match="below market_reference_price"):
        validate_master_trader_decision_v2(decision)
    decision = _new_trade()
    decision["entry_type"] = "limit"
    with pytest.raises(ValueError, match="market entries only"):
        validate_master_trader_decision_v2(decision)


def test_v1_records_remain_readable_without_silent_upgrade() -> None:
    old = _v1_base()
    expected = v1.validate_master_trader_decision(old)
    result = validate_master_trader_decision_versioned(old)
    assert result == expected
    assert result["contract_version"] == v1.MASTER_TRADER_CONTRACT_VERSION
    assert "thesis" not in result
    assert master_trader_decision_digest_versioned(old) == v1.master_trader_decision_digest(old)


def test_v2_versioned_reader_preserves_v2_contract() -> None:
    decision = _new_trade()
    result = validate_master_trader_decision_versioned(decision)
    assert result["contract_version"] == MASTER_TRADER_CONTRACT_VERSION_V2
    assert result == validate_master_trader_decision_v2(decision)


def test_unknown_contract_version_fails_closed() -> None:
    decision = _v1_base()
    decision["contract_version"] = "aidy_master_trader_decision_v99"
    with pytest.raises(ValueError, match="Unsupported Master Trader contract version"):
        validate_master_trader_decision_versioned(decision)


def test_position_sizing_and_hidden_reasoning_fields_stay_forbidden() -> None:
    for field in ("lot_size", "risk_pct", "analysis", "chain_of_thought", "scratchpad"):
        decision = _new_trade()
        decision[field] = "forbidden"
        with pytest.raises(ValueError, match="unsupported fields"):
            validate_master_trader_decision_v2(decision)


def test_v2_digest_is_deterministic_and_reasoning_sensitive() -> None:
    first = _new_trade()
    second = deepcopy(first)
    assert master_trader_decision_digest_v2(first) == master_trader_decision_digest_v2(second)
    second["counter_argument"] = (
        "A stronger contrary break could invalidate the directional case before the expected horizon."
    )
    assert master_trader_decision_digest_v2(first) != master_trader_decision_digest_v2(second)
