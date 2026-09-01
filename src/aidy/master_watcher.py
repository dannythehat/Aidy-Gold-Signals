from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

import httpx

from aidy.context_composer_v2 import (
    CONTEXT_COMPOSER_VERSION_V2,
    CONTEXT_DOSSIER_VERSION_V2,
    verify_context_dossier_v2,
)
from aidy.context_packet import compute_context_hash
from aidy.decision_ledger import verify_ex_ante_record
from aidy.master_trader_contract_v2 import (
    MASTER_TRADER_CONTRACT_VERSION_V2,
    validate_master_trader_decision_versioned,
)
from aidy.paper_simulator import verify_paper_state
from aidy.pit_reconstruction import normalize_as_of

WATCHER_VERSION = "aidy_master_watcher_v1"
WATCHER_BUNDLE_VERSION = "aidy_master_watcher_evidence_bundle_v1"
WATCHER_OBSERVATION_VERSION = "aidy_master_watcher_observation_v1"
WATCHER_RECEIPT_VERSION = "aidy_master_watcher_receipt_v1"
WATCHER_MANIFEST_VERSION = "aidy_day47_master_watcher_manifest_v1"
WATCHER_SCHEMA_NAME = "aidy_master_watcher_observation_v1"
WATCHER_SCHEMA_VERSION = "aidy_master_watcher_json_schema_v1"
WATCHER_GATEWAY_VERSION = "aidy_openai_master_watcher_gateway_v1"
WATCHER_PROMPT_VERSION = "aidy_master_watcher_prompt_v1"
WATCHER_MODEL_ID = "gpt-5.6-sol"
WATCHER_REASONING_EFFORT = "medium"
WATCHER_API_URL = "https://api.openai.com/v1/responses"
WATCHER_API_KEY_ENV = "OPENAI_API_KEY"
WATCHER_CADENCE_SECONDS = 300
WATCHER_MAX_CONTEXT_AGE_SECONDS = 300
WATCHER_MAX_OUTPUT_TOKENS = 1200
WATCHER_TIMEOUT_SECONDS = 90.0
WATCHER_MAX_ATTEMPTS = 2
WATCHER_RETRY_BACKOFF_SECONDS = 0.5
WATCHER_PRICING_VERSION = "openai_gpt_5_6_sol_pricing_2026_08_20"
WATCHER_INPUT_PER_MILLION_USD = Decimal("5.00")
WATCHER_CACHED_INPUT_PER_MILLION_USD = Decimal("0.50")
WATCHER_OUTPUT_PER_MILLION_USD = Decimal("30.00")

WATCHER_ASSESSMENTS = ("hold", "management_review", "close_review")
WATCHER_THESIS_ASSESSMENTS = ("intact", "weakened", "invalidated", "unknown")
WATCHER_RECEIPT_STATUSES = ("observed", "blocked", "suppressed", "model_failed")
ACTIVE_PAPER_STATES = frozenset({"open", "partial"})

WATCHER_INSTRUCTIONS = """You are AIDY Master Watcher V1. You observe one active paper-only XAUUSD signal and return a bounded management observation, not a trading action.
Use only the supplied fresh point-in-time context, immutable original thesis/invalidation, current deterministic paper state, and validated hardened historical evidence. Unknown stays unknown. Do not invent market facts, probabilities, broker state, follower state, account state, Telegram state, execution state, or hidden reasoning.
Your assessment is observation-only: hold, management_review, or close_review. Day 48 owns any later conversion into a manage_trade or close_trade contract. Do not emit stop changes, target changes, position sizing, lot size, account risk, execution instructions, publication instructions, or a Master Trader action object.
Treat the original thesis and invalidation condition as immutable historical inputs. A profitable path does not prove the thesis was valid, and an invalidated thesis does not itself execute or close anything. Counter-evidence and uncertainty must be considered explicitly.
Return only the strict JSON object requested. Confidence is informational metadata only and cannot become a safety gate. observation_summary and evidence_change_summary must be concise final conclusions, never chain-of-thought or a reasoning trace."""

