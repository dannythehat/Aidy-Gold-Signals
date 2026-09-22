from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.gold_cycle_environment import build_cycle_environment
from aidy.gold_evidence_dependency import (
    build_evidence_dependency_engine,
    extract_dependency_signals,
)
from aidy.gold_environment_contract import assert_no_hindsight_fields
from aidy.gold_expert_gate_contract import build_expert_gate_packet
from aidy.gold_expert_trust import build_trust_envelope, build_trust_scopes
from aidy.gold_family_meta_direction import (
    FAMILY_META_DIRECTION_VERSION,
    build_family_meta_direction_view,
    verify_family_meta_direction_view,
)

AS_OF = datetime(2026, 9, 22, 14, 0, tzinfo=UTC)


def _environment(at: datetime = AS_OF) -> dict:
    return build_cycle_environment(
        as_of_utc=at,
        target_window_start_utc=at + timedelta(minutes=15),
        session_code="london_new_york_overlap",
        observed_state="bullish",
        gold_state={
            "market_structure": {
                "timeframes": {
                    "M5": {"net_close_direction": "up", "state": "known"},
                    "M15": {"net_close_direction": "up", "state": "known"},
                    "H1": {"net_close_direction": "up", "state": "known"},
                    "H4": {"net_close_direction": "up", "state": "known"},
                    "D1": {"net_close_direction": "up", "state": "known"},
                }
            },
            "move_observation": {
                "five_minute_distribution_state": "normal",
                "five_minute_range_state": "normal",
                "windows": {
                    "5m": {"direction": "up", "return_bps": "2"},
                    "15m": {"direction": "up", "return_bps": "4"},
                    "60m": {"direction": "up", "return_bps": "6"},
                },
            },
            "volatility": {
                "state": "normal",
                "jump_continuous": {"state": "continuous_dominant"},
            },
            "scheduled_event_risk": {
                "state": "known",
                "timing_state": "outside_near_event_window",
            },
        },
        semantic_context={
            "data_quality": {
                "quote_state": "known",
                "quote_freshness": "fresh",
                "spread_state": "unknown",
            },
            "cross_market": {"series": {}},
        },
        regime={"compound_regime_key": "trend|normal"},
    )


def _profile() -> dict:
    return {
        "selected_scope_type": "mini_exact",
        "selected_scope_key": "fixture_scope",
        "selected_scope_payload": {},
        "sample_n": 20,
        "correct_n": 15,
        "incorrect_n": 5,
        "net_score": 10,
        "raw_accuracy": "0.750000",
        "shrunk_accuracy": "0.625000",
        "raw_score_mean": "0.500000",
        "shrunk_score_mean": "0.250000",
        "sample_confidence": "0.500000",
        "recent_sample_n": 20,
        "recent_accuracy": "0.750000",
        "recent_net_score": 10,
        "recent_state": "stable",
        "uncertainty_state": "moderate",
        "fallback_path": [],
    }


def _expert(gate_id: str, family: str, vote: str) -> dict:
    env = _environment()
    packet = build_expert_gate_packet(
        gate_id=gate_id,
        gate_version=f"{gate_id}_v1",
        gate_mode="directional",
        dependency_family=family,
        target_horizon_minutes=15,
        as_of_utc=AS_OF,
        global_environment=env,
        mini_environment={"session": "london_new_york_overlap"},
        evidence_inputs=[
            {
                "evidence_id": f"{gate_id}_evidence",
                "source": "blocker1_test",
                "path": f"fixture.{gate_id}",
                "observed_at_utc": AS_OF - timedelta(seconds=1),
                "state": "known",
                "value": vote,
            }
        ],
        subcalculators=[
            {
                "calculator_id": f"{gate_id}_calc",
                "version": f"{gate_id}_calc_v1",
                "role": "directional",
                "dependency_family": family,
                "state": "known",
                "vote": vote,
                "strength": "0.80",
                "evidence_refs": [f"{gate_id}_evidence"],
                "observation": {
                    "correlation_group": f"{gate_id}_group",
                    "fixture": True,
                },
                "explanation": "Blocker-1 reachability fixture.",
            }
        ],
        conclusion=vote,
        internal_conviction="0.80",
        explanation_parts=[
            {
                "text": f"{gate_id} says {vote}.",
                "source_refs": [f"calc:{gate_id}_calc"],
            }
        ],
    )
    scopes = build_trust_scopes(packet=packet)
    trust = build_trust_envelope(
        packet=packet,
        profiles_by_subject={
            f"gate:{gate_id}": _profile(),
            f"subcalculator:{gate_id}_calc": _profile(),
        },
    )
    return {
        "expert_packet": packet,
        "trust_scopes": scopes,
        "trust_envelope": trust,
    }


