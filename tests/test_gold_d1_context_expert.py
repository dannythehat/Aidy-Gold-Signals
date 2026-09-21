from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.gold_cycle_environment import build_cycle_environment
from aidy.gold_d1_context_expert import (
    D1_CONTEXT_EXPERT_VERSION,
    D1_GATE_ID,
    D1_MAX_CONTEXT_AGE_HOURS,
    build_d1_context_expert,
    evaluate_d1_context_value,
)
from aidy.gold_expert_gate_contract import verify_expert_gate_packet
from aidy.gold_price_expert_math import build_price_expert_math_packet

BASE = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
STEP = timedelta(days=1)


def _text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001")), "f").rstrip("0").rstrip(".")


def _rows(
    values: list[Decimal],
    *,
    mode: str = "retrospective",
    timeframe: str = "D1",
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    previous = values[0]
    duration = timedelta(days=1) if timeframe == "D1" else timedelta(hours=4)
    for index, close in enumerate(values):
        opened = BASE + duration * index
        open_price = previous if index else close
        high = max(open_price, close) + Decimal("0.50")
        low = min(open_price, close) - Decimal("0.50")
        row: dict[str, object] = {
            "symbol": "XAUUSD",
            "timeframe": timeframe,
            "open_time_utc": opened,
            "open": _text(open_price),
            "high": _text(high),
            "low": _text(low),
            "close": _text(close),
            "source": "build9_fixture",
            "source_file_sha256": "a" * 64,
            "source_payload_sha256": "b" * 64,
            "derivation_version": "build9-fixture-v1",
        }
        if mode == "pit":
            row.update(
                {
                    "load_identity": f"build9-pit-{timeframe}-{index}",
                    "provenance_class": "pit_observed",
                    "pit_eligible": True,
                    "first_observed_at": (opened + duration).isoformat(),
                }
            )
        else:
            row.update(
                {
                    "research_identity": f"build9-retro-{timeframe}-{index}",
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
    duration = {"D1": timedelta(days=1), "H4": timedelta(hours=4)}[timeframe]
    return latest + duration


def _environment(as_of: datetime) -> dict:
    return build_cycle_environment(
        as_of_utc=as_of,
        target_window_start_utc=as_of + timedelta(minutes=15),
        session_code="london",
        observed_state="bullish",
        gold_state={
            "market_structure": {
                "timeframes": {
                    "M5": {
                        "net_close_direction": "up",
                        "directional_persistence_ratio": "0.60",
                        "latest_close_range_position": "0.66",
                        "state": "known",
                    },
                    "M15": {
                        "net_close_direction": "up",
                        "directional_persistence_ratio": "0.62",
                        "latest_close_range_position": "0.68",
                        "state": "known",
                    },
                    "H1": {
                        "net_close_direction": "up",
                        "directional_persistence_ratio": "0.64",
                        "latest_close_range_position": "0.70",
                        "state": "known",
                    },
                    "H4": {
                        "net_close_direction": "up",
                        "directional_persistence_ratio": "0.61",
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
                    "5m": {"direction": "up", "return_bps": "1"},
                    "15m": {"direction": "up", "return_bps": "2"},
                    "60m": {"direction": "up", "return_bps": "4"},
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


def _uptrend(count: int = 35) -> list[Decimal]:
    return [
        Decimal(100)
        + Decimal(index) * Decimal("0.55")
        + Decimal(index * index) * Decimal("0.01")
        for index in range(count)
    ]


def test_build9_fresh_complete_d1_is_context_only_and_auditable() -> None:
    rows = _rows(_uptrend())
    as_of = _as_of(rows)
    result = build_d1_context_expert(
        global_environment=_environment(as_of),
        price_math_packet=_packet(rows),
    )
    packet = result["expert_packet"]

    assert result["expert_version"] == D1_CONTEXT_EXPERT_VERSION
    assert packet["gate_id"] == D1_GATE_ID
    assert packet["gate_mode"] == "context_only"
    assert packet["conclusion"] == "context_only"
    assert packet["gate_scoreable"] is False
    assert packet["internal_conviction"] is None
    assert verify_expert_gate_packet(packet)
    assert result["context_decision"] == "use_context"
    assert result["context_usable"] is True

    policy = result["forecast_influence_policy"]
    assert policy["context_only"] is True
    assert policy["direct_15m_direction_allowed"] is False
    assert policy["direct_next_15m_authority"] is False
    assert policy["default_next_15m_weight"] == "0"

    for item in packet["subcalculators"]:
        assert item["role"] == "context_only"
        assert item["scoreable"] is False
        assert item["vote"] in {"context_only", "unknown"}


def test_build9_stale_d1_abstains_from_usable_context() -> None:
    rows = _rows(_uptrend())
    as_of = _as_of(rows) + timedelta(hours=D1_MAX_CONTEXT_AGE_HOURS + 1)
    result = build_d1_context_expert(
        global_environment=_environment(as_of),
        price_math_packet=_packet(rows, as_of=as_of),
    )
    assert result["freshness"]["stale"] is True
    assert result["context_decision"] == "abstain"
    assert result["context_usable"] is False
    assert result["expert_packet"]["conclusion"] == "context_only"
    assert all(
        item["vote"] == "unknown"
        for item in result["expert_packet"]["subcalculators"]
        if item["calculator_id"] != "d1_data_quality"
    )


def test_build9_partial_d1_history_abstains() -> None:
    rows = _rows(_uptrend(12))
    as_of = _as_of(rows)
    result = build_d1_context_expert(
        global_environment=_environment(as_of),
        price_math_packet=_packet(rows),
    )
    assert result["freshness"]["stale"] is False
    assert result["completeness"]["complete"] is False
    assert result["completeness"]["missing_components"]
    assert result["context_decision"] == "abstain"
    assert result["context_usable"] is False


def test_build9_missing_d1_abstains_without_direction() -> None:
    rows = _rows(_uptrend(30), timeframe="H4")
    as_of = _as_of(rows)
    result = build_d1_context_expert(
        global_environment=_environment(as_of),
        price_math_packet=_packet(rows, as_of=as_of),
    )
    assert result["context_decision"] == "abstain"
    assert result["context_usable"] is False
    packet = result["expert_packet"]
    assert packet["gate_mode"] == "context_only"
    assert packet["conclusion"] == "context_only"
    assert packet["gate_scoreable"] is False


def test_build9_never_forces_a_15m_direction_even_in_strong_d1_trend() -> None:
    rows = _rows(_uptrend(50))
    as_of = _as_of(rows)
    result = build_d1_context_expert(
        global_environment=_environment(as_of),
        price_math_packet=_packet(rows),
    )
    packet = result["expert_packet"]
    assert packet["conclusion"] not in {"bullish", "bearish"}
    assert result["forecast_influence_policy"]["direct_15m_direction_allowed"] is False
    assert result["forecast_influence_policy"]["default_next_15m_weight"] == "0"
    assert all(item["role"] == "context_only" for item in packet["subcalculators"])


def test_build9_context_value_is_separate_from_direct_forecast_value() -> None:
    cases = (
        [{"baseline_correct": 1, "with_context_correct": 1, "direct_d1_direction_correct": 0}] * 10
        + [{"baseline_correct": 0, "with_context_correct": 1, "direct_d1_direction_correct": 0}] * 6
        + [{"baseline_correct": 0, "with_context_correct": 0, "direct_d1_direction_correct": 1}] * 4
    )
    summary = evaluate_d1_context_value(cases, minimum_sample_n=20)
    assert summary["sample_n"] == 20
    assert Decimal(summary["context_accuracy_delta"]) > 0
    assert summary["context_value_proven"] is True
    assert summary["direct_forecast_sample_n"] == 20
    assert Decimal(summary["direct_forecast_accuracy"]) < Decimal("0.50")
    assert summary["direct_forecast_metric_separate"] is True
    assert summary["direct_15m_authority"] is False
    assert summary["default_next_15m_weight"] == "0"


def test_build9_context_value_requires_minimum_sample() -> None:
    summary = evaluate_d1_context_value(
        [{"baseline_correct": 0, "with_context_correct": 1}] * 10,
        minimum_sample_n=20,
    )
    assert summary["context_accuracy_delta"] == "1.000000"
    assert summary["context_value_proven"] is False
    assert summary["direct_15m_authority"] is False


def test_build9_pit_mode_uses_completed_daily_bars_only() -> None:
    rows = _rows(_uptrend(), mode="pit")
    as_of = _as_of(rows)
    result = build_d1_context_expert(
        global_environment=_environment(as_of),
        price_math_packet=_packet(rows, mode="pit"),
    )
    packet = result["expert_packet"]
    assert packet["no_hindsight_attestation"]["future_values_used"] is False
    assert result["future_values_used"] is False
    for evidence in packet["evidence_inputs"]:
        assert evidence["provenance"]["price_math_mode"] == "pit"
        assert evidence["provenance"]["completed_bars_only"] is True


def test_build9_chronological_freeze_ignores_later_daily_rows() -> None:
    values = _uptrend(45)
    prefix = _rows(values[:30], mode="pit")
    all_rows = _rows(values, mode="pit")
    as_of = _as_of(prefix)
    environment = _environment(as_of)
    first = build_d1_context_expert(
        global_environment=environment,
        price_math_packet=_packet(prefix, mode="pit", as_of=as_of),
    )
    second = build_d1_context_expert(
        global_environment=environment,
        price_math_packet=_packet(all_rows, mode="pit", as_of=as_of),
    )
    assert first["expert_packet"]["packet_digest"] == second["expert_packet"]["packet_digest"]
    assert first["context_decision"] == second["context_decision"]


def test_build9_rejects_mismatched_as_of() -> None:
    rows = _rows(_uptrend())
    as_of = _as_of(rows)
    with pytest.raises(ValueError, match="same as-of"):
        build_d1_context_expert(
            global_environment=_environment(as_of + timedelta(minutes=15)),
            price_math_packet=_packet(rows),
        )


def test_build9_attaches_build3_context_trust_without_directional_conviction() -> None:
    rows = _rows(_uptrend())
    as_of = _as_of(rows)
    base = build_d1_context_expert(
        global_environment=_environment(as_of),
        price_math_packet=_packet(rows),
    )
    exact = base["trust_scopes"][0]
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
    result = build_d1_context_expert(
        global_environment=_environment(as_of),
        price_math_packet=_packet(rows),
        trust_score_rows_by_subject={f"gate:{D1_GATE_ID}": [score_row]},
    )
    gate_profile = next(
        item for item in result["trust_envelope"]["subject_profiles"]
        if item["subject_type"] == "gate"
    )["profile"]
    assert gate_profile["selected_scope_type"] == "mini_exact"
    assert gate_profile["sample_n"] == 30
    assert result["expert_packet"]["internal_conviction"] is None


def test_build9_dependency_metadata_is_context_only() -> None:
    rows = _rows(_uptrend())
    as_of = _as_of(rows)
    result = build_d1_context_expert(
        global_environment=_environment(as_of),
        price_math_packet=_packet(rows),
    )
    assert result["dependency_metadata"]["d1_trend_context"]["dependency_family"] == "structure"
    assert result["dependency_metadata"]["d1_location_context"]["dependency_family"] == "location"
    for item in result["expert_packet"]["subcalculators"]:
        assert item["role"] == "context_only"
        assert item["scoreable"] is False
        assert item["observation"]["correlation_group"]
