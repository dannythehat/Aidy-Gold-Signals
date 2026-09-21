from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.gold_cycle_environment import build_cycle_environment
from aidy.gold_expert_gate_contract import verify_expert_gate_packet
from aidy.gold_price_expert_math import build_price_expert_math_packet
from aidy.gold_volatility_jump_expert import (
    CLOCK_BASELINE_MINIMUM_N,
    VOLATILITY_JUMP_EXPERT_VERSION,
    VOLATILITY_JUMP_GATE_ID,
    build_volatility_jump_expert,
    summarise_volatility_regime_ablation,
)

AS_OF = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)


def _text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001")), "f").rstrip("0").rstrip(".")


def _m15_rows(*, mode: str = "retrospective") -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    start = AS_OF - timedelta(minutes=15 * 70)
    value = Decimal("2400")
    for index in range(70):
        opened = start + timedelta(minutes=15 * index)
        value += Decimal("0.18") + Decimal(index % 4) * Decimal("0.02")
        row: dict[str, object] = {
            "symbol": "XAUUSD",
            "timeframe": "M15",
            "open_time_utc": opened,
            "open": _text(value - Decimal("0.08")),
            "high": _text(value + Decimal("0.28")),
            "low": _text(value - Decimal("0.30")),
            "close": _text(value),
            "source": "build13_m15_fixture",
            "source_file_sha256": "a" * 64,
            "source_payload_sha256": "b" * 64,
            "derivation_version": "build13-fixture-v1",
        }
        if mode == "pit":
            row.update(
                {
                    "load_identity": f"build13-m15-pit-{index}",
                    "provenance_class": "pit_observed",
                    "pit_eligible": True,
                    "first_observed_at": (opened + timedelta(minutes=15)).isoformat(),
                }
            )
        else:
            row.update(
                {
                    "research_identity": f"build13-m15-retro-{index}",
                    "provenance_class": "retrospective_history",
                    "pit_eligible": False,
                }
            )
        rows.append(row)
    return rows


def _m1_values(*, expansion: bool = True) -> list[Decimal]:
    values: list[Decimal] = []
    value = Decimal("2400")
    for index in range(40):
        if index < 25:
            value += Decimal("0.01") if index % 2 else Decimal("-0.005")
        elif expansion:
            step = Decimal("0.75") if index % 2 else Decimal("-0.55")
            value += step
        else:
            value += Decimal("0.02") if index % 2 else Decimal("-0.015")
        values.append(value)
    return values


def _m1_rows(*, mode: str = "retrospective", expansion: bool = True) -> list[dict[str, object]]:
    values = _m1_values(expansion=expansion)
    start = AS_OF - timedelta(minutes=len(values))
    rows: list[dict[str, object]] = []
    previous = values[0]
    for index, close in enumerate(values):
        opened = start + timedelta(minutes=index)
        open_price = previous if index else close
        high = max(open_price, close) + Decimal("0.05")
        low = min(open_price, close) - Decimal("0.05")
        row: dict[str, object] = {
            "symbol": "XAUUSD",
            "timeframe": "M1",
            "open_time_utc": opened,
            "open": _text(open_price),
            "high": _text(high),
            "low": _text(low),
            "close": _text(close),
            "source": "build13_m1_fixture",
            "source_file_sha256": "c" * 64,
            "source_payload_sha256": "d" * 64,
            "derivation_version": "build13-fixture-v1",
        }
        if mode == "pit":
            row.update(
                {
                    "load_identity": f"build13-m1-pit-{index}",
                    "provenance_class": "pit_observed",
                    "pit_eligible": True,
                    "first_observed_at": (opened + timedelta(minutes=1)).isoformat(),
                }
            )
        else:
            row.update(
                {
                    "research_identity": f"build13-m1-retro-{index}",
                    "provenance_class": "retrospective_history",
                    "pit_eligible": False,
                }
            )
        rows.append(row)
        previous = close
    return rows


