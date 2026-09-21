"""Canonical capability catalogue for AIDY's Gold intelligence toolbox.

The owner mandate is explicit: AIDY must know what evidence/tooling exists, what each
surface is for, and whether it is actually connected at the current point in time.
Existence is not the same as availability. This manifest therefore includes live,
downstream and research-only capabilities without silently promoting unavailable data.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256
from typing import Any

GOLD_TOOLBOX_MANIFEST_VERSION = "aidy_gold_toolbox_manifest_v1"


def _digest(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


_CATALOG: tuple[dict[str, str], ...] = (
    {"name": "gold_m1_candles", "category": "price", "owner": "aidy", "purpose": "minute-by-minute XAUUSD path"},
    {"name": "gold_m5_structure", "category": "price", "owner": "aidy", "purpose": "short-horizon displacement and structure"},
    {"name": "gold_m15_structure", "category": "price", "owner": "aidy", "purpose": "intraday trend/range context"},
    {"name": "gold_h1_structure", "category": "price", "owner": "aidy", "purpose": "hourly trend and regime context"},
    {"name": "gold_h4_structure", "category": "price", "owner": "aidy", "purpose": "higher-timeframe structure"},
    {"name": "gold_d1_context", "category": "price", "owner": "aidy", "purpose": "daily reference context when available"},
    {"name": "session_day_map", "category": "time", "owner": "aidy", "purpose": "Asia/London/New York session state"},
    {"name": "price_location_reference_levels", "category": "structure", "owner": "aidy", "purpose": "position versus observed highs/lows/opening and round levels"},
    {"name": "liquidity_sweep_reclaim_proxies", "category": "liquidity", "owner": "aidy", "purpose": "measured penetration/reclaim patterns without claiming hidden order flow"},
    {"name": "realized_volatility", "category": "volatility", "owner": "aidy", "purpose": "realized volatility state from admitted candles"},
    {"name": "jump_vs_continuous_volatility", "category": "volatility", "owner": "aidy", "purpose": "distinguish jump-dominant from continuous movement"},
    {"name": "scheduled_event_context", "category": "events", "owner": "aidy", "purpose": "PIT-linked scheduled event timing when present"},
    {"name": "economic_calendar_on_demand", "category": "events", "owner": "super_signals", "purpose": "live scheduled macro calendar around a signal or move"},
    {"name": "macro_actual_surprise", "category": "events", "owner": "aidy", "purpose": "first-print versus consensus macro surprise"},
    {"name": "rates_macro_vintages", "category": "macro", "owner": "aidy", "purpose": "PIT nominal yields, real yields, breakevens, curve and CPI revision context"},
    {"name": "cross_market_backdrop", "category": "cross_market", "owner": "aidy", "purpose": "PIT cross-market backdrop already stored by AIDY"},
    {"name": "intraday_cross_asset_reaction", "category": "cross_market", "owner": "aidy", "purpose": "USD/yield/cross-asset reaction at the exact Gold move"},
    {"name": "cme_contract_state", "category": "futures", "owner": "aidy", "purpose": "CME Gold contract and roll/liquidity state"},
    {"name": "gvz_implied_volatility", "category": "volatility", "owner": "aidy", "purpose": "Gold implied-volatility context"},
    {"name": "breaking_news_event_search", "category": "news", "owner": "aidy", "purpose": "breaking news/official release search around an abnormal move"},
    {"name": "gold_movement_detector", "category": "learning", "owner": "aidy", "purpose": "symmetric UP/DOWN abnormal movement detection"},
    {"name": "gold_movement_episode_memory", "category": "learning", "owner": "aidy", "purpose": "immutable abnormal-move episode storage"},
    {"name": "gold_movement_analogue_retrieval", "category": "learning", "owner": "aidy", "purpose": "retrieve prior comparable Gold episodes with counterexamples"},
    {"name": "recent_gold_candles_on_demand", "category": "price", "owner": "super_signals", "purpose": "bounded live candle inspection during signal reasoning"},
    {"name": "provider_history_conditional_alpha", "category": "provider", "owner": "super_signals", "purpose": "PIT provider side/session/conditional evidence"},
    {"name": "recent_provider_messages", "category": "provider", "owner": "super_signals", "purpose": "recent message sequence and management semantics"},
    {"name": "execution_slippage_liquidity", "category": "execution", "owner": "super_signals", "purpose": "entry state, latency, slippage and execution friction"},
    {"name": "provider_historical_analogues", "category": "provider", "owner": "super_signals", "purpose": "prior-resolved comparable provider cases"},
    {"name": "probability_ev_management", "category": "decision", "owner": "super_signals", "purpose": "bounded probability/EV/management research context"},
    {"name": "failure_attribution_self_critique", "category": "learning", "owner": "super_signals", "purpose": "prior resolved AIDY decision failures and self-critique"},
    {"name": "self_calibration", "category": "learning", "owner": "super_signals", "purpose": "AIDY's own prior resolved reasoning calibration"},
    {"name": "provider_decision_memory", "category": "learning", "owner": "aidy", "purpose": "persistent provider decision/outcome memory"},
)


def build_gold_toolbox_manifest(
    *,
    gold_state: Mapping[str, Any],
    semantic_context: Mapping[str, Any],
    live_source_availability: Mapping[str, Any],
) -> dict[str, Any]:
    """Describe the whole known arsenal without pretending disconnected research is live."""

    move = gold_state.get("move_observation")
    move = move if isinstance(move, Mapping) else {}
    volatility = gold_state.get("volatility")
    volatility = volatility if isinstance(volatility, Mapping) else {}
    cross_market = semantic_context.get("cross_market")
    cross_market = cross_market if isinstance(cross_market, Mapping) else {}
    series = cross_market.get("series")
    series = series if isinstance(series, Mapping) else {}
    scheduled = gold_state.get("scheduled_event_risk")
    scheduled = scheduled if isinstance(scheduled, Mapping) else {}

    live_here = {
        "gold_m1_candles",
        "gold_m5_structure",
        "gold_m15_structure",
        "gold_h1_structure",
        "gold_h4_structure",
        "session_day_map",
        "price_location_reference_levels",
        "liquidity_sweep_reclaim_proxies",
        "realized_volatility",
        "jump_vs_continuous_volatility",
        "gold_movement_detector",
        "gold_movement_episode_memory",
        "gold_movement_analogue_retrieval",
    }
    if (
        isinstance(gold_state.get("market_structure"), Mapping)
        and gold_state["market_structure"].get("timeframes", {}).get("D1")
    ):
        live_here.add("gold_d1_context")
    if scheduled.get("decision_input_allowed") is True:
        live_here.add("scheduled_event_context")
    if any(
        isinstance(value, Mapping) and value.get("state") == "known"
        for value in series.values()
    ):
        live_here.add("cross_market_backdrop")
    if (
        isinstance(volatility.get("gvz"), Mapping)
        and volatility["gvz"].get("state") == "known"
    ):
        live_here.add("gvz_implied_volatility")

    downstream_runtime_resolves = {
        "economic_calendar_on_demand",
        "recent_gold_candles_on_demand",
        "provider_history_conditional_alpha",
        "recent_provider_messages",
        "execution_slippage_liquidity",
        "provider_historical_analogues",
        "probability_ev_management",
        "failure_attribution_self_critique",
        "self_calibration",
    }

    research_not_live_connected = {
        "macro_actual_surprise",
        "rates_macro_vintages",
        "intraday_cross_asset_reaction",
        "cme_contract_state",
        "breaking_news_event_search",
        "provider_decision_memory",
    }

    capabilities: list[dict[str, Any]] = []
    for item in _CATALOG:
        name = item["name"]
        if name in live_here:
            status = "live_here"
            callable_now = name in {"gold_movement_detector"}
        elif name in downstream_runtime_resolves:
            status = "super_signals_runtime_resolves"
            callable_now = False
        elif name in research_not_live_connected:
            status = "research_exists_not_live_connected"
            callable_now = False
        else:
            status = "known_unknown"
            callable_now = False
        capabilities.append(
            {
                **item,
                "status": status,
                "callable_now_in_standalone": callable_now,
            }
        )

    result: dict[str, Any] = {
        "contract_version": GOLD_TOOLBOX_MANIFEST_VERSION,
        "purpose": "gold_move_and_trade_evidence_routing",
        "decision_rule": (
            "Know the full arsenal. Use every material connected evidence surface, route to a "
            "downstream callable tool when it can resolve a real uncertainty, and preserve UNKNOWN "
            "for research that exists but is not live-connected. Never invent a missing tool result."
        ),
        "known_capability_count": len(capabilities),
        "live_here_count": sum(item["status"] == "live_here" for item in capabilities),
        "capabilities": capabilities,
        "required_for_abnormal_move_review": [
            "gold_m1_candles",
            "gold_m5_structure",
            "gold_m15_structure",
            "gold_h1_structure",
            "gold_h4_structure",
            "session_day_map",
            "price_location_reference_levels",
            "liquidity_sweep_reclaim_proxies",
            "realized_volatility",
            "jump_vs_continuous_volatility",
            "scheduled_event_context",
            "economic_calendar_on_demand",
            "macro_actual_surprise",
            "rates_macro_vintages",
            "cross_market_backdrop",
            "intraday_cross_asset_reaction",
            "cme_contract_state",
            "gvz_implied_volatility",
            "breaking_news_event_search",
            "gold_movement_analogue_retrieval",
        ],
        "live_source_availability": dict(live_source_availability),
        "move_state": str(move.get("state") or "unknown"),
        "research_only": True,
        "live_money_execution_allowed": False,
    }
    result["manifest_digest"] = _digest(result)
    return result


def verify_gold_toolbox_manifest(value: Mapping[str, Any]) -> bool:
    body = dict(value)
    supplied = str(body.pop("manifest_digest", ""))
    capabilities = body.get("capabilities")
    return (
        bool(supplied)
        and supplied == _digest(body)
        and body.get("contract_version") == GOLD_TOOLBOX_MANIFEST_VERSION
        and isinstance(capabilities, list)
        and body.get("known_capability_count") == len(capabilities)
        and body.get("research_only") is True
        and body.get("live_money_execution_allowed") is False
    )


__all__ = [
    "GOLD_TOOLBOX_MANIFEST_VERSION",
    "build_gold_toolbox_manifest",
    "verify_gold_toolbox_manifest",
]
