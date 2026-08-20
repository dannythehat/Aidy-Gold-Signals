from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy.setup_detector import SETUP_DEFINITIONS, SETUP_TAXONOMY_VERSION

MASTER_TRADER_CONTRACT_VERSION = "aidy_master_trader_decision_v1"
MASTER_TRADER_SCHEMA_NAME = "aidy_master_trader_decision_v1"
MASTER_TRADER_SCHEMA_VERSION = "aidy_master_trader_json_schema_v1"
MASTER_TRADER_MANIFEST_VERSION = "aidy_master_trader_contract_manifest_v1"
MASTER_TRADER_DIGEST_ALGORITHM = "sha256"

SUPPORTED_SYMBOL = "XAUUSD"
SUPPORTED_ACTIONS = ("new_trade", "manage_trade", "close_trade", "no_trade")
SUPPORTED_DIRECTIONS = ("long", "short")
SUPPORTED_MANAGEMENT_INSTRUCTIONS = (
    "move_stop",
    "replace_targets",
    "move_stop_and_targets",
)
SUPPORTED_ENTRY_TYPE = "market"
SUPPORTED_CLOSE_SCOPE = "full"

_SETUP_CODES = tuple(sorted(str(item["setup_id"]) for item in SETUP_DEFINITIONS))
_REQUIRED_FIELDS = (
    "contract_version",
    "action",
    "symbol",
    "evaluated_at_utc",
    "valid_until_utc",
    "confidence",
    "setup_taxonomy_version",
    "setup_codes",
    "reason_codes",
    "decision_summary",
    "target_decision_id",
    "direction",
    "entry_type",
    "market_reference_price",
    "stop_loss",
    "targets",
    "management_instruction",
    "new_stop_loss",
    "new_targets",
    "close_scope",
)
_REQUIRED_FIELD_SET = frozenset(_REQUIRED_FIELDS)
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_SAFE_DECISION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")

