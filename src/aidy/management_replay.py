from __future__ import annotations

import copy
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy.decision_ledger import verify_ex_ante_record
from aidy.management_contract_v2 import verify_management_action_record
from aidy.paper_simulator import (
    apply_paper_observation,
    normalize_paper_observation,
    paper_position_outcome_payload,
    start_paper_position,
)
from aidy.pit_reconstruction import normalize_as_of

MANAGEMENT_REPLAY_VERSION = "aidy_management_replay_v1"
MANAGED_STATE_VERSION = "aidy_managed_replay_state_v1"
UNCHANGED_BENCHMARK_VERSION = "aidy_management_do_nothing_benchmark_v1"
MANAGEMENT_EVALUATION_VERSION = "aidy_management_counterfactual_evaluation_v1"
MANAGEMENT_REPLAY_MANIFEST_VERSION = "aidy_day49_management_replay_manifest_v1"
DEFAULT_MIN_EFFECTIVE_N = 30


class ManagementReplayError(ValueError):
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
        raise ManagementReplayError("replay_timestamp_invalid", f"{name} is invalid.") from exc


def _decimal(value: Any, *, name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ManagementReplayError("replay_number_invalid", f"{name} is required.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ManagementReplayError("replay_number_invalid", f"{name} must be numeric.") from exc
    if not parsed.is_finite():
        raise ManagementReplayError("replay_number_invalid", f"{name} must be finite.")
    return parsed


def _q(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def _state_digest(state: Mapping[str, Any]) -> str:
    body = copy.deepcopy(dict(state))
    body.pop("state_digest", None)
    return digest(body)


def verify_managed_replay_state(state: Mapping[str, Any]) -> bool:
    if not isinstance(state, Mapping):
        return False
    supplied = str(state.get("state_digest") or "")
    try:
        if state.get("state_version") != MANAGED_STATE_VERSION:
            return False
        if state.get("replay_version") != MANAGEMENT_REPLAY_VERSION:
            return False
        if state.get("paper_only") is not True or state.get("execution_allowed") is not False:
            return False
        if state.get("position_state") not in {
            "open",
            "partial",
            "closed_targets",
            "closed_stop",
            "closed_management",
        }:
            return False
        remaining = list(state.get("remaining_leg_indices") or [])
        hit = list(state.get("hit_target_indices") or [])
        if set(remaining) & set(hit):
            return False
        if len(set(remaining)) != len(remaining) or len(set(hit)) != len(hit):
            return False
        if int(state.get("target_count", -1)) != len(state.get("current_targets") or []):
            return False
        if state.get("position_state").startswith("closed_") and remaining:
            return False
    except (TypeError, ValueError):
        return False
    return bool(supplied) and supplied == _state_digest(state)


def start_managed_replay(ex_ante_record: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(ex_ante_record, Mapping) or not verify_ex_ante_record(ex_ante_record):
        raise ManagementReplayError("replay_ex_ante_invalid", "Valid ex-ante record required.")
    paper = start_paper_position(ex_ante_record)
    target_count = int(paper["initial_target_count"])
    state: dict[str, Any] = {
        "state_version": MANAGED_STATE_VERSION,
        "replay_version": MANAGEMENT_REPLAY_VERSION,
        "benchmark_version": UNCHANGED_BENCHMARK_VERSION,
        "position_id": paper["position_id"],
        "originating_decision_id": paper["decision_id"],
        "ex_ante_digest": paper["ex_ante_digest"],
        "symbol": paper["symbol"],
        "direction": paper["direction"],
        "entry_price": paper["entry_price"],
        "original_stop_loss": paper["stop_loss"],
        "current_stop_loss": paper["stop_loss"],
        "target_count": target_count,
        "current_targets": copy.deepcopy(list(paper["targets"])),
        "remaining_leg_indices": list(range(1, target_count + 1)),
        "hit_target_indices": [],
        "position_state": "open",
        "realized_r": "0.000000",
        "closed_at_utc": None,
        "closed_price": None,
        "last_observation_at_utc": None,
        "observation_count": 0,
        "applied_management_action_ids": [],
        "events": [],
        "paper_only": True,
        "execution_allowed": False,
    }
    state["state_digest"] = _state_digest(state)
    return state


def serialize_managed_replay_state(state: Mapping[str, Any]) -> str:
    if not verify_managed_replay_state(state):
        raise ManagementReplayError("replay_state_invalid", "Cannot serialize invalid replay state.")
    return canonical_json(state)


def restore_managed_replay_state(payload: str) -> dict[str, Any]:
    if not isinstance(payload, str) or not payload.strip():
        raise ManagementReplayError("replay_state_invalid", "Serialized state is empty.")
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ManagementReplayError("replay_state_invalid", "Serialized state is invalid JSON.") from exc
    if not isinstance(value, dict) or not verify_managed_replay_state(value):
        raise ManagementReplayError("replay_state_invalid", "Serialized state failed verification.")
    return value


def _directional_r(state: Mapping[str, Any], price: Decimal) -> Decimal:
    entry = _decimal(state["entry_price"], name="entry_price")
    original_stop = _decimal(state["original_stop_loss"], name="original_stop_loss")
    risk = abs(entry - original_stop)
    if risk <= 0:
        raise ManagementReplayError("replay_geometry_invalid", "Original risk must be positive.")
    move = price - entry if state["direction"] == "long" else entry - price
    return move / risk


def _add_leg_result(state: dict[str, Any], *, price: Decimal, leg_count: int) -> None:
    realized = _decimal(state["realized_r"], name="realized_r")
    contribution = _directional_r(state, price) * Decimal(leg_count) / Decimal(state["target_count"])
    state["realized_r"] = _q(realized + contribution)


def _observation_context_hash(observation: Mapping[str, Any]) -> str | None:
    context = observation.get("context")
    if not isinstance(context, Mapping):
        return None
    value = context.get("context_hash")
    return str(value) if isinstance(value, str) and value else None


def _validate_action_for_observation(
    action: Mapping[str, Any], *, state: Mapping[str, Any], observation: Mapping[str, Any]
) -> dict[str, Any]:
    if not isinstance(action, Mapping) or not verify_management_action_record(action):
        raise ManagementReplayError("replay_management_action_invalid", "Invalid Day 48 action record.")
    normalized = copy.deepcopy(dict(action))
    if normalized.get("position_id") != state.get("position_id"):
        raise ManagementReplayError("replay_management_target_mismatch", "Action targets another position.")
    if normalized.get("originating_decision_id") != state.get("originating_decision_id"):
        raise ManagementReplayError("replay_management_target_mismatch", "Action targets another decision.")
    decision = normalized.get("decision")
    if not isinstance(decision, Mapping):
        raise ManagementReplayError("replay_management_action_invalid", "Action decision is missing.")
    action_at = _utc(decision.get("evaluated_at_utc"), name="management.evaluated_at_utc")
    observation_at = _utc(observation.get("as_of_utc"), name="observation.as_of_utc")
    if action_at != observation_at:
        raise ManagementReplayError(
            "replay_delayed_or_mismatched_evidence",
            "Management action must be evaluated on the exact observation timestamp.",
        )
    context_hash = _observation_context_hash(observation)
    if not context_hash or context_hash != normalized.get("context_hash"):
        raise ManagementReplayError(
            "replay_delayed_or_mismatched_evidence",
            "Management action context does not match the replay observation.",
        )
    return normalized


def _apply_action(state: dict[str, Any], action: Mapping[str, Any], *, mid: Decimal, stamp: datetime) -> None:
    decision = action["decision"]
    action_id = str(action["management_action_id"])
    if action_id in state["applied_management_action_ids"]:
        return
    if state["position_state"].startswith("closed_"):
        raise ManagementReplayError("replay_action_after_closure", "Management cannot progress after closure.")
    if decision["action"] == "close_trade":
        leg_count = len(state["remaining_leg_indices"])
        _add_leg_result(state, price=mid, leg_count=leg_count)
        state["remaining_leg_indices"] = []
        state["position_state"] = "closed_management"
        state["closed_at_utc"] = stamp.isoformat()
        state["closed_price"] = str(mid)
    else:
        instruction = decision["management_instruction"]
        if instruction in {"move_stop", "move_stop_and_targets"}:
            new_stop = _decimal(decision["new_stop_loss"], name="new_stop_loss")
            current = _decimal(state["current_stop_loss"], name="current_stop_loss")
            if state["direction"] == "long":
                valid = current <= new_stop < mid
            else:
                valid = current >= new_stop > mid
            if not valid:
                raise ManagementReplayError(
                    "replay_management_geometry_invalid",
                    "Replay stop change worsens risk or crosses current price.",
                )
            state["current_stop_loss"] = str(decision["new_stop_loss"])
        if instruction in {"replace_targets", "move_stop_and_targets"}:
            replacements = list(decision["new_targets"])
            remaining = list(state["remaining_leg_indices"])
            if len(replacements) != len(remaining):
                raise ManagementReplayError(
                    "replay_ambiguous_target_mapping",
                    "Replay requires one replacement target per remaining leg.",
                )
            target_values = [_decimal(item, name="new_target") for item in replacements]
            if state["direction"] == "long":
                valid = target_values == sorted(target_values) and all(item > mid for item in target_values)
            else:
                valid = target_values == sorted(target_values, reverse=True) and all(
                    item < mid for item in target_values
                )
            if not valid:
                raise ManagementReplayError(
                    "replay_management_geometry_invalid", "Replacement target geometry is invalid."
                )
            for leg_index, replacement in zip(remaining, replacements, strict=True):
                state["current_targets"][int(leg_index) - 1] = str(replacement)
    state["applied_management_action_ids"].append(action_id)
    state["events"].append(
        {
            "event_type": "management_action",
            "as_of_utc": stamp.isoformat(),
            "management_action_id": action_id,
            "action": decision["action"],
            "resulting_state": state["position_state"],
        }
    )


def apply_managed_replay_observation(
    state: Mapping[str, Any],
    observation: Mapping[str, Any],
    *,
    management_action: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not verify_managed_replay_state(state):
        raise ManagementReplayError("replay_state_invalid", "Managed replay state is invalid.")
    normalized = normalize_paper_observation(observation)
    stamp = _utc(normalized["as_of_utc"], name="observation.as_of_utc")
    previous = state.get("last_observation_at_utc")
    if previous is not None and stamp <= _utc(previous, name="last_observation_at_utc"):
        raise ManagementReplayError("replay_observation_order_invalid", "Observations must be chronological.")
    updated = copy.deepcopy(dict(state))
    updated.pop("state_digest", None)
    if updated["position_state"].startswith("closed_"):
        if management_action is not None:
            raise ManagementReplayError("replay_action_after_closure", "Action supplied after closure.")
        updated["state_digest"] = _state_digest(updated)
        return updated

    mid = _decimal(normalized["mid"], name="observation.mid")
    stop = _decimal(updated["current_stop_loss"], name="current_stop_loss")
    stop_hit = mid <= stop if updated["direction"] == "long" else mid >= stop
    target_hits: list[int] = []
    if not stop_hit:
        for leg_index in list(updated["remaining_leg_indices"]):
            target = _decimal(updated["current_targets"][int(leg_index) - 1], name="current_target")
            hit = mid >= target if updated["direction"] == "long" else mid <= target
            if hit:
                target_hits.append(int(leg_index))

    if stop_hit:
        leg_count = len(updated["remaining_leg_indices"])
        _add_leg_result(updated, price=stop, leg_count=leg_count)
        updated["remaining_leg_indices"] = []
        updated["position_state"] = "closed_stop"
        updated["closed_at_utc"] = stamp.isoformat()
        updated["closed_price"] = str(stop)
    elif target_hits:
        for leg_index in target_hits:
            target = _decimal(updated["current_targets"][leg_index - 1], name="current_target")
            _add_leg_result(updated, price=target, leg_count=1)
        hit_set = set(target_hits)
        updated["hit_target_indices"] = sorted(set(updated["hit_target_indices"]) | hit_set)
        updated["remaining_leg_indices"] = [
            item for item in updated["remaining_leg_indices"] if int(item) not in hit_set
        ]
        if updated["remaining_leg_indices"]:
            updated["position_state"] = "partial"
        else:
            updated["position_state"] = "closed_targets"
            updated["closed_at_utc"] = stamp.isoformat()
            updated["closed_price"] = str(mid)

    updated["observation_count"] += 1
    updated["last_observation_at_utc"] = stamp.isoformat()
    updated["events"].append(
        {
            "event_type": "market_observation",
            "as_of_utc": stamp.isoformat(),
            "observation_digest": normalized["observation_digest"],
            "mid": normalized["mid"],
            "stop_hit": stop_hit,
            "target_hits": target_hits,
            "resulting_state": updated["position_state"],
        }
    )
    if management_action is not None:
        action = _validate_action_for_observation(management_action, state=updated, observation=normalized)
        _apply_action(updated, action, mid=mid, stamp=stamp)
    updated["state_digest"] = _state_digest(updated)
    return updated


def _actions_by_timestamp(actions: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_time: dict[str, dict[str, Any]] = {}
    for raw in actions:
        if not isinstance(raw, Mapping) or not verify_management_action_record(raw):
            raise ManagementReplayError("replay_management_action_invalid", "Invalid management action.")
        action = copy.deepcopy(dict(raw))
        action_id = str(action["management_action_id"])
        previous = by_id.get(action_id)
        if previous is not None:
            if previous["ledger_digest"] != action["ledger_digest"]:
                raise ManagementReplayError("replay_conflicting_action", "Duplicate action ID conflicts.")
            continue
        by_id[action_id] = action
        stamp = _utc(action["decision"]["evaluated_at_utc"], name="management.evaluated_at_utc").isoformat()
        if stamp in by_time:
            raise ManagementReplayError(
                "replay_conflicting_action", "Multiple different management actions share a timestamp."
            )
        by_time[stamp] = action
    return by_time


def _unchanged_replay(
    ex_ante_record: Mapping[str, Any], observations: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    state = start_paper_position(ex_ante_record)
    for raw in observations:
        if str(state["position_state"]).startswith("closed_"):
            break
        state = apply_paper_observation(state, raw)
    return state


def replay_management_episode(
    *,
    ex_ante_record: Mapping[str, Any],
    observations: Iterable[Mapping[str, Any]],
    management_actions: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    observation_rows = [copy.deepcopy(dict(item)) for item in observations]
    action_map = _actions_by_timestamp(management_actions)
    baseline = _unchanged_replay(ex_ante_record, observation_rows)
    managed = start_managed_replay(ex_ante_record)
    seen_action_times: set[str] = set()
    for raw in observation_rows:
        stamp = _utc(raw.get("as_of_utc"), name="observation.as_of_utc").isoformat()
        action = action_map.get(stamp)
        if action is not None:
            seen_action_times.add(stamp)
        managed = apply_managed_replay_observation(managed, raw, management_action=action)
    missing = sorted(set(action_map) - seen_action_times)
    if missing:
        raise ManagementReplayError(
            "replay_delayed_or_mismatched_evidence",
            f"Management action has no exact replay observation: {missing[0]}",
        )
    baseline_closed = str(baseline["position_state"]).startswith("closed_")
    managed_closed = str(managed["position_state"]).startswith("closed_")
    result: dict[str, Any] = {
        "evaluation_version": MANAGEMENT_EVALUATION_VERSION,
        "replay_version": MANAGEMENT_REPLAY_VERSION,
        "unchanged_benchmark_version": UNCHANGED_BENCHMARK_VERSION,
        "originating_decision_id": ex_ante_record.get("decision_id"),
        "position_id": managed["position_id"],
        "baseline_complete": baseline_closed,
        "managed_complete": managed_closed,
        "entry_quality": {
            "unchanged_final_state": baseline["position_state"],
            "unchanged_realized_r": baseline["realized_r"],
            "unchanged_outcome_digest": (
                paper_position_outcome_payload(baseline)["outcome_digest"] if baseline_closed else None
            ),
        },
        "management_quality": {
            "managed_final_state": managed["position_state"],
            "managed_realized_r": managed["realized_r"],
            "management_action_count": len(managed["applied_management_action_ids"]),
            "management_delta_r": (
                _q(
                    _decimal(managed["realized_r"], name="managed_realized_r")
                    - _decimal(baseline["realized_r"], name="baseline_realized_r")
                )
                if baseline_closed and managed_closed
                else None
            ),
        },
        "entry_and_management_effects_separate": True,
        "unchanged_trade_is_counterfactual": True,
        "management_promoted": False,
        "paper_only": True,
        "execution_allowed": False,
        "managed_state_digest": managed["state_digest"],
        "baseline_state_digest": baseline["state_digest"],
    }
    result["evaluation_digest"] = digest(result)
    return result


def _mean(values: list[Decimal]) -> str | None:
    if not values:
        return None
    return _q(sum(values, Decimal(0)) / Decimal(len(values)))


def _segment(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row[key])].append(row)
    output: dict[str, Any] = {}
    for name in sorted(groups):
        items = groups[name]
        deltas = [
            _decimal(item["management_delta_r"], name="management_delta_r")
            for item in items
            if item["management_delta_r"] is not None
        ]
        output[name] = {
            "episode_count": len(items),
            "effective_n": len({str(item["independence_cluster_id"]) for item in items}),
            "mean_management_delta_r": _mean(deltas),
        }
    return output


def evaluate_management_cohort(
    episodes: Iterable[Mapping[str, Any]], *, minimum_effective_n: int = DEFAULT_MIN_EFFECTIVE_N
) -> dict[str, Any]:
    if isinstance(minimum_effective_n, bool) or minimum_effective_n < 1:
        raise ValueError("minimum_effective_n must be a positive integer.")
    raw_rows = [copy.deepcopy(dict(item)) for item in episodes]
    by_episode: dict[str, dict[str, Any]] = {}
    for row in raw_rows:
        episode_id = str(row.get("episode_id") or "")
        if not episode_id:
            raise ManagementReplayError("replay_episode_invalid", "episode_id is required.")
        previous = by_episode.get(episode_id)
        if previous is not None:
            if digest(previous) != digest(row):
                raise ManagementReplayError(
                    "replay_episode_conflict", "Duplicate episode_id has conflicting payloads."
                )
            continue
        by_episode[episode_id] = row

    evaluated: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for episode_id in sorted(by_episode):
        row = by_episode[episode_id]
        cluster = str(row.get("independence_cluster_id") or "")
        regime = str(row.get("regime") or "unknown")
        setup = str(row.get("setup_family") or "unknown")
        if not cluster:
            raise ManagementReplayError(
                "replay_episode_invalid", "independence_cluster_id is required."
            )
        try:
            result = replay_management_episode(
                ex_ante_record=row["ex_ante_record"],
                observations=row["observations"],
                management_actions=row.get("management_actions") or [],
            )
        except (KeyError, TypeError, ValueError) as exc:
            rejected.append({"episode_id": episode_id, "reason": str(exc)})
            continue
        delta = result["management_quality"]["management_delta_r"]
        evaluated.append(
            {
                "episode_id": episode_id,
                "independence_cluster_id": cluster,
                "regime": regime,
                "setup_family": setup,
                "baseline_complete": result["baseline_complete"],
                "managed_complete": result["managed_complete"],
                "unchanged_realized_r": result["entry_quality"]["unchanged_realized_r"],
                "managed_realized_r": result["management_quality"]["managed_realized_r"],
                "management_delta_r": delta,
                "evaluation_digest": result["evaluation_digest"],
            }
        )
    eligible = [row for row in evaluated if row["management_delta_r"] is not None]
    effective_n = len({row["independence_cluster_id"] for row in eligible})
    deltas = [_decimal(row["management_delta_r"], name="management_delta_r") for row in eligible]
    baseline = [_decimal(row["unchanged_realized_r"], name="unchanged_realized_r") for row in eligible]
    managed = [_decimal(row["managed_realized_r"], name="managed_realized_r") for row in eligible]
    sufficient = effective_n >= minimum_effective_n
    result: dict[str, Any] = {
        "evaluation_version": MANAGEMENT_EVALUATION_VERSION,
        "unchanged_benchmark_version": UNCHANGED_BENCHMARK_VERSION,
        "raw_episode_count": len(raw_rows),
        "unique_episode_count": len(by_episode),
        "evaluated_episode_count": len(evaluated),
        "eligible_complete_episode_count": len(eligible),
        "rejected_episode_count": len(rejected),
        "effective_n": effective_n,
        "minimum_effective_n": minimum_effective_n,
        "inference_state": "sufficient" if sufficient else "insufficient",
        "mean_unchanged_r": _mean(baseline),
        "mean_managed_r": _mean(managed),
        "mean_management_delta_r": _mean(deltas),
        "management_better_count": sum(value > 0 for value in deltas),
        "management_worse_count": sum(value < 0 for value in deltas),
        "management_equal_count": sum(value == 0 for value in deltas),
        "regime_segmentation": _segment(eligible, "regime"),
        "setup_segmentation": _segment(eligible, "setup_family"),
        "rejected": rejected,
        "entry_and_management_effects_separate": True,
        "individual_trade_can_promote_management": False,
        "promotion_allowed": False,
        "paper_only": True,
        "formal_forward_evidence": False,
    }
    result["evaluation_digest"] = digest(result)
    return result


def day49_manifest() -> dict[str, Any]:
    value: dict[str, Any] = {
        "manifest_version": MANAGEMENT_REPLAY_MANIFEST_VERSION,
        "replay_version": MANAGEMENT_REPLAY_VERSION,
        "managed_state_version": MANAGED_STATE_VERSION,
        "unchanged_benchmark_version": UNCHANGED_BENCHMARK_VERSION,
        "evaluation_version": MANAGEMENT_EVALUATION_VERSION,
        "observation_before_same_timestamp_management": True,
        "unchanged_benchmark_frozen_before_evaluation": True,
        "entry_and_management_effects_separate": True,
        "duplicate_actions_idempotent": True,
        "conflicting_actions_fail_closed": True,
        "delayed_or_mismatched_evidence_fails_closed": True,
        "restart_serialization_supported": True,
        "raw_and_effective_n_reported": True,
        "regime_and_setup_segmentation_reported": True,
        "default_minimum_effective_n": DEFAULT_MIN_EFFECTIVE_N,
        "individual_trade_can_promote_management": False,
        "promotion_allowed": False,
        "paper_only": True,
        "execution_allowed": False,
        "formal_forward_evidence_created": False,
        "super_signals_modified": False,
    }
    value["manifest_digest"] = digest(value)
    return value
