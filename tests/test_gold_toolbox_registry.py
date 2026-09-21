from __future__ import annotations

from aidy.gold_toolbox_registry import (
    GOLD_TOOLBOX_MANIFEST_VERSION,
    build_gold_toolbox_manifest,
    verify_gold_toolbox_manifest,
)


def _gold_state() -> dict:
    return {
        "move_observation": {"state": "known"},
        "market_structure": {
            "timeframes": {
                "M1": {"state": "known"},
                "M5": {"state": "known"},
                "M15": {"state": "known"},
                "H1": {"state": "known"},
                "H4": {"state": "known"},
            }
        },
        "scheduled_event_risk": {
            "state": "unknown",
            "decision_input_allowed": False,
        },
        "volatility": {
            "decision_input_allowed": True,
            "gvz": {"state": "unknown"},
        },
    }


def test_manifest_lists_the_full_known_gold_arsenal_without_false_live_claims() -> None:
    manifest = build_gold_toolbox_manifest(
        gold_state=_gold_state(),
        semantic_context={"cross_market": {"series": {}}},
        live_source_availability={
            "rates_macro_vintages": "unknown_no_operational_day28_vintage_feed",
            "tiered_macro_events": "unknown_no_operational_day29_schedule_feed",
        },
    )

    assert manifest["contract_version"] == GOLD_TOOLBOX_MANIFEST_VERSION
    assert manifest["known_capability_count"] >= 34
    assert verify_gold_toolbox_manifest(manifest)

    capabilities = {item["name"]: item for item in manifest["capabilities"]}
    assert capabilities["gold_m1_candles"]["status"] == "live_here"
    assert capabilities["gold_movement_detector"]["status"] == "live_here"
    assert capabilities["gold_movement_episode_memory"]["status"] == "live_here"
    assert capabilities["gold_cycle_15m_memory"]["status"] == "live_here"
    assert capabilities["gold_contextual_marker_brain"]["status"] == "live_here"
    assert capabilities["economic_calendar_on_demand"]["status"] == (
        "super_signals_runtime_resolves"
    )
    assert capabilities["provider_history_conditional_alpha"]["status"] == (
        "super_signals_runtime_resolves"
    )
    assert capabilities["rates_macro_vintages"]["status"] == (
        "research_exists_not_live_connected"
    )
    assert capabilities["breaking_news_event_search"]["status"] == (
        "research_exists_not_live_connected"
    )
    assert capabilities["intraday_cross_asset_reaction"]["status"] == (
        "research_exists_not_live_connected"
    )


def test_manifest_promotes_only_evidence_that_is_actually_known() -> None:
    gold = _gold_state()
    gold["market_structure"]["timeframes"]["D1"] = {"state": "known"}
    gold["scheduled_event_risk"] = {
        "state": "known",
        "decision_input_allowed": True,
    }
    gold["volatility"]["gvz"] = {"state": "known"}

    manifest = build_gold_toolbox_manifest(
        gold_state=gold,
        semantic_context={
            "cross_market": {
                "series": {
                    "DXY": {"state": "known"},
                }
            }
        },
        live_source_availability={},
    )
    capabilities = {item["name"]: item for item in manifest["capabilities"]}

    assert capabilities["gold_d1_context"]["status"] == "live_here"
    assert capabilities["scheduled_event_context"]["status"] == "live_here"
    assert capabilities["cross_market_backdrop"]["status"] == "live_here"
    assert capabilities["gvz_implied_volatility"]["status"] == "live_here"
