from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.gold_cycle_environment import build_cycle_environment
from aidy.gold_environment_gate_selector import (
    build_environment_aware_gate_selector,
    build_gate_selector_input,
)
from aidy.gold_evidence_dependency import build_evidence_dependency_engine
from aidy.gold_expert_gate_contract import build_expert_gate_packet
from aidy.gold_expert_trust import (
    build_trust_envelope,
    build_trust_scopes,
    select_conditional_trust,
)
from aidy.gold_meta_direction import (
    META_DIRECTION_AGGREGATOR_VERSION,
    build_meta_direction_view,
    verify_meta_direction_view,
)

AS_OF = datetime(2026, 9, 21, 15, 0, tzinfo=UTC)


def _environment() -> dict:
    return build_cycle_environment(
        as_of_utc=AS_OF,
        target_window_start_utc=AS_OF + timedelta(minutes=15),
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


def _row(scope: dict, *, n: int, correct: int) -> dict:
    recent_n = min(n, 20)
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


def _expert(
    gate_id: str,
    *,
    conclusion: str,
    family: str,
    mode: str = "directional",
    n: int = 100,
    correct: int = 75,
    state: str = "known",
) -> dict:
    context_only = mode == "context_only"
    effective_conclusion = (
        "context_only"
        if context_only and state == "known"
        else "unknown"
        if state != "known"
        else conclusion
    )
    packet = build_expert_gate_packet(
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
        },
        evidence_inputs=[
            {
                "evidence_id": f"{gate_id}_evidence",
                "source": "build22_fixture",
                "path": f"fixture.{gate_id}",
                "observed_at_utc": AS_OF - timedelta(seconds=1),
                "state": "known" if state == "known" else "unknown",
                "value": "known" if state == "known" else None,
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
                "observation": {"fixture": gate_id},
                "explanation": f"{gate_id} fixture evidence.",
            }
        ],
        conclusion=effective_conclusion,
        internal_conviction=(
            "0.70"
            if mode == "directional"
            and state == "known"
            and conclusion in {"bullish", "bearish"}
            else None
        ),
        explanation_parts=[
            {
                "text": f"{gate_id} says {effective_conclusion}.",
                "source_refs": [f"calc:{gate_id}_calc"],
            }
        ],
        contradictions=[],
    )
    scopes = build_trust_scopes(packet=packet)
    rows = [_row(scopes[0], n=n, correct=correct)] if state == "known" else []
    profile = select_conditional_trust(score_rows=rows, scopes=scopes)
    trust = build_trust_envelope(
        packet=packet,
        profiles_by_subject={f"gate:{gate_id}": profile},
    )
    return {
        "expert_packet": packet,
        "trust_envelope": trust,
    }


def _family_parent(family: str) -> str:
    return {
        "structure": "price_action",
        "momentum": "price_action",
        "liquidity": "liquidity_mechanism",
        "event": "macro_information",
        "volatility": "volatility_regime",
    }[family]


def _dependency(experts: list[dict]) -> dict:
    signals = []
    for expert in experts:
        packet = expert["expert_packet"]
        if packet["gate_mode"] != "directional" or packet["conclusion"] == "unknown":
            continue
        family = packet["dependency_family"]
        signals.append(
            {
                "signal_id": f"{packet['gate_id']}:{packet['gate_id']}_calc",
                "gate_id": packet["gate_id"],
                "calculator_id": f"{packet['gate_id']}_calc",
                "dependency_family": family,
                "parent_family": _family_parent(family),
                "correlation_group": f"{packet['gate_id']}_group",
                "role": "directional",
                "state": "known",
                "vote": packet["conclusion"],
                "raw_weight": "1",
                "evidence_identity": f"{packet['gate_id']}_evidence",
            }
        )
    return build_evidence_dependency_engine(
        signals=signals,
        historical_rows=[],
        as_of_utc=AS_OF,
    )


