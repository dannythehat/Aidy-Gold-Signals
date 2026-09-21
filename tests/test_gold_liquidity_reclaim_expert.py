from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.gold_cycle_environment import build_cycle_environment
from aidy.gold_expert_gate_contract import verify_expert_gate_packet
from aidy.gold_liquidity_reclaim_expert import (
    LIQUIDITY_RECLAIM_EXPERT_VERSION,
    LIQUIDITY_RECLAIM_GATE_ID,
    build_liquidity_reclaim_expert,
)
from aidy.gold_price_expert_math import build_price_expert_math_packet
from aidy.gold_price_location_expert import build_price_location_expert

AS_OF = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)


def _text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001")), "f").rstrip("0").rstrip(".")


def _m15_rows(*, mode: str = "retrospective") -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    start = AS_OF - timedelta(minutes=15 * 60)
    value = Decimal("110")
    for index in range(60):
        opened = start + timedelta(minutes=15 * index)
        value += Decimal("0.08") + Decimal(index % 3) * Decimal("0.01")
        row: dict[str, object] = {
            "symbol": "XAUUSD",
            "timeframe": "M15",
            "open_time_utc": opened,
            "open": _text(value - Decimal("0.05")),
            "high": _text(value + Decimal("0.20")),
            "low": _text(value - Decimal("0.25")),
            "close": _text(value),
            "source": "build12_m15_fixture",
            "source_file_sha256": "a" * 64,
            "source_payload_sha256": "b" * 64,
            "derivation_version": "build12-fixture-v1",
        }
        if mode == "pit":
            row.update(
                {
                    "load_identity": f"build12-m15-pit-{index}",
                    "provenance_class": "pit_observed",
                    "pit_eligible": True,
                    "first_observed_at": (opened + timedelta(minutes=15)).isoformat(),
                }
            )
        else:
            row.update(
                {
                    "research_identity": f"build12-m15-retro-{index}",
                    "provenance_class": "retrospective_history",
                    "pit_eligible": False,
                }
            )
        rows.append(row)
    return rows


def _m1_rows(
    bars: list[tuple[str, str, str, str]],
    *,
    mode: str = "retrospective",
) -> list[dict[str, object]]:
    start = AS_OF - timedelta(minutes=len(bars))
    rows: list[dict[str, object]] = []
    for index, (open_, high, low, close) in enumerate(bars):
        opened = start + timedelta(minutes=index)
        row: dict[str, object] = {
            "symbol": "XAUUSD",
            "timeframe": "M1",
            "open_time_utc": opened,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "source": "build12_m1_fixture",
            "source_file_sha256": "c" * 64,
            "source_payload_sha256": "d" * 64,
            "derivation_version": "build12-fixture-v1",
        }
        if mode == "pit":
            row.update(
                {
                    "load_identity": f"build12-m1-pit-{index}",
                    "provenance_class": "pit_observed",
                    "pit_eligible": True,
                    "first_observed_at": (opened + timedelta(minutes=1)).isoformat(),
                }
            )
        else:
            row.update(
                {
                    "research_identity": f"build12-m1-retro-{index}",
                    "provenance_class": "retrospective_history",
                    "pit_eligible": False,
                }
            )
        rows.append(row)
    return rows


def _baseline_bars(count: int = 30, *, price: Decimal = Decimal("100.40")) -> list[tuple[str, str, str, str]]:
    bars: list[tuple[str, str, str, str]] = []
    for index in range(count):
        offset = Decimal(index % 3) * Decimal("0.01")
        open_ = price + offset
        close = open_ + Decimal("0.01")
        bars.append(
            (
                _text(open_),
                _text(open_ + Decimal("0.08")),
                _text(open_ - Decimal("0.08")),
                _text(close),
            )
        )
    return bars


def _high_reclaim_bars() -> list[tuple[str, str, str, str]]:
    bars = _baseline_bars(25)
    bars.extend(
        [
            ("100.50", "100.70", "100.40", "100.60"),
            ("100.90", "101.50", "100.50", "100.70"),
            ("100.70", "100.95", "100.55", "100.75"),
            ("100.80", "101.05", "100.60", "100.78"),
            ("100.78", "100.92", "100.60", "100.72"),
        ]
    )
    return bars


