from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.gold_cycle_environment import build_cycle_environment
from aidy.gold_expert_gate_contract import verify_expert_gate_packet
from aidy.gold_momentum_impulse_expert import (
    MOMENTUM_HORIZONS_MINUTES,
    MOMENTUM_IMPULSE_EXPERT_VERSION,
    MOMENTUM_IMPULSE_GATE_ID,
    build_momentum_impulse_expert,
)
from aidy.gold_price_expert_math import build_price_expert_math_packet

BASE = datetime(2026, 9, 21, 7, 0, tzinfo=UTC)


def _text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001")), "f").rstrip("0").rstrip(".")


def _rows(
    values: list[Decimal],
    *,
    mode: str = "retrospective",
    base: datetime = BASE,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    previous = values[0]
    for index, close in enumerate(values):
        opened = base + timedelta(minutes=index)
        open_price = previous if index else close
        high = max(open_price, close) + Decimal("0.03")
        low = min(open_price, close) - Decimal("0.03")
        row: dict[str, object] = {
            "symbol": "XAUUSD",
            "timeframe": "M1",
            "open_time_utc": opened,
            "open": _text(open_price),
            "high": _text(high),
            "low": _text(low),
            "close": _text(close),
            "source": "build10_fixture",
            "source_file_sha256": "a" * 64,
            "source_payload_sha256": "b" * 64,
            "derivation_version": "build10-fixture-v1",
        }
        if mode == "pit":
            row.update(
                {
                    "load_identity": f"build10-pit-{index}",
                    "provenance_class": "pit_observed",
                    "pit_eligible": True,
                    "first_observed_at": (opened + timedelta(minutes=1)).isoformat(),
                }
            )
        else:
            row.update(
                {
                    "research_identity": f"build10-retro-{index}",
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
    return latest + timedelta(minutes=1)


def _environment(
    as_of: datetime,
    *,
    volatility_state: str = "normal",
) -> dict:
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
                        "directional_persistence_ratio": "0.68",
                        "latest_close_range_position": "0.72",
                        "state": "known",
                    },
                    "M15": {
                        "net_close_direction": "up",
                        "directional_persistence_ratio": "0.66",
                        "latest_close_range_position": "0.70",
                        "state": "known",
                    },
                    "H1": {
                        "net_close_direction": "up",
                        "directional_persistence_ratio": "0.61",
                        "latest_close_range_position": "0.65",
                        "state": "known",
                    },
                    "H4": {
                        "net_close_direction": "up",
                        "directional_persistence_ratio": "0.58",
                        "latest_close_range_position": "0.62",
                        "state": "known",
                    },
                    "D1": {"net_close_direction": "up", "state": "known"},
                }
            },
            "move_observation": {
                "five_minute_distribution_state": "within_recent_distribution",
                "five_minute_range_state": "normal_range",
                "windows": {
                    "5m": {"direction": "up", "return_bps": "2"},
                    "15m": {"direction": "up", "return_bps": "5"},
                    "60m": {"direction": "up", "return_bps": "12"},
                },
            },
            "volatility": {
                "state": volatility_state,
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
        regime={"compound_regime_key": f"trend|{volatility_state}"},
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


def _expert(
    values: list[Decimal],
    *,
    mode: str = "retrospective",
    base: datetime = BASE,
    volatility_state: str = "normal",
    trust_score_rows_by_subject=None,
) -> dict:
    rows = _rows(values, mode=mode, base=base)
    as_of = _as_of(rows)
    return build_momentum_impulse_expert(
        global_environment=_environment(as_of, volatility_state=volatility_state),
        price_math_packet=_packet(rows, mode=mode),
        m1_candle_rows=rows,
        trust_score_rows_by_subject=trust_score_rows_by_subject,
    )


def _clean_impulse(count: int = 75) -> list[Decimal]:
    value = Decimal(100)
    values = [value]
    for index in range(1, count):
        increment = Decimal("0.04") + Decimal(index) * Decimal("0.0015")
        value += increment
        values.append(value)
    return values


def _clean_down_impulse(count: int = 75) -> list[Decimal]:
    value = Decimal(130)
    values = [value]
    for index in range(1, count):
        decrement = Decimal("0.04") + Decimal(index) * Decimal("0.0015")
        value -= decrement
        values.append(value)
    return values


def test_build10_clean_continuation_impulse_is_bullish_and_auditable() -> None:
    result = _expert(_clean_impulse())
    packet = result["expert_packet"]
    assert result["expert_version"] == MOMENTUM_IMPULSE_EXPERT_VERSION
    assert packet["gate_id"] == MOMENTUM_IMPULSE_GATE_ID
    assert packet["conclusion"] == "bullish"
    assert packet["gate_scoreable"] is True
    assert verify_expert_gate_packet(packet)

    assert tuple(int(name[:-1]) for name in result["returns"]) == MOMENTUM_HORIZONS_MINUTES
    assert all(result["returns"][f"{m}m"]["direction"] == "bullish" for m in MOMENTUM_HORIZONS_MINUTES)
    assert all(result["normalised_returns"][f"{m}m"]["rv_units"] is not None for m in MOMENTUM_HORIZONS_MINUTES)

    impulse = next(
        item for item in packet["subcalculators"]
        if item["calculator_id"] == "momentum_impulse_drift"
    )
    assert impulse["vote"] == "bullish"
    assert impulse["observation"]["state"] in {"continuation_impulse", "persistent_drift"}
    assert result["consensus_audit"]["single_large_candle_guard_applied"] is False
    assert result["live_money_execution_allowed"] is False


def test_build10_clean_down_impulse_is_bearish() -> None:
    result = _expert(_clean_down_impulse())
    assert result["expert_packet"]["conclusion"] == "bearish"
    impulse = next(
        item for item in result["expert_packet"]["subcalculators"]
        if item["calculator_id"] == "momentum_impulse_drift"
    )
    assert impulse["vote"] == "bearish"


def test_build10_one_large_final_candle_does_not_equal_persistent_momentum() -> None:
    values = [Decimal(100)]
    for index in range(1, 74):
        values.append(Decimal(100) + (Decimal("0.02") if index % 2 else Decimal("-0.02")))
    values.append(Decimal("102.50"))

    result = _expert(values)
    packet = result["expert_packet"]
    persistence = next(
        item for item in packet["subcalculators"]
        if item["calculator_id"] == "momentum_persistence_efficiency"
    )
    exhaustion = next(
        item for item in packet["subcalculators"]
        if item["calculator_id"] == "momentum_exhaustion"
    )
    impulse = next(
        item for item in packet["subcalculators"]
        if item["calculator_id"] == "momentum_impulse_drift"
    )

    assert result["returns"]["1m"]["direction"] == "bullish"
    assert all(result["returns"][f"{m}m"]["direction"] == "bullish" for m in MOMENTUM_HORIZONS_MINUTES)
    assert persistence["vote"] == "neutral"
    assert impulse["observation"]["state"] == "noisy_or_unconfirmed"
    assert exhaustion["observation"]["state"] == "single_bar_exhaustion_risk"
    assert exhaustion["vote"] == "bearish"
    assert packet["conclusion"] != "bullish"


def test_build10_choppy_direction_does_not_masquerade_as_momentum() -> None:
    values = [Decimal(100)]
    for index in range(1, 75):
        values.append(
            Decimal(100)
            + (Decimal("0.35") if index % 2 else Decimal("-0.30"))
            + Decimal(index) * Decimal("0.001")
        )
    result = _expert(values)
    assert result["expert_packet"]["conclusion"] in {"neutral", "abstain"}
    impulse = next(
        item for item in result["expert_packet"]["subcalculators"]
        if item["calculator_id"] == "momentum_impulse_drift"
    )
    assert impulse["observation"]["state"] == "noisy_or_unconfirmed"


def test_build10_gapped_m1_history_fails_closed() -> None:
    rows = _rows(_clean_impulse())
    del rows[-20]
    as_of = _as_of(rows)
    result = build_momentum_impulse_expert(
        global_environment=_environment(as_of),
        price_math_packet=_packet(rows),
        m1_candle_rows=rows,
    )
    assert result["continuity"]["contiguous"] is False
    assert result["expert_packet"]["conclusion"] == "unknown"
    assert result["expert_packet"]["gate_scoreable"] is False


def test_build10_requires_61_completed_m1_bars() -> None:
    values = _clean_impulse(40)
    result = _expert(values)
    assert result["continuity"]["state"] == "insufficient"
    assert result["expert_packet"]["conclusion"] == "unknown"


def test_build10_regime_changes_conditional_trust_scope() -> None:
    normal = _expert(_clean_impulse(), volatility_state="normal")
    elevated = _expert(_clean_impulse(), volatility_state="elevated")
    assert normal["normalisation_context"]["volatility_state"] == "normal"
    assert elevated["normalisation_context"]["volatility_state"] == "elevated"

    normal_scope = next(
        scope for scope in normal["trust_scopes"]
        if scope["scope_type"] == "mini_reduced_clock_regime"
    )
    elevated_scope = next(
        scope for scope in elevated["trust_scopes"]
        if scope["scope_type"] == "mini_reduced_clock_regime"
    )
    assert normal_scope["scope_key"] != elevated_scope["scope_key"]


def test_build10_clock_bucket_changes_conditional_trust_scope() -> None:
    first = _expert(_clean_impulse(), base=BASE)
    second = _expert(_clean_impulse(), base=BASE + timedelta(minutes=15))
    first_clock = first["normalisation_context"]["utc_clock_bucket_15m"]
    second_clock = second["normalisation_context"]["utc_clock_bucket_15m"]
    assert first_clock != second_clock

    first_scope = next(
        scope for scope in first["trust_scopes"]
        if scope["scope_type"] == "mini_reduced_clock_regime"
    )
    second_scope = next(
        scope for scope in second["trust_scopes"]
        if scope["scope_type"] == "mini_reduced_clock_regime"
    )
    assert first_scope["scope_key"] != second_scope["scope_key"]


def test_build10_correlated_price_influence_is_tagged_for_later_penalty() -> None:
    result = _expert(_clean_impulse())
    assert result["correlation_policy"]["price_expert_overlap_tagged"] is True
    assert result["correlation_policy"]["later_correlation_penalty_required"] is True
    assert result["correlation_policy"]["automatic_extra_weight_for_shared_price_inputs"] is False

    for calculator_id, metadata in result["dependency_metadata"].items():
        if calculator_id == "momentum_clock_regime_context":
            continue
        assert metadata["later_penalty_tag"] == "correlated_price_expert_input"

    for item in result["expert_packet"]["subcalculators"]:
        if item["role"] == "directional":
            assert item["observation"]["later_penalty_tag"] == "correlated_price_expert_input"


def test_build10_pit_mode_uses_completed_m1_and_ignores_future_rows() -> None:
    values = _clean_impulse(85)
    prefix = _rows(values[:75], mode="pit")
    all_rows = _rows(values, mode="pit")
    as_of = _as_of(prefix)
    environment = _environment(as_of)
    packet_one = _packet(prefix, mode="pit", as_of=as_of)
    packet_two = _packet(all_rows, mode="pit", as_of=as_of)

    first = build_momentum_impulse_expert(
        global_environment=environment,
        price_math_packet=packet_one,
        m1_candle_rows=prefix,
    )
    second = build_momentum_impulse_expert(
        global_environment=environment,
        price_math_packet=packet_two,
        m1_candle_rows=all_rows,
    )
    assert first["expert_packet"]["packet_digest"] == second["expert_packet"]["packet_digest"]
    assert first["returns"] == second["returns"]
    assert first["future_values_used"] is False


def test_build10_rejects_mismatched_as_of() -> None:
    rows = _rows(_clean_impulse())
    as_of = _as_of(rows)
    with pytest.raises(ValueError, match="same as-of"):
        build_momentum_impulse_expert(
            global_environment=_environment(as_of + timedelta(minutes=15)),
            price_math_packet=_packet(rows),
            m1_candle_rows=rows,
        )


def test_build10_attaches_build3_conditional_trust() -> None:
    base = _expert(_clean_impulse())
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
    result = _expert(
        _clean_impulse(),
        trust_score_rows_by_subject={
            f"gate:{MOMENTUM_IMPULSE_GATE_ID}": [score_row],
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