def _selector(experts: list[dict], expected: list[str] | None = None) -> dict:
    expected_ids = expected or [item["expert_packet"]["gate_id"] for item in experts]
    return build_environment_aware_gate_selector(
        global_environment=_environment(),
        expected_gate_ids=expected_ids,
        gate_inputs=[build_gate_selector_input(item) for item in experts],
        dependency_engine=_dependency(experts),
        calibration_rows=[],
    )


def _view(
    experts: list[dict],
    *,
    expected: list[str] | None = None,
    meta_calibration_rows: list[dict] | None = None,
) -> dict:
    return build_meta_direction_view(
        global_environment=_environment(),
        selector=_selector(experts, expected),
        expert_results=experts,
        meta_calibration_rows=meta_calibration_rows or [],
    )


def test_build22_bullish_view_is_traceable_to_gate_packets() -> None:
    experts = [
        _expert("structure_gate", conclusion="bullish", family="structure"),
        _expert("liquidity_gate", conclusion="bullish", family="liquidity"),
        _expert("macro_context", conclusion="context_only", family="event", mode="context_only"),
    ]
    view = _view(experts)

    assert view["aggregator_version"] == META_DIRECTION_AGGREGATOR_VERSION
    assert view["direction"] == "bullish"
    assert {row["gate_id"] for row in view["supporting_gates"]} == {
        "structure_gate",
        "liquidity_gate",
    }
    assert [row["gate_id"] for row in view["context_only_gates"]] == ["macro_context"]
    assert all(row["packet_digest"] for row in view["all_gate_traces"])
    assert "structure_gate" in view["readable_why"]
    assert verify_meta_direction_view(view)


def test_build22_bearish_view_works() -> None:
    experts = [
        _expert("structure_gate", conclusion="bearish", family="structure"),
        _expert("liquidity_gate", conclusion="bearish", family="liquidity"),
    ]
    view = _view(experts)

    assert view["direction"] == "bearish"
    assert Decimal(view["authority_totals"]["signed"]) < 0


def test_build22_strong_high_trust_contradiction_forces_abstain() -> None:
    experts = [
        _expert("bull_gate", conclusion="bullish", family="structure"),
        _expert("bear_gate", conclusion="bearish", family="liquidity"),
    ]
    view = _view(experts)

    assert view["strong_contradiction"] is True
    assert view["direction"] == "abstain"
    assert view["decision_reason"] == "strong_cross_gate_contradiction"
    assert view["calibrated_confidence"] is None


def test_build22_balanced_reduced_votes_can_resolve_neutral() -> None:
    experts = [
        _expert("bull_gate", conclusion="bullish", family="structure", n=15, correct=9),
        _expert("bear_gate", conclusion="bearish", family="liquidity", n=15, correct=9),
    ]
    view = _view(experts)

    assert view["direction"] in {"neutral", "abstain"}
    assert view["calibrated_confidence"] is None


def test_build22_no_directional_authority_abstains() -> None:
    experts = [
        _expert("macro_context", conclusion="context_only", family="event", mode="context_only"),
        _expert("vol_context", conclusion="context_only", family="volatility", mode="context_only"),
    ]
    view = _view(experts)

    assert view["direction"] == "abstain"
    assert view["decision_reason"] == "insufficient_directional_authority"
    assert view["authority_totals"]["directional_total"] == "0.000000"


def test_build22_context_only_gate_never_casts_directional_vote() -> None:
    experts = [
        _expert("bull_gate", conclusion="bullish", family="structure"),
        _expert("macro_context", conclusion="context_only", family="event", mode="context_only"),
    ]
    view = _view(experts)

    context = view["context_only_gates"][0]
    assert context["directional_authority_weight"] == "0.000000"
    assert view["traceability"]["context_only_gates_cast_directional_vote"] is False


def test_build22_no_magic_confidence_without_meta_calibration() -> None:
    view = _view(
        [_expert("bull_gate", conclusion="bullish", family="structure")]
    )

    assert view["direction"] == "bullish"
    assert view["calibrated_confidence"] is None
    assert view["confidence_state"] == "withheld_unavailable"
    assert view["traceability"]["magic_percentage_created"] is False