def _low_reclaim_bars() -> list[tuple[str, str, str, str]]:
    bars = _baseline_bars(25, price=Decimal("99.60"))
    bars.extend(
        [
            ("99.50", "99.70", "99.30", "99.40"),
            ("99.10", "99.50", "98.50", "99.30"),
            ("99.30", "99.45", "99.05", "99.25"),
            ("99.20", "99.40", "98.95", "99.22"),
            ("99.22", "99.40", "99.10", "99.28"),
        ]
    )
    return bars


def _failed_high_reclaim_bars() -> list[tuple[str, str, str, str]]:
    bars = _high_reclaim_bars()
    bars[-1] = ("100.90", "101.35", "100.80", "101.20")
    return bars


def _location_payload(mid: str) -> dict[str, object]:
    def ref(level: str, side: str) -> dict[str, str]:
        return {"level": level, "relative_side": side, "distance_bps": "0"}

    return {
        "state": "known",
        "mid": mid,
        "reference_distances": {
            "prior_day_high": ref("101.00", "below"),
            "prior_day_low": ref("99.00", "above"),
            "asia_overnight_high": ref("101.80", "below"),
            "asia_overnight_low": ref("98.20", "above"),
            "london_opening_15m_high": ref("102.20", "below"),
            "london_opening_15m_low": ref("97.80", "above"),
        },
        "range_positions": {
            "prior_day": "0.500000",
            "asia_overnight": "0.500000",
            "london_opening_15m": "0.500000",
        },
        "round_number_references": {},
    }


def _environment(*, mid: str, volatility: str = "normal") -> dict:
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
                "five_minute_distribution_state": "within_recent_distribution",
                "five_minute_range_state": "normal_range",
                "windows": {
                    "5m": {"direction": "flat", "return_bps": "0"},
                    "15m": {"direction": "flat", "return_bps": "0"},
                    "60m": {"direction": "up", "return_bps": "2"},
                },
            },
            "location": _location_payload(mid),
            "volatility": {
                "state": volatility,
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
        regime={"compound_regime_key": f"range|{volatility}"},
    )


def _price_packet(*, mode: str = "retrospective") -> dict:
    return build_price_expert_math_packet(
        as_of=AS_OF,
        symbol="XAUUSD",
        candle_rows=_m15_rows(mode=mode),
        mode=mode,
    )


def _expert(
    bars: list[tuple[str, str, str, str]],
    *,
    mode: str = "retrospective",
    volatility: str = "normal",
    gc_rows=None,
) -> dict:
    m1 = _m1_rows(bars, mode=mode)
    mid = str(bars[-1][3])
    environment = _environment(mid=mid, volatility=volatility)
    packet = _price_packet(mode=mode)
    location = build_price_location_expert(
        global_environment=environment,
        price_math_packet=packet,
    )
    return build_liquidity_reclaim_expert(
        global_environment=environment,
        price_math_packet=packet,
        price_location_result=location,
        m1_candle_rows=m1,
        retrospective_gc_flow_rows=gc_rows,
    )


def _event(result: dict, reference: str) -> dict:
    return next(item for item in result["events"] if item["reference"] == reference)


def test_build12_high_sweep_reclaim_retest_is_bearish_proxy() -> None:
    result = _expert(_high_reclaim_bars())
    event = _event(result, "prior_day_high")
    assert result["expert_version"] == LIQUIDITY_RECLAIM_EXPERT_VERSION
    assert result["expert_packet"]["gate_id"] == LIQUIDITY_RECLAIM_GATE_ID
    assert verify_expert_gate_packet(result["expert_packet"])
    assert event["proxy_state"] == "reclaim_retest_hold"
    assert event["penetration_depth_usd"] == "0.500000"
    assert Decimal(event["penetration_depth_bps"]) > 0
    assert event["reclaimed"] is True
    assert event["reclaim_speed_bars"] == 0
    assert event["confirmation_closes"] >= 2
    assert event["retest"] is True
    assert event["retest_hold"] is True
    assert event["rejection_geometry"]["rejection_quality"] == "strong"
    calculator = next(
        item for item in result["expert_packet"]["subcalculators"]
        if item["calculator_id"] == "liquidity_prior_day_high"
    )
    assert calculator["vote"] == "bearish"
    assert calculator["observation"]["proxy_not_order_flow"] is True
    assert result["expert_packet"]["conclusion"] == "bearish"