_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_RETRY_STATUS_CODES = frozenset({408, 409, 429})
_SECRET_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "client_secret",
        "cloudflare_api_token",
        "metaapi_token",
        "openai_api_key",
        "password",
        "private_key",
        "secret",
        "service_account_json",
        "telegram_bot_token",
    }
)
_RUNTIME_KEYS = frozenset(
    {
        "account",
        "account_balance",
        "account_equity",
        "account_id",
        "broker",
        "broker_account",
        "follower",
        "follower_id",
        "leverage",
        "lot",
        "lot_size",
        "margin",
        "metaapi",
        "mt5",
        "position_size",
        "risk_amount",
        "risk_pct",
        "risk_percent",
        "super_signals",
        "telegram",
        "ticket",
        "vantage",
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
_FUTURE_KEYS = frozenset(
    {
        "counterfactual",
        "future_evaluation",
        "future_return",
        "future_returns",
        "outcome",
        "outcome_label",
        "outcomes",
    }
)
_SECRET_MARKERS = ("sk-", "bearer ", "-----begin private key-----")
_GATEWAY_EXCEPTIONS = (httpx.HTTPError, OSError, RuntimeError, TypeError, ValueError)


class WatcherError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def _utc(value: Any, *, name: str) -> datetime:
    try:
        return normalize_as_of(value)
    except (TypeError, ValueError) as exc:
        raise WatcherError("watch_timestamp_invalid", f"{name} must be timezone-aware.") from exc


def _decimal(value: Any, *, name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise WatcherError("watch_cost_invalid", f"{name} must be a finite decimal.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise WatcherError("watch_cost_invalid", f"{name} must be a finite decimal.") from exc
    if not parsed.is_finite():
        raise WatcherError("watch_cost_invalid", f"{name} must be a finite decimal.")
    return parsed


def _text(value: Any, *, name: str, minimum: int = 1, maximum: int = 400) -> str:
    if not isinstance(value, str):
        raise WatcherError("watch_observation_invalid", f"{name} must be text.")
    normalized = " ".join(value.strip().split())
    if not minimum <= len(normalized) <= maximum:
        raise WatcherError(
            "watch_observation_invalid",
            f"{name} must contain {minimum}-{maximum} characters.",
        )
    return normalized


def _assert_safe(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _SECRET_KEYS:
                raise WatcherError("watch_secret_field_forbidden", f"Secret field at {path}.{key}.")
            if normalized in _RUNTIME_KEYS:
                raise WatcherError(
                    "watch_execution_state_forbidden",
                    f"Execution/account field at {path}.{key}.",
                )
            if normalized in _HIDDEN_REASONING_KEYS:
                raise WatcherError(
                    "watch_hidden_reasoning_forbidden",
                    f"Hidden reasoning field at {path}.{key}.",
                )
            if normalized in _FUTURE_KEYS:
                raise WatcherError(
                    "watch_future_evidence_forbidden",
                    f"Future/outcome field at {path}.{key}.",
                )
            if normalized == "future_derived" and item is not False:
                raise WatcherError(
                    "watch_future_evidence_forbidden",
                    f"Future-derived evidence at {path}.{key}.",
                )
            if normalized == "evaluation_only" and item is not False:
                raise WatcherError(
                    "watch_evaluation_evidence_forbidden",
                    f"Evaluation-only evidence at {path}.{key}.",
                )
            _assert_safe(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_safe(item, path=f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.strip().lower()
        if any(marker in lowered for marker in _SECRET_MARKERS):
            raise WatcherError("watch_secret_value_forbidden", f"Secret-like value at {path}.")


def _safe_digest(value: Any, *, name: str) -> str:
    result = str(value or "").strip().lower()
    if not _HEX64.fullmatch(result):
        raise WatcherError("watch_identity_invalid", f"{name} must be a sha256 digest.")
    return result


def _context_snapshot(
    context: Mapping[str, Any], *, now: datetime
) -> tuple[dict[str, Any], datetime]:
    if not isinstance(context, Mapping):
        raise WatcherError("watch_context_missing", "Fresh context is required.")
    snapshot = copy.deepcopy(dict(context))
    _assert_safe(snapshot, path="current_context")
    if snapshot.get("symbol") != "XAUUSD":
        raise WatcherError("watch_context_symbol_invalid", "Watcher supports XAUUSD only.")
    if snapshot.get("objective_only") is not True:
        raise WatcherError("watch_context_boundary_invalid", "Watcher context must be objective-only.")
    if snapshot.get("retrospective_history_included") is not False:
        raise WatcherError(
            "watch_context_boundary_invalid",
            "Retrospective history cannot enter current context.",
        )
    if snapshot.get("broker_follower_state_included") is not False:
        raise WatcherError(
            "watch_context_boundary_invalid",
            "Broker/follower state cannot enter context.",
        )
    supplied_hash = _safe_digest(snapshot.get("context_hash"), name="context_hash")
    if supplied_hash != compute_context_hash(snapshot):
        raise WatcherError("watch_context_hash_invalid", "Fresh context hash does not verify.")
    as_of = _utc(snapshot.get("as_of_utc"), name="current_context.as_of_utc")
    age = int((now - as_of).total_seconds())
    if age < 0:
        raise WatcherError("watch_context_future", "Fresh context cannot be from the future.")
    if age > WATCHER_MAX_CONTEXT_AGE_SECONDS:
        raise WatcherError("watch_context_stale", "Fresh context exceeded watcher age limit.")
    quality = snapshot.get("data_quality")
    if not isinstance(quality, Mapping):
        raise WatcherError(
            "watch_context_quality_missing",
            "Fresh context data_quality is required.",
        )
    if quality.get("quote_freshness") != "fresh":
        raise WatcherError(
            "watch_quote_stale_or_unknown",
            "Gold quote freshness must be fresh.",
        )
    gold = snapshot.get("gold")
    quote = gold.get("quote_context") if isinstance(gold, Mapping) else None
    if not isinstance(quote, Mapping) or quote.get("mid") is None:
        raise WatcherError("watch_quote_missing", "Fresh Gold mid is required.")
    return snapshot, as_of


def _original_binding(
    *, ex_ante_record: Mapping[str, Any], paper_state: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    if not isinstance(ex_ante_record, Mapping) or not verify_ex_ante_record(ex_ante_record):
        raise WatcherError(
            "watch_ex_ante_invalid",
            "A valid immutable ex-ante record is required.",
        )
    if ex_ante_record.get("cycle_disposition") != "decision_admitted":
        raise WatcherError(
            "watch_decision_not_admitted",
            "Only admitted AIDY decisions can be watched.",
        )
    raw_decision = ex_ante_record.get("decision")
    if not isinstance(raw_decision, Mapping):
        raise WatcherError("watch_decision_missing", "Ex-ante record has no decision snapshot.")
    decision = validate_master_trader_decision_versioned(raw_decision)
    if decision["contract_version"] != MASTER_TRADER_CONTRACT_VERSION_V2:
        raise WatcherError(
            "watch_v2_required",
            "Watcher requires falsifiable Master Trader V2.",
        )
    if decision["action"] != "new_trade":
        raise WatcherError(
            "watch_new_trade_required",
            "Watcher follows originating new_trade decisions only.",
        )

    if not isinstance(paper_state, Mapping) or not verify_paper_state(paper_state):
        raise WatcherError(
            "watch_paper_state_invalid",
            "A verified Day 46 paper state is required.",
        )
    state = copy.deepcopy(dict(paper_state))
    if state.get("position_state") not in ACTIVE_PAPER_STATES:
        raise WatcherError("watch_position_inactive", "Closed paper positions are not watched.")
    if state.get("decision_id") != ex_ante_record.get("decision_id"):
        raise WatcherError(
            "watch_decision_binding_mismatch",
            "Paper state decision identity mismatch.",
        )
    if state.get("ex_ante_digest") != ex_ante_record.get("ex_ante_digest"):
        raise WatcherError(
            "watch_ex_ante_binding_mismatch",
            "Paper state ex-ante digest mismatch.",
        )
    if state.get("model_decision_digest") != ex_ante_record.get("model_decision_digest"):
        raise WatcherError(
            "watch_model_binding_mismatch",
            "Paper state model-decision digest mismatch.",
        )

    thesis = {
        "thesis": decision["thesis"],
        "expected_horizon_minutes": decision["expected_horizon_minutes"],
        "counter_argument": decision["counter_argument"],
        "invalidation_condition": copy.deepcopy(decision["invalidation_condition"]),
    }
    if canonical_json(state.get("thesis_snapshot")) != canonical_json(thesis):
        raise WatcherError(
            "watch_original_thesis_mutated",
            "Original thesis/invalidation binding changed.",
        )
    if state.get("direction") != decision.get("direction"):
        raise WatcherError(
            "watch_direction_binding_mismatch",
            "Paper direction differs from origin decision.",
        )
    expected_entry = f"{Decimal(str(decision['market_reference_price'])):.6f}"
    if state.get("entry_price") != expected_entry:
        raise WatcherError(
            "watch_geometry_binding_mismatch",
            "Paper entry differs from origin decision.",
        )
    return copy.deepcopy(dict(ex_ante_record)), decision, state, digest(thesis)


def _dossier_snapshot(
    dossier: Mapping[str, Any],
    *,
    current_context: Mapping[str, Any],
    context_as_of: datetime,
    decision: Mapping[str, Any],
    state: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(dossier, Mapping) or not verify_context_dossier_v2(dossier):
        raise WatcherError(
            "watch_historical_dossier_invalid",
            "Verified Day 35 dossier is required.",
        )
    snapshot = copy.deepcopy(dict(dossier))
    _assert_safe(snapshot, path="historical_dossier")
    if snapshot.get("composer_version") != CONTEXT_COMPOSER_VERSION_V2:
        raise WatcherError(
            "watch_historical_dossier_invalid",
            "Unexpected composer version.",
        )
    if snapshot.get("dossier_version") != CONTEXT_DOSSIER_VERSION_V2:
        raise WatcherError(
            "watch_historical_dossier_invalid",
            "Unexpected dossier version.",
        )
    if snapshot.get("symbol") != "XAUUSD":
        raise WatcherError(
            "watch_historical_dossier_invalid",
            "Historical dossier symbol mismatch.",
        )
    dossier_as_of = _utc(snapshot.get("as_of_utc"), name="historical_dossier.as_of_utc")
    if dossier_as_of != context_as_of:
        raise WatcherError(
            "watch_dossier_context_time_mismatch",
            "Dossier and fresh context must share T.",
        )
    identity = snapshot.get("current_context_identity")
    if not isinstance(identity, Mapping):
        raise WatcherError(
            "watch_dossier_context_missing",
            "Dossier context identity is missing.",
        )
    if identity.get("context_hash") != current_context.get("context_hash"):
        raise WatcherError(
            "watch_dossier_context_hash_mismatch",
            "Dossier context hash mismatch.",
        )
    hypothesis = snapshot.get("hypothesis")
    if not isinstance(hypothesis, Mapping) or hypothesis.get("direction") != decision.get(
        "direction"
    ):
        raise WatcherError(
            "watch_dossier_direction_mismatch",
            "Dossier hypothesis direction mismatch.",
        )
    current_state = snapshot.get("current_aidy_state")
    if not isinstance(current_state, Mapping):
        raise WatcherError(
            "watch_dossier_state_missing",
            "Dossier AIDY state binding is missing.",
        )
    if current_state.get("paper_position_id") != state.get("position_id"):
        raise WatcherError(
            "watch_dossier_state_mismatch",
            "Dossier position identity mismatch.",
        )
    if current_state.get("paper_state_digest") != state.get("state_digest"):
        raise WatcherError(
            "watch_dossier_state_mismatch",
            "Dossier paper-state digest mismatch.",
        )
    for field in ("history_state", "counter_evidence", "support_evidence", "uncertainty"):
        if not isinstance(snapshot.get(field), Mapping):
            raise WatcherError(
                "watch_historical_evidence_missing",
                f"Dossier {field} is required.",
            )
    return snapshot


def _position_snapshot(state: Mapping[str, Any]) -> dict[str, Any]:
    invalidation = state.get("invalidation")
    invalidation = invalidation if isinstance(invalidation, Mapping) else {}
    return {
        "position_id": state["position_id"],
        "originating_decision_id": state["decision_id"],
        "paper_state_digest": state["state_digest"],
        "position_state": state["position_state"],
        "direction": state["direction"],
        "entry_price": state["entry_price"],
        "stop_loss": state["stop_loss"],
        "targets": copy.deepcopy(state["targets"]),
        "hit_target_indices": copy.deepcopy(state["hit_target_indices"]),
        "remaining_target_indices": copy.deepcopy(state["remaining_target_indices"]),
        "realized_r": state["realized_r"],
        "opened_at_utc": state["opened_at_utc"],
        "last_observation_at_utc": state["last_observation_at_utc"],
        "observation_count": state["observation_count"],
        "invalidation_status": invalidation.get("status"),
        "first_invalidation_at_utc": invalidation.get("first_triggered_at_utc"),
        "invalidation_evaluation_count": invalidation.get("evaluation_count"),
        "invalidation_unknown_count": invalidation.get("unknown_count"),
    }


def build_watcher_evidence_bundle(
    *,
    ex_ante_record: Mapping[str, Any],
    paper_state: Mapping[str, Any],
    current_context: Mapping[str, Any],
    historical_dossier: Mapping[str, Any],
    now_utc: datetime | str,
) -> dict[str, Any]:
    now = _utc(now_utc, name="now_utc")
    record, decision, state, thesis_digest = _original_binding(
        ex_ante_record=ex_ante_record,
        paper_state=paper_state,
    )
    context, context_as_of = _context_snapshot(current_context, now=now)
    last_state_at = state.get("last_observation_at_utc") or state.get("opened_at_utc")
    if context_as_of < _utc(last_state_at, name="paper_state.last_observation_at_utc"):
        raise WatcherError(
            "watch_context_predates_state",
            "Fresh context predates current paper state.",
        )
    dossier = _dossier_snapshot(
        historical_dossier,
        current_context=context,
        context_as_of=context_as_of,
        decision=decision,
        state=state,
    )
    original = {
        "originating_decision_id": record["decision_id"],
        "model_decision_digest": record["model_decision_digest"],
        "evaluated_at_utc": decision["evaluated_at_utc"],
        "valid_until_utc": decision["valid_until_utc"],
        "direction": decision["direction"],
        "setup_codes": copy.deepcopy(decision["setup_codes"]),
        "market_reference_price": decision["market_reference_price"],
        "stop_loss": decision["stop_loss"],
        "targets": copy.deepcopy(decision["targets"]),
        "thesis": decision["thesis"],
        "expected_horizon_minutes": decision["expected_horizon_minutes"],
        "counter_argument": decision["counter_argument"],
        "invalidation_condition": copy.deepcopy(decision["invalidation_condition"]),
        "original_thesis_digest": thesis_digest,
    }
    bundle: dict[str, Any] = {
        "bundle_version": WATCHER_BUNDLE_VERSION,
        "watcher_version": WATCHER_VERSION,
        "instruction_type": "active_signal_management_observation",
        "original_decision": original,
        "current_paper_position": _position_snapshot(state),
        "fresh_pit_context": context,
        "historical_evidence": {
            "dossier_digest": dossier["dossier_digest"],
            "history_state": copy.deepcopy(dossier["history_state"]),
            "counter_evidence": copy.deepcopy(dossier["counter_evidence"]),
            "support_evidence": copy.deepcopy(dossier["support_evidence"]),
            "uncertainty": copy.deepcopy(dossier["uncertainty"]),
            "invalidation_inputs": copy.deepcopy(dossier.get("invalidation_inputs") or {}),
            "prompt_section_order": copy.deepcopy(dossier["prompt_section_order"]),
        },
        "boundaries": {
            "paper_only": True,
            "management_action_contract_allowed": False,
            "publication_allowed": False,
            "execution_allowed": False,
            "account_state_allowed": False,
            "follower_state_allowed": False,
            "original_thesis_mutation_allowed": False,
            "confidence_is_safety_gate": False,
            "day48_action_conversion_required": True,
        },
    }
    _assert_safe(bundle, path="watcher_bundle")
    bundle["watch_input_digest"] = digest(bundle)
    return bundle


def verify_watcher_evidence_bundle(bundle: Mapping[str, Any]) -> bool:
    if not isinstance(bundle, Mapping):
        return False
    supplied = str(bundle.get("watch_input_digest") or "")
    body = copy.deepcopy(dict(bundle))
    body.pop("watch_input_digest", None)
    try:
        _assert_safe(body, path="watcher_bundle")
        if body.get("bundle_version") != WATCHER_BUNDLE_VERSION:
            return False
        if body.get("watcher_version") != WATCHER_VERSION:
            return False
        boundaries = body.get("boundaries")
        if not isinstance(boundaries, Mapping):
            return False
        expected_false = (
            "management_action_contract_allowed",
            "publication_allowed",
            "execution_allowed",
            "account_state_allowed",
            "follower_state_allowed",
            "original_thesis_mutation_allowed",
            "confidence_is_safety_gate",
        )
        if any(boundaries.get(field) is not False for field in expected_false):
            return False
        if boundaries.get("paper_only") is not True:
            return False
        if boundaries.get("day48_action_conversion_required") is not True:
            return False
    except (TypeError, ValueError):
        return False
    return bool(supplied) and supplied == digest(body)


def watcher_json_schema() -> dict[str, Any]:
    required = [
        "observation_version",
        "position_id",
        "originating_decision_id",
        "observed_at_utc",
        "context_hash",
        "paper_state_digest",
        "original_thesis_digest",
        "assessment",
        "thesis_assessment",
        "reason_codes",
        "observation_summary",
        "evidence_change_summary",
        "confidence",
        "management_action_emitted",
        "publication_requested",
        "execution_requested",
    ]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": {
            "observation_version": {
                "type": "string",
                "enum": [WATCHER_OBSERVATION_VERSION],
            },
            "position_id": {"type": "string"},
            "originating_decision_id": {"type": "string"},
            "observed_at_utc": {"type": "string"},
            "context_hash": {"type": "string"},
            "paper_state_digest": {"type": "string"},
            "original_thesis_digest": {"type": "string"},
            "assessment": {"type": "string", "enum": list(WATCHER_ASSESSMENTS)},
            "thesis_assessment": {
                "type": "string",
                "enum": list(WATCHER_THESIS_ASSESSMENTS),
            },
            "reason_codes": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "items": {"type": "string"},
            },
            "observation_summary": {"type": "string"},
            "evidence_change_summary": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "management_action_emitted": {"type": "boolean", "enum": [False]},
            "publication_requested": {"type": "boolean", "enum": [False]},
            "execution_requested": {"type": "boolean", "enum": [False]},
        },
    }


def watcher_response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": WATCHER_SCHEMA_NAME,
        "strict": True,
        "schema": watcher_json_schema(),
    }


def validate_watcher_observation(
    value: Mapping[str, Any], *, expected_bundle: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise WatcherError(
            "watch_observation_invalid",
            "Watcher observation must be an object.",
        )
    expected_fields = set(watcher_json_schema()["required"])
    if set(value) != expected_fields:
        raise WatcherError(
            "watch_observation_invalid",
            "Watcher observation fields mismatch.",
        )
    if value["observation_version"] != WATCHER_OBSERVATION_VERSION:
        raise WatcherError(
            "watch_observation_invalid",
            "Unsupported watcher observation version.",
        )
    assessment = value["assessment"]
    thesis_assessment = value["thesis_assessment"]
    if assessment not in WATCHER_ASSESSMENTS:
        raise WatcherError("watch_observation_invalid", "Unsupported watcher assessment.")
    if thesis_assessment not in WATCHER_THESIS_ASSESSMENTS:
        raise WatcherError("watch_observation_invalid", "Unsupported thesis assessment.")
    codes = value["reason_codes"]
    if not isinstance(codes, list) or not 1 <= len(codes) <= 8:
        raise WatcherError(
            "watch_observation_invalid",
            "Watcher reason_codes must contain 1-8 items.",
        )
    normalized_codes: list[str] = []
    for raw in codes:
        if not isinstance(raw, str) or not _SAFE_CODE.fullmatch(raw.strip()):
            raise WatcherError(
                "watch_observation_invalid",
                "Watcher reason code is invalid.",
            )
        normalized_codes.append(raw.strip())
    if len(normalized_codes) != len(set(normalized_codes)):
        raise WatcherError(
            "watch_observation_invalid",
            "Watcher reason codes cannot duplicate.",
        )
    confidence = value["confidence"]
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= float(confidence) <= 1
    ):
        raise WatcherError(
            "watch_observation_invalid",
            "Watcher confidence must be 0-1.",
        )
    if value["management_action_emitted"] is not False:
        raise WatcherError(
            "watch_action_emitted_forbidden",
            "Day 47 cannot emit management actions.",
        )
    if value["publication_requested"] is not False or value["execution_requested"] is not False:
        raise WatcherError(
            "watch_side_effect_requested",
            "Watcher cannot publish or execute.",
        )
    normalized = {
        "observation_version": WATCHER_OBSERVATION_VERSION,
        "position_id": _text(value["position_id"], name="position_id", maximum=256),
        "originating_decision_id": _text(
            value["originating_decision_id"],
            name="originating_decision_id",
            maximum=256,
        ),
        "observed_at_utc": _utc(value["observed_at_utc"], name="observed_at_utc").isoformat(),
        "context_hash": _safe_digest(value["context_hash"], name="context_hash"),
        "paper_state_digest": _safe_digest(
            value["paper_state_digest"],
            name="paper_state_digest",
        ),
        "original_thesis_digest": _safe_digest(
            value["original_thesis_digest"],
            name="original_thesis_digest",
        ),
        "assessment": assessment,
        "thesis_assessment": thesis_assessment,
        "reason_codes": normalized_codes,
        "observation_summary": _text(
            value["observation_summary"],
            name="observation_summary",
            minimum=12,
            maximum=400,
        ),
        "evidence_change_summary": _text(
            value["evidence_change_summary"],
            name="evidence_change_summary",
            minimum=12,
            maximum=400,
        ),
        "confidence": float(confidence),
        "management_action_emitted": False,
        "publication_requested": False,
        "execution_requested": False,
    }
    _assert_safe(normalized, path="watcher_observation")
    if expected_bundle is not None:
        if not verify_watcher_evidence_bundle(expected_bundle):
            raise WatcherError("watch_bundle_invalid", "Expected watcher bundle is invalid.")
        position = expected_bundle["current_paper_position"]
        original = expected_bundle["original_decision"]
        context = expected_bundle["fresh_pit_context"]
        identities = {
            "position_id": position["position_id"],
            "originating_decision_id": original["originating_decision_id"],
            "observed_at_utc": context["as_of_utc"],
            "context_hash": context["context_hash"],
            "paper_state_digest": position["paper_state_digest"],
            "original_thesis_digest": original["original_thesis_digest"],
        }
        for field, wanted in identities.items():
            if normalized[field] != wanted:
                raise WatcherError(
                    "watch_observation_identity_mismatch",
                    f"Watcher observation {field} mismatch.",
                )
    return normalized


def watcher_observation_digest(observation: Mapping[str, Any]) -> str:
    return digest(validate_watcher_observation(observation))


def _prompt_digest() -> str:
    return sha256(WATCHER_INSTRUCTIONS.encode()).hexdigest()


def build_watcher_request(evidence_bundle: Mapping[str, Any]) -> dict[str, Any]:
    if not verify_watcher_evidence_bundle(evidence_bundle):
        raise WatcherError(
            "watch_bundle_invalid",
            "Watcher request requires a verified evidence bundle.",
        )
    _assert_safe(evidence_bundle, path="watcher_request")
    return {
        "model": WATCHER_MODEL_ID,
        "instructions": WATCHER_INSTRUCTIONS,
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": canonical_json(
                            {
                                "task": "Return one AIDY Master Watcher V1 observation only.",
                                "evidence_bundle": evidence_bundle,
                            }
                        ),
                    }
                ],
            }
        ],
        "reasoning": {"effort": WATCHER_REASONING_EFFORT},
        "text": {"format": watcher_response_format(), "verbosity": "low"},
        "max_output_tokens": WATCHER_MAX_OUTPUT_TOKENS,
        "store": False,
        "metadata": {
            "aidy_watcher_gateway_version": WATCHER_GATEWAY_VERSION,
            "aidy_watcher_prompt_version": WATCHER_PROMPT_VERSION,
            "aidy_watcher_schema_version": WATCHER_SCHEMA_VERSION,
        },
    }


