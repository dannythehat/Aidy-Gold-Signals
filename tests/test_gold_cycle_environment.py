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
            "data_quality": {
                "quote_state": "known",
                "quote_freshness": "fresh",
                "spread_state": "unknown",
                "flags": ["spread_unknown"],
            },
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
    assert dimensions["utc_clock_bucket_15m"] == "07:15"
    assert dimensions["week_transition_state"] == "post_weekend_day"
    assert dimensions["market_calendar_state"] == "weekday_session"
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
    assert dimensions["data_quality_state"] == "fresh"
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
        "global_core",
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
    }.issubset(scopes)
    assert "full_environment" not in scopes
    assert environment["environment_contract"]["monolithic_full_environment_key_used"] is False


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



def test_build1_environment_is_deterministic_for_identical_pit_inputs() -> None:
    first = _build()
    second = _build()
    assert first == second
    assert first["environment_digest"] == second["environment_digest"]
    assert first["environment_key"] == second["environment_key"]


@pytest.mark.parametrize(
    ("distance", "expected"),
    [
        ("1.0", "at_level_0_1bp"),
        ("1.01", "near_1_3bp"),
        ("3.0", "near_1_3bp"),
        ("3.01", "close_3_8bp"),
        ("8.0", "close_3_8bp"),
        ("8.01", "moderate_8_20bp"),
        ("20.0", "moderate_8_20bp"),
        ("20.01", "far_gt20bp"),
    ],
)
def test_build1_distance_bucket_edges_are_frozen(distance: str, expected: str) -> None:
    environment = _build(distance=distance)
    assert environment["learning_dimensions"]["nearest_reference_distance_band"] == expected


def test_build1_rejects_hindsight_fields_before_environment_freeze() -> None:
    state = _gold_state()
    state["outcome"] = "bullish"
    with pytest.raises(ValueError, match="hindsight field"):
        build_cycle_environment(
            as_of_utc=AS_OF,
            target_window_start_utc=TARGET,
            session_code="london",
            observed_state="bearish",
            gold_state=state,
            semantic_context={},
            regime={},
        )


def test_build1_rejects_explicit_future_values_flag() -> None:
    state = _gold_state()
    state["future_values_used"] = True
    with pytest.raises(ValueError, match="future-valued evidence"):
        build_cycle_environment(
            as_of_utc=AS_OF,
            target_window_start_utc=TARGET,
            session_code="london",
            observed_state="bearish",
            gold_state=state,
            semantic_context={},
            regime={},
        )


def test_build1_missing_quality_is_explicit_unknown() -> None:
    environment = build_cycle_environment(
        as_of_utc=AS_OF,
        target_window_start_utc=TARGET,
        session_code="london",
        observed_state="bearish",
        gold_state=_gold_state(),
        semantic_context={"cross_market": {"series": {}}},
        regime={},
    )
    assert environment["learning_dimensions"]["data_quality_state"] == "unknown"
    assert environment["exact_facts"]["data_quality"]["source_present"] is False


def test_build1_stale_quote_is_explicit_stale_quality() -> None:
    environment = build_cycle_environment(
        as_of_utc=AS_OF,
        target_window_start_utc=TARGET,
        session_code="london",
        observed_state="bearish",
        gold_state=_gold_state(),
        semantic_context={
            "data_quality": {
                "quote_state": "known",
                "quote_freshness": "stale",
                "spread_state": "known",
            }
        },
        regime={},
    )
    assert environment["learning_dimensions"]["data_quality_state"] == "stale"
    assert environment["exact_facts"]["data_quality"]["quote_freshness"] == "stale"


def test_build1_weekend_market_state_is_not_mislabelled_as_missing() -> None:
    saturday = datetime(2026, 9, 26, 10, 5, tzinfo=UTC)
    environment = build_cycle_environment(
        as_of_utc=saturday,
        target_window_start_utc=saturday + timedelta(minutes=5),
        session_code="weekend",
        observed_state="neutral",
        gold_state=_gold_state(),
        semantic_context={},
        regime={},
    )
    dimensions = environment["learning_dimensions"]
    assert dimensions["market_calendar_state"] == "calendar_closed_weekend"
    assert dimensions["week_transition_state"] == "calendar_weekend"
    assert dimensions["session_phase"] == "unknown"


@pytest.mark.parametrize(
    ("as_of", "expected_minutes"),
    [
        (datetime(2026, 3, 27, 8, 25, tzinfo=UTC), 25),
        (datetime(2026, 3, 30, 7, 25, tzinfo=UTC), 25),
    ],
)
def test_build1_london_session_phase_is_dst_safe(
    as_of: datetime,
    expected_minutes: int,
) -> None:
    environment = build_cycle_environment(
        as_of_utc=as_of,
        target_window_start_utc=as_of + timedelta(minutes=5),
        session_code="london",
        observed_state="neutral",
        gold_state=_gold_state(),
        semantic_context={},
        regime={},
    )
    session = environment["exact_facts"]["session"]
    assert session["active_session_minutes_since_open"] == expected_minutes
    assert session["active_session_phase"] == "opening_15_30m"


def test_build1_preserves_exact_facts_but_reuses_repeatable_environment() -> None:
    left = _build(distance="2.10")
    right = _build(distance="2.90")
    assert (
        left["exact_facts"]["location"]["nearest_reference"]["distance_bps"]
        != right["exact_facts"]["location"]["nearest_reference"]["distance_bps"]
    )
    assert left["environment_key"] == right["environment_key"]
    assert left["environment_contract"]["factor_keys"] == right["environment_contract"]["factor_keys"]


def test_build1_contract_is_factorised_not_one_giant_environment_key() -> None:
    environment = _build()
    contract = environment["environment_contract"]
    assert contract["monolithic_full_environment_key_used"] is False
    assert contract["mini_environment_contract"]["state"] == "deferred_to_expert_gate_builds"
    assert len(contract["factor_keys"]) >= 8
    assert environment["environment_key"].startswith("envcore_")
    assert "full_environment" not in {row["scope_type"] for row in environment["scopes"]}


def test_build1_every_registered_dimension_is_present_or_unknown() -> None:
    environment = build_cycle_environment(
        as_of_utc=AS_OF,
        target_window_start_utc=TARGET,
        session_code="london",
        observed_state="unknown",
        gold_state={},
        semantic_context={},
        regime={},
    )
    dimensions = environment["learning_dimensions"]
    # The registry count is authoritative; all entries are materialised even when evidence is absent.
    assert len(dimensions) == environment["environment_contract"]["dimension_count"]
    assert all(value is not None and value != "" for value in dimensions.values())
    assert dimensions["m5_direction"] == "unknown"
    assert dimensions["nearest_reference"] == "unknown"
    assert dimensions["data_quality_state"] in {"unknown", "partial"}


def test_build1_environment_digest_detects_mutation() -> None:
    environment = _build()
    assert verify_cycle_environment(environment)
    environment["learning_dimensions"]["session"] = "asia"
    assert verify_cycle_environment(environment) is False
