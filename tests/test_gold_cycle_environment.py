from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aidy.gold_cycle_environment import (
    GOLD_CYCLE_ENVIRONMENT_VERSION,
    build_cycle_environment,
    verify_cycle_environment,
)

AS_OF = datetime(2026, 9, 21, 7, 25, tzinfo=UTC)
TARGET = datetime(2026, 9, 21, 7, 30, tzinfo=UTC)


def _gold_state(*, reference_distance: str = "2.4") -> dict:
    return {
        "unknowns": ["gvz"],
        "market_structure": {
            "timeframes": {
                "M5": {
                    "state": "known",
                    "net_close_direction": "down",
                    "directional_persistence_ratio": "0.71",
                    "latest_close_range_position": "0.22",
                },
                "M15": {
                    "state": "known",
                    "net_close_direction": "down",
                    "directional_persistence_ratio": "0.57",
                    "latest_close_range_position": "0.31",
                },
                "H1": {
                    "state": "known",
                    "net_close_direction": "down",
                    "directional_persistence_ratio": "0.70",
                    "latest_close_range_position": "0.38",
                },
                "H4": {
                    "state": "known",
                    "net_close_direction": "up",
                    "directional_persistence_ratio": "0.80",
                    "latest_close_range_position": "0.73",
                },
                "D1": {
                    "state": "known",
                    "net_close_direction": "up",
                    "directional_persistence_ratio": "0.66",
                    "latest_close_range_position": "0.62",
                },
            }
        },
        "move_observation": {
            "five_minute_distribution_state": "elevated_recent_displacement",
            "five_minute_range_state": "range_expansion",
            "five_minute_abs_return_percentile": "0.91",
            "five_minute_range_percentile": "0.88",
            "windows": {
                "5m": {"direction": "down", "return_bps": "-3.2", "range_bps": "5.1"},
                "15m": {"direction": "down", "return_bps": "-7.8", "range_bps": "10.4"},
                "60m": {"direction": "up", "return_bps": "4.0", "range_bps": "19.2"},
            },
        },
        "location": {
            "mid": "4387.2",
            "reference_distances": {
                "asia_overnight_low": {
                    "relative_side": "above",
                    "distance_bps": reference_distance,
                    "level": "4386.15",
                },
                "prior_day_high": {
                    "relative_side": "below",
                    "distance_bps": "-18.0",
                    "level": "4395.1",
                },
            },
            "range_positions": {
                "prior_day": "0.42",
                "asia_overnight": "0.18",
                "london": "0.29",
                "london_opening_15m": "0.33",
            },
            "round_number_references": {
                "nearest_10_usd": {"distance_bps": "-6.3"},
                "nearest_50_usd": {"distance_bps": "-28.0"},
            },
        },
        "liquidity": {
            "sweep_reclaim_proxies": [
                {"kind": "confirmed_m15_swing_penetration_reclaim_proxy", "side": "low"}
            ],
            "prior_day_breakout": {"state": "downside_failed"},
        },
        "volatility": {
            "state": "partial",
            "realized_volatility": {"state": "known"},
            "jump_continuous": {"state": "continuous_dominant"},
            "vol_of_vol": {"state": "known"},
            "gvz": {"state": "unknown"},
            "iv_minus_rv": {"state": "unknown"},
        },
        "scheduled_event_risk": {
            "state": "known",
            "timing_state": "clear_current_window",
            "events_in_window": [],
            "next_scheduled_event": {
                "event_type": "us_cpi",
                "scheduled_at": (AS_OF + timedelta(minutes=65)).isoformat(),
            },
        },
    }


def _build(*, distance: str = "2.4") -> dict:
    return build_cycle_environment(
        as_of_utc=AS_OF,
        target_window_start_utc=TARGET,
        session_code="london",
        observed_state="bearish",
        gold_state=_gold_state(reference_distance=distance),
        semantic_context={
            "cross_market": {
                "series": {
                    "DXY": {"state": "known"},
                    "REAL10Y": {"state": "known"},
                    "SPX": {"state": "unknown"},
                }
            }
        },
        regime={"compound_regime_key": "trend|range_expansion"},
    )


def test_cycle_environment_captures_real_start_state() -> None:
    environment = _build()
    facts = environment["exact_facts"]
    dimensions = environment["learning_dimensions"]

    assert environment["environment_version"] == GOLD_CYCLE_ENVIRONMENT_VERSION
    assert verify_cycle_environment(environment)
    assert facts["decision_lead_seconds"] == 300
    # 07:25 UTC is 08:25 London local time during UK DST.
    assert facts["session"]["active_session_minutes_since_open"] == 25
    assert dimensions["session_phase"] == "opening_15_30m"
    assert dimensions["nearest_reference"] == "asia_overnight_low"
    assert dimensions["nearest_reference_side"] == "above"
    assert dimensions["nearest_reference_distance_band"] == "near_1_3bp"
    assert dimensions["prior_day_zone"] == "lower_middle"
    assert dimensions["asia_overnight_zone"] == "lower_quartile"
    assert dimensions["active_session_zone"] == "lower_middle"
    assert dimensions["liquidity_signature"] == "low_side_reclaim"
    assert dimensions["liquidity_intensity"] == "low"
    assert dimensions["prior_day_breakout_state"] == "downside_failed"
    assert dimensions["event_proximity"] == "within_120m"
    assert dimensions["cross_market_known_count"] == 2
    assert dimensions["cross_market_coverage"] == "low"
    assert environment["future_values_used"] is False
    assert environment["live_money_execution_allowed"] is False


def test_environment_uses_repeatable_buckets_not_exact_price_identity() -> None:
    left = _build(distance="2.1")
    right = _build(distance="2.9")

    assert left["exact_facts"]["location"]["nearest_reference"]["distance_bps"] != (
        right["exact_facts"]["location"]["nearest_reference"]["distance_bps"]
    )
    assert left["learning_dimensions"] == right["learning_dimensions"]
    assert left["environment_key"] == right["environment_key"]


def test_environment_key_changes_when_market_condition_changes() -> None:
    near = _build(distance="2.9")
    farther = _build(distance="9.0")

    assert near["learning_dimensions"]["nearest_reference_distance_band"] == "near_1_3bp"
    assert farther["learning_dimensions"]["nearest_reference_distance_band"] == (
        "moderate_8_20bp"
    )
    assert near["environment_key"] != farther["environment_key"]


def test_environment_has_liquidity_location_and_session_scopes() -> None:
    environment = _build()
    scopes = {row["scope_type"] for row in environment["scopes"]}
    assert {
        "global",
        "session",
        "session_phase",
        "session_state",
        "higher_timeframe",
        "liquidity_location",
        "session_liquidity",
        "location_structure",
        "session_move_regime",
        "volatility_move_regime",
        "session_state_event",
        "event_regime",
        "full_environment",
    }.issubset(scopes)


def test_environment_rejects_decision_after_target_window_start() -> None:
    with pytest.raises(ValueError, match="frozen before"):
        build_cycle_environment(
            as_of_utc=TARGET,
            target_window_start_utc=TARGET,
            session_code="london",
            observed_state="neutral",
            gold_state=_gold_state(),
            semantic_context={},
            regime={},
        )