def test_build22_confidence_requires_sufficient_historical_meta_calibration() -> None:
    env = _environment()
    rows = [
        {
            "environment_key": env["environment_key"],
            "observed_at_utc": (AS_OF - timedelta(minutes=30)).isoformat(),
            "sample_n": 80,
            "empirical_accuracy": "0.70",
        }
    ]
    view = _view(
        [_expert("bull_gate", conclusion="bullish", family="structure")],
        meta_calibration_rows=rows,
    )

    assert view["confidence_state"] == "known_from_historical_meta_calibration"
    assert view["calibrated_confidence"] == "0.660000"
    assert view["meta_calibration"]["sample_n"] == 80


def test_build22_small_meta_calibration_sample_withholds_confidence() -> None:
    env = _environment()
    rows = [
        {
            "environment_key": env["environment_key"],
            "observed_at_utc": (AS_OF - timedelta(minutes=30)).isoformat(),
            "sample_n": 10,
            "empirical_accuracy": "0.90",
        }
    ]
    view = _view(
        [_expert("bull_gate", conclusion="bullish", family="structure")],
        meta_calibration_rows=rows,
    )

    assert view["calibrated_confidence"] is None
    assert view["confidence_state"] == "withheld_insufficient_sample"


def test_build22_future_meta_calibration_is_excluded() -> None:
    env = _environment()
    rows = [
        {
            "environment_key": env["environment_key"],
            "observed_at_utc": (AS_OF + timedelta(minutes=1)).isoformat(),
            "sample_n": 100,
            "empirical_accuracy": "0.99",
        }
    ]
    view = _view(
        [_expert("bull_gate", conclusion="bullish", family="structure")],
        meta_calibration_rows=rows,
    )

    assert view["calibrated_confidence"] is None
    assert view["meta_calibration"]["excluded_current_or_future_n"] == 1


def test_build22_unavailable_expected_gate_is_visible() -> None:
    expert = _expert("bull_gate", conclusion="bullish", family="structure")
    view = _view(
        [expert],
        expected=["bull_gate", "missing_gate"],
    )

    assert [row["gate_id"] for row in view["unavailable_gates"]] == ["missing_gate"]


def test_build22_selector_packet_digest_mismatch_fails_closed() -> None:
    expert = _expert("bull_gate", conclusion="bullish", family="structure")
    selector = _selector([expert])
    selector["all_gates"][0]["packet_digest"] = "0" * 64
    body = dict(selector)
    body.pop("selector_digest", None)

    # Tampering should fail selector verification before packet matching.
    with pytest.raises(ValueError, match="verified Build-21 selector"):
        build_meta_direction_view(
            global_environment=_environment(),
            selector=selector,
            expert_results=[expert],
        )


def test_build22_current_outcome_in_expert_result_is_rejected() -> None:
    expert = _expert("bull_gate", conclusion="bullish", family="structure")
    selector = _selector([expert])
    expert["outcome"] = "winner"

    with pytest.raises(ValueError, match="hindsight"):
        build_meta_direction_view(
            global_environment=_environment(),
            selector=selector,
            expert_results=[expert],
        )


def test_build22_deterministic_under_expert_input_reordering() -> None:
    experts = [
        _expert("structure_gate", conclusion="bullish", family="structure"),
        _expert("liquidity_gate", conclusion="bullish", family="liquidity"),
        _expert("macro_context", conclusion="context_only", family="event", mode="context_only"),
    ]
    selector = _selector(experts)

    left = build_meta_direction_view(
        global_environment=_environment(),
        selector=selector,
        expert_results=experts,
    )
    right = build_meta_direction_view(
        global_environment=_environment(),
        selector=selector,
        expert_results=list(reversed(experts)),
    )

    assert left == right
    assert left["view_digest"] == right["view_digest"]


def test_build22_remains_research_only() -> None:
    view = _view(
        [_expert("bull_gate", conclusion="bullish", family="structure")]
    )

    assert view["future_values_used"] is False
    assert view["research_only"] is True
    assert view["formal_forward_evidence_created"] is False
    assert view["live_money_execution_allowed"] is False
