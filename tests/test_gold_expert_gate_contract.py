from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aidy.gold_cycle_environment import build_cycle_environment
from aidy.gold_expert_gate_contract import (
    EXPERT_GATE_CONTRACT_VERSION,
    build_expert_gate_packet,
)
from aidy.gold_expert_gate_contract import (
    subcalculator_is_scoreable as contract_is_scoreable,
)
from aidy.gold_expert_gate_contract import (
    verify_expert_gate_packet,
)

AS_OF = datetime(2026, 9, 21, 8, 10, tzinfo=UTC)
TARGET = datetime(2026, 9, 21, 8, 15, tzinfo=UTC)


def _environment() -> dict:
    return build_cycle_environment(
        as_of_utc=AS_OF,
        target_window_start_utc=TARGET,
        session_code="london",
        observed_state="bullish",
        gold_state={
            "market_structure": {
                "timeframes": {
                    "M5": {
                        "net_close_direction": "up",
                        "directional_persistence_ratio": "0.71",
                        "latest_close_range_position": "0.82",
                        "state": "known",
                    },
                    "M15": {
                        "net_close_direction": "up",
                        "directional_persistence_ratio": "0.67",
                        "latest_close_range_position": "0.78",
                        "state": "known",
                    },
                    "H1": {
                        "net_close_direction": "down",
                        "directional_persistence_ratio": "0.58",
                        "latest_close_range_position": "0.31",
                        "state": "known",
                    },
                    "H4": {
                        "net_close_direction": "up",
                        "directional_persistence_ratio": "0.63",
                        "latest_close_range_position": "0.66",
                        "state": "known",
                    },
                    "D1": {
                        "net_close_direction": "up",
                        "state": "known",
                    },
                }
            },
            "move_observation": {
                "five_minute_distribution_state": "normal",
                "five_minute_range_state": "normal",
                "windows": {
                    "5m": {"direction": "up", "return_bps": "2.1"},
                    "15m": {"direction": "up", "return_bps": "4.2"},
                    "60m": {"direction": "down", "return_bps": "-3.7"},
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
        regime={"compound_regime_key": "mixed|normal"},
    )


def _known_evidence() -> list[dict]:
    return [
        {
            "evidence_id": "h1_slope",
            "source": "gold_state_engine",
            "path": "market_structure.timeframes.H1.slope_bps_per_bar",
            "observed_at_utc": AS_OF - timedelta(seconds=10),
            "state": "known",
            "value": "-1.42",
            "provenance": {"timeframe": "H1", "completed_bars_only": True},
        },
        {
            "evidence_id": "h1_persistence",
            "source": "gold_state_engine",
            "path": "market_structure.timeframes.H1.directional_persistence_ratio",
            "observed_at_utc": AS_OF - timedelta(seconds=10),
            "state": "known",
            "value": "0.71",
        },
    ]


def _known_calculators() -> list[dict]:
    return [
        {
            "calculator_id": "net_slope",
            "version": "h1_net_slope_v1",
            "role": "directional",
            "dependency_family": "structure",
            "state": "known",
            "vote": "bearish",
            "strength": "0.72",
            "evidence_refs": ["h1_slope"],
            "observation": {
                "slope_bps_per_bar": "-1.42",
                "slope_state": "negative",
            },
            "explanation": "Completed H1 slope is negative.",
        },
        {
            "calculator_id": "close_persistence",
            "version": "h1_close_persistence_v1",
            "role": "directional",
            "dependency_family": "structure",
            "state": "known",
            "vote": "bearish",
            "strength": "0.64",
            "evidence_refs": ["h1_persistence"],
            "observation": {
                "down_step_ratio": "0.71",
                "persistence_state": "bearish_persistent",
            },
            "explanation": "Most completed H1 close steps are lower.",
        },
    ]


def _build(**overrides) -> dict:
    kwargs = {
        "gate_id": "h1_structure_expert",
        "gate_version": "h1_structure_expert_v1",
        "gate_mode": "directional",
        "dependency_family": "structure",
        "target_horizon_minutes": 15,
        "as_of_utc": AS_OF,
        "global_environment": _environment(),
        "mini_environment": {
            "timeframe": "H1",
            "session": "london",
            "volatility": "normal",
            "h4_alignment": "bullish",
        },
        "evidence_inputs": _known_evidence(),
        "subcalculators": _known_calculators(),
        "conclusion": "bearish",
        "internal_conviction": "0.78",
        "explanation_parts": [
            {
                "text": "H1 structure is bearish because slope and close persistence agree.",
                "source_refs": ["calc:net_slope", "calc:close_persistence"],
            }
        ],
        "contradictions": [
            {
                "text": "H4 remains bullish.",
                "source_refs": ["evidence:h1_persistence"],
            }
        ],
    }
    kwargs.update(overrides)
    return build_expert_gate_packet(**kwargs)


def test_build2_directional_packet_is_auditable_and_verifiable() -> None:
    packet = _build()
    assert packet["contract_version"] == EXPERT_GATE_CONTRACT_VERSION
    assert packet["gate_id"] == "h1_structure_expert"
    assert packet["gate_scoreable"] is True
    assert packet["conclusion"] == "bearish"
    assert packet["internal_conviction"] == "0.780000"
    assert packet["global_environment_ref"]["environment_key"].startswith("envcore_")
    assert packet["mini_environment"]["mini_environment_key"].startswith("minienv_")
    assert packet["no_hindsight_attestation"]["future_values_used"] is False
    assert packet["live_money_execution_allowed"] is False
    assert verify_expert_gate_packet(packet)


def test_build2_packet_digest_detects_mutation() -> None:
    packet = _build()
    packet["conclusion"] = "bullish"
    assert verify_expert_gate_packet(packet) is False


def test_build2_missing_inputs_must_resolve_unknown_not_fake_direction() -> None:
    evidence = [
        {
            "evidence_id": "h1_missing",
            "source": "gold_state_engine",
            "path": "market_structure.timeframes.H1",
            "observed_at_utc": AS_OF,
            "state": "unknown",
            "value": None,
        }
    ]
    calculators = [
        {
            "calculator_id": "h1_missing_state",
            "version": "h1_missing_state_v1",
            "role": "directional",
            "dependency_family": "structure",
            "state": "unknown",
            "vote": "unknown",
            "evidence_refs": ["h1_missing"],
            "observation": {"state": "unknown"},
            "explanation": "H1 evidence is unavailable.",
        }
    ]

    packet = _build(
        evidence_inputs=evidence,
        subcalculators=calculators,
        conclusion="unknown",
        internal_conviction=None,
        explanation_parts=[
            {
                "text": "H1 direction is unknown because the required H1 evidence is missing.",
                "source_refs": ["calc:h1_missing_state", "evidence:h1_missing"],
            }
        ],
        contradictions=[],
    )
    assert packet["conclusion"] == "unknown"
    assert packet["gate_scoreable"] is False
    assert verify_expert_gate_packet(packet)

    with pytest.raises(ValueError, match="must conclude unknown"):
        _build(
            evidence_inputs=evidence,
            subcalculators=calculators,
            conclusion="bearish",
            internal_conviction="0.90",
            explanation_parts=[
                {
                    "text": "This direction must not be accepted.",
                    "source_refs": ["calc:h1_missing_state"],
                }
            ],
            contradictions=[],
        )


def test_build2_context_only_gate_cannot_accidentally_vote_direction() -> None:
    evidence = [
        {
            "evidence_id": "vol_state",
            "source": "volatility_intelligence",
            "path": "realized_volatility.state",
            "observed_at_utc": AS_OF,
            "state": "known",
            "value": "expanding",
        }
    ]
    calculators = [
        {
            "calculator_id": "vol_regime",
            "version": "vol_regime_v1",
            "role": "context_only",
            "dependency_family": "volatility",
            "state": "known",
            "vote": "context_only",
            "evidence_refs": ["vol_state"],
            "observation": {"volatility_state": "expanding"},
            "explanation": "Volatility is expanding.",
        }
    ]
    packet = _build(
        gate_id="volatility_expert",
        gate_version="volatility_expert_v1",
        gate_mode="context_only",
        dependency_family="volatility",
        evidence_inputs=evidence,
        subcalculators=calculators,
        conclusion="context_only",
        internal_conviction=None,
        explanation_parts=[
            {
                "text": "Volatility is an expanding context state, not a directional vote.",
                "source_refs": ["calc:vol_regime"],
            }
        ],
        contradictions=[],
    )
    assert packet["gate_scoreable"] is False
    assert verify_expert_gate_packet(packet)

    with pytest.raises(ValueError, match="context-only gate"):
        _build(
            gate_id="volatility_expert",
            gate_version="volatility_expert_v1",
            gate_mode="context_only",
            dependency_family="volatility",
            evidence_inputs=evidence,
            subcalculators=calculators,
            conclusion="bullish",
            internal_conviction="0.80",
            explanation_parts=[
                {
                    "text": "Invalid directional conclusion.",
                    "source_refs": ["calc:vol_regime"],
                }
            ],
            contradictions=[],
        )


def test_build2_future_dated_evidence_is_rejected() -> None:
    evidence = _known_evidence()
    evidence[0]["observed_at_utc"] = AS_OF + timedelta(seconds=1)
    with pytest.raises(ValueError, match="observed after"):
        _build(evidence_inputs=evidence)


def test_build2_hindsight_named_field_is_rejected() -> None:
    calculators = _known_calculators()
    calculators[0]["observation"]["future_return"] = "12.0"
    with pytest.raises(ValueError, match="hindsight field"):
        _build(subcalculators=calculators)


def test_build2_unknown_evidence_cannot_power_known_calculator() -> None:
    evidence = _known_evidence()
    evidence[0]["state"] = "unknown"
    evidence[0]["value"] = None
    calculators = _known_calculators()
    calculators[0]["evidence_refs"] = ["h1_slope"]
    with pytest.raises(ValueError, match="no known evidence input"):
        _build(
            evidence_inputs=evidence,
            subcalculators=[calculators[0]],
            conclusion="bearish",
            explanation_parts=[
                {
                    "text": "A missing input cannot justify a known calculation.",
                    "source_refs": ["calc:net_slope"],
                }
            ],
            contradictions=[],
        )


def test_build2_evidence_reference_integrity_is_enforced() -> None:
    calculators = _known_calculators()
    calculators[0]["evidence_refs"] = ["does_not_exist"]
    with pytest.raises(ValueError, match="references unknown evidence"):
        _build(subcalculators=calculators)


def test_build2_explanation_must_trace_to_real_inputs_or_calculators() -> None:
    with pytest.raises(ValueError, match="unknown source ref"):
        _build(
            explanation_parts=[
                {
                    "text": "Unsupported narrative.",
                    "source_refs": ["calc:made_up_calculator"],
                }
            ]
        )


def test_build2_explanation_is_generated_from_traceable_parts() -> None:
    packet = _build(
        explanation_parts=[
            {
                "text": "Slope is negative.",
                "source_refs": ["calc:net_slope"],
            },
            {
                "text": "Close persistence confirms the same direction.",
                "source_refs": ["calc:close_persistence", "evidence:h1_persistence"],
            },
        ]
    )
    assert packet["readable_explanation"] == (
        "Slope is negative. Close persistence confirms the same direction."
    )
    assert all(part["source_refs"] for part in packet["explanation_parts"])
    assert verify_expert_gate_packet(packet)


def test_build2_internal_conviction_is_explicitly_not_historical_reliability() -> None:
    packet = _build()
    assert packet["internal_conviction"] == "0.780000"
    assert packet["historical_reliability"] == {
        "state": "not_attached_until_build_3",
        "separate_from_internal_conviction": True,
    }


def test_build2_mini_environment_changes_without_rewriting_global_environment() -> None:
    london = _build()
    near_event = _build(
        mini_environment={
            "timeframe": "H1",
            "session": "london",
            "volatility": "normal",
            "event_proximity": "within_30m",
        }
    )
    assert (
        london["global_environment_ref"]["environment_digest"]
        == near_event["global_environment_ref"]["environment_digest"]
    )
    assert (
        london["mini_environment"]["mini_environment_key"]
        != near_event["mini_environment"]["mini_environment_key"]
    )


def test_build2_gate_asof_must_match_frozen_environment() -> None:
    with pytest.raises(ValueError, match="must match"):
        _build(as_of_utc=AS_OF + timedelta(seconds=1))


def test_build2_direction_requires_matching_scoreable_subcalculator() -> None:
    calculators = _known_calculators()
    calculators[0]["vote"] = "bullish"
    calculators[1]["vote"] = "bullish"
    with pytest.raises(ValueError, match="matching scoreable"):
        _build(subcalculators=calculators, conclusion="bearish")


def _neutral_calculators() -> list[dict]:
    """Both directional subcalculators vote neutral with no strength.

    This is exactly what the live experts emit: gold_h1_price_structure_expert
    writes `"strength": _fmt(base if vote in {"bullish","bearish"} else None)`.
    """
    calculators = _known_calculators()
    for item in calculators:
        item["vote"] = "neutral"
        item["strength"] = None
    return calculators


def test_build2_a_neutral_vote_is_scoreable_evidence() -> None:
    """A neutral vote is a falsifiable claim - "no meaningful move" - and the rest
    of the system already scores it. Only this contract used to disagree, which
    threw away 30 per cent of every directional expert's output."""
    packet = _build(
        subcalculators=_neutral_calculators(),
        conclusion="neutral",
        internal_conviction=None,
    )
    assert verify_expert_gate_packet(packet)
    votes = {item["calculator_id"]: item for item in packet["subcalculators"]}
    for item in votes.values():
        assert item["vote"] == "neutral"
        assert item["scoreable"] is True, "a neutral vote must become evidence"


def test_build2_a_neutral_vote_does_not_require_strength() -> None:
    """Experts emit strength=None beside a neutral vote. Tying the strength
    requirement to scoreability would raise on every one of them and take the
    whole shadow loop down."""
    packet = _build(
        subcalculators=_neutral_calculators(),
        conclusion="neutral",
        internal_conviction=None,
    )
    for item in packet["subcalculators"]:
        assert item["strength"] is None
    assert verify_expert_gate_packet(packet)


def test_build2_a_committed_direction_still_requires_strength() -> None:
    calculators = _known_calculators()
    for item in calculators:
        item["strength"] = None
    with pytest.raises(ValueError, match="strength"):
        _build(subcalculators=calculators)


def test_build2_construction_and_verification_share_one_scoreable_rule() -> None:
    """The rule was written out twice - once when building the packet, once when
    verifying it - and changing only the first silently failed every expert with
    "packet failed Build-2 verification". One definition now, used by both.
    """
    import inspect

    from aidy import gold_expert_gate_contract as contract

    source = inspect.getsource(contract)
    builder = source.index("def build_expert_gate_packet(")
    verifier = source.index("def verify_expert_gate_packet(")

    # Neither half may re-spell the rule; both must call the shared helper.
    for half in (source[builder:verifier], source[verifier:]):
        assert 'vote in {"bullish", "bearish"}' not in half, (
            "the scoreable rule must not be written out again; "
            "call subcalculator_is_scoreable()"
        )
    assert source.count("def subcalculator_is_scoreable(") == 1


def test_build2_abstain_and_unknown_remain_unscoreable() -> None:
    """Only a committed claim can be checked. An abstention makes none."""
    for vote in ("abstain", "unknown"):
        assert (
            contract_is_scoreable(role="directional", state="known", vote=vote) is False
        )
    assert contract_is_scoreable(role="directional", state="known", vote="neutral")
    assert contract_is_scoreable(role="directional", state="unknown", vote="neutral") is False
    assert contract_is_scoreable(role="context_only", state="known", vote="neutral") is False
