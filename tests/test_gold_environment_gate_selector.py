from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.gold_cycle_environment import build_cycle_environment
from aidy.gold_environment_gate_selector import (
    build_environment_aware_gate_selector,
    build_gate_selector_input,
    verify_environment_aware_gate_selector,
)
from aidy.gold_evidence_dependency import build_evidence_dependency_engine
from aidy.gold_expert_gate_contract import build_expert_gate_packet
from aidy.gold_expert_trust import (
    build_trust_envelope,
    build_trust_scopes,
    select_conditional_trust,
)

AS_OF = datetime(2026, 9, 21, 14, 30, tzinfo=UTC)
TARGET = AS_OF + timedelta(minutes=15)


def _environment() -> dict:
    return build_cycle_environment(
        as_of_utc=AS_OF,
        target_window_start_utc=TARGET,
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
                "five_minute_distribution_state": "within_recent_distribution",
                "five_minute_range_state": "normal_range",
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


def _packet(
    gate_id: str,
    *,
    family: str = "structure",
    conclusion: str = "bullish",
    mode: str = "directional",
    state: str = "known",
) -> dict:
    context_only = mode == "context_only"
    return build_expert_gate_packet(
        gate_id=gate_id,
        gate_version=f"{gate_id}_v1",
        gate_mode=mode,
        dependency_family=family,
        target_horizon_minutes=15,
        as_of_utc=AS_OF,
        global_environment=_environment(),
        mini_environment={
            "session": "london_new_york_overlap",
            "volatility_state": "normal",
            "regime": "trend",
        },
        evidence_inputs=[
            {
                "evidence_id": f"{gate_id}_evidence",
                "source": "build21_fixture",
                "path": f"fixtures.{gate_id}",
                "observed_at_utc": AS_OF - timedelta(seconds=1),
                "state": "known" if state == "known" else "unknown",
                "value": "fixture" if state == "known" else None,
            }
        ],
        subcalculators=[
            {
                "calculator_id": f"{gate_id}_calc",
                "version": f"{gate_id}_calc_v1",
                "role": "context_only" if context_only else "directional",
                "dependency_family": family,
                "state": state,
                "vote": (
                    "context_only"
                    if context_only and state == "known"
                    else "unknown"
                    if state != "known"
                    else conclusion
                ),
                **(
                    {"strength": "0.70"}
                    if not context_only and state == "known"
                    else {}
                ),
                "evidence_refs": [f"{gate_id}_evidence"],
                "observation": {"fixture": True},
                "explanation": "Build 21 selector fixture.",
            }
        ],
        conclusion=(
            "context_only"
            if context_only and state == "known"
            else "unknown"
            if state != "known"
            else conclusion
        ),
        internal_conviction=(
            "0.70"
            if mode == "directional" and state == "known" and conclusion in {"bullish", "bearish"}
            else None
        ),
        explanation_parts=[
            {
                "text": "Build 21 selector fixture.",
                "source_refs": [f"calc:{gate_id}_calc"],
            }
        ],
        contradictions=[],
    )


def _row(scope: dict, *, n: int, correct: int, recent_correct: int | None = None) -> dict:
    recent_n = min(n, 20)
    if recent_correct is None:
        recent_correct = round((correct / n) * recent_n) if n else 0
    return {
        "scope_key": scope["scope_key"],
        "scope_type": scope["scope_type"],
        "sample_n": n,
        "correct_n": correct,
        "incorrect_n": n - correct,
        "net_score": (correct * 2) - n,
        "score_mean": f"{((correct * 2) - n) / n:.6f}" if n else None,
        "accuracy": f"{correct / n:.6f}" if n else None,
        "wilson_95_low": None,
        "wilson_95_high": None,
        "recent_window": 20,
        "recent_sample_n": recent_n,
        "recent_correct_n": recent_correct,
        "recent_net_score": (recent_correct * 2) - recent_n,
        "recent_accuracy": (
            f"{recent_correct / recent_n:.6f}" if recent_n else None
        ),
    }


def _expert_result(
    gate_id: str,
    *,
    n: int,
    correct: int,
    family: str = "structure",
    conclusion: str = "bullish",
    mode: str = "directional",
    state: str = "known",
    force_gate_global: bool = False,
    recent_correct: int | None = None,
) -> dict:
    packet = _packet(
        gate_id,
        family=family,
        conclusion=conclusion,
        mode=mode,
        state=state,
    )
    scopes = build_trust_scopes(packet=packet)
    rows = []
    if state == "known":
        if force_gate_global:
            rows = [_row(scopes[-1], n=n, correct=correct, recent_correct=recent_correct)]
        else:
            rows = [_row(scopes[0], n=n, correct=correct, recent_correct=recent_correct)]
    profile = select_conditional_trust(score_rows=rows, scopes=scopes)
    envelope = build_trust_envelope(
        packet=packet,
        profiles_by_subject={f"gate:{gate_id}": profile},
    )
    return {
        "expert_packet": packet,
        "trust_envelope": envelope,
    }


def _signals(gates: list[tuple[str, str]]) -> list[dict]:
    return [
        {
            "signal_id": f"{gate_id}:{gate_id}_calc",
            "gate_id": gate_id,
            "calculator_id": f"{gate_id}_calc",
            "dependency_family": family,
            "parent_family": {
                "structure": "price_action",
                "momentum": "price_action",
                "liquidity": "liquidity_mechanism",
                "event": "macro_information",
            }.get(family, "price_action"),
            "correlation_group": f"{gate_id}_group",
            "role": "directional",
            "state": "known",
            "vote": "bullish",
            "raw_weight": "1",
            "evidence_identity": f"{gate_id}_evidence",
        }
        for gate_id, family in gates
    ]


def _dependency(gates: list[tuple[str, str]]) -> dict:
    return build_evidence_dependency_engine(
        signals=_signals(gates),
        historical_rows=[],
        as_of_utc=AS_OF,
    )


def _selector(
    experts: list[dict],
    expected: list[str],
    dependency: dict,
    calibration_rows: list[dict] | None = None,
) -> dict:
    return build_environment_aware_gate_selector(
        global_environment=_environment(),
        expected_gate_ids=expected,
        gate_inputs=[build_gate_selector_input(item) for item in experts],
        dependency_engine=dependency,
        calibration_rows=calibration_rows or [],
    )


def _by_gate(result: dict) -> dict[str, dict]:
    return {item["gate_id"]: item for item in result["all_gates"]}


def test_build21_small_n_star_performer_is_suppressed() -> None:
    expert = _expert_result(
        "small_star",
        n=4,
        correct=4,
        force_gate_global=True,
    )
    result = _selector(
        [expert],
        ["small_star"],
        _dependency([("small_star", "structure")]),
    )
    gate = _by_gate(result)["small_star"]

    assert gate["classification"] == "reduced_trust"
    assert gate["sample_n"] == 4
    assert Decimal(gate["shrunk_accuracy"]) < Decimal("0.60")
    assert "sample_n_below_high_trust_minimum" in gate["reasons"]
    assert Decimal(gate["observation_weight"]) > 0


def test_build21_strong_large_n_contextual_performer_rises() -> None:
    expert = _expert_result("large_strong", n=100, correct=75)
    result = _selector(
        [expert],
        ["large_strong"],
        _dependency([("large_strong", "structure")]),
    )
    gate = _by_gate(result)["large_strong"]

    assert gate["classification"] == "high_trust"
    assert gate["sample_n"] == 100
    assert Decimal(gate["shrunk_accuracy"]) >= Decimal("0.58")
    assert Decimal(gate["trust_score"]) >= Decimal("0.30")
    assert gate["context_label"] == "mini_exact"


def test_build21_missing_gate_gets_exactly_zero_authority() -> None:
    result = _selector(
        [],
        ["missing_gate"],
        _dependency([]),
    )
    gate = _by_gate(result)["missing_gate"]

    assert gate["classification"] == "unavailable"
    assert gate["trust_score"] == "0.000000"
    assert gate["observation_weight"] == "0.000000"
    assert gate["directional_authority_weight"] == "0.000000"


def test_build21_unknown_current_gate_gets_zero_authority() -> None:
    expert = _expert_result(
        "unknown_gate",
        n=0,
        correct=0,
        state="insufficient",
    )
    result = _selector(
        [expert],
        ["unknown_gate"],
        _dependency([]),
    )
    gate = _by_gate(result)["unknown_gate"]

    assert gate["classification"] == "unavailable"
    assert gate["directional_authority_weight"] == "0.000000"


def test_build21_weak_gate_remains_observable_and_scoreable() -> None:
    expert = _expert_result("weak_gate", n=100, correct=45)
    result = _selector(
        [expert],
        ["weak_gate"],
        _dependency([("weak_gate", "structure")]),
    )
    gate = _by_gate(result)["weak_gate"]

    assert gate["classification"] == "reduced_trust"
    assert gate["weak_gate_remains_observable"] is True
    assert Decimal(gate["observation_weight"]) >= Decimal("0.05")
    assert Decimal(gate["directional_authority_weight"]) > 0


def test_build21_recently_weaker_gate_is_reduced_even_if_long_run_is_strong() -> None:
    expert = _expert_result(
        "drifting_gate",
        n=100,
        correct=70,
        recent_correct=8,
    )
    result = _selector(
        [expert],
        ["drifting_gate"],
        _dependency([("drifting_gate", "structure")]),
    )
    gate = _by_gate(result)["drifting_gate"]

    assert gate["recency_adjustment"]["state"] == "recently_weaker"
    assert gate["recency_adjustment"]["multiplier"] == "0.650000"
    assert gate["classification"] == "reduced_trust"


def test_build21_calibration_penalty_is_historical_and_bounded() -> None:
    expert = _expert_result("cal_gate", n=100, correct=75)
    rows = [
        {
            "gate_id": "cal_gate",
            "observed_at_utc": (AS_OF - timedelta(minutes=30)).isoformat(),
            "sample_n": 50,
            "mean_absolute_calibration_error": "0.25",
        }
    ]
    result = _selector(
        [expert],
        ["cal_gate"],
        _dependency([("cal_gate", "structure")]),
        calibration_rows=rows,
    )
    gate = _by_gate(result)["cal_gate"]

    assert gate["calibration_adjustment"]["state"] == "poor"
    assert gate["calibration_adjustment"]["multiplier"] == "0.500000"
    assert gate["classification"] == "reduced_trust"


def test_build21_future_calibration_record_is_excluded() -> None:
    expert = _expert_result("cal_gate", n=100, correct=75)
    rows = [
        {
            "gate_id": "cal_gate",
            "observed_at_utc": (AS_OF + timedelta(minutes=1)).isoformat(),
            "sample_n": 100,
            "mean_absolute_calibration_error": "0.01",
        }
    ]
    result = _selector(
        [expert],
        ["cal_gate"],
        _dependency([("cal_gate", "structure")]),
        calibration_rows=rows,
    )
    calibration = _by_gate(result)["cal_gate"]["calibration_adjustment"]

    assert calibration["state"] == "unknown"
    assert calibration["excluded_current_or_future_n"] == 1


def test_build21_build20_dependency_penalty_reduces_correlated_gate_authority() -> None:
    first = _expert_result("a_structure", n=100, correct=75)
    second = _expert_result("b_structure", n=100, correct=75)
    dependency = _dependency(
        [
            ("a_structure", "structure"),
            ("b_structure", "structure"),
        ]
    )
    result = _selector(
        [first, second],
        ["a_structure", "b_structure"],
        dependency,
    )
    rows = _by_gate(result)
    multipliers = sorted(
        Decimal(rows[gate]["dependency_adjustment"]["multiplier"])
        for gate in rows
    )

    assert multipliers == [Decimal("0.500000"), Decimal("1.000000")]
    assert (
        Decimal(rows["a_structure"]["trust_score"])
        != Decimal(rows["b_structure"]["trust_score"])
    )


def test_build21_independent_liquidity_macro_structure_do_not_penalize_each_other() -> None:
    experts = [
        _expert_result("structure_gate", n=100, correct=75, family="structure"),
        _expert_result("liquidity_gate", n=100, correct=75, family="liquidity"),
        _expert_result("macro_gate", n=100, correct=75, family="event"),
    ]
    dependency = _dependency(
        [
            ("structure_gate", "structure"),
            ("liquidity_gate", "liquidity"),
            ("macro_gate", "event"),
        ]
    )
    result = _selector(
        experts,
        ["structure_gate", "liquidity_gate", "macro_gate"],
        dependency,
    )

    assert len(result["selected_high_trust_gates"]) == 3
    assert all(
        row["dependency_adjustment"]["multiplier"] == "1.000000"
        for row in result["selected_high_trust_gates"]
    )


def test_build21_context_only_gate_never_gets_directional_authority() -> None:
    expert = _expert_result(
        "macro_context",
        n=100,
        correct=75,
        family="event",
        mode="context_only",
        conclusion="context_only",
    )
    result = _selector(
        [expert],
        ["macro_context"],
        _dependency([]),
    )
    gate = _by_gate(result)["macro_context"]

    assert Decimal(gate["observation_weight"]) > 0
    assert gate["directional_authority_weight"] == "0.000000"


def test_build21_current_outcome_injection_fails_closed() -> None:
    expert = _expert_result("safe_gate", n=100, correct=75)
    expert["outcome"] = "bullish"

    with pytest.raises(ValueError, match="hindsight"):
        build_gate_selector_input(expert)


def test_build21_calibration_outcome_injection_fails_closed() -> None:
    expert = _expert_result("safe_gate", n=100, correct=75)
    gate_input = build_gate_selector_input(expert)
    dependency = _dependency([("safe_gate", "structure")])

    with pytest.raises(ValueError, match="hindsight"):
        build_environment_aware_gate_selector(
            global_environment=_environment(),
            expected_gate_ids=["safe_gate"],
            gate_inputs=[gate_input],
            dependency_engine=dependency,
            calibration_rows=[
                {
                    "gate_id": "safe_gate",
                    "observed_at_utc": (AS_OF - timedelta(minutes=1)).isoformat(),
                    "sample_n": 100,
                    "mean_absolute_calibration_error": "0.05",
                    "outcome": "winner",
                }
            ],
        )


def test_build21_replay_is_deterministic_under_input_reordering() -> None:
    experts = [
        _expert_result("structure_gate", n=100, correct=75, family="structure"),
        _expert_result("liquidity_gate", n=60, correct=40, family="liquidity"),
        _expert_result("macro_gate", n=80, correct=55, family="event"),
    ]
    dependency = _dependency(
        [
            ("structure_gate", "structure"),
            ("liquidity_gate", "liquidity"),
            ("macro_gate", "event"),
        ]
    )
    inputs = [build_gate_selector_input(item) for item in experts]
    args = {
        "global_environment": _environment(),
        "expected_gate_ids": ["macro_gate", "structure_gate", "liquidity_gate"],
        "dependency_engine": dependency,
        "calibration_rows": [],
    }
    left = build_environment_aware_gate_selector(
        gate_inputs=inputs,
        **args,
    )
    right = build_environment_aware_gate_selector(
        gate_inputs=list(reversed(inputs)),
        **args,
    )

    assert left == right
    assert left["selector_digest"] == right["selector_digest"]
    assert verify_environment_aware_gate_selector(left)


def test_build21_selector_is_attention_only_not_trade_direction() -> None:
    expert = _expert_result("structure_gate", n=100, correct=75)
    result = _selector(
        [expert],
        ["structure_gate"],
        _dependency([("structure_gate", "structure")]),
    )

    assert result["selector_creates_direction"] is False
    assert result["selector_can_see_current_outcome"] is False
    assert result["future_values_used"] is False
    assert result["formal_forward_evidence_created"] is False
    assert result["live_money_execution_allowed"] is False