def test_build12_low_sweep_reclaim_is_bullish_proxy() -> None:
    result = _expert(_low_reclaim_bars())
    event = _event(result, "prior_day_low")
    assert event["proxy_state"] in {"reclaim_confirmed", "reclaim_retest_hold"}
    calculator = next(
        item for item in result["expert_packet"]["subcalculators"]
        if item["calculator_id"] == "liquidity_prior_day_low"
    )
    assert calculator["vote"] == "bullish"
    assert result["expert_packet"]["conclusion"] == "bullish"


def test_build12_no_sweep_stays_neutral() -> None:
    result = _expert(_baseline_bars())
    event = _event(result, "prior_day_high")
    assert event["proxy_state"] == "no_sweep"
    calculator = next(
        item for item in result["expert_packet"]["subcalculators"]
        if item["calculator_id"] == "liquidity_prior_day_high"
    )
    assert calculator["vote"] == "neutral"
    assert result["expert_packet"]["conclusion"] == "neutral"


def test_build12_failed_reclaim_is_not_rewarded_directionally() -> None:
    result = _expert(_failed_high_reclaim_bars())
    event = _event(result, "prior_day_high")
    assert event["proxy_state"] == "reclaim_failed"
    assert event["latest_failed_back_through"] is True
    calculator = next(
        item for item in result["expert_packet"]["subcalculators"]
        if item["calculator_id"] == "liquidity_prior_day_high"
    )
    assert calculator["vote"] == "neutral"


def test_build12_competing_level_distance_is_explicit() -> None:
    result = _expert(_high_reclaim_bars())
    event = _event(result, "prior_day_high")
    competing = event["competing_level"]
    assert competing["nearest_competing_reference"] is not None
    assert Decimal(competing["distance_bps"]) > 0


def test_build12_session_and_volatility_context_condition_trust() -> None:
    normal = _expert(_high_reclaim_bars(), volatility="normal")
    elevated = _expert(_high_reclaim_bars(), volatility="elevated")
    normal_scope = next(
        scope for scope in normal["trust_scopes"]
        if scope["scope_type"] == "mini_reduced_session_liquidity"
    )
    elevated_scope = next(
        scope for scope in elevated["trust_scopes"]
        if scope["scope_type"] == "mini_reduced_session_liquidity"
    )
    assert normal_scope["scope_key"] != elevated_scope["scope_key"]


def test_build12_ohlc_proxy_language_never_claims_real_order_flow() -> None:
    result = _expert(_high_reclaim_bars())
    policy = result["proxy_policy"]
    assert policy["ohlc_sweep_reclaim_is_proxy"] is True
    assert policy["genuine_order_flow_claimed"] is False
    assert policy["hidden_order_flow_claimed"] is False

    rendered = " ".join(
        [part["text"] for part in result["expert_packet"]["explanation_parts"]]
        + [item["explanation"] for item in result["expert_packet"]["subcalculators"]]
    ).lower()
    assert "not genuine order flow" in rendered
    assert "order flow confirms" not in rendered
    assert "institutional orders" not in rendered
    assert "smart money orders" not in rendered


def test_build12_retrospective_genuine_gc_flow_is_stored_separately() -> None:
    gc = [
        {
            "observed_at_utc": "2026-09-20T14:30:00+00:00",
            "source": "retrospective_gc_research_fixture",
            "delta": "125",
        }
    ]
    result = _expert(_high_reclaim_bars(), gc_rows=gc)
    stored = result["retrospective_gc_flow"]
    assert stored["state"] == "present"
    assert stored["provenance_class"] == "retrospective_genuine_gc_flow"
    assert stored["row_count"] == 1
    assert stored["used_in_ohlc_proxy_calculation"] is False
    assert stored["used_in_expert_conclusion"] is False
    assert stored["separate_from_ohlc_proxy"] is True