def _usage(response: Mapping[str, Any]) -> dict[str, int]:
    usage = response.get("usage")
    if not isinstance(usage, Mapping):
        return {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
        }
    input_details = usage.get("input_tokens_details")
    output_details = usage.get("output_tokens_details")
    cached = int(input_details.get("cached_tokens", 0)) if isinstance(input_details, Mapping) else 0
    reasoning = (
        int(output_details.get("reasoning_tokens", 0))
        if isinstance(output_details, Mapping)
        else 0
    )
    return {
        "input_tokens": int(usage.get("input_tokens", 0)),
        "cached_input_tokens": cached,
        "output_tokens": int(usage.get("output_tokens", 0)),
        "reasoning_tokens": reasoning,
        "total_tokens": int(usage.get("total_tokens", 0)),
    }


def _estimated_cost_usd(usage: Mapping[str, int]) -> str:
    input_tokens = max(int(usage["input_tokens"]), 0)
    cached = min(max(int(usage["cached_input_tokens"]), 0), input_tokens)
    uncached = input_tokens - cached
    output = max(int(usage["output_tokens"]), 0)
    million = Decimal(1_000_000)
    cost = (
        Decimal(uncached) * WATCHER_INPUT_PER_MILLION_USD
        + Decimal(cached) * WATCHER_CACHED_INPUT_PER_MILLION_USD
        + Decimal(output) * WATCHER_OUTPUT_PER_MILLION_USD
    ) / million
    return str(cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def _extract_structured_text(response: Mapping[str, Any]) -> tuple[str | None, str | None]:
    texts: list[str] = []
    refusals: list[str] = []
    output = response.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, Mapping) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, Mapping):
                    continue
                if part.get("type") == "refusal":
                    refusal = part.get("refusal") or part.get("text")
                    if isinstance(refusal, str) and refusal:
                        refusals.append(refusal)
                elif part.get("type") == "output_text":
                    text = part.get("text")
                    if isinstance(text, str) and text:
                        texts.append(text)
    if refusals:
        return None, "model_refusal"
    if len(texts) != 1:
        return None, "missing_or_ambiguous_output_text"
    return texts[0], None


