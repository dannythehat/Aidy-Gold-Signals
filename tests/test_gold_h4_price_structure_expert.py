from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.gold_cycle_environment import build_cycle_environment
from aidy.gold_expert_gate_contract import verify_expert_gate_packet
from aidy.gold_h4_price_structure_expert import (
    H4_GATE_ID,
    H4_PRICE_STRUCTURE_EXPERT_VERSION,
    build_h4_price_structure_expert,
    evaluate_h4_incremental_value,
    summarise_h4_chronological_replay,
)
from aidy.gold_price_expert_math import build_price_expert_math_packet

BASE = datetime(2026, 9, 21, 6, 0, tzinfo=UTC)
STEP = timedelta(hours=4)


def _text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001")), "f").rstrip("0").rstrip(".")


def _rows(
    values: list[Decimal],
    *,
    mode: str = "retrospective",
    timeframe: str = "H4",
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    previous = values[0]
    for index, close in enumerate(values):
        opened = BASE + STEP * index
        open_price = previous if index else close
        high = max(open_price, close) + Decimal("0.20")
        low = min(open_price, close) - Decimal("0.20")
        row: dict[str, object] = {
            "symbol": "XAUUSD",
            "timeframe": timeframe,
            "open_time_utc": opened,
            "open": _text(open_price),
            "high": _text(high),
            "low": _text(low),
            "close": _text(close),
            "source": "build8_fixture",
            "source_file_sha256": "a" * 64,
            "source_payload_sha256": "b" * 64,
            "derivation_version": "build8-fixture-v1",
        }
        if mode == "pit":
            row.update(
                {
                    "load_identity": f"build8-pit-{timeframe}-{index}",
                    "provenance_class": "pit_observed",
                    "pit_eligible": True,
                    "first_observed_at": (opened + STEP).isoformat(),
                }
            )
        else:
            row.update(
                {
                    "research_identity": f"build8-retro-{timeframe}-{index}",
                    "provenance_class": "retrospective_history",
                    "pit_eligible": False,
                }
            )
        rows.append(row)
        previous = close
    return rows


def _as_of(rows: list[dict[str, object]]) -> datetime:
    latest = max(row["open_time_utc"] for row in rows)
    assert isinstance(latest, datetime)
    timeframe = str(rows[0]["timeframe"])
    duration = {
        "H4": timedelta(hours=4),
        "D1": timedelta(days=1),
    }[timeframe]
    return latest + duration


def _environment(
    as_of: datetime,
    *,
    legacy_h4: str = "up",
    m5: str = "up",
    m15: str = "up",
    h1: str = "up",
    observed: str = "bullish",
) -> dict:
    target = as_of + timedelta(minutes=15)
    return build_cycle_environment(
        as_of_utc=as_of,
        target_window_start_utc=target,
        session_code="london",
        observed_state=observed,
        gold_state={
            "market_structure": {
                "timeframes": {
                    "M5": {
                        "net_close_direction": m5,
                        "directional_persistence_ratio": "0.60",
                        "latest_close_range_position": "0.66",
                        "state": "known" if m5 in {"up", "down"} else "unknown",
                    },
                    "M15": {
                        "net_close_direction": m15,
                        "directional_persistence_ratio": "0.62",
                        "latest_close_range_position": "0.68",
                        "state": "known" if m15 in {"up", "down"} else "unknown",
                    },
                    "H1": {
                        "net_close_direction": h1,
                        "directional_persistence_ratio": "0.64",
                        "latest_close_range_position": "0.70",
                        "state": "known" if h1 in {"up", "down"} else "unknown",
                    },
                    "H4": {
                        "net_close_direction": legacy_h4,
                        "directional_persistence_ratio": "0.64",
                        "latest_close_range_position": "0.70",
                        "state": "known" if legacy_h4 in {"up", "down"} else "unknown",
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
                    "5m": {"direction": m5, "return_bps": "1.0"},
                    "15m": {"direction": m15, "return_bps": "2.0"},
                    "60m": {"direction": h1, "return_bps": "4.0"},
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


def _price_packet(
    rows: list[dict[str, object]],
    *,
    mode: str = "retrospective",
    as_of: datetime | None = None,
) -> dict:
    return build_price_expert_math_packet(
        as_of=as_of or _as_of(rows),
        symbol="XAUUSD",
        candle_rows=rows,
        mode=mode,
    )


def _expert(
    values: list[Decimal],
    *,
    mode: str = "retrospective",
    legacy_h4: str = "up",
    m5: str = "up",
    m15: str = "up",
    h1: str = "up",
    trust_score_rows_by_subject=None,
) -> dict:
    rows = _rows(values, mode=mode)
    as_of = _as_of(rows)
    return build_h4_price_structure_expert(
        global_environment=_environment(
            as_of,
            legacy_h4=legacy_h4,
            m5=m5,
            m15=m15,
            h1=h1,
        ),
        price_math_packet=_price_packet(rows, mode=mode),
        trust_score_rows_by_subject=trust_score_rows_by_subject,
    )


def _uptrend(count: int = 30) -> list[Decimal]:
    return [
        Decimal(100)
        + Decimal(index) * Decimal("0.40")
        + Decimal(index * index) * Decimal("0.015")
        for index in range(count)
    ]


def _downtrend(count: int = 30) -> list[Decimal]:
    return [
        Decimal(130)
        - Decimal(index) * Decimal("0.40")
        - Decimal(index * index) * Decimal("0.015")
        for index in range(count)
    ]


def test_build8_clean_h4_uptrend_is_bullish_and_auditable() -> None:
    result = _expert(_uptrend())
    packet = result["expert_packet"]
    assert result["expert_version"] == H4_PRICE_STRUCTURE_EXPERT_VERSION
    assert packet["gate_id"] == H4_GATE_ID
    assert packet["conclusion"] == "bullish"
    assert packet["gate_scoreable"] is True
    assert verify_expert_gate_packet(packet)

    trend = next(
        item for item in packet["subcalculators"]
        if item["calculator_id"] == "h4_trend_quality"
    )
    assert trend["vote"] == "bullish"
    assert trend["observation"]["quality_gate_passed"] is True
    assert trend["observation"]["eight_bar_horizon_hours"] == 32
    assert Decimal(trend["strength"]) >= Decimal("0.60")

    policy = result["forecast_influence_policy"]
    assert policy["direct_next_15m_authority"] is False
    assert policy["timeframe_priority_bonus"] == "0"
    assert policy["default_next_15m_weight"] == "0"
    assert policy["requires_incremental_conditional_value"] is True
    assert policy["higher_timeframe_does_not_imply_higher_weight"] is True

    assert result["independent_calibration"]["copied_h1_thresholds"] is False
    assert result["independent_calibration"]["trend_quality_primary_horizon_hours"] == 32
    assert result["consensus_audit"]["complexity_does_not_add_weight"] is True
    assert result["live_money_execution_allowed"] is False


def test_build8_clean_h4_downtrend_is_bearish() -> None:
    result = _expert(_downtrend(), legacy_h4="down")
    assert result["expert_packet"]["conclusion"] == "bearish"
    trend = next(
        item for item in result["expert_packet"]["subcalculators"]
        if item["calculator_id"] == "h4_trend_quality"
    )
    assert trend["vote"] == "bearish"


def test_build8_chop_does_not_masquerade_as_a_trend() -> None:
    values = [Decimal(100), Decimal(101)] * 16
    result = _expert(values, legacy_h4="up")
    packet = result["expert_packet"]
    assert packet["conclusion"] in {"neutral", "abstain"}
    trend = next(
        item for item in packet["subcalculators"]
        if item["calculator_id"] == "h4_trend_quality"
    )
    assert trend["vote"] == "neutral"
    assert result["legacy_comparison"]["legacy_h4_vote"] == "bullish"
    assert result["legacy_comparison"]["agreement"] is False


def test_build8_positive_first_to_last_choppy_path_is_not_bullish() -> None:
    values = [
        Decimal(100),
        Decimal(106),
        Decimal(99),
        Decimal(107),
        Decimal(98),
        Decimal(108),
        Decimal(97),
        Decimal(109),
        Decimal(96),
        Decimal(110),
        Decimal(95),
        Decimal(111),
        Decimal(94),
        Decimal(112),
        Decimal(93),
        Decimal(113),
        Decimal(101),
        Decimal(114),
        Decimal(102),
        Decimal(115),
        Decimal(103),
        Decimal(116),
    ]
    assert values[-1] > values[0]
    result = _expert(values, legacy_h4="up")
    packet = result["expert_packet"]
    trend = next(
        item for item in packet["subcalculators"]
        if item["calculator_id"] == "h4_trend_quality"
    )
    assert trend["observation"]["eight_bar_return_bps"] is not None
    assert Decimal(trend["observation"]["eight_bar_return_bps"]) > 0
    assert trend["vote"] == "neutral"
    assert trend["observation"]["quality_gate_passed"] is False
    assert packet["conclusion"] != "bullish"


def test_build8_lower_timeframe_conflict_is_explicit_and_scoreable() -> None:
    result = _expert(_uptrend(), m5="down", m15="down", h1="down")
    conflict = next(
        item for item in result["expert_packet"]["subcalculators"]
        if item["calculator_id"] == "h4_lower_timeframe_conflict"
    )
    assert conflict["observation"]["conflict"] is True
    assert conflict["observation"]["lower_consensus"] == "bearish"
    assert conflict["vote"] == "bullish"
    assert conflict["scoreable"] is True
    assert "not an override" in conflict["explanation"].lower()


def test_build8_h4_cannot_earn_next15_influence_from_timeframe_alone() -> None:
    result = _expert(_uptrend())
    policy = result["forecast_influence_policy"]
    assert policy["direct_next_15m_authority"] is False
    assert policy["timeframe_priority_bonus"] == "0"
    assert policy["default_next_15m_weight"] == "0"

    insufficient = evaluate_h4_incremental_value(
        [{"baseline_correct": 0, "with_h4_correct": 1}] * 10,
        minimum_sample_n=20,
    )
    assert insufficient["accuracy_delta"] == "1.000000"
    assert insufficient["incremental_conditional_value_proven"] is False
    assert insufficient["eligible_for_future_next_15m_influence"] is False

    proven = evaluate_h4_incremental_value(
        (
            [{"baseline_correct": 1, "with_h4_correct": 1}] * 12
            + [{"baseline_correct": 0, "with_h4_correct": 1}] * 5
            + [{"baseline_correct": 0, "with_h4_correct": 0}] * 3
        ),
        minimum_sample_n=20,
    )
    assert proven["sample_n"] == 20
    assert Decimal(proven["accuracy_delta"]) > 0
    assert proven["incremental_conditional_value_proven"] is True
    assert proven["eligible_for_future_next_15m_influence"] is True
    assert proven["timeframe_priority_bonus"] == "0"


def test_build8_reversal_surfaces_conflict_instead_of_hiding_it() -> None:
    values = _uptrend(22)
    values.extend(
        [
            values[-1] - Decimal("0.8"),
            values[-1] - Decimal("1.8"),
            values[-1] - Decimal("3.0"),
            values[-1] - Decimal("4.5"),
            values[-1] - Decimal("6.2"),
            values[-1] - Decimal("8.0"),
        ]
    )
    result = _expert(values)
    packet = result["expert_packet"]
    assert packet["conclusion"] in {"abstain", "neutral", "bearish"}
    assert packet["contradictions"] or (
        result["consensus_audit"]["positive_family_count"]
        and result["consensus_audit"]["negative_family_count"]
    )


def test_build8_missing_h4_stays_unknown() -> None:
    values = [Decimal(2000 + index) for index in range(25)]
    rows = _rows(values, timeframe="D1")
    as_of = _as_of(rows)
    result = build_h4_price_structure_expert(
        global_environment=_environment(as_of, legacy_h4="unknown", observed="unknown"),
        price_math_packet=_price_packet(rows, as_of=as_of),
    )
    assert result["expert_packet"]["conclusion"] == "unknown"
    assert result["expert_packet"]["gate_scoreable"] is False
    assert all(
        item["vote"] == "unknown"
        for item in result["expert_packet"]["subcalculators"]
        if item["role"] == "directional"
    )


def test_build8_pit_mode_keeps_completed_bar_provenance_and_no_future_values() -> None:
    values = _uptrend()
    rows = _rows(values, mode="pit")
    as_of = _as_of(rows)
    result = build_h4_price_structure_expert(
        global_environment=_environment(as_of),
        price_math_packet=_price_packet(rows, mode="pit"),
    )
    packet = result["expert_packet"]
    assert packet["conclusion"] == "bullish"
    assert packet["no_hindsight_attestation"]["future_values_used"] is False
    assert result["future_values_used"] is False
    for evidence in packet["evidence_inputs"]:
        assert evidence["provenance"]["price_math_mode"] == "pit"
        assert evidence["provenance"]["completed_bars_only"] is True


def test_build8_rejects_mismatched_as_of_between_environment_and_price_math() -> None:
    values = _uptrend()
    rows = _rows(values)
    as_of = _as_of(rows)
    with pytest.raises(ValueError, match="same as-of"):
        build_h4_price_structure_expert(
            global_environment=_environment(as_of + timedelta(minutes=15)),
            price_math_packet=_price_packet(rows),
        )


def test_build8_attaches_build3_environment_specific_trust() -> None:
    base = _expert(_uptrend())
    scopes = base["trust_scopes"]
    exact = scopes[0]
    score_row = {
        "scope_key": exact["scope_key"],
        "scope_type": exact["scope_type"],
        "sample_n": 30,
        "correct_n": 24,
        "incorrect_n": 6,
        "net_score": 20,
        "score_mean": "0.666667",
        "accuracy": "0.8",
        "recent_window": 20,
        "recent_sample_n": 12,
        "recent_correct_n": 10,
        "recent_net_score": 9,
        "recent_accuracy": "0.833333",
        "wilson_95_low": "0.626",
        "wilson_95_high": "0.905",
    }
    result = _expert(
        _uptrend(),
        trust_score_rows_by_subject={
            f"gate:{H4_GATE_ID}": [score_row],
        },
    )
    gate_profile = next(
        item for item in result["trust_envelope"]["subject_profiles"]
        if item["subject_type"] == "gate"
    )["profile"]
    assert gate_profile["selected_scope_type"] == "mini_exact"
    assert gate_profile["sample_n"] == 30
    assert result["trust_envelope"][
        "historical_reliability_separate_from_internal_conviction"
    ] is True


def test_build8_chronological_freeze_is_unchanged_by_later_rows() -> None:
    values = _uptrend(35)
    prefix = _rows(values[:25], mode="pit")
    all_rows = _rows(values, mode="pit")
    as_of = _as_of(prefix)
    first_math = _price_packet(prefix, mode="pit", as_of=as_of)
    second_math = _price_packet(all_rows, mode="pit", as_of=as_of)
    environment = _environment(as_of)
    first = build_h4_price_structure_expert(
        global_environment=environment,
        price_math_packet=first_math,
    )
    second = build_h4_price_structure_expert(
        global_environment=environment,
        price_math_packet=second_math,
    )
    assert first["expert_packet"]["packet_digest"] == second["expert_packet"]["packet_digest"]
    assert first["expert_packet"]["conclusion"] == second["expert_packet"]["conclusion"]


def test_build8_dependency_and_correlation_metadata_are_explicit() -> None:
    result = _expert(_uptrend())
    metadata = result["dependency_metadata"]
    assert metadata["h4_trend_quality"]["dependency_family"] == "structure"
    assert metadata["h4_trend_quality"]["correlation_group"] == "h4_path_structure"
    assert metadata["h4_acceleration"]["dependency_family"] == "momentum"
    assert metadata["h4_acceleration"]["correlation_group"] == "h4_momentum_transition"
    assert metadata["h4_lower_timeframe_conflict"]["dependency_family"] == "cross_market"
    assert (
        metadata["h4_lower_timeframe_conflict"]["correlation_group"]
        == "h4_lower_timeframe_conflict"
    )
    for item in result["expert_packet"]["subcalculators"]:
        assert item["dependency_family"]
        assert item["observation"]["correlation_group"]


def test_build8_h4_trust_scope_is_separate_from_h1() -> None:
    result = _expert(_uptrend())
    assert result["expert_packet"]["gate_id"] == "h4_price_structure_expert"
    assert all(
        scope["payload"]["gate_id"] == "h4_price_structure_expert"
        for scope in result["trust_scopes"]
    )
    assert all(
        scope["payload"]["gate_id"] != "h1_price_structure_expert"
        for scope in result["trust_scopes"]
    )


def test_build8_replay_compares_against_legacy_without_awarding_complexity() -> None:
    summary = summarise_h4_chronological_replay(
        [
            {
                "expert_conclusion": "bullish",
                "legacy_vote": "bullish",
                "realised_direction": "bullish",
                "realised_return_bps": "7",
            },
            {
                "expert_conclusion": "abstain",
                "legacy_vote": "bearish",
                "realised_direction": "bullish",
                "realised_return_bps": "6",
            },
            {
                "expert_conclusion": "bearish",
                "legacy_vote": "bearish",
                "realised_direction": "bearish",
                "realised_return_bps": "-3",
            },
        ]
    )
    assert summary["case_count"] == 3
    assert summary["expert_scoreable_n"] == 2
    assert summary["legacy_scoreable_n"] == 3
    assert summary["expert_net_impact_score"] == 3
    assert summary["legacy_net_impact_score"] == 1
    assert summary["net_impact_delta_vs_legacy"] == 2
    assert summary["expert_complexity_is_not_acceptance_evidence"] is True
