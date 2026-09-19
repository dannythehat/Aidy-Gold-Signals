from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.gold_state_engine import (
    GOLD_STATE_ENGINE_VERSION,
    PROVIDER_GOLD_STATE_VERSION,
    build_gold_state_engine,
    verify_gold_state_engine,
)


AS_OF = datetime(2026, 9, 18, 16, 0, tzinfo=UTC)
_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400}


def _row(
    *,
    timeframe: str,
    opened: datetime,
    price: Decimal,
    close_delta: Decimal = Decimal("0.2"),
) -> dict[str, object]:
    seconds = _SECONDS[timeframe]
    return {
        "load_identity": f"{timeframe}:{opened.isoformat()}",
        "evidence_id": f"e:{timeframe}:{opened.isoformat()}",
        "archive_key": f"gold/{timeframe}/{int(opened.timestamp())}.json",
        "payload_digest": "c" * 64,
        "symbol": "XAUUSD",
        "timeframe": timeframe,
        "open_time_utc": opened,
        "first_observed_at": opened + timedelta(seconds=seconds),
        "open": str(price),
        "high": str(price + Decimal("0.6")),
        "low": str(price - Decimal("0.4")),
        "close": str(price + close_delta),
        "source": "twelve_data",
    }


def _candles(*, shock: bool = False) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    # 130 completed M1 bars give the displacement engine 24 prior non-overlapping
    # five-minute baseline blocks plus the current five-minute block.
    start = AS_OF - timedelta(minutes=130)
    price = Decimal("4380")
    for index in range(130):
        opened = start + timedelta(minutes=index)
        delta = Decimal("0.05")
        if shock and index >= 125:
            delta = Decimal("4")
        rows.append(_row(timeframe="M1", opened=opened, price=price, close_delta=delta))
        price += delta

    for timeframe, bars in (("M5", 8), ("M15", 8), ("H1", 8), ("H4", 8)):
        duration = timedelta(seconds=_SECONDS[timeframe])
        start_tf = AS_OF - duration * bars
        base = Decimal("4300")
        for index in range(bars):
            rows.append(
                _row(
                    timeframe=timeframe,
                    opened=start_tf + duration * index,
                    price=base + Decimal(index),
                    close_delta=Decimal("0.5"),
                )
            )
    return rows


def _price_structure() -> dict[str, object]:
    return {
        "mode": "pit",
        "pit_eligible": True,
        "future_values_used": False,
        "structure_semantic_digest": "s" * 64,
        "structure": {
            "prior_periods": {
                "prior_day": {
                    "state": "known",
                    "high": "4390",
                    "low": "4350",
                    "close": "4370",
                }
            },
            "asia_overnight_range": {
                "state": "known",
                "high": "4385",
                "low": "4360",
            },
            "opening_ranges": {"london": {"15m": {"state": "known", "high": "4388", "low": "4372"}}},
            "session_extremes": {
                "asia": {"state": "complete", "high": "4385", "low": "4360"},
                "london": {"state": "observed_so_far", "high": "4392", "low": "4370"},
                "new_york": {"state": "observed_so_far", "high": "4395", "low": "4380"},
            },
            "prior_day_breakout": {
                "state": "upside_failed",
                "prior_day_high": "4390",
                "prior_day_low": "4350",
            },
            "swing_extreme_penetration_with_reversion": {
                "high_side": {
                    "state": "known",
                    "penetrated": True,
                    "reverted": True,
                    "swing_price": "4391",
                    "max_penetration_bps": "3.2",
                },
                "low_side": {
                    "state": "known",
                    "penetrated": False,
                    "reverted": False,
                    "swing_price": "4362",
                    "max_penetration_bps": "0",
                },
            },
            "wick_footprint": {"state": "known", "close_location": "0.4"},
        },
    }


def _volatility(*, jump_state: str = "continuous_dominant") -> dict[str, object]:
    return {
        "mode": "pit",
        "state": "partial",
        "decision_input_allowed": True,
        "retrospective_history_included": False,
        "volatility_state_digest": "v" * 64,
        "realized_volatility": {"state": "known", "annualized_percent": {"5": "20"}},
        "jump_continuous": {"state": jump_state},
        "vol_of_vol": {"state": "unknown_insufficient_history"},
        "gvz": {"state": "unknown"},
        "iv_minus_rv": {"state": "unknown_missing_iv_or_comparable_rv"},
    }


def _context(*, event_known: bool = False) -> dict[str, object]:
    event = (
        {
            "evidence_state": "known",
            "timing_state": "inside_high_impact_window",
            "events_in_window": [{"event_type": "cpi", "scheduled_at": AS_OF.isoformat()}],
            "next_scheduled_event": None,
        }
        if event_known
        else {"evidence_state": "unknown", "timing_state": "unknown"}
    )
    return {
        "gold": {"quote_context": {"mid": "4387"}},
        "event_risk": event,
    }


def _build(*, shock: bool = False, event_known: bool = False) -> dict:
    return build_gold_state_engine(
        as_of=AS_OF,
        symbol="XAUUSD",
        candle_rows=_candles(shock=shock),
        semantic_context=_context(event_known=event_known),
        price_structure_packet=_price_structure(),
        volatility_state=_volatility(),
    )


