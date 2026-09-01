from __future__ import annotations

import copy
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy.decision_ledger import (
    build_outcome_attachment,
    verify_ex_ante_record,
)
from aidy.master_trader_contract_v2 import (
    MASTER_TRADER_CONTRACT_VERSION_V2,
    evaluate_machine_condition,
    validate_machine_condition,
    validate_master_trader_decision_versioned,
)

PAPER_SIMULATOR_VERSION = "aidy_paper_position_simulator_v1"
PAPER_STATE_VERSION = "aidy_paper_position_state_v1"
PAPER_OBSERVATION_VERSION = "aidy_paper_market_observation_v1"
PAPER_INVALIDATION_VERSION = "aidy_paper_thesis_invalidation_v1"
PAPER_OUTCOME_CONTRACT_VERSION = "aidy_paper_trade_outcome_v1"
PAPER_MANIFEST_VERSION = "aidy_day46_paper_simulator_manifest_v1"

SUPPORTED_POSITION_STATES = ("open", "partial", "closed_targets", "closed_stop")
SUPPORTED_SYMBOL = "XAUUSD"

_FORBIDDEN_CONTEXT_KEYS = frozenset(
    {
        "account",
        "account_balance",
        "account_equity",
        "account_id",
        "broker",
        "broker_account",
        "follower",
        "follower_id",
        "lot_size",
        "margin",
        "metaapi",
        "mt5",
        "position_size",
        "risk_pct",
        "risk_percent",
        "super_signals",
        "telegram",
        "ticket",
        "vantage",
    }
)
_OUTCOME_CONTEXT_KEYS = frozenset(
    {
        "counterfactual",
        "future_evaluation",
        "future_return",
        "future_returns",
        "mae",
        "mfe",
        "outcome",
        "outcome_label",
        "outcomes",
        "pnl",
        "realized_pnl",
        "trade_outcome",
    }
)
_PIT_TIMESTAMP_KEYS = frozenset(
    {
        "available_at_utc",
        "captured_at_utc",
        "observed_at_utc",
        "published_at_utc",
        "retrieved_at_utc",
    }
)