def _histories(experts: list[dict], *, correct_n: int = 15) -> tuple[list[dict], list[dict]]:
    start = AS_OF - timedelta(days=5)
    outcomes = []
    for i in range(90):
        outcomes.append(
            {
                "resolved_at_utc": (start - timedelta(days=2) + timedelta(minutes=i)).isoformat(),
                "realised_direction": ("bullish", "bearish", "neutral")[i % 3],
            }
        )

    rows = []
    for i in range(20):
        decision = start + timedelta(hours=2 * i)
        realised = "bullish" if i < correct_n else "bearish"
        resolved = decision + timedelta(minutes=15)
        outcomes.append(
            {
                "resolved_at_utc": resolved.isoformat(),
                "realised_direction": realised,
            }
        )
        for expert in experts:
            packet = expert["expert_packet"]
            calc = packet["subcalculators"][0]
            predicted = str(calc["vote"])
            correct = int(predicted == realised)
            rows.append(
                {
                    "result_id": f"{packet['gate_id']}-{i}",
                    "gate_id": packet["gate_id"],
                    "subject_id": calc["calculator_id"],
                    "subject_version": calc["version"],
                    "decision_time_utc": decision.isoformat(),
                    "predicted_class": predicted,
                    "resolved_at_utc": resolved.isoformat(),
                    "realised_direction": realised,
                    "correct": correct,
                }
            )
    return rows, outcomes


def _dependency(experts: list[dict]) -> dict:
    return build_evidence_dependency_engine(
        signals=extract_dependency_signals(experts),
        historical_rows=(),
        as_of_utc=AS_OF,
    )


def test_blocker1_two_independent_families_reach_bullish() -> None:
    experts = [
        _expert("structure_gate", "structure", "bullish"),
        _expert("liquidity_gate", "liquidity", "bullish"),
    ]
    history, outcomes = _histories(experts)
    view = build_family_meta_direction_view(
        global_environment=_environment(),
        expert_results=experts,
        dependency_engine=_dependency(experts),
        historical_subcalculator_rows=history,
        resolved_outcome_rows=outcomes,
    )

    assert view["aggregator_version"] == FAMILY_META_DIRECTION_VERSION
    assert view["direction"] == "bullish"
    assert view["decision_reason"] == "bullish_family_evidence"
    assert view["qualifying_family_count"] == 2
    assert Decimal(view["meta_balance"]) == Decimal("1.000000")
    assert {row["family_id"] for row in view["families"] if row["qualifies"]} == {
        "price_action",
        "liquidity_mechanism",
    }
    assert verify_family_meta_direction_view(view)


