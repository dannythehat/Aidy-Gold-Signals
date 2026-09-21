from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy.gold_state_engine import verify_gold_state_engine

GOLD_MOVEMENT_INVESTIGATOR_VERSION = "aidy_gold_movement_investigator_v1"
GOLD_MOVEMENT_LEARNING_CARD_VERSION = "aidy_gold_movement_learning_card_v1"

_ABNORMAL_DISPLACEMENT = {
    "elevated_recent_displacement",
    "extreme_recent_displacement",
}
_ABNORMAL_RANGE = {"range_expansion", "extreme_range_expansion"}
_FORWARD_WINDOWS = ("5m", "15m", "30m", "60m")


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str, *, name: str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware.")
    return parsed.astimezone(UTC)


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _event_candidates(
    *,
    semantic_context: Mapping[str, Any],
    event_intelligence_state: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    candidates: list[dict[str, Any]] = []
    missing: list[str] = []

    event_risk = semantic_context.get("event_risk")
    event_risk = event_risk if isinstance(event_risk, Mapping) else {}
    if event_risk.get("evidence_state") == "known":
        events = event_risk.get("events_in_window")
        if isinstance(events, list) and events:
            candidates.append(
                {
                    "mechanism": "scheduled_macro_event_window",
                    "support_level": "plausible_unconfirmed",
                    "confidence": "0.45",
                    "evidence_refs": ["$.event_risk.events_in_window"],
                    "contrary_evidence": [],
                    "causal_claim": False,
                    "detail": {"events_in_window": events[:5]},
                }
            )
        elif str(event_risk.get("timing_state") or "") not in {
            "clear_current_window",
            "clear_tiered_windows",
        }:
            missing.append("qualified_scheduled_event_detail")
    else:
        missing.append("qualified_scheduled_event_context")

    event_state = (
        event_intelligence_state
        if isinstance(event_intelligence_state, Mapping)
        else {}
    )
    if str(event_state.get("timing_state") or "") == "inside_tiered_window":
        current = event_state.get("events_in_window")
        candidates.append(
            {
                "mechanism": "tiered_macro_event_window",
                "support_level": "plausible_unconfirmed",
                "confidence": "0.5",
                "evidence_refs": [
                    "$.architecture_v2_extensions.event_intelligence.events_in_window"
                ],
                "contrary_evidence": [],
                "causal_claim": False,
                "detail": {"events_in_window": list(current or [])[:5]},
            }
        )

    surprise = event_state.get("surprise_state")
    surprise = surprise if isinstance(surprise, Mapping) else {}
    if surprise.get("surprise_state") == "known":
        refs = [
            "$.architecture_v2_extensions.event_intelligence.surprise_state"
        ]
        candidates.append(
            {
                "mechanism": "observed_macro_release_surprise",
                "support_level": "supported_mechanism",
                "confidence": "0.75",
                "evidence_refs": refs,
                "contrary_evidence": [],
                "causal_claim": False,
                "detail": {
                    "event_class": surprise.get("event_class"),
                    "surprise_value": surprise.get("surprise_value"),
                    "first_print_state": surprise.get("first_print_state"),
                    "consensus_state": surprise.get("consensus_state"),
                },
            }
        )
    else:
        missing.append("first_print_vs_consensus_surprise")

    return candidates, sorted(set(missing))


def _market_candidates(
    *,
    gold_state: Mapping[str, Any],
    semantic_context: Mapping[str, Any],
    rates_macro_state: Mapping[str, Any],
    cme_contract_state: Mapping[str, Any],
    volatility_state: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    candidates: list[dict[str, Any]] = []
    missing: list[str] = []

    volatility = gold_state.get("volatility")
    volatility = volatility if isinstance(volatility, Mapping) else {}
    jump = volatility.get("jump_continuous")
    jump = jump if isinstance(jump, Mapping) else {}
    jump_state = str(jump.get("state") or "unknown")
    if jump_state == "jump_dominant":
        candidates.append(
            {
                "mechanism": "jump_dominant_market_reaction",
                "support_level": "supported_mechanism",
                "confidence": "0.65",
                "evidence_refs": ["$.gold_state.volatility.jump_continuous"],
                "contrary_evidence": [],
                "causal_claim": False,
                "detail": {"jump_state": jump_state},
            }
        )
    elif jump_state.startswith("unknown"):
        missing.append("qualified_jump_vs_continuous_state")

    liquidity = gold_state.get("liquidity")
    liquidity = liquidity if isinstance(liquidity, Mapping) else {}
    proxies = liquidity.get("sweep_reclaim_proxies")
    if isinstance(proxies, list) and proxies:
        candidates.append(
            {
                "mechanism": "measured_liquidity_reclaim_pattern",
                "support_level": "plausible_unconfirmed",
                "confidence": "0.35",
                "evidence_refs": ["$.gold_state.liquidity.sweep_reclaim_proxies"],
                "contrary_evidence": [],
                "causal_claim": False,
                "detail": {
                    "proxy_count": len(proxies),
                    "proxy_not_order_flow": True,
                },
            }
        )

    cross_market = semantic_context.get("cross_market")
    cross_market = cross_market if isinstance(cross_market, Mapping) else {}
    series = cross_market.get("series")
    series = series if isinstance(series, Mapping) else {}
    known_series = sorted(
        str(name)
        for name, value in series.items()
        if isinstance(value, Mapping) and value.get("state") == "known"
    )
    if known_series:
        candidates.append(
            {
                "mechanism": "cross_market_backdrop_available",
                "support_level": "context_only",
                "confidence": "0",
                "evidence_refs": ["$.cross_market.series"],
                "contrary_evidence": [],
                "causal_claim": False,
                "detail": {"known_series": known_series},
            }
        )
        missing.append("intraday_cross_asset_reaction_at_spike")
    else:
        missing.append("intraday_cross_asset_reaction_at_spike")

    rates = rates_macro_state if isinstance(rates_macro_state, Mapping) else {}
    rates_state = str(rates.get("state") or rates.get("evidence_state") or "unknown")
    if rates_state.startswith("unknown") or not rates:
        missing.append("qualified_rates_macro_state")

    cme = cme_contract_state if isinstance(cme_contract_state, Mapping) else {}
    cme_state = str(cme.get("state") or "unknown")
    if cme_state.startswith("unknown") or not cme:
        missing.append("qualified_cme_contract_state")

    volatility_state = (
        volatility_state if isinstance(volatility_state, Mapping) else {}
    )
    gvz = volatility_state.get("gvz")
    gvz = gvz if isinstance(gvz, Mapping) else {}
    if gvz.get("state") != "known":
        missing.append("qualified_gvz_state")

    return candidates, sorted(set(missing))


def build_gold_movement_investigation(
    *,
    as_of: datetime | str,
    gold_state: Mapping[str, Any],
    semantic_context: Mapping[str, Any],
    rates_macro_state: Mapping[str, Any] | None = None,
    event_intelligence_state: Mapping[str, Any] | None = None,
    cme_contract_state: Mapping[str, Any] | None = None,
    volatility_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Investigate an abnormal Gold move without inventing a cause.

    This is the bridge between movement detection and causal learning. It ranks only
    evidence-backed mechanisms and separately records the evidence that is still missing.
    A scheduled event near a spike is not automatically called the cause.
    """

    cutoff = _utc(as_of, name="as_of")
    if not verify_gold_state_engine(gold_state):
        raise ValueError("Gold movement investigation requires a verified Gold State Engine packet.")
    if _utc(str(gold_state.get("as_of_utc")), name="gold_state.as_of_utc") != cutoff:
        raise ValueError("Gold movement investigation and Gold State must share the same as-of time.")

    move = gold_state.get("move_observation")
    move = move if isinstance(move, Mapping) else {}
    displacement = str(move.get("five_minute_distribution_state") or "unknown")
    range_state = str(move.get("five_minute_range_state") or "unknown")
    volatility = gold_state.get("volatility")
    volatility = volatility if isinstance(volatility, Mapping) else {}
    jump = volatility.get("jump_continuous")
    jump = jump if isinstance(jump, Mapping) else {}
    jump_state = str(jump.get("state") or "unknown")

    triggered_by: list[str] = []
    if displacement in _ABNORMAL_DISPLACEMENT:
        triggered_by.append("abnormal_5m_displacement")
    if range_state in _ABNORMAL_RANGE:
        triggered_by.append("abnormal_5m_range")
    if jump_state == "jump_dominant":
        triggered_by.append("jump_dominant_volatility")

    direction = "unknown"
    windows = move.get("windows")
    windows = windows if isinstance(windows, Mapping) else {}
    five = windows.get("5m")
    if isinstance(five, Mapping):
        direction = str(five.get("direction") or "unknown")

    if not triggered_by:
        result: dict[str, Any] = {
            "investigator_version": GOLD_MOVEMENT_INVESTIGATOR_VERSION,
            "as_of_utc": cutoff.isoformat(),
            "symbol": "XAUUSD",
            "state": "not_triggered",
            "investigation_required": False,
            "triggered_by": [],
            "move_direction": direction,
            "attribution_state": "not_applicable",
            "leading_mechanism": None,
            "mechanism_candidates": [],
            "missing_evidence": [],
            "required_follow_up_tools": [],
            "cause_known": False,
            "cause_unknown": False,
            "research_only": True,
            "predictive_edge_claimed": False,
            "live_money_execution_allowed": False,
            "future_values_used": False,
        }
        result["investigation_digest"] = _digest(result)
        return result

    event_candidates, event_missing = _event_candidates(
        semantic_context=semantic_context,
        event_intelligence_state=event_intelligence_state or {},
    )
    market_candidates, market_missing = _market_candidates(
        gold_state=gold_state,
        semantic_context=semantic_context,
        rates_macro_state=rates_macro_state or {},
        cme_contract_state=cme_contract_state or {},
        volatility_state=volatility_state or {},
    )
    candidates = event_candidates + market_candidates
    rank = {
        "supported_mechanism": 3,
        "plausible_unconfirmed": 2,
        "context_only": 1,
    }
    causal_candidates = [
        item for item in candidates if item.get("support_level") != "context_only"
    ]
    causal_candidates.sort(
        key=lambda item: (
            rank.get(str(item.get("support_level")), 0),
            _decimal(item.get("confidence")) or Decimal(0),
        ),
        reverse=True,
    )
    leading = causal_candidates[0] if causal_candidates else None
    if leading is None:
        attribution_state = "cause_unknown"
    else:
        attribution_state = str(leading.get("support_level") or "cause_unknown")

    missing = sorted(set(event_missing + market_missing))
    if not any(
        item.get("support_level") == "supported_mechanism" for item in causal_candidates
    ):
        missing.append("breaking_news_or_official_release_at_spike")
    missing = sorted(set(missing))

    follow_up_map = {
        "first_print_vs_consensus_surprise": "macro_actual_surprise",
        "intraday_cross_asset_reaction_at_spike": "intraday_cross_asset_reaction",
        "qualified_rates_macro_state": "rates_macro_vintages",
        "qualified_cme_contract_state": "cme_contract_state",
        "qualified_gvz_state": "gvz_implied_volatility",
        "breaking_news_or_official_release_at_spike": "breaking_news_event_search",
        "qualified_scheduled_event_context": "economic_calendar",
        "qualified_scheduled_event_detail": "economic_calendar",
        "qualified_jump_vs_continuous_state": "volatility_jump_state",
    }
    follow_up = sorted(
        {follow_up_map[item] for item in missing if item in follow_up_map}
    )

    result = {
        "investigator_version": GOLD_MOVEMENT_INVESTIGATOR_VERSION,
        "as_of_utc": cutoff.isoformat(),
        "symbol": "XAUUSD",
        "state": "investigated",
        "investigation_required": True,
        "triggered_by": sorted(triggered_by),
        "move_direction": direction,
        "move_snapshot": {
            "five_minute_distribution_state": displacement,
            "five_minute_range_state": range_state,
            "five_minute_abs_return_percentile": move.get(
                "five_minute_abs_return_percentile"
            ),
            "five_minute_range_percentile": move.get("five_minute_range_percentile"),
            "jump_state": jump_state,
        },
        "attribution_state": attribution_state,
        "leading_mechanism": leading,
        "mechanism_candidates": candidates,
        "missing_evidence": missing,
        "required_follow_up_tools": follow_up,
        "cause_known": False,
        "cause_unknown": attribution_state == "cause_unknown",
        "research_only": True,
        "predictive_edge_claimed": False,
        "live_money_execution_allowed": False,
        "future_values_used": False,
    }
    result["investigation_digest"] = _digest(result)
    return result


def verify_gold_movement_investigation(value: Mapping[str, Any]) -> bool:
    body = dict(value)
    supplied = str(body.pop("investigation_digest", ""))
    return (
        bool(supplied)
        and supplied == _digest(body)
        and body.get("investigator_version") == GOLD_MOVEMENT_INVESTIGATOR_VERSION
        and body.get("symbol") == "XAUUSD"
        and body.get("research_only") is True
        and body.get("predictive_edge_claimed") is False
        and body.get("live_money_execution_allowed") is False
        and body.get("future_values_used") is False
        and body.get("cause_known") is False
    )


def _signed_direction(value: Decimal | None) -> str:
    if value is None:
        return "unknown"
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "flat"


def build_gold_movement_learning_card(
    *,
    investigation: Mapping[str, Any],
    available_at: datetime | str,
    forward_windows: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Attach post-move behaviour only after the investigation itself is immutable."""

    if not verify_gold_movement_investigation(investigation):
        raise ValueError("Learning card requires a verified movement investigation.")
    trigger_at = _utc(str(investigation["as_of_utc"]), name="investigation.as_of_utc")
    available = _utc(available_at, name="available_at")
    if available <= trigger_at:
        raise ValueError("Movement learning cannot become available at or before the trigger.")

    normalized: dict[str, Any] = {}
    for name in _FORWARD_WINDOWS:
        raw = forward_windows.get(name)
        raw = raw if isinstance(raw, Mapping) else {}
        value = _decimal(raw.get("return_bps"))
        normalized[name] = {
            "return_bps": None if value is None else str(value),
            "direction": _signed_direction(value),
            "observed": value is not None,
        }

    initial = str(investigation.get("move_direction") or "unknown")
    observed_dirs = [
        normalized[name]["direction"]
        for name in ("15m", "30m", "60m")
        if normalized[name]["direction"] not in {"unknown", "flat"}
    ]
    if initial not in {"up", "down"} or not observed_dirs:
        path_class = "insufficient_forward_path"
    else:
        same = sum(item == initial for item in observed_dirs)
        opposite = sum(item != initial for item in observed_dirs)
        if same and not opposite:
            path_class = "continuation"
        elif opposite and not same:
            path_class = "reversal"
        else:
            path_class = "mixed"

    leading = investigation.get("leading_mechanism")
    leading = leading if isinstance(leading, Mapping) else {}
    tags = sorted(
        {
            *(f"trigger:{item}" for item in investigation.get("triggered_by") or []),
            f"direction:{initial}",
            f"attribution:{investigation.get('attribution_state')}",
            f"path:{path_class}",
            f"mechanism:{leading.get('mechanism') or 'unknown'}",
        }
    )
    result: dict[str, Any] = {
        "learning_card_version": GOLD_MOVEMENT_LEARNING_CARD_VERSION,
        "symbol": "XAUUSD",
        "trigger_at_utc": trigger_at.isoformat(),
        "available_at_utc": available.isoformat(),
        "investigation_digest": investigation["investigation_digest"],
        "triggered_by": list(investigation.get("triggered_by") or []),
        "initial_move_direction": initial,
        "attribution_state": investigation.get("attribution_state"),
        "leading_mechanism": dict(leading),
        "forward_path": normalized,
        "path_class": path_class,
        "tags": tags,
        "same_episode_retrieval_allowed": False,
        "active_cohort_tuning_allowed": False,
        "predictive_rule_created": False,
        "research_only": True,
        "live_money_execution_allowed": False,
    }
    result["learning_card_digest"] = _digest(result)
    return result


def verify_gold_movement_learning_card(value: Mapping[str, Any]) -> bool:
    body = dict(value)
    supplied = str(body.pop("learning_card_digest", ""))
    return (
        bool(supplied)
        and supplied == _digest(body)
        and body.get("learning_card_version") == GOLD_MOVEMENT_LEARNING_CARD_VERSION
        and body.get("symbol") == "XAUUSD"
        and body.get("same_episode_retrieval_allowed") is False
        and body.get("active_cohort_tuning_allowed") is False
        and body.get("predictive_rule_created") is False
        and body.get("research_only") is True
        and body.get("live_money_execution_allowed") is False
    )


__all__ = [
    "GOLD_MOVEMENT_INVESTIGATOR_VERSION",
    "GOLD_MOVEMENT_LEARNING_CARD_VERSION",
    "build_gold_movement_investigation",
    "build_gold_movement_learning_card",
    "verify_gold_movement_investigation",
    "verify_gold_movement_learning_card",
]