def test_build12_gapped_m1_fails_closed() -> None:
    bars = _high_reclaim_bars()
    m1 = _m1_rows(bars)
    del m1[-10]
    environment = _environment(mid=bars[-1][3])
    packet = _price_packet()
    location = build_price_location_expert(
        global_environment=environment,
        price_math_packet=packet,
    )
    result = build_liquidity_reclaim_expert(
        global_environment=environment,
        price_math_packet=packet,
        price_location_result=location,
        m1_candle_rows=m1,
    )
    assert result["continuity"]["contiguous"] is False
    assert result["expert_packet"]["conclusion"] == "unknown"
    assert result["expert_packet"]["gate_scoreable"] is False


def test_build12_pit_mode_uses_completed_m1_and_no_future_values() -> None:
    result = _expert(_high_reclaim_bars(), mode="pit")
    assert result["future_values_used"] is False
    assert result["expert_packet"]["no_hindsight_attestation"]["future_values_used"] is False
    for evidence in result["expert_packet"]["evidence_inputs"]:
        provenance = evidence["provenance"]
        assert provenance["future_values_used"] is False


def test_build12_chronological_freeze_ignores_later_m1_rows() -> None:
    bars = _high_reclaim_bars()
    prefix = _m1_rows(bars, mode="pit")
    later = prefix + _m1_rows(
        [
            ("100.70", "102.00", "100.60", "101.80"),
            ("101.80", "102.20", "101.60", "102.00"),
        ],
        mode="pit",
    )
    # Give the later rows timestamps after the frozen AS_OF.
    later[-2]["open_time_utc"] = AS_OF
    later[-2]["first_observed_at"] = (AS_OF + timedelta(minutes=1)).isoformat()
    later[-1]["open_time_utc"] = AS_OF + timedelta(minutes=1)
    later[-1]["first_observed_at"] = (AS_OF + timedelta(minutes=2)).isoformat()

    environment = _environment(mid=bars[-1][3])
    packet = _price_packet(mode="pit")
    location = build_price_location_expert(
        global_environment=environment,
        price_math_packet=packet,
    )
    first = build_liquidity_reclaim_expert(
        global_environment=environment,
        price_math_packet=packet,
        price_location_result=location,
        m1_candle_rows=prefix,
    )
    second = build_liquidity_reclaim_expert(
        global_environment=environment,
        price_math_packet=packet,
        price_location_result=location,
        m1_candle_rows=later,
    )
    assert first["expert_packet"]["packet_digest"] == second["expert_packet"]["packet_digest"]
    assert first["events"] == second["events"]


def test_build12_rejects_mismatched_as_of() -> None:
    bars = _high_reclaim_bars()
    packet = _price_packet()
    environment = _environment(mid=bars[-1][3])
    location = build_price_location_expert(
        global_environment=environment,
        price_math_packet=packet,
    )
    bad_environment = build_cycle_environment(
        as_of_utc=AS_OF + timedelta(minutes=15),
        target_window_start_utc=AS_OF + timedelta(minutes=30),
        session_code="london",
        observed_state="neutral",
        gold_state={
            "market_structure": {"timeframes": {}},
            "move_observation": {"windows": {}},
            "location": _location_payload(bars[-1][3]),
            "volatility": {"state": "normal"},
        },
        semantic_context={
            "data_quality": {
                "quote_state": "known",
                "quote_freshness": "fresh",
                "spread_state": "unknown",
            },
            "cross_market": {"series": {}},
        },
        regime={"compound_regime_key": "range|normal"},
    )
    with pytest.raises(ValueError, match="same as-of"):
        build_liquidity_reclaim_expert(
            global_environment=bad_environment,
            price_math_packet=packet,
            price_location_result=location,
            m1_candle_rows=_m1_rows(bars),
        )
