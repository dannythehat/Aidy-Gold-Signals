from __future__ import annotations

import copy
import runpy
from datetime import UTC, datetime, timedelta

import pytest

from aidy.management_contract_v2 import build_management_action_record
from aidy.management_replay import (
    ManagementReplayError,
    apply_managed_replay_observation,
    day49_manifest,
    evaluate_management_cohort,
    replay_management_episode,
    restore_managed_replay_state,
    serialize_managed_replay_state,
    start_managed_replay,
    verify_managed_replay_state,
)
from aidy.paper_simulator import PAPER_OBSERVATION_VERSION

DAY48 = runpy.run_path("tests/test_day48_management_contract_v2.py")
WATCH = datetime(2026, 9, 1, 14, 10, tzinfo=UTC)


def _inputs():
    return DAY48["_inputs"]()


def _action(*, close: bool = False) -> tuple[dict, dict]:
    record, state, context, receipt = _inputs()
    if close:
        receipt = DAY48["_watcher_receipt"](
            record,
            state,
            context,
            assessment="close_review",
            thesis_assessment="invalidated",
            watcher_reason="thesis_broken",
        )
        decision = DAY48["_close"](record)
    else:
        decision = DAY48["_manage"](record)
    action = build_management_action_record(
        decision=decision,
        watcher_receipt=receipt,
        ex_ante_record=record,
        paper_state=state,
        current_context=context,
    )
    return record, action


def _observation(minutes_after_watch: int, mid: float) -> dict:
    stamp = WATCH + timedelta(minutes=minutes_after_watch)
    context = DAY48["_context"](mid)
    context["as_of_utc"] = stamp.isoformat()
    from aidy.context_packet import compute_context_hash

    context["context_hash"] = compute_context_hash(context)
    return {
        "observation_version": PAPER_OBSERVATION_VERSION,
        "as_of_utc": stamp.isoformat(),
        "symbol": "XAUUSD",
        "mid": mid,
        "context": context,
    }


def test_do_nothing_baseline_exposes_harmful_management() -> None:
    record, action = _action()
    result = replay_management_episode(
        ex_ante_record=record,
        observations=[_observation(0, 2505.0), _observation(10, 2490.0), _observation(20, 2531.0)],
        management_actions=[action],
    )
    assert result["entry_quality"]["unchanged_realized_r"] == "1.000000"
    assert result["management_quality"]["managed_realized_r"] == "-0.250000"
    assert result["management_quality"]["management_delta_r"] == "-1.250000"
    assert result["management_promoted"] is False


def test_close_can_help_without_rewriting_entry_quality() -> None:
    record, action = _action(close=True)
    result = replay_management_episode(
        ex_ante_record=record,
        observations=[_observation(0, 2505.0), _observation(10, 2479.0)],
        management_actions=[action],
    )
    assert result["entry_quality"]["unchanged_realized_r"] == "-1.000000"
    assert result["management_quality"]["managed_realized_r"] == "0.250000"
    assert result["management_quality"]["management_delta_r"] == "1.250000"


def test_restart_round_trip_is_deterministic() -> None:
    record, _ = _action()
    state = start_managed_replay(record)
    state = apply_managed_replay_observation(state, _observation(0, 2505.0))
    restored = restore_managed_replay_state(serialize_managed_replay_state(state))
    assert restored == state
    assert verify_managed_replay_state(restored)


def test_identical_duplicate_action_is_idempotent() -> None:
    record, action = _action()
    observations = [_observation(0, 2505.0), _observation(10, 2490.0), _observation(20, 2531.0)]
    one = replay_management_episode(
        ex_ante_record=record, observations=observations, management_actions=[action]
    )
    two = replay_management_episode(
        ex_ante_record=record,
        observations=observations,
        management_actions=[action, copy.deepcopy(action)],
    )
    assert one == two


def test_conflicting_actions_same_timestamp_fail_closed() -> None:
    record, manage = _action()
    _, close = _action(close=True)
    with pytest.raises(ManagementReplayError, match="share a timestamp"):
        replay_management_episode(
            ex_ante_record=record,
            observations=[_observation(0, 2505.0), _observation(10, 2479.0)],
            management_actions=[manage, close],
        )


def test_delayed_action_without_exact_observation_fails_closed() -> None:
    record, action = _action()
    with pytest.raises(ManagementReplayError, match="no exact replay observation"):
        replay_management_episode(
            ex_ante_record=record,
            observations=[_observation(10, 2479.0)],
            management_actions=[action],
        )


def test_context_mismatch_fails_closed() -> None:
    record, action = _action()
    with pytest.raises(ManagementReplayError, match="context does not match"):
        replay_management_episode(
            ex_ante_record=record,
            observations=[_observation(0, 2506.0), _observation(10, 2479.0)],
            management_actions=[action],
        )


def test_cohort_reports_effective_n_and_segmentations() -> None:
    record, action = _action(close=True)
    observations = [_observation(0, 2505.0), _observation(10, 2479.0)]
    episodes = [
        {
            "episode_id": "ep-1",
            "independence_cluster_id": "cluster-a",
            "regime": "trend",
            "setup_family": "trend_pullback",
            "ex_ante_record": record,
            "observations": observations,
            "management_actions": [action],
        },
        {
            "episode_id": "ep-2",
            "independence_cluster_id": "cluster-a",
            "regime": "range",
            "setup_family": "trend_pullback",
            "ex_ante_record": record,
            "observations": observations,
            "management_actions": [action],
        },
        {
            "episode_id": "ep-3",
            "independence_cluster_id": "cluster-b",
            "regime": "trend",
            "setup_family": "trend_pullback",
            "ex_ante_record": record,
            "observations": observations,
            "management_actions": [action],
        },
    ]
    result = evaluate_management_cohort(episodes, minimum_effective_n=3)
    assert result["raw_episode_count"] == 3
    assert result["effective_n"] == 2
    assert result["inference_state"] == "insufficient"
    assert result["regime_segmentation"]["trend"]["effective_n"] == 2
    assert result["setup_segmentation"]["trend_pullback"]["episode_count"] == 3
    assert result["promotion_allowed"] is False


def test_duplicate_episode_dedups_and_conflict_rejects() -> None:
    record, action = _action(close=True)
    episode = {
        "episode_id": "ep-1",
        "independence_cluster_id": "cluster-a",
        "regime": "trend",
        "setup_family": "trend_pullback",
        "ex_ante_record": record,
        "observations": [_observation(0, 2505.0), _observation(10, 2479.0)],
        "management_actions": [action],
    }
    result = evaluate_management_cohort([episode, copy.deepcopy(episode)], minimum_effective_n=1)
    assert result["raw_episode_count"] == 2
    assert result["unique_episode_count"] == 1
    conflict = copy.deepcopy(episode)
    conflict["regime"] = "range"
    with pytest.raises(ManagementReplayError, match="conflicting payloads"):
        evaluate_management_cohort([episode, conflict])


def test_manifest_freezes_benchmark_and_forbids_auto_promotion() -> None:
    manifest = day49_manifest()
    assert manifest["unchanged_benchmark_frozen_before_evaluation"] is True
    assert manifest["entry_and_management_effects_separate"] is True
    assert manifest["raw_and_effective_n_reported"] is True
    assert manifest["promotion_allowed"] is False
    assert manifest["execution_allowed"] is False