def test_blocker1_independent_family_disagreement_abstains() -> None:
    bullish = _expert("structure_gate", "structure", "bullish")
    bearish = _expert("liquidity_gate", "liquidity", "bearish")
    experts = [bullish, bearish]

    # Give each subject a genuinely useful own directional history.
    start = AS_OF - timedelta(days=5)
    outcomes = [
        {
            "resolved_at_utc": (start - timedelta(days=2) + timedelta(minutes=i)).isoformat(),
            "realised_direction": ("bullish", "bearish", "neutral")[i % 3],
        }
        for i in range(90)
    ]
    history = []
    for i in range(20):
        decision = start + timedelta(hours=2 * i)
        realised = "bullish" if i % 2 == 0 else "bearish"
        resolved = decision + timedelta(minutes=15)
        outcomes.append({"resolved_at_utc": resolved.isoformat(), "realised_direction": realised})
        for expert in experts:
            packet = expert["expert_packet"]
            calc = packet["subcalculators"][0]
            predicted = str(calc["vote"])
            # Create 15/20 correct for each subject without changing current vote.
            should_be_correct = i < 15
            row_realised = predicted if should_be_correct else (
                "bearish" if predicted == "bullish" else "bullish"
            )
            history.append(
                {
                    "result_id": f"{packet['gate_id']}-{i}",
                    "gate_id": packet["gate_id"],
                    "subject_id": calc["calculator_id"],
                    "subject_version": calc["version"],
                    "decision_time_utc": decision.isoformat(),
                    "predicted_class": predicted,
                    "resolved_at_utc": resolved.isoformat(),
                    "realised_direction": row_realised,
                    "correct": int(predicted == row_realised),
                }
            )

    view = build_family_meta_direction_view(
        global_environment=_environment(),
        expert_results=experts,
        dependency_engine=_dependency(experts),
        historical_subcalculator_rows=history,
        resolved_outcome_rows=outcomes,
    )
    assert view["direction"] == "abstain"
    assert view["decision_reason"] == "genuine_independent_disagreement"


def test_global_core_trust_scope_repeats_across_adjacent_clock_buckets() -> None:
    left = _expert("scope_gate", "structure", "bullish")
    packet_left = left["expert_packet"]

    later = AS_OF + timedelta(minutes=15)
    env_right = _environment(later)
    packet_right = build_expert_gate_packet(
        gate_id="scope_gate",
        gate_version="scope_gate_v1",
        gate_mode="directional",
        dependency_family="structure",
        target_horizon_minutes=15,
        as_of_utc=later,
        global_environment=env_right,
        mini_environment={"session": "london_new_york_overlap"},
        evidence_inputs=[
            {
                "evidence_id": "scope_gate_evidence",
                "source": "blocker1_test",
                "path": "fixture.scope_gate",
                "observed_at_utc": later - timedelta(seconds=1),
                "state": "known",
                "value": "bullish",
            }
        ],
        subcalculators=[
            {
                "calculator_id": "scope_gate_calc",
                "version": "scope_gate_calc_v1",
                "role": "directional",
                "dependency_family": "structure",
                "state": "known",
                "vote": "bullish",
                "strength": "0.80",
                "evidence_refs": ["scope_gate_evidence"],
                "observation": {"correlation_group": "scope_gate_group"},
                "explanation": "scope fixture",
            }
        ],
        conclusion="bullish",
        internal_conviction="0.80",
        explanation_parts=[
            {"text": "scope gate bullish", "source_refs": ["calc:scope_gate_calc"]}
        ],
    )

    assert packet_left["global_environment_ref"]["environment_key"] != packet_right["global_environment_ref"]["environment_key"]
    left_core = next(s for s in build_trust_scopes(packet=packet_left) if s["scope_type"] == "global_core")
    right_core = next(s for s in build_trust_scopes(packet=packet_right) if s["scope_type"] == "global_core")
    assert left_core["scope_key"] == right_core["scope_key"]


@pytest.mark.parametrize(
    "field",
    [
        "realised_direction",
        "realized_direction",
        "realised_return_bps",
        "realized_return_bps",
        "score",
        "correct",
        "impact_class",
    ],
)
def test_real_outcome_fields_fail_closed_in_predecision_contract(field: str) -> None:
    with pytest.raises(ValueError, match="hindsight field"):
        assert_no_hindsight_fields({field: "forbidden"}, path="fixture")
