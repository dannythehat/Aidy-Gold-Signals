from __future__ import annotations

import copy
import json
import math
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy import master_trader_contract as v1

MASTER_TRADER_CONTRACT_VERSION_V2 = "aidy_master_trader_decision_v2_falsifiable"
MASTER_TRADER_SCHEMA_NAME_V2 = "aidy_master_trader_decision_v2_falsifiable"
MASTER_TRADER_SCHEMA_VERSION_V2 = "aidy_master_trader_json_schema_v2_falsifiable"
MASTER_TRADER_MANIFEST_VERSION_V2 = "aidy_master_trader_contract_manifest_v2_falsifiable"
MASTER_TRADER_COMPATIBILITY_VERSION = "aidy_master_trader_version_reader_v1"
MACHINE_CONDITION_VERSION = "aidy_machine_evaluable_condition_v1"

SUPPORTED_CONDITION_OPERATORS = ("eq", "neq", "lt", "lte", "gt", "gte")
SUPPORTED_CONDITION_VALUE_TYPES = ("number", "text", "boolean")
SUPPORTED_SHADOW_DIRECTIONS = ("long", "short", "flat")
MIN_HORIZON_MINUTES = 1
MAX_HORIZON_MINUTES = 10_080

_V1_FIELDS = tuple(v1.master_trader_json_schema()["properties"])
_V2_FIELDS = (
    "thesis",
    "expected_horizon_minutes",
    "counter_argument",
    "invalidation_condition",
    "abstention_basis",
    "shadow_thesis",
    "shadow_direction",
    "shadow_horizon_minutes",
    "shadow_evaluation_condition",
)
_REQUIRED_FIELDS = frozenset((*_V1_FIELDS, *_V2_FIELDS))
_ACTIONABLE_ACTIONS = frozenset({"new_trade", "manage_trade", "close_trade"})
_PATH = re.compile(
    r"^\$\.[A-Za-z_][A-Za-z0-9_]*(?:(?:\.[A-Za-z_][A-Za-z0-9_]*)|(?:\[\d+\]))*$"
)
_WORD = re.compile(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)?")
_VAGUE_STATEMENTS = frozenset(
    {
        "bullish",
        "bearish",
        "looks good",
        "looks bad",
        "maybe",
        "not sure",
        "n/a",
        "na",
        "none",
        "unknown",
        "trade looks good",
        "trade looks bad",
        "evidence supportive",
        "evidence insufficient",
    }
)
_FORBIDDEN_CONDITION_SEGMENTS = frozenset(
    {
        "account",
        "account_balance",
        "account_equity",
        "account_id",
        "analysis",
        "balance",
        "broker",
        "broker_account",
        "chain_of_thought",
        "counterfactual",
        "equity",
        "evaluation_only",
        "follower",
        "follower_id",
        "future_evaluation",
        "future_return",
        "future_returns",
        "hidden_reasoning",
        "horizon_assessments",
        "lot_size",
        "mae",
        "margin",
        "metaapi",
        "mfe",
        "mt5",
        "outcome",
        "outcome_label",
        "outcomes",
        "pnl",
        "position",
        "position_id",
        "realized_pnl",
        "reasoning_trace",
        "risk_pct",
        "risk_percent",
        "scratchpad",
        "super_signals",
        "telegram",
        "thoughts",
        "ticket",
        "vantage",
    }
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _bounded_statement(
    value: Any,
    *,
    name: str,
    minimum_characters: int = 12,
    maximum_characters: int = 400,
    minimum_words: int = 3,
) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be text.")
    text = " ".join(value.strip().split())
    if not minimum_characters <= len(text) <= maximum_characters:
        raise ValueError(
            f"{name} must contain {minimum_characters}-{maximum_characters} characters."
        )
    words = _WORD.findall(text)
    if len(words) < minimum_words or text.casefold() in _VAGUE_STATEMENTS:
        raise ValueError(f"{name} is too vague to be auditable.")
    return text


def _horizon(value: Any, *, name: str, required: bool) -> int | None:
    if value is None:
        if required:
            raise ValueError(f"{name} is required for this action.")
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer number of minutes or null.")
    if not MIN_HORIZON_MINUTES <= value <= MAX_HORIZON_MINUTES:
        raise ValueError(
            f"{name} must be between {MIN_HORIZON_MINUTES} and {MAX_HORIZON_MINUTES} minutes."
        )
    return value


def _condition_value(value: Any, *, value_type: str, name: str) -> Any:
    if value_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{name}.value must be a JSON number for value_type=number.")
        if not math.isfinite(float(value)):
            raise ValueError(f"{name}.value must be finite.")
        return value
    if value_type == "text":
        if not isinstance(value, str):
            raise TypeError(f"{name}.value must be text for value_type=text.")
        text = value.strip()
        if not 1 <= len(text) <= 200:
            raise ValueError(f"{name}.value text must contain 1-200 characters.")
        return text
    if value_type == "boolean":
        if not isinstance(value, bool):
            raise TypeError(f"{name}.value must be boolean for value_type=boolean.")
        return value
    raise ValueError(f"{name}.value_type is unsupported.")


def _path_tokens(path: str) -> list[str | int]:
    if not _PATH.fullmatch(path):
        raise ValueError("field_path must be a validated absolute JSON path.")
    raw = path[2:]
    tokens: list[str | int] = []
    cursor = 0
    while cursor < len(raw):
        key_match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", raw[cursor:])
        if key_match is None:
            raise ValueError("field_path contains an invalid token.")
        key = key_match.group(0)
        tokens.append(key)
        cursor += len(key)
        while cursor < len(raw) and raw[cursor] == "[":
            end = raw.find("]", cursor)
            if end < 0:
                raise ValueError("field_path contains an unclosed index.")
            tokens.append(int(raw[cursor + 1 : end]))
            cursor = end + 1
        if cursor == len(raw):
            break
        if raw[cursor] != ".":
            raise ValueError("field_path contains an invalid separator.")
        cursor += 1
    return tokens


def validate_machine_condition(value: Any, *, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a JSON object.")
    required = {"condition_version", "field_path", "operator", "value_type", "value"}
    fields = set(value)
    if fields != required:
        missing = sorted(required - fields)
        extras = sorted(fields - required)
        raise ValueError(f"{name} fields mismatch; missing={missing}, extras={extras}.")
    if value["condition_version"] != MACHINE_CONDITION_VERSION:
        raise ValueError(f"{name}.condition_version is unsupported.")
    field_path = value["field_path"]
    if not isinstance(field_path, str) or not _PATH.fullmatch(field_path.strip()):
        raise ValueError(f"{name}.field_path must be a safe absolute JSON path.")
    normalized_path = field_path.strip()
    path_segments = {
        token.casefold() for token in _path_tokens(normalized_path) if isinstance(token, str)
    }
    forbidden = sorted(path_segments & _FORBIDDEN_CONDITION_SEGMENTS)
    if forbidden:
        raise ValueError(f"{name}.field_path contains forbidden evidence segments: {forbidden}.")
    operator = value["operator"]
    if operator not in SUPPORTED_CONDITION_OPERATORS:
        raise ValueError(f"{name}.operator is unsupported.")
    value_type = value["value_type"]
    if value_type not in SUPPORTED_CONDITION_VALUE_TYPES:
        raise ValueError(f"{name}.value_type is unsupported.")
    if operator in {"lt", "lte", "gt", "gte"} and value_type != "number":
        raise ValueError(f"{name} ordering operators require value_type=number.")
    normalized_value = _condition_value(value["value"], value_type=value_type, name=name)
    return {
        "condition_version": MACHINE_CONDITION_VERSION,
        "field_path": normalized_path,
        "operator": operator,
        "value_type": value_type,
        "value": normalized_value,
    }


def _resolve_path(context: Mapping[str, Any], path: str) -> Any:
    current: Any = context
    for token in _path_tokens(path):
        if isinstance(token, str):
            if not isinstance(current, Mapping) or token not in current:
                return None
            current = current[token]
        else:
            if (
                not isinstance(current, Sequence)
                or isinstance(current, (str, bytes, bytearray))
                or token >= len(current)
            ):
                return None
            current = current[token]
    return current


def _decimal_observation(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if not isinstance(value, (int, float, Decimal, str)):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def evaluate_machine_condition(
    condition: Mapping[str, Any], context: Mapping[str, Any]
) -> bool | None:
    """Evaluate a validated condition; unavailable/type-mismatched evidence stays UNKNOWN."""

    normalized = validate_machine_condition(condition, name="condition")
    observed = _resolve_path(context, normalized["field_path"])
    value_type = normalized["value_type"]
    if value_type == "number":
        observed_number = _decimal_observation(observed)
        expected_number = _decimal_observation(normalized["value"])
        if observed_number is None or expected_number is None:
            return None
        left: Any = observed_number
        right: Any = expected_number
    elif value_type == "text":
        if not isinstance(observed, str):
            return None
        left = observed
        right = normalized["value"]
    else:
        if not isinstance(observed, bool):
            return None
        left = observed
        right = normalized["value"]

    operator = normalized["operator"]
    if operator == "eq":
        return left == right
    if operator == "neq":
        return left != right
    if operator == "lt":
        return left < right
    if operator == "lte":
        return left <= right
    if operator == "gt":
        return left > right
    if operator == "gte":
        return left >= right
    raise AssertionError("Validated operator became unsupported.")


def _validate_actionable(decision: Mapping[str, Any], normalized: dict[str, Any]) -> None:
    normalized["thesis"] = _bounded_statement(decision["thesis"], name="thesis")
    normalized["counter_argument"] = _bounded_statement(
        decision["counter_argument"], name="counter_argument"
    )
    normalized["expected_horizon_minutes"] = _horizon(
        decision["expected_horizon_minutes"],
        name="expected_horizon_minutes",
        required=True,
    )
    if decision["invalidation_condition"] is None:
        raise ValueError("invalidation_condition is required for actionable decisions.")
    normalized["invalidation_condition"] = validate_machine_condition(
        decision["invalidation_condition"], name="invalidation_condition"
    )
    for field in (
        "abstention_basis",
        "shadow_thesis",
        "shadow_direction",
        "shadow_horizon_minutes",
        "shadow_evaluation_condition",
    ):
        if decision[field] is not None:
            raise ValueError(f"{field} must be null for actionable decisions.")
        normalized[field] = None


def _validate_no_trade(decision: Mapping[str, Any], normalized: dict[str, Any]) -> None:
    if decision["thesis"] is not None:
        raise ValueError("thesis must be null for no_trade; use abstention_basis and shadow_thesis.")
    if decision["expected_horizon_minutes"] is not None:
        raise ValueError("expected_horizon_minutes must be null for no_trade.")
    if decision["invalidation_condition"] is not None:
        raise ValueError("invalidation_condition must be null for no_trade.")
    normalized["thesis"] = None
    normalized["expected_horizon_minutes"] = None
    normalized["invalidation_condition"] = None
    normalized["counter_argument"] = _bounded_statement(
        decision["counter_argument"], name="counter_argument"
    )
    normalized["abstention_basis"] = _bounded_statement(
        decision["abstention_basis"], name="abstention_basis"
    )
    normalized["shadow_thesis"] = _bounded_statement(
        decision["shadow_thesis"], name="shadow_thesis"
    )
    shadow_direction = decision["shadow_direction"]
    if shadow_direction not in SUPPORTED_SHADOW_DIRECTIONS:
        raise ValueError("shadow_direction must be long, short or flat for no_trade.")
    normalized["shadow_direction"] = shadow_direction
    normalized["shadow_horizon_minutes"] = _horizon(
        decision["shadow_horizon_minutes"],
        name="shadow_horizon_minutes",
        required=True,
    )
    if decision["shadow_evaluation_condition"] is None:
        raise ValueError("shadow_evaluation_condition is required for no_trade.")
    normalized["shadow_evaluation_condition"] = validate_machine_condition(
        decision["shadow_evaluation_condition"], name="shadow_evaluation_condition"
    )


def _v1_payload(decision: Mapping[str, Any]) -> dict[str, Any]:
    payload = {field: copy.deepcopy(decision[field]) for field in _V1_FIELDS}
    payload["contract_version"] = v1.MASTER_TRADER_CONTRACT_VERSION
    return payload


def validate_master_trader_decision_v2(decision: Mapping[str, Any]) -> dict[str, Any]:
    """Validate V2 reasoning metadata while delegating accepted trade geometry to Day 20 V1."""

    if not isinstance(decision, Mapping):
        raise TypeError("Master Trader V2 decision must be a JSON object.")
    fields = set(decision)
    missing = _REQUIRED_FIELDS - fields
    extras = fields - _REQUIRED_FIELDS
    if missing:
        raise ValueError(f"Master Trader V2 decision is missing fields: {sorted(missing)}")
    if extras:
        raise ValueError(f"Master Trader V2 decision contains unsupported fields: {sorted(extras)}")
    if decision["contract_version"] != MASTER_TRADER_CONTRACT_VERSION_V2:
        raise ValueError("Unsupported Master Trader V2 contract version.")

    # Delegation preserves every accepted Day-20 geometry, symbol, setup, sizing and hidden-trace rule.
    v1_normalized = v1.validate_master_trader_decision(_v1_payload(decision))
    normalized = copy.deepcopy(dict(decision))
    for field, value in v1_normalized.items():
        if field != "contract_version":
            normalized[field] = value
    normalized["contract_version"] = MASTER_TRADER_CONTRACT_VERSION_V2

    action = normalized["action"]
    if action in _ACTIONABLE_ACTIONS:
        _validate_actionable(decision, normalized)
    else:
        _validate_no_trade(decision, normalized)
    return normalized


def validate_master_trader_decision_versioned(decision: Mapping[str, Any]) -> dict[str, Any]:
    """Read V1 and V2 records without silently upgrading V1 history."""

    if not isinstance(decision, Mapping):
        raise TypeError("Master Trader decision must be a JSON object.")
    version = decision.get("contract_version")
    if version == v1.MASTER_TRADER_CONTRACT_VERSION:
        return v1.validate_master_trader_decision(decision)
    if version == MASTER_TRADER_CONTRACT_VERSION_V2:
        return validate_master_trader_decision_v2(decision)
    raise ValueError("Unsupported Master Trader contract version.")


def master_trader_decision_digest_v2(decision: Mapping[str, Any]) -> str:
    return _digest(validate_master_trader_decision_v2(decision))


def master_trader_decision_digest_versioned(decision: Mapping[str, Any]) -> str:
    normalized = validate_master_trader_decision_versioned(decision)
    if normalized["contract_version"] == v1.MASTER_TRADER_CONTRACT_VERSION:
        return v1.master_trader_decision_digest(normalized)
    return _digest(normalized)


def _condition_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["condition_version", "field_path", "operator", "value_type", "value"],
        "properties": {
            "condition_version": {"type": "string", "enum": [MACHINE_CONDITION_VERSION]},
            "field_path": {"type": "string"},
            "operator": {"type": "string", "enum": list(SUPPORTED_CONDITION_OPERATORS)},
            "value_type": {"type": "string", "enum": list(SUPPORTED_CONDITION_VALUE_TYPES)},
            "value": {"type": ["number", "string", "boolean"]},
        },
    }


def _schema_v2() -> dict[str, Any]:
    schema = v1.master_trader_json_schema()
    schema["properties"]["contract_version"] = {
        "type": "string",
        "enum": [MASTER_TRADER_CONTRACT_VERSION_V2],
    }
    condition = _condition_schema()
    schema["properties"].update(
        {
            "thesis": {"type": ["string", "null"]},
            "expected_horizon_minutes": {
                "type": ["integer", "null"],
                "minimum": MIN_HORIZON_MINUTES,
                "maximum": MAX_HORIZON_MINUTES,
            },
            "counter_argument": {"type": "string"},
            "invalidation_condition": {"anyOf": [condition, {"type": "null"}]},
            "abstention_basis": {"type": ["string", "null"]},
            "shadow_thesis": {"type": ["string", "null"]},
            "shadow_direction": {
                "type": ["string", "null"],
                "enum": [*SUPPORTED_SHADOW_DIRECTIONS, None],
            },
            "shadow_horizon_minutes": {
                "type": ["integer", "null"],
                "minimum": MIN_HORIZON_MINUTES,
                "maximum": MAX_HORIZON_MINUTES,
            },
            "shadow_evaluation_condition": {"anyOf": [condition, {"type": "null"}]},
        }
    )
    schema["required"] = list(schema["properties"])
    return schema


_MASTER_TRADER_JSON_SCHEMA_V2 = _schema_v2()


def master_trader_json_schema_v2() -> dict[str, Any]:
    return copy.deepcopy(_MASTER_TRADER_JSON_SCHEMA_V2)


def master_trader_response_format_v2() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": MASTER_TRADER_SCHEMA_NAME_V2,
        "strict": True,
        "schema": master_trader_json_schema_v2(),
    }


def master_trader_contract_manifest_v2() -> dict[str, Any]:
    v1_manifest = v1.master_trader_contract_manifest()
    schema = master_trader_json_schema_v2()
    manifest = {
        "manifest_version": MASTER_TRADER_MANIFEST_VERSION_V2,
        "contract_version": MASTER_TRADER_CONTRACT_VERSION_V2,
        "schema_version": MASTER_TRADER_SCHEMA_VERSION_V2,
        "schema_name": MASTER_TRADER_SCHEMA_NAME_V2,
        "schema_digest": _digest(schema),
        "compatibility_version": MASTER_TRADER_COMPATIBILITY_VERSION,
        "source_v1_contract_version": v1.MASTER_TRADER_CONTRACT_VERSION,
        "source_v1_manifest_digest": v1_manifest["manifest_digest"],
        "v1_records_version_readable": True,
        "v1_silent_upgrade_allowed": False,
        "v1_trade_geometry_delegated": True,
        "supported_symbol": v1.SUPPORTED_SYMBOL,
        "supported_actions": list(v1.SUPPORTED_ACTIONS),
        "machine_condition_version": MACHINE_CONDITION_VERSION,
        "machine_condition_operators": list(SUPPORTED_CONDITION_OPERATORS),
        "machine_condition_unknown_propagates": True,
        "machine_condition_exact_decimal_strings_supported": True,
        "machine_condition_forbidden_future_or_runtime_paths": True,
        "actionable_thesis_required": True,
        "actionable_expected_horizon_required": True,
        "counter_argument_required_for_all_actions": True,
        "actionable_invalidation_required": True,
        "no_trade_abstention_basis_required": True,
        "no_trade_shadow_evaluation_required": True,
        "position_sizing_fields_allowed": False,
        "confidence_controls_position_size": False,
        "hidden_chain_of_thought_required": False,
        "hidden_reasoning_trace_stored": False,
        "gateway_promoted_by_day33": False,
        "execution_implemented_by_this_contract": False,
    }
    manifest["manifest_digest"] = _digest(manifest)
    return manifest