def _clock_history() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(CLOCK_BASELINE_MINIMUM_N + 5):
        observed = AS_OF - timedelta(days=index + 1)
        rows.append(
            {
                "utc_clock_bucket_15m": "09:45",
                "realized_vol_bps": _text(Decimal("0.8") + Decimal(index % 5) * Decimal("0.12")),
                "observed_at_utc": observed.isoformat(),
            }
        )
        rows.append(
            {
                "utc_clock_bucket_15m": "09:30",
                "realized_vol_bps": _text(Decimal("0.8") + Decimal(index % 5) * Decimal("0.12")),
                "observed_at_utc": observed.isoformat(),
            }
        )
    return rows


def _environment(*, event_timing: str = "outside_near_event_window") -> dict:
    return build_cycle_environment(
        as_of_utc=AS_OF,
        target_window_start_utc=AS_OF + timedelta(minutes=15),
        session_code="london",
        observed_state="neutral",
        gold_state={
            "market_structure": {
                "timeframes": {
                    "M5": {"net_close_direction": "flat", "state": "known"},
                    "M15": {"net_close_direction": "flat", "state": "known"},
                    "H1": {"net_close_direction": "up", "state": "known"},
                    "H4": {"net_close_direction": "up", "state": "known"},
                    "D1": {"net_close_direction": "up", "state": "known"},
                }
            },
            "move_observation": {
                "five_minute_distribution_state": "elevated_recent_displacement",
                "five_minute_range_state": "range_expansion",
                "windows": {
                    "5m": {"direction": "up", "return_bps": "4"},
                    "15m": {"direction": "up", "return_bps": "7"},
                    "60m": {"direction": "up", "return_bps": "10"},
                },
            },
            "volatility": {
                "state": "known",
                "realized_volatility": {"state": "known"},
                "jump_continuous": {"state": "continuous_dominant"},
                "vol_of_vol": {"state": "known"},
                "gvz": {"state": "unknown"},
                "iv_minus_rv": {"state": "unknown"},
            },
            "scheduled_event_risk": {
                "state": "known",
                "timing_state": event_timing,
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
        regime={"compound_regime_key": "expansion|normal"},
    )


def _price_packet(*, mode: str = "retrospective") -> dict:
    return build_price_expert_math_packet(
        as_of=AS_OF,
        symbol="XAUUSD",
        candle_rows=_m15_rows(mode=mode),
        mode=mode,
    )


def _qualified_state(
    *,
    jump_state: str = "continuous_dominant",
    sparse_iv: bool = False,
) -> dict[str, object]:
    return {
        "as_of_utc": (AS_OF - timedelta(minutes=5)).isoformat(),
        "mode": "pit",
        "pit_reconstructable": True,
        "state": "known",
        "realized_volatility": {
            "state": "known",
            "annualized_percent": {"5": "24", "10": "21", "21": "19"},
            "term_structure_state": "short_above_long",
        },
        "jump_continuous": {
            "state": jump_state,
            "jump_share": "0.65" if jump_state == "jump_dominant" else "0.10",
            "estimator": "realized_variation_minus_bipower_variation",
        },
        "vol_of_vol": {
            "state": "known",
            "annualized_vol_dispersion_percent": "4.25",
            "window_trading_days": 21,
        },
        "gvz": (
            {"state": "unknown"}
            if sparse_iv
            else {
                "state": "known",
                "value_annualized_percent": "27.2",
                "underlying_proxy": "SPDR_Gold_Shares_ETF_GLD",
            }
        ),
        "iv_minus_rv": (
            {"state": "unknown_missing_iv_or_comparable_rv"}
            if sparse_iv
            else {
                "state": "implied_above_realized",
                "spread_percentage_points": "8.2",
                "cross_instrument_proxy": True,
            }
        ),
    }


def _expert(
    *,
    jump_state: str = "continuous_dominant",
    event_timing: str = "outside_near_event_window",
    sparse_iv: bool = False,
    mode: str = "retrospective",
    expansion: bool = True,
    external: dict[str, object] | None = None,
) -> dict:
    return build_volatility_jump_expert(
        global_environment=_environment(event_timing=event_timing),
        price_math_packet=_price_packet(mode=mode),
        m1_candle_rows=_m1_rows(mode=mode, expansion=expansion),
        clock_volatility_history=_clock_history(),
        qualified_volatility_state=(
            external
            if external is not None
            else _qualified_state(jump_state=jump_state, sparse_iv=sparse_iv)
        ),
    )


def test_build13_is_context_only_and_never_forces_direction() -> None:
    result = _expert()
    packet = result["expert_packet"]
    assert result["expert_version"] == VOLATILITY_JUMP_EXPERT_VERSION
    assert packet["gate_id"] == VOLATILITY_JUMP_GATE_ID
    assert packet["gate_mode"] == "context_only"
    assert packet["conclusion"] == "context_only"
    assert packet["gate_scoreable"] is False
    assert packet["internal_conviction"] is None
    assert verify_expert_gate_packet(packet)
    assert result["direction_policy"]["directional_vote_allowed"] is False
    assert result["direction_policy"]["volatility_alone_creates_direction"] is False
    assert all(item["role"] == "context_only" for item in packet["subcalculators"])


def test_build13_clock_normalised_percentile_detects_compression_to_expansion() -> None:
    result = _expert()
    clock = result["clock_normalised"]
    assert clock["state"] == "known"
    assert clock["current_clock_bucket_15m"] == "09:45"
    assert clock["prior_clock_bucket_15m"] == "09:30"
    assert clock["current_clock_sample_n"] >= CLOCK_BASELINE_MINIMUM_N
    assert clock["prior_clock_sample_n"] >= CLOCK_BASELINE_MINIMUM_N
    assert Decimal(clock["current_clock_percentile"]) >= Decimal("0.80")
    assert Decimal(clock["prior_clock_percentile"]) <= Decimal("0.25")
    assert result["transition_state"] == "compression_to_expansion"


def test_build13_continuous_expansion_is_distinct_from_jump() -> None:
    result = _expert(jump_state="continuous_dominant")
    assert result["jump_regime"]["state"] == "continuous_volatility_expansion"
    assert result["rich_regime"] == "compression_breaking_to_expansion"
    assert result["jump_regime"]["event_causal_claim"] is False


def test_build13_event_proximate_jump_is_distinct_without_causal_claim() -> None:
    result = _expert(
        jump_state="jump_dominant",
        event_timing="near_event_window",
    )
    assert result["jump_regime"]["state"] == "event_proximate_jump"
    assert result["rich_regime"] == "event_proximate_jump"
    assert result["jump_regime"]["event_proximity_used"] is True
    assert result["jump_regime"]["event_causal_claim"] is False
    assert result["direction_policy"]["event_proximity_is_causal_claim"] is False


def test_build13_jump_outside_event_window_remains_jump_without_event_label() -> None:
    result = _expert(jump_state="jump_dominant")
    assert result["jump_regime"]["state"] == "jump_dominant"
    assert result["jump_regime"]["event_proximity_used"] is False


def test_build13_sparse_gvz_iv_remains_unknown() -> None:
    result = _expert(sparse_iv=True)
    assert result["optional_components"]["gvz"]["state"] == "unknown"
    assert result["optional_components"]["gvz"]["value_annualized_percent"] is None
    assert result["optional_components"]["iv_rv"]["state"] == "unknown"
    calc = next(
        item for item in result["expert_packet"]["subcalculators"]
        if item["calculator_id"] == "volatility_iv_rv_context"
    )
    assert calc["vote"] == "unknown"
    assert calc["state"] == "insufficient"


def test_build13_known_vol_of_vol_is_retained_as_context() -> None:
    result = _expert()
    vov = result["optional_components"]["vol_of_vol"]
    assert vov["state"] == "known"
    assert vov["window_trading_days"] == 21
    assert Decimal(vov["annualized_vol_dispersion_percent"]) > 0


def test_build13_unqualified_retrospective_external_state_cannot_enter_context() -> None:
    state = _qualified_state()
    state["mode"] = "retrospective_research"
    state["pit_reconstructable"] = False
    result = _expert(external=state)
    assert result["qualified_external_state"]["qualified"] is False
    assert result["jump_regime"]["state"] == "unknown"
    assert result["optional_components"]["gvz"]["state"] == "unknown"
    assert result["optional_components"]["iv_rv"]["state"] == "unknown"


def test_build13_simple_atr_baseline_is_retained_for_ablation() -> None:
    result = _expert()
    baseline = result["simple_atr_baseline"]
    assert baseline["state"] == "known"
    assert baseline["band"] in {"low", "normal", "high"}
    calc = next(
        item for item in result["expert_packet"]["subcalculators"]
        if item["calculator_id"] == "volatility_simple_atr_baseline"
    )
    assert calc["vote"] == "context_only"


def test_build13_richer_regime_ablation_requires_incremental_value() -> None:
    cases = (
        [{"simple_atr_correct": 1, "rich_regime_correct": 1}] * 10
        + [{"simple_atr_correct": 0, "rich_regime_correct": 1}] * 6
        + [{"simple_atr_correct": 0, "rich_regime_correct": 0}] * 4
    )
    summary = summarise_volatility_regime_ablation(cases, minimum_sample_n=20)
    assert summary["sample_n"] == 20
    assert Decimal(summary["rich_minus_simple_accuracy"]) > 0
    assert summary["richer_regime_incremental_value_proven"] is True
    assert summary["complexity_grants_no_weight"] is True
    assert summary["directional_authority"] is False


def test_build13_richer_regime_does_not_earn_weight_from_small_sample() -> None:
    summary = summarise_volatility_regime_ablation(
        [{"simple_atr_correct": 0, "rich_regime_correct": 1}] * 8,
        minimum_sample_n=20,
    )
    assert summary["rich_minus_simple_accuracy"] == "1.000000"
    assert summary["richer_regime_incremental_value_proven"] is False


def test_build13_pit_mode_uses_only_completed_m1_and_no_future_values() -> None:
    result = _expert(mode="pit")
    packet = result["expert_packet"]
    assert packet["no_hindsight_attestation"]["future_values_used"] is False
    assert result["future_values_used"] is False
    for evidence in packet["evidence_inputs"]:
        assert evidence["provenance"]["future_values_used"] is False


def test_build13_chronological_freeze_ignores_future_m1_and_clock_rows() -> None:
    m1 = _m1_rows(mode="pit")
    future_m1 = list(m1)
    future_m1.append(
        {
            "symbol": "XAUUSD",
            "timeframe": "M1",
            "open_time_utc": AS_OF,
            "open": "2400",
            "high": "2500",
            "low": "2390",
            "close": "2490",
            "source": "future_fixture",
            "load_identity": "future-build13",
            "provenance_class": "pit_observed",
            "pit_eligible": True,
            "first_observed_at": (AS_OF + timedelta(minutes=1)).isoformat(),
        }
    )
    history = _clock_history()
    future_history = list(history) + [
        {
            "utc_clock_bucket_15m": "09:45",
            "realized_vol_bps": "999",
            "observed_at_utc": (AS_OF + timedelta(minutes=1)).isoformat(),
        }
    ]
    environment = _environment()
    packet = _price_packet(mode="pit")
    external = _qualified_state()
    first = build_volatility_jump_expert(
        global_environment=environment,
        price_math_packet=packet,
        m1_candle_rows=m1,
        clock_volatility_history=history,
        qualified_volatility_state=external,
    )
    second = build_volatility_jump_expert(
        global_environment=environment,
        price_math_packet=packet,
        m1_candle_rows=future_m1,
        clock_volatility_history=future_history,
        qualified_volatility_state=external,
    )
    assert first["expert_packet"]["packet_digest"] == second["expert_packet"]["packet_digest"]
    assert first["clock_normalised"] == second["clock_normalised"]


def test_build13_rejects_mismatched_as_of() -> None:
    packet = _price_packet()
    bad = build_cycle_environment(
        as_of_utc=AS_OF + timedelta(minutes=15),
        target_window_start_utc=AS_OF + timedelta(minutes=30),
        session_code="london",
        observed_state="neutral",
        gold_state={
            "market_structure": {"timeframes": {}},
            "move_observation": {"windows": {}},
            "volatility": {"state": "unknown"},
        },
        semantic_context={
            "data_quality": {
                "quote_state": "known",
                "quote_freshness": "fresh",
                "spread_state": "unknown",
            },
            "cross_market": {"series": {}},
        },
        regime={"compound_regime_key": "unknown"},
    )
    with pytest.raises(ValueError, match="same as-of"):
        build_volatility_jump_expert(
            global_environment=bad,
            price_math_packet=packet,
            m1_candle_rows=_m1_rows(),
            clock_volatility_history=_clock_history(),
            qualified_volatility_state=_qualified_state(),
        )