def _safe_gateway_failure(
    *,
    reason: str,
    attempts: int,
    latency_ms: int,
    request_digest: str,
    response: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    provider_usage = _usage(response or {})
    return {
        "gateway_version": WATCHER_GATEWAY_VERSION,
        "status": "failed_closed",
        "publication_allowed": False,
        "execution_allowed": False,
        "failure_reason": reason,
        "structured_observation": None,
        "observation_digest": None,
        "request_digest": request_digest,
        "attempts": attempts,
        "latency_ms": latency_ms,
        "response_id": str((response or {}).get("id") or "") or None,
        "provider_status": str((response or {}).get("status") or "") or None,
        "provider_model": str((response or {}).get("model") or "") or None,
        "usage": provider_usage,
        "estimated_cost_usd": _estimated_cost_usd(provider_usage),
        "pricing_version": WATCHER_PRICING_VERSION,
        "prompt_version": WATCHER_PROMPT_VERSION,
        "prompt_digest": _prompt_digest(),
        "model_id": WATCHER_MODEL_ID,
        "reasoning_effort": WATCHER_REASONING_EFFORT,
    }


class OpenAIMasterWatcherGateway:
    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("OpenAI API key is required.")
        self._api_key = api_key.strip()
        self._transport = transport
        self._sleep = sleep

    @classmethod
    def from_env(cls, **kwargs: Any) -> OpenAIMasterWatcherGateway:
        key = os.environ.get(WATCHER_API_KEY_ENV, "")
        if not key:
            raise RuntimeError(f"{WATCHER_API_KEY_ENV} is not configured.")
        return cls(key, **kwargs)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(api_key=<redacted>, model={WATCHER_MODEL_ID!r})"

    async def evaluate(self, evidence_bundle: Mapping[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            payload = build_watcher_request(evidence_bundle)
        except (TypeError, ValueError):
            return _safe_gateway_failure(
                reason="unsafe_or_invalid_input",
                attempts=0,
                latency_ms=int((time.perf_counter() - started) * 1000),
                request_digest="",
            )
        request_digest = digest(payload)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(WATCHER_TIMEOUT_SECONDS)
        attempts = 0
        response: Mapping[str, Any] | None = None
        async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
            while attempts < WATCHER_MAX_ATTEMPTS:
                attempts += 1
                try:
                    http_response = await client.post(
                        WATCHER_API_URL,
                        headers=headers,
                        json=payload,
                    )
                except httpx.RequestError:
                    if attempts < WATCHER_MAX_ATTEMPTS:
                        await self._sleep(WATCHER_RETRY_BACKOFF_SECONDS)
                        continue
                    return _safe_gateway_failure(
                        reason="api_transport_error",
                        attempts=attempts,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        request_digest=request_digest,
                    )
                status_code = http_response.status_code
                if status_code >= 500 or status_code in _RETRY_STATUS_CODES:
                    if attempts < WATCHER_MAX_ATTEMPTS:
                        await self._sleep(WATCHER_RETRY_BACKOFF_SECONDS)
                        continue
                    return _safe_gateway_failure(
                        reason="api_retryable_error",
                        attempts=attempts,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        request_digest=request_digest,
                    )
                if status_code < 200 or status_code >= 300:
                    return _safe_gateway_failure(
                        reason="api_nonretryable_error",
                        attempts=attempts,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        request_digest=request_digest,
                    )
                try:
                    parsed_response = http_response.json()
                except ValueError:
                    return _safe_gateway_failure(
                        reason="invalid_provider_json",
                        attempts=attempts,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        request_digest=request_digest,
                    )
                if not isinstance(parsed_response, Mapping):
                    return _safe_gateway_failure(
                        reason="invalid_provider_json",
                        attempts=attempts,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        request_digest=request_digest,
                    )
                response = parsed_response
                break
        latency_ms = int((time.perf_counter() - started) * 1000)
        if response is None:
            return _safe_gateway_failure(
                reason="api_transport_error",
                attempts=attempts,
                latency_ms=latency_ms,
                request_digest=request_digest,
            )
        if response.get("status") != "completed" or response.get("error") is not None:
            return _safe_gateway_failure(
                reason="provider_incomplete_or_failed",
                attempts=attempts,
                latency_ms=latency_ms,
                request_digest=request_digest,
                response=response,
            )
        output_text, output_error = _extract_structured_text(response)
        if output_error is not None or output_text is None:
            return _safe_gateway_failure(
                reason=output_error or "missing_output_text",
                attempts=attempts,
                latency_ms=latency_ms,
                request_digest=request_digest,
                response=response,
            )
        try:
            parsed = json.loads(output_text)
        except json.JSONDecodeError:
            return _safe_gateway_failure(
                reason="malformed_structured_output",
                attempts=attempts,
                latency_ms=latency_ms,
                request_digest=request_digest,
                response=response,
            )
        try:
            observation = validate_watcher_observation(
                parsed,
                expected_bundle=evidence_bundle,
            )
        except (TypeError, ValueError):
            return _safe_gateway_failure(
                reason="semantic_validator_rejection",
                attempts=attempts,
                latency_ms=latency_ms,
                request_digest=request_digest,
                response=response,
            )
        provider_usage = _usage(response)
        return {
            "gateway_version": WATCHER_GATEWAY_VERSION,
            "status": "accepted",
            "publication_allowed": False,
            "execution_allowed": False,
            "failure_reason": None,
            "structured_observation": observation,
            "observation_digest": watcher_observation_digest(observation),
            "request_digest": request_digest,
            "attempts": attempts,
            "latency_ms": latency_ms,
            "response_id": str(response.get("id") or "") or None,
            "provider_status": str(response.get("status") or "") or None,
            "provider_model": str(response.get("model") or "") or None,
            "usage": provider_usage,
            "estimated_cost_usd": _estimated_cost_usd(provider_usage),
            "pricing_version": WATCHER_PRICING_VERSION,
            "prompt_version": WATCHER_PROMPT_VERSION,
            "prompt_digest": _prompt_digest(),
            "model_id": WATCHER_MODEL_ID,
            "reasoning_effort": WATCHER_REASONING_EFFORT,
        }


def _receipt_digest(receipt: Mapping[str, Any]) -> str:
    body = copy.deepcopy(dict(receipt))
    body.pop("receipt_digest", None)
    return digest(body)


def verify_watcher_receipt(receipt: Mapping[str, Any]) -> bool:
    if not isinstance(receipt, Mapping):
        return False
    supplied = str(receipt.get("receipt_digest") or "")
    if not supplied or supplied != _receipt_digest(receipt):
        return False
    try:
        _assert_safe(receipt, path="watcher_receipt")
        if receipt.get("receipt_version") != WATCHER_RECEIPT_VERSION:
            return False
        if receipt.get("watcher_version") != WATCHER_VERSION:
            return False
        if receipt.get("status") not in WATCHER_RECEIPT_STATUSES:
            return False
        if receipt.get("publication_allowed") is not False:
            return False
        if receipt.get("execution_allowed") is not False:
            return False
        call_count = receipt.get("model_call_count")
        attempted = receipt.get("call_attempted")
        if call_count not in {0, 1} or attempted is not (call_count == 1):
            return False
        observation = receipt.get("observation")
        if receipt.get("status") == "observed":
            if not isinstance(observation, Mapping):
                return False
            normalized = validate_watcher_observation(observation)
            if receipt.get("observation_digest") != watcher_observation_digest(normalized):
                return False
        elif observation is not None or receipt.get("observation_digest") is not None:
            return False
        if _decimal(receipt.get("estimated_cost_usd"), name="estimated_cost_usd") < 0:
            return False
    except (TypeError, ValueError):
        return False
    return True


def _history(receipts: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in receipts:
        if not isinstance(raw, Mapping) or not verify_watcher_receipt(raw):
            raise WatcherError(
                "watch_history_invalid",
                "Watcher history contains an invalid receipt.",
            )
        result.append(copy.deepcopy(dict(raw)))
    return result


def _preparation(
    *,
    status: str,
    reason_code: str,
    checked_at: datetime,
    cycle_index: int,
    position_id: str | None,
    context_hash: str | None,
    paper_state_digest: str | None,
    thesis_digest: str | None,
    watch_input_digest: str | None,
    evidence_bundle: Mapping[str, Any] | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "preparation_version": "aidy_master_watcher_preparation_v1",
        "watcher_version": WATCHER_VERSION,
        "status": status,
        "reason_code": reason_code,
        "checked_at_utc": checked_at.isoformat(),
        "cycle_index": cycle_index,
        "position_id": position_id,
        "context_hash": context_hash,
        "paper_state_digest": paper_state_digest,
        "original_thesis_digest": thesis_digest,
        "watch_input_digest": watch_input_digest,
        "call_allowed": status == "ready",
        "evidence_bundle": None if evidence_bundle is None else copy.deepcopy(dict(evidence_bundle)),
    }
    result["preparation_digest"] = digest(result)
    return result


def prepare_watch_cycle(
    *,
    ex_ante_record: Mapping[str, Any],
    paper_state: Mapping[str, Any],
    current_context: Mapping[str, Any],
    historical_dossier: Mapping[str, Any],
    now_utc: datetime | str,
    previous_receipts: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    now = _utc(now_utc, name="now_utc")
    try:
        history = _history(previous_receipts)
    except WatcherError as exc:
        return _preparation(
            status="blocked",
            reason_code=exc.code,
            checked_at=now,
            cycle_index=0,
            position_id=None,
            context_hash=None,
            paper_state_digest=None,
            thesis_digest=None,
            watch_input_digest=None,
            evidence_bundle=None,
        )
    cycle_index = len(history)
    try:
        bundle = build_watcher_evidence_bundle(
            ex_ante_record=ex_ante_record,
            paper_state=paper_state,
            current_context=current_context,
            historical_dossier=historical_dossier,
            now_utc=now,
        )
    except WatcherError as exc:
        position_id = None
        state_digest = None
        if isinstance(paper_state, Mapping):
            position_id = str(paper_state.get("position_id") or "") or None
            state_digest = str(paper_state.get("state_digest") or "") or None
        context_hash = None
        if isinstance(current_context, Mapping):
            context_hash = str(current_context.get("context_hash") or "") or None
        return _preparation(
            status="blocked",
            reason_code=exc.code,
            checked_at=now,
            cycle_index=cycle_index,
            position_id=position_id,
            context_hash=context_hash,
            paper_state_digest=state_digest,
            thesis_digest=None,
            watch_input_digest=None,
            evidence_bundle=None,
        )

    position = bundle["current_paper_position"]
    original = bundle["original_decision"]
    context = bundle["fresh_pit_context"]
    input_digest = bundle["watch_input_digest"]
    position_id = position["position_id"]
    same_position = [row for row in history if row.get("position_id") == position_id]
    seen_inputs = {
        str(row.get("watch_input_digest"))
        for row in same_position
        if row.get("status") == "observed"
    }
    if input_digest in seen_inputs:
        return _preparation(
            status="suppressed",
            reason_code="watch_duplicate_input",
            checked_at=now,
            cycle_index=cycle_index,
            position_id=position_id,
            context_hash=context["context_hash"],
            paper_state_digest=position["paper_state_digest"],
            thesis_digest=original["original_thesis_digest"],
            watch_input_digest=input_digest,
            evidence_bundle=None,
        )
    call_receipts = [row for row in same_position if row.get("call_attempted") is True]
    if call_receipts:
        last = max(
            _utc(row["checked_at_utc"], name="receipt.checked_at_utc")
            for row in call_receipts
        )
        elapsed = int((now - last).total_seconds())
        if elapsed < 0:
            return _preparation(
                status="blocked",
                reason_code="watch_history_from_future",
                checked_at=now,
                cycle_index=cycle_index,
                position_id=position_id,
                context_hash=context["context_hash"],
                paper_state_digest=position["paper_state_digest"],
                thesis_digest=original["original_thesis_digest"],
                watch_input_digest=input_digest,
                evidence_bundle=None,
            )
        if elapsed < WATCHER_CADENCE_SECONDS:
            return _preparation(
                status="suppressed",
                reason_code="watch_cadence_not_due",
                checked_at=now,
                cycle_index=cycle_index,
                position_id=position_id,
                context_hash=context["context_hash"],
                paper_state_digest=position["paper_state_digest"],
                thesis_digest=original["original_thesis_digest"],
                watch_input_digest=input_digest,
                evidence_bundle=None,
            )
    return _preparation(
        status="ready",
        reason_code="watch_call_allowed",
        checked_at=now,
        cycle_index=cycle_index,
        position_id=position_id,
        context_hash=context["context_hash"],
        paper_state_digest=position["paper_state_digest"],
        thesis_digest=original["original_thesis_digest"],
        watch_input_digest=input_digest,
        evidence_bundle=bundle,
    )


def _build_receipt(
    *,
    preparation: Mapping[str, Any],
    status: str,
    reason_codes: list[str],
    call_attempted: bool,
    provider_attempts: int,
    gateway_result: Mapping[str, Any] | None,
    observation: Mapping[str, Any] | None,
    estimated_cost_usd: str,
) -> dict[str, Any]:
    identity = {
        "position_id": preparation.get("position_id"),
        "cycle_index": preparation.get("cycle_index"),
        "checked_at_utc": preparation.get("checked_at_utc"),
        "watch_input_digest": preparation.get("watch_input_digest"),
        "status": status,
    }
    receipt: dict[str, Any] = {
        "receipt_version": WATCHER_RECEIPT_VERSION,
        "watcher_version": WATCHER_VERSION,
        "receipt_id": f"watch:{digest(identity)[:32]}",
        "cycle_index": int(preparation["cycle_index"]),
        "checked_at_utc": preparation["checked_at_utc"],
        "position_id": preparation.get("position_id"),
        "context_hash": preparation.get("context_hash"),
        "paper_state_digest": preparation.get("paper_state_digest"),
        "original_thesis_digest": preparation.get("original_thesis_digest"),
        "watch_input_digest": preparation.get("watch_input_digest"),
        "status": status,
        "reason_codes": list(reason_codes),
        "call_attempted": call_attempted,
        "model_call_count": 1 if call_attempted else 0,
        "provider_attempts": int(provider_attempts),
        "gateway_version": None if gateway_result is None else gateway_result.get("gateway_version"),
        "request_digest": None if gateway_result is None else gateway_result.get("request_digest"),
        "prompt_version": None if gateway_result is None else gateway_result.get("prompt_version"),
        "prompt_digest": None if gateway_result is None else gateway_result.get("prompt_digest"),
        "model_id": None if gateway_result is None else gateway_result.get("model_id"),
        "usage": None if gateway_result is None else copy.deepcopy(gateway_result.get("usage")),
        "estimated_cost_usd": str(estimated_cost_usd),
        "observation": None if observation is None else copy.deepcopy(dict(observation)),
        "observation_digest": None if observation is None else watcher_observation_digest(observation),
        "publication_allowed": False,
        "execution_allowed": False,
        "management_action_contract_emitted": False,
        "formal_forward_evidence": False,
        "super_signals_modified": False,
    }
    receipt["receipt_digest"] = _receipt_digest(receipt)
    return receipt


async def run_watch_cycle(
    *,
    ex_ante_record: Mapping[str, Any],
    paper_state: Mapping[str, Any],
    current_context: Mapping[str, Any],
    historical_dossier: Mapping[str, Any],
    now_utc: datetime | str,
    gateway: Any,
    previous_receipts: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    preparation = prepare_watch_cycle(
        ex_ante_record=ex_ante_record,
        paper_state=paper_state,
        current_context=current_context,
        historical_dossier=historical_dossier,
        now_utc=now_utc,
        previous_receipts=previous_receipts,
    )
    if preparation["status"] == "blocked":
        return _build_receipt(
            preparation=preparation,
            status="blocked",
            reason_codes=[str(preparation["reason_code"])],
            call_attempted=False,
            provider_attempts=0,
            gateway_result=None,
            observation=None,
            estimated_cost_usd="0.000000",
        )
    if preparation["status"] == "suppressed":
        return _build_receipt(
            preparation=preparation,
            status="suppressed",
            reason_codes=[str(preparation["reason_code"])],
            call_attempted=False,
            provider_attempts=0,
            gateway_result=None,
            observation=None,
            estimated_cost_usd="0.000000",
        )
    bundle = preparation.get("evidence_bundle")
    if not isinstance(bundle, Mapping) or not verify_watcher_evidence_bundle(bundle):
        return _build_receipt(
            preparation=preparation,
            status="blocked",
            reason_codes=["watch_bundle_invalid"],
            call_attempted=False,
            provider_attempts=0,
            gateway_result=None,
            observation=None,
            estimated_cost_usd="0.000000",
        )
    try:
        result = await gateway.evaluate(bundle)
    except _GATEWAY_EXCEPTIONS:
        result = _safe_gateway_failure(
            reason="gateway_exception",
            attempts=1,
            latency_ms=0,
            request_digest="",
        )
    if not isinstance(result, Mapping):
        result = _safe_gateway_failure(
            reason="gateway_result_invalid",
            attempts=1,
            latency_ms=0,
            request_digest="",
        )
    attempts = int(result.get("attempts") or 0)
    cost = str(result.get("estimated_cost_usd") or "0.000000")
    if result.get("publication_allowed") is not False or result.get("execution_allowed") is not False:
        return _build_receipt(
            preparation=preparation,
            status="model_failed",
            reason_codes=["watch_gateway_boundary_violation"],
            call_attempted=True,
            provider_attempts=attempts,
            gateway_result=result,
            observation=None,
            estimated_cost_usd=cost,
        )
    if result.get("status") != "accepted":
        return _build_receipt(
            preparation=preparation,
            status="model_failed",
            reason_codes=[str(result.get("failure_reason") or "watch_gateway_failed")],
            call_attempted=True,
            provider_attempts=attempts,
            gateway_result=result,
            observation=None,
            estimated_cost_usd=cost,
        )
    raw_observation = result.get("structured_observation")
    try:
        observation = validate_watcher_observation(
            raw_observation,
            expected_bundle=bundle,
        )
    except (TypeError, ValueError):
        return _build_receipt(
            preparation=preparation,
            status="model_failed",
            reason_codes=["watch_observation_semantic_rejection"],
            call_attempted=True,
            provider_attempts=attempts,
            gateway_result=result,
            observation=None,
            estimated_cost_usd=cost,
        )
    if result.get("observation_digest") != watcher_observation_digest(observation):
        return _build_receipt(
            preparation=preparation,
            status="model_failed",
            reason_codes=["watch_observation_digest_mismatch"],
            call_attempted=True,
            provider_attempts=attempts,
            gateway_result=result,
            observation=None,
            estimated_cost_usd=cost,
        )
    return _build_receipt(
        preparation=preparation,
        status="observed",
        reason_codes=["watch_observation_recorded"],
        call_attempted=True,
        provider_attempts=attempts,
        gateway_result=result,
        observation=observation,
        estimated_cost_usd=cost,
    )


def reconcile_watcher_receipt(
    existing: Mapping[str, Any], incoming: Mapping[str, Any]
) -> dict[str, Any]:
    if not verify_watcher_receipt(existing) or not verify_watcher_receipt(incoming):
        raise WatcherError(
            "watch_receipt_invalid",
            "Cannot reconcile invalid watcher receipts.",
        )
    if existing["receipt_id"] != incoming["receipt_id"]:
        raise WatcherError(
            "watch_receipt_identity_mismatch",
            "Watcher receipt IDs differ.",
        )
    if existing["receipt_digest"] != incoming["receipt_digest"]:
        raise WatcherError(
            "watch_receipt_conflict",
            "Watcher receipt identity has conflicting payloads.",
        )
    return copy.deepcopy(dict(existing))


def watcher_history_summary(receipts: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    history = _history(receipts)
    cost = Decimal(0)
    for row in history:
        cost += _decimal(row["estimated_cost_usd"], name="estimated_cost_usd")
    result: dict[str, Any] = {
        "summary_version": "aidy_master_watcher_history_summary_v1",
        "watcher_version": WATCHER_VERSION,
        "receipt_count": len(history),
        "model_call_count": sum(int(row["model_call_count"]) for row in history),
        "provider_attempt_count": sum(int(row["provider_attempts"]) for row in history),
        "observed_count": sum(row["status"] == "observed" for row in history),
        "blocked_count": sum(row["status"] == "blocked" for row in history),
        "suppressed_count": sum(row["status"] == "suppressed" for row in history),
        "model_failed_count": sum(row["status"] == "model_failed" for row in history),
        "estimated_cost_usd": str(
            cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        ),
        "publication_count": 0,
        "execution_count": 0,
    }
    result["summary_digest"] = digest(result)
    return result


def master_watcher_manifest() -> dict[str, Any]:
    result: dict[str, Any] = {
        "manifest_version": WATCHER_MANIFEST_VERSION,
        "watcher_version": WATCHER_VERSION,
        "bundle_version": WATCHER_BUNDLE_VERSION,
        "observation_version": WATCHER_OBSERVATION_VERSION,
        "receipt_version": WATCHER_RECEIPT_VERSION,
        "schema_version": WATCHER_SCHEMA_VERSION,
        "gateway_version": WATCHER_GATEWAY_VERSION,
        "model_id": WATCHER_MODEL_ID,
        "prompt_version": WATCHER_PROMPT_VERSION,
        "prompt_digest": _prompt_digest(),
        "cadence_seconds": WATCHER_CADENCE_SECONDS,
        "max_context_age_seconds": WATCHER_MAX_CONTEXT_AGE_SECONDS,
        "active_paper_states": sorted(ACTIVE_PAPER_STATES),
        "day35_dossier_required": True,
        "day46_verified_paper_state_required": True,
        "master_trader_v2_origin_required": True,
        "original_thesis_immutable": True,
        "original_invalidation_immutable": True,
        "duplicate_input_suppresses_call": True,
        "stale_or_missing_evidence_fails_closed": True,
        "call_count_logged": True,
        "provider_attempts_logged": True,
        "cost_logged": True,
        "confidence_is_safety_gate": False,
        "management_action_contract_allowed": False,
        "day48_action_conversion_required": True,
        "publication_allowed": False,
        "execution_allowed": False,
        "broker_account_follower_state_allowed": False,
        "formal_forward_evidence_created": False,
        "super_signals_modified": False,
    }
    result["manifest_digest"] = digest(result)
    return result
