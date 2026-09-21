from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aidy.gold_cycle_environment import build_cycle_environment
from aidy.gold_expert_gate_contract import build_expert_gate_packet
from aidy.gold_expert_trust import (
    EXPERT_TRUST_ENGINE_VERSION,
    aggregate_context_rows,
    build_trust_envelope,
    build_trust_scopes,
    score_directional_outcome,
    score_expert_packet,
    select_conditional_trust,
)

AS_OF = datetime(2026, 9, 21, 8, 10, tzinfo=UTC)
TARGET = datetime(2026, 9, 21, 8, 15, tzinfo=UTC)


def _environment(*, session: str = "london") -> dict:
    return build_cycle_environment(
        as_of_utc=AS_OF,
        target_window_start_utc=TARGET,
        session_code=session,
        observed_state="bearish",
        gold_state={
            "market_structure": {
                "timeframes": {
                    "M5": {"net_close_direction": "down", "state": "known"},
                    "M15": {"net_close_direction": "down", "state": "known"},
                    "H1": {"net_close_direction": "down", "state": "known"},
                    "H4": {"net_close_direction": "up", "state": "known"},
                    "D1": {"net_close_direction": "up", "state": "known"},
                }
            },
            "move_observation": {
                "five_minute_distribution_state": "normal",
                "five_minute_range_state": "normal",
                "windows": {
                    "5m": {"direction": "down"},
                    "15m": {"direction": "down"},
                    "60m": {"direction": "down"},
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
            }
        },
        regime={"compound_regime_key": "trend|normal"},
    )


def _packet(*, mini: dict | None = None) -> dict:
    return build_expert_gate_packet(
        gate_id="h1_structure_expert",
        gate_version="h1_structure_expert_v1",
        gate_mode="directional",
        dependency_family="structure",
        target_horizon_minutes=15,
        as_of_utc=AS_OF,
        global_environment=_environment(),
        mini_environment=mini
        or {
            "timeframe": "H1",
            "session": "london",
            "volatility": "normal",
            "h4_alignment": "bullish",
        },
        evidence_inputs=[
            {
                "evidence_id": "h1_slope",
                "source": "gold_state_engine",
                "path": "H1.slope",
                "observed_at_utc": AS_OF - timedelta(seconds=5),
                "state": "known",
                "value": "-1.4",
            },
            {
                "evidence_id": "h1_persistence",
                "source": "gold_state_engine",
                "path": "H1.persistence",
                "observed_at_utc": AS_OF - timedelta(seconds=5),
                "state": "known",
                "value": "0.71",
            },
        ],
        subcalculators=[
            {
                "calculator_id": "net_slope",
                "version": "h1_net_slope_v1",
                "role": "directional",
                "dependency_family": "structure",
                "state": "known",
                "vote": "bearish",
                "strength": "0.72",
                "evidence_refs": ["h1_slope"],
                "observation": {"slope": "-1.4"},
                "explanation": "H1 slope is negative.",
            },
            {
                "calculator_id": "close_persistence",
                "version": "h1_close_persistence_v1",
                "role": "directional",
                "dependency_family": "structure",
                "state": "known",
                "vote": "bearish",
                "strength": "0.66",
                "evidence_refs": ["h1_persistence"],
                "observation": {"down_ratio": "0.71"},
                "explanation": "H1 close persistence is bearish.",
            },
        ],
        conclusion="bearish",
        internal_conviction="0.78",
        explanation_parts=[
            {
                "text": "H1 slope and close persistence agree bearish.",
                "source_refs": ["calc:net_slope", "calc:close_persistence"],
            }
        ],
        contradictions=[],
    )


def _scopes(packet: dict) -> list[dict]:
    return build_trust_scopes(
        packet=packet,
        reduced_contexts=[
            {
                "name": "session_volatility",
                "mini_dimensions": ["session", "volatility"],
                "minimum_sample_n": 8,
            },
            {
                "name": "session_only",
                "mini_dimensions": ["session"],
                "minimum_sample_n": 5,
            },
        ],
    )


def _row(scope: dict, *, n: int, correct: int, net: int) -> dict:
    return {
        "scope_key": scope["scope_key"],
        "scope_type": scope["scope_type"],
        "sample_n": n,
        "correct_n": correct,
        "incorrect_n": n - correct,
        "net_score": net,
        "score_mean": f"{net / n:.6f}" if n else None,
        "accuracy": f"{correct / n:.6f}" if n else None,
        "wilson_95_low": None,
        "wilson_95_high": None,
        "recent_window": 20,
        "recent_sample_n": min(n, 20),
        "recent_correct_n": min(correct, 20),
        "recent_net_score": net if n <= 20 else 0,
        "recent_accuracy": f"{correct / n:.6f}" if 0 < n <= 20 else None,
    }


def _synthetic_result(
    *,
    scope_keys: list[str],
    resolved: datetime,
    correct: int,
    score: int,
    subject_type: str = "gate",
    subject_id: str = "h1_structure_expert",
    subject_version: str = "h1_structure_expert_v1",
) -> dict:
    return {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "subject_version": subject_version,
        "resolved_at_utc": resolved.isoformat(),
        "correct": correct,
        "score": score,
        "scope_keys": scope_keys,
    }


def test_build3_small_8_of_10_does_not_automatically_beat_137_of_200() -> None:
    scope = {
        "scope_type": "gate_global",
        "scope_key": "gate_global_test",
        "payload": {},
        "minimum_sample_n": 1,
    }
    small = select_conditional_trust(
        score_rows=[_row(scope, n=10, correct=8, net=6)],
        scopes=[scope],
    )
    large = select_conditional_trust(
        score_rows=[_row(scope, n=200, correct=137, net=74)],
        scopes=[scope],
    )
    assert small["raw_accuracy"] == "0.800000"
    assert large["raw_accuracy"] == "0.685000"
    assert float(small["shrunk_accuracy"]) < float(large["shrunk_accuracy"])


def test_build3_exact_context_only_wins_after_minimum_sample() -> None:
    packet = _packet()
    scopes = _scopes(packet)
    exact, reduced, _, global_core, gate_global = scopes
    rows = [
        _row(exact, n=11, correct=10, net=18),
        _row(reduced, n=40, correct=26, net=12),
        _row(global_core, n=70, correct=44, net=18),
        _row(gate_global, n=100, correct=60, net=20),
    ]
    profile = select_conditional_trust(score_rows=rows, scopes=scopes)
    assert profile["selected_scope_type"] == reduced["scope_type"]

    rows[0] = _row(exact, n=12, correct=10, net=16)
    profile = select_conditional_trust(score_rows=rows, scopes=scopes)
    assert profile["selected_scope_type"] == "mini_exact"


def test_build3_fallback_order_is_exact_then_reduced_then_core_then_global() -> None:
    packet = _packet()
    scopes = _scopes(packet)
    exact, reduced_a, reduced_b, global_core, gate_global = scopes

    profile = select_conditional_trust(
        score_rows=[
            _row(exact, n=2, correct=2, net=4),
            _row(reduced_a, n=3, correct=3, net=6),
            _row(reduced_b, n=5, correct=3, net=1),
            _row(global_core, n=20, correct=12, net=5),
            _row(gate_global, n=100, correct=58, net=15),
        ],
        scopes=scopes,
    )
    assert profile["selected_scope_type"] == reduced_b["scope_type"]

    profile = select_conditional_trust(
        score_rows=[
            _row(global_core, n=5, correct=4, net=4),
            _row(gate_global, n=100, correct=58, net=15),
        ],
        scopes=scopes,
    )
    assert profile["selected_scope_type"] == "gate_global"


def test_build3_no_history_falls_back_to_neutral_prior() -> None:
    profile = select_conditional_trust(
        score_rows=[],
        scopes=_scopes(_packet()),
    )
    assert profile["selected_scope_type"] == "neutral_prior"
    assert profile["shrunk_accuracy"] == "0.500000"
    assert profile["shrunk_score_mean"] == "0.000000"


def test_build3_future_or_current_outcomes_are_excluded_from_lookup() -> None:
    packet = _packet()
    scopes = _scopes(packet)
    keys = [scope["scope_key"] for scope in scopes]
    results = [
        _synthetic_result(
            scope_keys=keys,
            resolved=AS_OF - timedelta(minutes=20),
            correct=1,
            score=1,
        ),
        _synthetic_result(
            scope_keys=keys,
            resolved=AS_OF,
            correct=1,
            score=2,
        ),
        _synthetic_result(
            scope_keys=keys,
            resolved=AS_OF + timedelta(minutes=15),
            correct=1,
            score=2,
        ),
    ]
    rows = aggregate_context_rows(
        results=results,
        scopes=scopes,
        subject_type="gate",
        subject_id="h1_structure_expert",
        subject_version="h1_structure_expert_v1",
        as_of_utc=AS_OF,
    )
    assert all(row["sample_n"] == 1 for row in rows)
    assert all(row["excluded_current_or_future_n"] == 2 for row in rows)


def test_build3_scoring_rule_is_exactly_plus2_plus1_zero_minus1_minus2() -> None:
    assert score_directional_outcome(
        vote="bullish",
        realised_direction="bullish",
        realised_return_bps="6.0",
        scoreable=True,
    )["score"] == 2
    assert score_directional_outcome(
        vote="bearish",
        realised_direction="bullish",
        realised_return_bps="6.0",
        scoreable=True,
    )["score"] == -2
    assert score_directional_outcome(
        vote="bullish",
        realised_direction="bullish",
        realised_return_bps="3.0",
        scoreable=True,
    )["score"] == 1
    assert score_directional_outcome(
        vote="bearish",
        realised_direction="bullish",
        realised_return_bps="3.0",
        scoreable=True,
    )["score"] == -1
    assert score_directional_outcome(
        vote="unknown",
        realised_direction="bullish",
        realised_return_bps="12.0",
        scoreable=False,
    )["score"] == 0


def test_build3_packet_resolution_is_idempotent_and_subject_specific() -> None:
    packet = _packet()
    scopes = _scopes(packet)
    args = {
        "packet": packet,
        "scopes": scopes,
        "resolved_at_utc": AS_OF + timedelta(minutes=20),
        "realised_direction": "bearish",
        "realised_return_bps": "-7.1",
    }
    first = score_expert_packet(**args)
    second = score_expert_packet(**args)
    assert first == second
    assert len(first) == 3
    assert {row["subject_type"] for row in first} == {"gate", "subcalculator"}
    assert all(row["score"] == 2 for row in first)
    assert len({row["result_id"] for row in first}) == 3


def test_build3_outcome_cannot_resolve_before_or_at_gate_freeze() -> None:
    with pytest.raises(ValueError, match="resolve after"):
        score_expert_packet(
            packet=_packet(),
            scopes=_scopes(_packet()),
            resolved_at_utc=AS_OF,
            realised_direction="bearish",
            realised_return_bps="-4",
        )


def test_build3_recent_statistics_are_separate_from_long_term() -> None:
    packet = _packet()
    scopes = _scopes(packet)
    keys = [scope["scope_key"] for scope in scopes]
    start = AS_OF - timedelta(days=4)
    results = []
    for i in range(40):
        recent_half = i >= 20
        correct = 0 if recent_half else 1
        results.append(
            _synthetic_result(
                scope_keys=keys,
                resolved=start + timedelta(minutes=30 * i),
                correct=correct,
                score=-1 if recent_half else 1,
            )
        )
    rows = aggregate_context_rows(
        results=results,
        scopes=scopes,
        subject_type="gate",
        subject_id="h1_structure_expert",
        subject_version="h1_structure_expert_v1",
        as_of_utc=AS_OF,
    )
    gate_global = rows[-1]
    assert gate_global["sample_n"] == 40
    assert gate_global["accuracy"] == "0.500000"
    assert gate_global["recent_sample_n"] == 20
    assert gate_global["recent_accuracy"] == "0.000000"

    profile = select_conditional_trust(score_rows=rows, scopes=scopes)
    assert profile["recent_state"] == "recently_weaker"


def test_build3_confidence_interval_and_uncertainty_are_exposed() -> None:
    packet = _packet()
    scope = _scopes(packet)[-1]
    results = [
        _synthetic_result(
            scope_keys=[scope["scope_key"]],
            resolved=AS_OF - timedelta(minutes=200 - i),
            correct=1 if i < 70 else 0,
            score=1 if i < 70 else -1,
        )
        for i in range(100)
    ]
    rows = aggregate_context_rows(
        results=results,
        scopes=[scope],
        subject_type="gate",
        subject_id="h1_structure_expert",
        subject_version="h1_structure_expert_v1",
        as_of_utc=AS_OF,
    )
    profile = select_conditional_trust(score_rows=rows, scopes=[scope])
    assert float(profile["wilson_95_low"]) < 0.70
    assert float(profile["wilson_95_high"]) > 0.70
    assert profile["uncertainty_state"] in {"moderate", "lower"}


def test_build3_different_mini_environments_create_different_exact_scorebooks() -> None:
    london = _packet()
    event = _packet(
        mini={
            "timeframe": "H1",
            "session": "london",
            "volatility": "expanding",
            "h4_alignment": "bullish",
        }
    )
    london_exact = _scopes(london)[0]
    event_exact = _scopes(event)[0]
    assert london_exact["scope_key"] != event_exact["scope_key"]
    assert _scopes(london)[-1]["scope_key"] == _scopes(event)[-1]["scope_key"]


def test_build3_reduced_context_is_explicit_not_guessed_by_engine() -> None:
    packet = _packet()
    with pytest.raises(ValueError, match="missing dimensions"):
        build_trust_scopes(
            packet=packet,
            reduced_contexts=[
                {
                    "name": "made_up",
                    "mini_dimensions": ["does_not_exist"],
                    "minimum_sample_n": 8,
                }
            ],
        )


def test_build3_trust_envelope_keeps_conviction_and_history_separate() -> None:
    packet = _packet()
    profile = {
        "engine_version": EXPERT_TRUST_ENGINE_VERSION,
        "selected_scope_type": "gate_global",
        "shrunk_accuracy": "0.640000",
    }
    envelope = build_trust_envelope(
        packet=packet,
        profiles_by_subject={
            "gate:h1_structure_expert": profile,
            "subcalculator:net_slope": profile,
        },
    )
    assert envelope["internal_conviction"] == "0.780000"
    assert envelope["historical_reliability_separate_from_internal_conviction"] is True
    assert envelope["future_values_used"] is False
    assert envelope["live_money_execution_allowed"] is False


def test_build3_score_math_is_deterministic() -> None:
    packet = _packet()
    scopes = _scopes(packet)
    rows = [
        _row(scopes[-1], n=73, correct=47, net=19),
    ]
    first = select_conditional_trust(score_rows=rows, scopes=[scopes[-1]])
    second = select_conditional_trust(score_rows=rows, scopes=[scopes[-1]])
    assert first == second