def test_gold_state_is_research_only_and_digest_verified() -> None:
    packet = _build()
    assert packet["gold_state_engine_version"] == GOLD_STATE_ENGINE_VERSION
    assert packet["contract_version"] == PROVIDER_GOLD_STATE_VERSION
    assert packet["research_only"] is True
    assert packet["descriptive_context_only"] is True
    assert packet["predictive_edge_claimed"] is False
    assert packet["live_money_execution_allowed"] is False
    assert packet["future_values_used"] is False
    assert verify_gold_state_engine(packet)


def test_multi_timeframe_close_path_is_explicit_not_predictive() -> None:
    packet = _build()
    structure = packet["market_structure"]
    assert structure["decision_input_allowed"] is True
    assert structure["predictive_edge_claimed"] is False
    assert set(structure["timeframes"]) == {"M1", "M5", "M15", "H1", "H4"}
    assert structure["timeframes"]["H1"]["net_close_direction"] == "up"
    assert structure["timeframes"]["H1"]["sample_bars"] == 8


def test_location_maps_current_mid_to_real_observed_reference_levels() -> None:
    location = _build()["location"]
    assert location["state"] == "known"
    assert location["mid"] == "4387"
    assert location["reference_distances"]["prior_day_high"]["relative_side"] == "below"
    assert location["reference_distances"]["london_high"]["source_path"].endswith(
        "session_extremes.london.high"
    )
    assert Decimal(location["range_positions"]["prior_day"]) > 0
    assert location["round_number_references"]["nearest_10_usd"]["descriptive_only"] is True
    assert location["round_numbers_predictive_edge_claimed"] is False


def test_liquidity_sweep_language_is_explicitly_a_proxy_not_hidden_order_flow() -> None:
    liquidity = _build()["liquidity"]
    kinds = {item["kind"] for item in liquidity["sweep_reclaim_proxies"]}
    assert "prior_day_high_penetration_reclaim_proxy" in kinds
    assert "confirmed_m15_swing_penetration_reclaim_proxy" in kinds
    assert liquidity["proxy_not_order_flow"] is True
    assert liquidity["hidden_order_flow_claimed"] is False


def test_large_recent_move_is_detected_without_claiming_a_cause() -> None:
    move = _build(shock=True)["move_observation"]
    assert move["five_minute_distribution_state"] == "extreme_recent_displacement"
    assert Decimal(move["five_minute_abs_return_percentile"]) >= Decimal("0.95")
    assert move["causal_attribution_proven"] is False


def test_scheduled_event_is_context_not_causal_attribution() -> None:
    move = _build(shock=True, event_known=True)["move_observation"]
    event_context = next(
        item for item in move["mechanism_context"]
        if item["mechanism"] == "scheduled_event_timing_context"
    )
    assert event_context["state"] == "inside_high_impact_window"
    assert event_context["causal_claim"] is False
    assert move["causal_attribution_proven"] is False


def test_missing_mid_stays_unknown() -> None:
    packet = build_gold_state_engine(
        as_of=AS_OF,
        symbol="XAUUSD",
        candle_rows=_candles(),
        semantic_context={"gold": {"quote_context": {}}, "event_risk": {"evidence_state": "unknown"}},
        price_structure_packet=_price_structure(),
        volatility_state=_volatility(),
    )
    assert packet["location"]["state"] == "unknown"
    assert "current_mid" in packet["unknowns"]


def test_forming_m1_bar_at_as_of_cannot_leak_into_state() -> None:
    rows = _candles()
    rows.append(
        _row(
            timeframe="M1",
            opened=AS_OF,
            price=Decimal("9999"),
            close_delta=Decimal("500"),
        )
    )
    packet = build_gold_state_engine(
        as_of=AS_OF,
        symbol="XAUUSD",
        candle_rows=rows,
        semantic_context=_context(),
        price_structure_packet=_price_structure(),
        volatility_state=_volatility(),
    )
    assert Decimal(packet["market_structure"]["timeframes"]["M1"]["latest_close"]) < Decimal("5000")


def test_retrospective_or_future_tainted_inputs_fail_closed() -> None:
    price = _price_structure()
    price["mode"] = "retrospective"
    with pytest.raises(ValueError, match="requires PIT price structure"):
        build_gold_state_engine(
            as_of=AS_OF,
            symbol="XAUUSD",
            candle_rows=_candles(),
            semantic_context=_context(),
            price_structure_packet=price,
            volatility_state=_volatility(),
        )

    price = _price_structure()
    price["future_values_used"] = True
    with pytest.raises(ValueError, match="future-valued"):
        build_gold_state_engine(
            as_of=AS_OF,
            symbol="XAUUSD",
            candle_rows=_candles(),
            semantic_context=_context(),
            price_structure_packet=price,
            volatility_state=_volatility(),
        )


def test_tampering_breaks_gold_state_digest() -> None:
    packet = _build()
    packet["location"]["mid"] = "9999"
    assert not verify_gold_state_engine(packet)