_FORBIDDEN_POSITION_SIZING_KEYS = frozenset(
    {
        "account_balance",
        "account_equity",
        "balance",
        "equity",
        "leverage",
        "lot",
        "lot_size",
        "lots",
        "margin",
        "position_size",
        "quantity",
        "risk_amount",
        "risk_pct",
        "risk_percent",
        "risk_percentage",
        "size",
        "units",
        "volume",
    }
)
_FORBIDDEN_REASONING_TRACE_KEYS = frozenset(
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


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _timestamp(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{name} must be timezone-aware ISO-8601 text.")
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be timezone-aware ISO-8601 text.") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware.")
    return parsed.astimezone(UTC)


def _number(value: Any, *, name: str, positive: bool = False) -> Decimal:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise TypeError(f"{name} must be a finite JSON number.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a finite JSON number.") from exc
    if not parsed.is_finite():
        raise ValueError(f"{name} must be a finite JSON number.")
    if positive and parsed <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return parsed


def _optional_number(value: Any, *, name: str) -> Decimal | None:
    if value is None:
        return None
    return _number(value, name=name, positive=True)


def _assert_no_forbidden_keys(value: Any, *, path: str = "decision") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_POSITION_SIZING_KEYS:
                raise ValueError(f"Position-sizing field is forbidden at {path}.{key}.")
            if normalized in _FORBIDDEN_REASONING_TRACE_KEYS:
                raise ValueError(f"Hidden reasoning-trace field is forbidden at {path}.{key}.")
            _assert_no_forbidden_keys(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_no_forbidden_keys(item, path=f"{path}[{index}]")


def _code_list(
    value: Any,
    *,
    name: str,
    allowed: set[str] | None = None,
    minimum: int = 0,
    maximum: int = 20,
) -> list[str]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a JSON array.")
    if not minimum <= len(value) <= maximum:
        raise ValueError(f"{name} must contain between {minimum} and {maximum} items.")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise TypeError(f"{name} entries must be strings.")
        code = item.strip()
        if not _SAFE_CODE.fullmatch(code):
            raise ValueError(f"{name} contains an invalid code: {item!r}.")
        if allowed is not None and code not in allowed:
            raise ValueError(f"{name} contains an unsupported code: {code}.")
        normalized.append(code)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{name} cannot contain duplicates.")
    return normalized


def _price_list(value: Any, *, name: str, minimum: int, maximum: int) -> list[Decimal]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a JSON array.")
    if not minimum <= len(value) <= maximum:
        raise ValueError(f"{name} must contain between {minimum} and {maximum} prices.")
    prices = [
        _number(item, name=f"{name}[{index}]", positive=True)
        for index, item in enumerate(value)
    ]
    if len(set(prices)) != len(prices):
        raise ValueError(f"{name} cannot contain duplicate prices.")
    return prices


def _nullable_text(value: Any, *, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{name} must be non-empty text or null.")
    return value.strip()


def _decision_id(value: Any, *, required: bool) -> str | None:
    normalized = _nullable_text(value, name="target_decision_id")
    if required and normalized is None:
        raise ValueError("target_decision_id is required for this action.")
    if not required and normalized is not None:
        raise ValueError("target_decision_id must be null for this action.")
    if normalized is not None and not _SAFE_DECISION_ID.fullmatch(normalized):
        raise ValueError("target_decision_id has an unsafe identifier format.")
    return normalized


def _neutral_trade_fields(decision: Mapping[str, Any]) -> None:
    expected_null = (
        "direction",
        "entry_type",
        "market_reference_price",
        "stop_loss",
        "management_instruction",
        "new_stop_loss",
        "close_scope",
    )
    for field in expected_null:
        if decision.get(field) is not None:
            raise ValueError(f"{field} must be null for this action.")
    if decision.get("targets") != []:
        raise ValueError("targets must be an empty array for this action.")
    if decision.get("new_targets") != []:
        raise ValueError("new_targets must be an empty array for this action.")


def _validate_new_trade(decision: Mapping[str, Any], *, setup_codes: list[str]) -> None:
    _decision_id(decision.get("target_decision_id"), required=False)
    if not setup_codes:
        raise ValueError("new_trade requires at least one accepted Day 15 setup code.")

    direction = decision.get("direction")
    if direction not in SUPPORTED_DIRECTIONS:
        raise ValueError("new_trade direction must be long or short.")
    if decision.get("entry_type") != SUPPORTED_ENTRY_TYPE:
        raise ValueError("AIDY V1 new_trade supports market entries only.")

    entry = _number(
        decision.get("market_reference_price"),
        name="market_reference_price",
        positive=True,
    )
    stop = _number(decision.get("stop_loss"), name="stop_loss", positive=True)
    targets = _price_list(decision.get("targets"), name="targets", minimum=1, maximum=3)

    if direction == "long":
        if not stop < entry:
            raise ValueError("Long new_trade requires stop_loss below market_reference_price.")
        if not all(target > entry for target in targets):
            raise ValueError("Long new_trade targets must be above market_reference_price.")
        if targets != sorted(targets):
            raise ValueError("Long new_trade targets must be strictly increasing.")
    else:
        if not stop > entry:
            raise ValueError("Short new_trade requires stop_loss above market_reference_price.")
        if not all(target < entry for target in targets):
            raise ValueError("Short new_trade targets must be below market_reference_price.")
        if targets != sorted(targets, reverse=True):
            raise ValueError("Short new_trade targets must be strictly decreasing.")

    if decision.get("management_instruction") is not None:
        raise ValueError("new_trade cannot contain management_instruction.")
    if decision.get("new_stop_loss") is not None:
        raise ValueError("new_trade cannot contain new_stop_loss.")
    if decision.get("new_targets") != []:
        raise ValueError("new_trade requires new_targets to be an empty array.")
    if decision.get("close_scope") is not None:
        raise ValueError("new_trade cannot contain close_scope.")


def _validate_manage_trade(decision: Mapping[str, Any]) -> None:
    _decision_id(decision.get("target_decision_id"), required=True)
    for field in ("direction", "entry_type", "market_reference_price", "stop_loss", "close_scope"):
        if decision.get(field) is not None:
            raise ValueError(f"{field} must be null for manage_trade.")
    if decision.get("targets") != []:
        raise ValueError("targets must be an empty array for manage_trade.")

    instruction = decision.get("management_instruction")
    if instruction not in SUPPORTED_MANAGEMENT_INSTRUCTIONS:
        raise ValueError("Unsupported manage_trade management_instruction.")

    new_stop = _optional_number(decision.get("new_stop_loss"), name="new_stop_loss")
    new_targets = _price_list(
        decision.get("new_targets"),
        name="new_targets",
        minimum=0,
        maximum=3,
    )

    if instruction == "move_stop":
        if new_stop is None or new_targets:
            raise ValueError("move_stop requires new_stop_loss and no new_targets.")
    elif instruction == "replace_targets":
        if new_stop is not None or not new_targets:
            raise ValueError("replace_targets requires 1-3 new_targets and no new_stop_loss.")
    elif new_stop is None or not new_targets:
        raise ValueError(
            "move_stop_and_targets requires new_stop_loss and 1-3 new_targets."
        )


def _validate_close_trade(decision: Mapping[str, Any]) -> None:
    _decision_id(decision.get("target_decision_id"), required=True)
    for field in (
        "direction",
        "entry_type",
        "market_reference_price",
        "stop_loss",
        "management_instruction",
        "new_stop_loss",
    ):
        if decision.get(field) is not None:
            raise ValueError(f"{field} must be null for close_trade.")
    if decision.get("targets") != [] or decision.get("new_targets") != []:
        raise ValueError("close_trade requires empty targets and new_targets arrays.")
    if decision.get("close_scope") != SUPPORTED_CLOSE_SCOPE:
        raise ValueError("AIDY V1 close_trade supports full close only.")


def _validate_no_trade(decision: Mapping[str, Any]) -> None:
    _decision_id(decision.get("target_decision_id"), required=False)
    _neutral_trade_fields(decision)


def _schema() -> dict[str, Any]:
    nullable_number = {"type": ["number", "null"]}
    nullable_text = {"type": ["string", "null"]}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(_REQUIRED_FIELDS),
        "properties": {
            "contract_version": {
                "type": "string",
                "enum": [MASTER_TRADER_CONTRACT_VERSION],
            },
            "action": {"type": "string", "enum": list(SUPPORTED_ACTIONS)},
            "symbol": {"type": "string", "enum": [SUPPORTED_SYMBOL]},
            "evaluated_at_utc": {"type": "string"},
            "valid_until_utc": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "setup_taxonomy_version": {
                "type": "string",
                "enum": [SETUP_TAXONOMY_VERSION],
            },
            "setup_codes": {
                "type": "array",
                "items": {"type": "string", "enum": list(_SETUP_CODES)},
            },
            "reason_codes": {"type": "array", "items": {"type": "string"}},
            "decision_summary": {"type": "string"},
            "target_decision_id": nullable_text,
            "direction": {
                "type": ["string", "null"],
                "enum": [*SUPPORTED_DIRECTIONS, None],
            },
            "entry_type": {
                "type": ["string", "null"],
                "enum": [SUPPORTED_ENTRY_TYPE, None],
            },
            "market_reference_price": nullable_number,
            "stop_loss": nullable_number,
            "targets": {"type": "array", "items": {"type": "number"}},
            "management_instruction": {
                "type": ["string", "null"],
                "enum": [*SUPPORTED_MANAGEMENT_INSTRUCTIONS, None],
            },
            "new_stop_loss": nullable_number,
            "new_targets": {"type": "array", "items": {"type": "number"}},
            "close_scope": {
                "type": ["string", "null"],
                "enum": [SUPPORTED_CLOSE_SCOPE, None],
            },
        },
    }


_MASTER_TRADER_JSON_SCHEMA = _schema()


def master_trader_json_schema() -> dict[str, Any]:
    """Return a defensive copy of the Day 20 strict Structured Outputs schema."""
    return copy.deepcopy(_MASTER_TRADER_JSON_SCHEMA)


def master_trader_response_format() -> dict[str, Any]:
    """Return the schema wrapper Day 21 can pass to the Responses API."""
    return {
        "type": "json_schema",
        "name": MASTER_TRADER_SCHEMA_NAME,
        "strict": True,
        "schema": master_trader_json_schema(),
    }


def validate_master_trader_decision(decision: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize one AIDY V1 model decision without executing it."""
    if not isinstance(decision, Mapping):
        raise TypeError("Master Trader decision must be a JSON object.")

    _assert_no_forbidden_keys(decision)
    fields = set(decision)
    missing = _REQUIRED_FIELD_SET - fields
    extras = fields - _REQUIRED_FIELD_SET
    if missing:
        raise ValueError(f"Master Trader decision is missing fields: {sorted(missing)}")
    if extras:
        raise ValueError(f"Master Trader decision contains unsupported fields: {sorted(extras)}")

    normalized = dict(decision)
    if normalized["contract_version"] != MASTER_TRADER_CONTRACT_VERSION:
        raise ValueError("Unsupported Master Trader contract version.")
    action = normalized["action"]
    if action not in SUPPORTED_ACTIONS:
        raise ValueError("Unsupported Master Trader action.")
    if normalized["symbol"] != SUPPORTED_SYMBOL:
        raise ValueError("AIDY V1 Master Trader supports XAUUSD only.")
    if normalized["setup_taxonomy_version"] != SETUP_TAXONOMY_VERSION:
        raise ValueError("Unsupported setup taxonomy version.")

    evaluated_at = _timestamp(normalized["evaluated_at_utc"], name="evaluated_at_utc")
    valid_until = _timestamp(normalized["valid_until_utc"], name="valid_until_utc")
    if valid_until <= evaluated_at:
        raise ValueError("valid_until_utc must be after evaluated_at_utc.")
    normalized["evaluated_at_utc"] = evaluated_at.isoformat()
    normalized["valid_until_utc"] = valid_until.isoformat()

    confidence = _number(normalized["confidence"], name="confidence")
    if not Decimal(0) <= confidence <= Decimal(1):
        raise ValueError("confidence must be between 0 and 1.")

    setup_codes = _code_list(
        normalized["setup_codes"],
        name="setup_codes",
        allowed=set(_SETUP_CODES),
        minimum=0,
        maximum=len(_SETUP_CODES),
    )
    reason_codes = _code_list(
        normalized["reason_codes"],
        name="reason_codes",
        minimum=1,
        maximum=8,
    )
    summary = normalized["decision_summary"]
    if not isinstance(summary, str):
        raise TypeError("decision_summary must be text.")
    summary = summary.strip()
    if not 1 <= len(summary) <= 500:
        raise ValueError("decision_summary must contain 1-500 characters.")

    normalized["setup_codes"] = setup_codes
    normalized["reason_codes"] = reason_codes
    normalized["decision_summary"] = summary

    if action == "new_trade":
        _validate_new_trade(normalized, setup_codes=setup_codes)
    elif action == "manage_trade":
        _validate_manage_trade(normalized)
    elif action == "close_trade":
        _validate_close_trade(normalized)
    else:
        _validate_no_trade(normalized)

    return normalized


def master_trader_decision_digest(decision: Mapping[str, Any]) -> str:
    return _digest(validate_master_trader_decision(decision))


def master_trader_contract_manifest() -> dict[str, Any]:
    schema = master_trader_json_schema()
    manifest = {
        "manifest_version": MASTER_TRADER_MANIFEST_VERSION,
        "contract_version": MASTER_TRADER_CONTRACT_VERSION,
        "schema_version": MASTER_TRADER_SCHEMA_VERSION,
        "schema_name": MASTER_TRADER_SCHEMA_NAME,
        "schema_digest": _digest(schema),
        "digest_algorithm": MASTER_TRADER_DIGEST_ALGORITHM,
        "supported_symbol": SUPPORTED_SYMBOL,
        "supported_actions": list(SUPPORTED_ACTIONS),
        "supported_entry_types": [SUPPORTED_ENTRY_TYPE],
        "supported_management_instructions": list(SUPPORTED_MANAGEMENT_INSTRUCTIONS),
        "supported_close_scopes": [SUPPORTED_CLOSE_SCOPE],
        "setup_taxonomy_version": SETUP_TAXONOMY_VERSION,
        "setup_codes": list(_SETUP_CODES),
        "no_trade_first_class": True,
        "pending_orders_supported": False,
        "position_sizing_fields_allowed": False,
        "confidence_controls_position_size": False,
        "hidden_chain_of_thought_required": False,
        "decision_summary_is_final_rationale_only": True,
        "gateway_implemented_by_this_contract": False,
        "execution_implemented_by_this_contract": False,
    }
    manifest["manifest_digest"] = _digest(manifest)
    return manifest
