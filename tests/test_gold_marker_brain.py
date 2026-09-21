from __future__ import annotations

from decimal import Decimal

from aidy.gold_marker_brain import (
    GOLD_MARKER_BRAIN_VERSION,
    apply_learning_to_reasons,
    build_environment_fingerprint,
    learning_multiplier,
    marker_id,
    score_marker_vote,
    select_score_profile,
    toolbox_cycle_coverage,
)


def _gold_state() -> dict:
    return {
        "market_structure": {
            "timeframes": {
                "H1": {"net_close_direction": "down"},
                "H4": {"net_close_direction": "up"},
                "D1": {"net_close_direction": "up"},
            }
        },
        "move_observation": {
            "five_minute_distribution_state": "extreme_recent_displacement",
            "five_minute_range_state": "range_expansion",
            "windows": {
                "5m": {"direction": "down"},
                "15m": {"direction": "down"},
                "60m": {"direction": "up"},
            },
        },
        "volatility": {
            "state": "partial",
            "jump_continuous": {"state": "continuous_dominant"},
            "realized_volatility": {"state": "known"},
            "gvz": {"state": "unknown"},
        },
        "liquidity": {
            "sweep_reclaim_proxies": [{"side": "low"}],
            "prior_day_breakout": {"state": "downside_failed"},
        },
        "scheduled_event_risk": {
            "state": "known",
            "timing_state": "outside_near_event_window",
        },
    }


def test_environment_fingerprint_is_contextual_and_multi_scope() -> None:
    env = build_environment_fingerprint(
        as_of_utc="2026-09-21T07:25:00+00:00",
        target_window_start_utc="2026-09-21T07:30:00+00:00",
        session_code="london",
        observed_state="bearish",
        gold_state=_gold_state(),
        semantic_context={},
        regime={"compound_regime_key": "trend|normal"},
    )
    assert env["environment_version"] == "aidy_gold_cycle_environment_v2"
    assert env["learning_dimensions"]["session"] == "london"
    assert env["learning_dimensions"]["observed_15m_state"] == "bearish"
    assert env["learning_dimensions"]["h4_direction"] == "bullish"
    assert env["learning_dimensions"]["five_minute_range_state"] == "range_expansion"
    scope_types = {item["scope_type"] for item in env["scopes"]}
    assert {
        "global",
        "session",
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
    }.issubset(scope_types)


def test_impact_scoring_rewards_and_penalizes_large_moves_more() -> None:
    assert score_marker_vote(
        vote="bullish",
        realised_direction="bullish",
        realised_return_bps=Decimal("6.8"),
    ) == (2, 1)
    assert score_marker_vote(
        vote="bearish",
        realised_direction="bullish",
        realised_return_bps=Decimal("6.8"),
    ) == (-2, 0)
    assert score_marker_vote(
        vote="bullish",
        realised_direction="bullish",
        realised_return_bps=Decimal("3.1"),
    ) == (1, 1)
    assert score_marker_vote(
        vote="bearish",
        realised_direction="bullish",
        realised_return_bps=Decimal("3.1"),
    ) == (-1, 0)


def test_learning_multiplier_is_bounded_and_sample_aware() -> None:
    assert learning_multiplier(sample_n=0, net_score=0) == Decimal("1")
    assert learning_multiplier(sample_n=2, net_score=4) < Decimal("1.2")
    assert learning_multiplier(sample_n=20, net_score=40) == Decimal("1.5")
    assert learning_multiplier(sample_n=20, net_score=-40) == Decimal("0.5")


def test_score_profile_prefers_specific_only_after_minimum_sample() -> None:
    scopes = [
        {"scope_type": "global", "scope_key": "global_x"},
        {"scope_type": "session", "scope_key": "session_x"},
        {"scope_type": "full_environment", "scope_key": "full_x"},
    ]
    profile = select_score_profile(
        score_rows=[
            {
                "scope_key": "global_x",
                "scope_type": "global",
                "sample_n": 10,
                "correct_n": 7,
                "incorrect_n": 3,
                "net_score": 4,
                "accuracy": "0.700000",
            },
            {
                "scope_key": "full_x",
                "scope_type": "full_environment",
                "sample_n": 3,
                "correct_n": 3,
                "incorrect_n": 0,
                "net_score": 6,
                "accuracy": "1.000000",
            },
        ],
        scopes=scopes,
    )
    assert profile["selected_scope_type"] == "global"
    assert profile["sample_n"] == 10


def test_learning_adjusts_each_marker_without_losing_base_weight() -> None:
    mid = marker_id(surface="gold_h4_structure", source_path="gold_state.h4")
    adjusted = apply_learning_to_reasons(
        reasons=[
            {
                "surface": "gold_h4_structure",
                "source_path": "gold_state.h4",
                "vote": "bullish",
                "weight": 1,
            }
        ],
        profiles={
            mid: {
                "selected_scope_type": "session",
                "sample_n": 20,
                "net_score": 20,
                "accuracy": "0.750000",
                "learned_multiplier": "1.250000",
            }
        },
    )
    assert adjusted[0]["base_weight"] == "1.000000"
    assert adjusted[0]["learned_multiplier"] == "1.250000"
    assert adjusted[0]["effective_weight"] == "1.250000"
    assert adjusted[0]["selected_score_scope"] == "session"


def test_toolbox_coverage_records_every_capability_even_when_not_scoreable() -> None:
    reasons = [
        {
            "surface": "gold_h4_structure",
            "source_path": "gold_state.h4",
            "vote": "bullish",
            "weight": 1,
        }
    ]
    manifest = {
        "capabilities": [
            {"name": "gold_h4_structure", "category": "price", "status": "live_here"},
            {"name": "realized_volatility", "category": "volatility", "status": "live_here"},
            {
                "name": "breaking_news_event_search",
                "category": "news",
                "status": "research_exists_not_live_connected",
            },
        ]
    }
    coverage = toolbox_cycle_coverage(
        toolbox_manifest=manifest,
        marker_reasons=reasons,
    )
    assert len(coverage) == 3
    by_name = {item["name"]: item for item in coverage}
    assert by_name["gold_h4_structure"]["scoreable_this_cycle"] is True
    assert by_name["realized_volatility"]["scoreable_this_cycle"] is False
    assert by_name["breaking_news_event_search"]["role_this_cycle"] == (
        "known_but_not_live_connected"
    )


def test_brain_version_is_explicit() -> None:
    assert GOLD_MARKER_BRAIN_VERSION == "aidy_gold_contextual_marker_brain_v2"