class PaperSimulatorError(ValueError):
    pass


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def _utc(value: Any, *, name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError as exc:
            raise PaperSimulatorError(f"{name} must be timezone-aware ISO-8601 text.") from exc
    else:
        raise TypeError(f"{name} must be a timezone-aware datetime or ISO-8601 string.")
    if parsed.tzinfo is None:
        raise PaperSimulatorError(f"{name} must be timezone-aware.")
    return parsed.astimezone(UTC)


def _decimal(value: Any, *, name: str, positive: bool = False) -> Decimal:
    if value is None or isinstance(value, bool):
        raise PaperSimulatorError(f"{name} must be a finite number.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise PaperSimulatorError(f"{name} must be a finite number.") from exc
    if not parsed.is_finite():
        raise PaperSimulatorError(f"{name} must be a finite number.")
    if positive and parsed <= 0:
        raise PaperSimulatorError(f"{name} must be greater than zero.")
    return parsed


def _q(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.000000")))


def _assert_pit_context(value: Any, *, as_of: datetime, path: str = "context") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_CONTEXT_KEYS:
                raise PaperSimulatorError(f"Execution/account field is forbidden at {path}.{key}.")
            if normalized in _OUTCOME_CONTEXT_KEYS:
                raise PaperSimulatorError(f"Future/outcome field is forbidden at {path}.{key}.")
            if normalized == "future_derived" and item is not False:
                raise PaperSimulatorError(f"Future-derived evidence is forbidden at {path}.{key}.")
            if normalized == "evaluation_only" and item is not False:
                raise PaperSimulatorError(f"Evaluation-only evidence is forbidden at {path}.{key}.")
            if normalized in _PIT_TIMESTAMP_KEYS and item is not None:
                available = _utc(item, name=f"{path}.{key}")
                if available > as_of:
                    raise PaperSimulatorError(
                        f"PIT evidence timestamp at {path}.{key} is later than the observation."
                    )
            _assert_pit_context(item, as_of=as_of, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_pit_context(item, as_of=as_of, path=f"{path}[{index}]")


def normalize_paper_observation(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("Paper observation must be a mapping.")
    required = {"observation_version", "as_of_utc", "symbol", "mid", "context"}
    if set(value) != required:
        raise PaperSimulatorError("Paper observation fields do not match the Day 46 contract.")
    if value["observation_version"] != PAPER_OBSERVATION_VERSION:
        raise PaperSimulatorError("Unsupported paper observation version.")
    if value["symbol"] != SUPPORTED_SYMBOL:
        raise PaperSimulatorError("Day 46 paper observations support XAUUSD only.")
    stamp = _utc(value["as_of_utc"], name="as_of_utc")
    mid = _decimal(value["mid"], name="mid", positive=True)
    context = value["context"]
    if not isinstance(context, Mapping):
        raise TypeError("Paper observation context must be a mapping.")
    snapshot = copy.deepcopy(dict(context))
    context_symbol = snapshot.get("symbol")
    if context_symbol is not None and context_symbol != SUPPORTED_SYMBOL:
        raise PaperSimulatorError("Observation context symbol does not match XAUUSD.")
    context_as_of = snapshot.get("as_of_utc")
    if context_as_of is not None and _utc(context_as_of, name="context.as_of_utc") > stamp:
        raise PaperSimulatorError("Observation context cannot come from the future.")
    _assert_pit_context(snapshot, as_of=stamp)
    normalized: dict[str, Any] = {
        "observation_version": PAPER_OBSERVATION_VERSION,
        "as_of_utc": stamp.isoformat(),
        "symbol": SUPPORTED_SYMBOL,
        "mid": _q(mid),
        "context": snapshot,
    }
    normalized["observation_digest"] = digest(normalized)
    return normalized


def build_paper_observation(
    *,
    as_of_utc: datetime | str,
    mid: Any,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    return normalize_paper_observation(
        {
            "observation_version": PAPER_OBSERVATION_VERSION,
            "as_of_utc": as_of_utc,
            "symbol": SUPPORTED_SYMBOL,
            "mid": mid,
            "context": context,
        }
    )


def _event_digest(event: Mapping[str, Any]) -> str:
    body = copy.deepcopy(dict(event))
    body.pop("event_digest", None)
    return digest(body)


def _state_digest(state: Mapping[str, Any]) -> str:
    body = copy.deepcopy(dict(state))
    body.pop("state_digest", None)
    return digest(body)


def verify_paper_state(state: Mapping[str, Any]) -> bool:
    if not isinstance(state, Mapping):
        return False
    if state.get("state_version") != PAPER_STATE_VERSION:
        return False
    if state.get("simulator_version") != PAPER_SIMULATOR_VERSION:
        return False
    if state.get("position_state") not in SUPPORTED_POSITION_STATES:
        return False
    supplied = str(state.get("state_digest") or "")
    if not supplied or supplied != _state_digest(state):
        return False
    events = state.get("lifecycle_events")
    if not isinstance(events, list) or not events:
        return False
    for event in events:
        if not isinstance(event, Mapping):
            return False
        if str(event.get("event_digest") or "") != _event_digest(event):
            return False
    return True


def _position_geometry(decision: Mapping[str, Any]) -> dict[str, Any]:
    entry = _decimal(decision["market_reference_price"], name="entry", positive=True)
    stop = _decimal(decision["stop_loss"], name="stop", positive=True)
    targets = [_decimal(item, name="target", positive=True) for item in decision["targets"]]
    return {
        "direction": decision["direction"],
        "entry_price": _q(entry),
        "stop_loss": _q(stop),
        "targets": [_q(item) for item in targets],
        "initial_target_count": len(targets),
        "risk_distance": _q(abs(entry - stop)),
    }


def start_paper_position(ex_ante_record: Mapping[str, Any]) -> dict[str, Any]:
    if not verify_ex_ante_record(ex_ante_record):
        raise PaperSimulatorError("Day 46 requires a valid immutable ex-ante ledger record.")
    if ex_ante_record.get("cycle_disposition") != "decision_admitted":
        raise PaperSimulatorError("Only admitted decisions can open a paper position.")
    raw_decision = ex_ante_record.get("decision")
    if not isinstance(raw_decision, Mapping):
        raise PaperSimulatorError("Admitted ledger record is missing its decision snapshot.")
    decision = validate_master_trader_decision_versioned(raw_decision)
    if decision["contract_version"] != MASTER_TRADER_CONTRACT_VERSION_V2:
        raise PaperSimulatorError("Day 46 requires the falsifiable Master Trader V2 contract.")
    if decision["action"] != "new_trade":
        raise PaperSimulatorError("Day 46 opens paper positions only from new_trade decisions.")

    geometry = _position_geometry(decision)
    invalidation_condition = validate_machine_condition(
        decision["invalidation_condition"], name="invalidation_condition"
    )
    opened_at = _utc(decision["evaluated_at_utc"], name="evaluated_at_utc")
    position_id = f"paper:{ex_ante_record['decision_id']}"
    opening_event: dict[str, Any] = {
        "event_type": "position_opened",
        "event_index": 0,
        "as_of_utc": opened_at.isoformat(),
        "observation_digest": None,
        "mid": geometry["entry_price"],
        "target_hits": [],
        "stop_hit": False,
        "invalidation_result": "not_evaluated",
        "resulting_state": "open",
    }
    opening_event["event_digest"] = _event_digest(opening_event)

    state: dict[str, Any] = {
        "state_version": PAPER_STATE_VERSION,
        "simulator_version": PAPER_SIMULATOR_VERSION,
        "position_id": position_id,
        "symbol": SUPPORTED_SYMBOL,
        "ex_ante_digest": str(ex_ante_record["ex_ante_digest"]),
        "decision_id": str(ex_ante_record["decision_id"]),
        "model_decision_digest": str(ex_ante_record.get("model_decision_digest") or ""),
        "opened_at_utc": opened_at.isoformat(),
        "position_state": "open",
        **geometry,
        "hit_target_indices": [],
        "remaining_target_indices": list(range(1, geometry["initial_target_count"] + 1)),
        "stop_hit": False,
        "closed_at_utc": None,
        "closed_price": None,
        "realized_r": "0.000000",
        "observation_count": 0,
        "last_observation_at_utc": None,
        "thesis_snapshot": {
            "thesis": decision["thesis"],
            "expected_horizon_minutes": decision["expected_horizon_minutes"],
            "counter_argument": decision["counter_argument"],
            "invalidation_condition": invalidation_condition,
        },
        "invalidation": {
            "invalidation_version": PAPER_INVALIDATION_VERSION,
            "condition_digest": digest(invalidation_condition),
            "status": "not_triggered",
            "first_triggered_at_utc": None,
            "evaluation_count": 0,
            "unknown_count": 0,
            "last_result": None,
        },
        "lifecycle_events": [opening_event],
        "paper_only": True,
        "execution_authority": False,
        "account_state_used": False,
        "follower_state_used": False,
        "telegram_action_allowed": False,
        "mt5_action_allowed": False,
    }
    state["state_digest"] = _state_digest(state)
    return state


def _directional_r(direction: str, *, entry: Decimal, price: Decimal, risk: Decimal) -> Decimal:
    move = price - entry if direction == "long" else entry - price
    return move / risk


def _realized_r(state: Mapping[str, Any]) -> Decimal:
    entry = _decimal(state["entry_price"], name="entry_price", positive=True)
    stop = _decimal(state["stop_loss"], name="stop_loss", positive=True)
    risk = abs(entry - stop)
    targets = [_decimal(item, name="target", positive=True) for item in state["targets"]]
    target_count = len(targets)
    result = Decimal(0)
    for index in state["hit_target_indices"]:
        result += _directional_r(
            str(state["direction"]),
            entry=entry,
            price=targets[int(index) - 1],
            risk=risk,
        ) / Decimal(target_count)
    if state["stop_hit"]:
        remaining = target_count - len(state["hit_target_indices"])
        result -= Decimal(remaining) / Decimal(target_count)
    return result


def _hit_targets(state: Mapping[str, Any], mid: Decimal) -> list[int]:
    targets = [_decimal(item, name="target", positive=True) for item in state["targets"]]
    remaining = set(int(item) for item in state["remaining_target_indices"])
    if state["direction"] == "long":
        return [index for index, target in enumerate(targets, start=1) if index in remaining and mid >= target]
    return [index for index, target in enumerate(targets, start=1) if index in remaining and mid <= target]


def _stop_is_hit(state: Mapping[str, Any], mid: Decimal) -> bool:
    stop = _decimal(state["stop_loss"], name="stop_loss", positive=True)
    if state["direction"] == "long":
        return mid <= stop
    return mid >= stop


def apply_paper_observation(
    state: Mapping[str, Any],
    observation: Mapping[str, Any],
) -> dict[str, Any]:
    if not verify_paper_state(state):
        raise PaperSimulatorError("Paper state digest or lifecycle history is invalid.")
    normalized = normalize_paper_observation(observation)
    observation_digest = str(normalized["observation_digest"])
    events = state["lifecycle_events"]
    if any(event.get("observation_digest") == observation_digest for event in events):
        return copy.deepcopy(dict(state))

    stamp = _utc(normalized["as_of_utc"], name="observation.as_of_utc")
    opened_at = _utc(state["opened_at_utc"], name="opened_at_utc")
    if stamp < opened_at:
        raise PaperSimulatorError("Paper observation predates the ex-ante decision.")
    last_at = state.get("last_observation_at_utc")
    if last_at is not None:
        previous = _utc(last_at, name="last_observation_at_utc")
        if stamp <= previous:
            same_time = [
                event
                for event in events
                if event.get("observation_digest") is not None
                and _utc(event["as_of_utc"], name="event.as_of_utc") == stamp
            ]
            if same_time:
                raise PaperSimulatorError("Conflicting paper observation at an already-seen timestamp.")
            raise PaperSimulatorError("Paper observations must be strictly chronological.")
    if state["position_state"].startswith("closed_"):
        raise PaperSimulatorError("Closed paper positions are immutable.")

    updated = copy.deepcopy(dict(state))
    updated.pop("state_digest", None)
    mid = _decimal(normalized["mid"], name="observation.mid", positive=True)

    invalidation_result = evaluate_machine_condition(
        updated["thesis_snapshot"]["invalidation_condition"], normalized["context"]
    )
    tracker = updated["invalidation"]
    tracker["evaluation_count"] += 1
    if invalidation_result is None:
        tracker["unknown_count"] += 1
        tracker["last_result"] = "unknown"
    elif invalidation_result:
        tracker["last_result"] = "true"
        if tracker["status"] != "triggered":
            tracker["status"] = "triggered"
            tracker["first_triggered_at_utc"] = stamp.isoformat()
    else:
        tracker["last_result"] = "false"

    stop_hit = _stop_is_hit(updated, mid)
    target_hits: list[int] = [] if stop_hit else _hit_targets(updated, mid)
    if target_hits:
        updated["hit_target_indices"] = sorted(
            set(int(item) for item in updated["hit_target_indices"]) | set(target_hits)
        )
        updated["remaining_target_indices"] = [
            item
            for item in updated["remaining_target_indices"]
            if int(item) not in set(target_hits)
        ]
        if updated["remaining_target_indices"]:
            updated["position_state"] = "partial"
        else:
            updated["position_state"] = "closed_targets"
            updated["closed_at_utc"] = stamp.isoformat()
            updated["closed_price"] = normalized["mid"]
    elif stop_hit:
        updated["stop_hit"] = True
        updated["position_state"] = "closed_stop"
        updated["closed_at_utc"] = stamp.isoformat()
        updated["closed_price"] = normalized["mid"]

    updated["realized_r"] = _q(_realized_r(updated))
    updated["observation_count"] += 1
    updated["last_observation_at_utc"] = stamp.isoformat()
    event: dict[str, Any] = {
        "event_type": "market_observation",
        "event_index": len(updated["lifecycle_events"]),
        "as_of_utc": stamp.isoformat(),
        "observation_digest": observation_digest,
        "mid": normalized["mid"],
        "target_hits": target_hits,
        "stop_hit": stop_hit,
        "invalidation_result": (
            "unknown" if invalidation_result is None else "true" if invalidation_result else "false"
        ),
        "resulting_state": updated["position_state"],
    }
    event["event_digest"] = _event_digest(event)
    updated["lifecycle_events"].append(event)
    updated["state_digest"] = _state_digest(updated)
    return updated


def serialize_paper_state(state: Mapping[str, Any]) -> str:
    if not verify_paper_state(state):
        raise PaperSimulatorError("Cannot serialize an invalid paper state.")
    return canonical_json(state)


def restore_paper_state(payload: str) -> dict[str, Any]:
    if not isinstance(payload, str) or not payload.strip():
        raise TypeError("Serialized paper state must be non-empty JSON text.")
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise PaperSimulatorError("Serialized paper state is not valid JSON.") from exc
    if not isinstance(decoded, dict) or not verify_paper_state(decoded):
        raise PaperSimulatorError("Serialized paper state failed deterministic verification.")
    return decoded


def reconcile_paper_state(
    existing: Mapping[str, Any],
    incoming: Mapping[str, Any],
) -> dict[str, Any]:
    if not verify_paper_state(existing) or not verify_paper_state(incoming):
        raise PaperSimulatorError("Cannot reconcile invalid paper state.")
    if existing["position_id"] != incoming["position_id"]:
        raise PaperSimulatorError("Paper position identities do not match.")
    if existing["ex_ante_digest"] != incoming["ex_ante_digest"]:
        raise PaperSimulatorError("Paper position ex-ante bindings do not match.")
    if existing["state_digest"] == incoming["state_digest"]:
        return copy.deepcopy(dict(existing))
    old_events = existing["lifecycle_events"]
    new_events = incoming["lifecycle_events"]
    if len(new_events) <= len(old_events) or new_events[: len(old_events)] != old_events:
        raise PaperSimulatorError("Paper lifecycle history was rewritten or forked.")
    return copy.deepcopy(dict(incoming))


def replay_paper_position(
    ex_ante_record: Mapping[str, Any],
    observations: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    state = start_paper_position(ex_ante_record)
    for observation in observations:
        state = apply_paper_observation(state, observation)
    return state


def paper_position_outcome_payload(state: Mapping[str, Any]) -> dict[str, Any]:
    if not verify_paper_state(state):
        raise PaperSimulatorError("Cannot build an outcome from invalid paper state.")
    if not str(state["position_state"]).startswith("closed_"):
        raise PaperSimulatorError("Paper outcome is available only after deterministic closure.")
    thesis_status = (
        "invalidated"
        if state["invalidation"]["status"] == "triggered"
        else "not_invalidated_observed"
    )
    result: dict[str, Any] = {
        "simulator_version": PAPER_SIMULATOR_VERSION,
        "position_id": state["position_id"],
        "final_position_state": state["position_state"],
        "closed_at_utc": state["closed_at_utc"],
        "economic_outcome": {
            "entry_price": state["entry_price"],
            "stop_loss": state["stop_loss"],
            "targets": copy.deepcopy(state["targets"]),
            "hit_target_indices": copy.deepcopy(state["hit_target_indices"]),
            "stop_hit": state["stop_hit"],
            "realized_r": state["realized_r"],
        },
        "thesis_outcome": {
            "status": thesis_status,
            "first_invalidation_at_utc": state["invalidation"]["first_triggered_at_utc"],
            "evaluation_count": state["invalidation"]["evaluation_count"],
            "unknown_count": state["invalidation"]["unknown_count"],
            "condition_digest": state["invalidation"]["condition_digest"],
        },
        "observation_count": state["observation_count"],
        "final_state_digest": state["state_digest"],
        "economic_and_thesis_outcomes_separate": True,
        "ex_ante_thesis_mutated": False,
        "formal_forward_evidence": False,
        "paper_only": True,
    }
    result["outcome_digest"] = digest(result)
    return result


def build_paper_outcome_attachment(
    *,
    ex_ante_record: Mapping[str, Any],
    state: Mapping[str, Any],
    attached_at_utc: datetime | str,
) -> dict[str, Any]:
    if not verify_ex_ante_record(ex_ante_record):
        raise PaperSimulatorError("Outcome attachment requires a valid ex-ante record.")
    if state.get("ex_ante_digest") != ex_ante_record.get("ex_ante_digest"):
        raise PaperSimulatorError("Paper state is not bound to this ex-ante record.")
    payload = paper_position_outcome_payload(state)
    attached_at = _utc(attached_at_utc, name="attached_at_utc")
    closed_at = _utc(state["closed_at_utc"], name="closed_at_utc")
    if attached_at < closed_at:
        raise PaperSimulatorError("Outcome cannot be attached before paper position closure.")
    return build_outcome_attachment(
        ex_ante_record=ex_ante_record,
        attachment_type="trade_outcome",
        attached_at_utc=attached_at,
        outcome_contract_version=PAPER_OUTCOME_CONTRACT_VERSION,
        outcome_identity=f"{state['position_id']}:final",
        outcome_payload=payload,
    )


def day46_manifest() -> dict[str, Any]:
    result: dict[str, Any] = {
        "manifest_version": PAPER_MANIFEST_VERSION,
        "simulator_version": PAPER_SIMULATOR_VERSION,
        "state_version": PAPER_STATE_VERSION,
        "observation_version": PAPER_OBSERVATION_VERSION,
        "invalidation_version": PAPER_INVALIDATION_VERSION,
        "outcome_contract_version": PAPER_OUTCOME_CONTRACT_VERSION,
        "paper_only": True,
        "v2_falsifiable_new_trade_required": True,
        "pit_observations_required": True,
        "unknown_invalidation_is_preserved": True,
        "invalidation_can_mutate_trade_state": False,
        "economic_and_thesis_outcomes_separate": True,
        "restart_safe_history_prefix_required": True,
        "outcomes_attach_without_ex_ante_mutation": True,
        "broker_access_allowed": False,
        "account_access_allowed": False,
        "follower_access_allowed": False,
        "telegram_action_allowed": False,
        "mt5_action_allowed": False,
        "formal_forward_evidence_created": False,
    }
    result["manifest_digest"] = digest(result)
    return result
