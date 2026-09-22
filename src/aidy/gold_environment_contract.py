"""Build 1: factorised Gold environment contract primitives.

This module defines the shared global environment registry and safety rules.
It deliberately does not implement any expert-gate mini-brain logic.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

ENVIRONMENT_CONTRACT_SCHEMA_VERSION = "aidy_gold_environment_contract_schema_v1"

FORBIDDEN_HINDSIGHT_KEYS = frozenset(
    {
        "future_return",
        "future_returns",
        "outcome",
        "outcome_label",
        "pnl",
        "realized_pnl",
        "profit",
        "loss",
        "win",
        "winner",
        "loser",
        "target_hit",
        "stop_hit",
        "mfe",
        "mae",
        "subsequent_price",
        "realised_direction",
        "realized_direction",
        "realised_return_bps",
        "realized_return_bps",
        "return_bps",
        "score",
        "correct",
        "impact_class",
    }
)

GLOBAL_ENVIRONMENT_DIMENSION_REGISTRY: tuple[dict[str, str], ...] = (
    {"name": "session", "family": "time_participation", "kind": "categorical"},
    {"name": "session_phase", "family": "time_participation", "kind": "bucket"},
    {"name": "utc_weekday", "family": "time_participation", "kind": "exact"},
    {"name": "utc_clock_bucket_15m", "family": "time_participation", "kind": "bucket"},
    {"name": "week_transition_state", "family": "time_participation", "kind": "categorical"},
    {"name": "market_calendar_state", "family": "time_participation", "kind": "categorical"},
    {"name": "observed_15m_state", "family": "structure", "kind": "categorical"},
    {"name": "m5_direction", "family": "structure", "kind": "categorical"},
    {"name": "m15_direction", "family": "structure", "kind": "categorical"},
    {"name": "h1_direction", "family": "structure", "kind": "categorical"},
    {"name": "h4_direction", "family": "structure", "kind": "categorical"},
    {"name": "d1_direction", "family": "structure", "kind": "categorical"},
    {"name": "five_minute_distribution_state", "family": "movement", "kind": "categorical"},
    {"name": "five_minute_range_state", "family": "movement", "kind": "categorical"},
    {"name": "m60_direction", "family": "movement", "kind": "categorical"},
    {"name": "nearest_reference", "family": "location", "kind": "categorical"},
    {"name": "nearest_reference_side", "family": "location", "kind": "categorical"},
    {"name": "nearest_reference_distance_band", "family": "location", "kind": "bucket"},
    {"name": "prior_day_zone", "family": "location", "kind": "bucket"},
    {"name": "asia_overnight_zone", "family": "location", "kind": "bucket"},
    {"name": "active_session_zone", "family": "location", "kind": "bucket"},
    {"name": "liquidity_signature", "family": "liquidity", "kind": "categorical"},
    {"name": "liquidity_intensity", "family": "liquidity", "kind": "bucket"},
    {"name": "prior_day_breakout_state", "family": "liquidity", "kind": "categorical"},
    {"name": "volatility_state", "family": "volatility", "kind": "categorical"},
    {"name": "jump_state", "family": "volatility", "kind": "categorical"},
    {"name": "event_timing_state", "family": "event", "kind": "categorical"},
    {"name": "event_proximity", "family": "event", "kind": "bucket"},
    {"name": "cross_market_known_count", "family": "cross_market", "kind": "exact"},
    {"name": "cross_market_coverage", "family": "cross_market", "kind": "bucket"},
    {"name": "cross_market_known_series", "family": "cross_market", "kind": "set"},
    {"name": "cross_market_age_bands", "family": "cross_market", "kind": "mapping"},
    {"name": "compound_regime", "family": "regime", "kind": "categorical"},
    {"name": "data_quality_state", "family": "data_quality", "kind": "categorical"},
)

GLOBAL_CORE_DIMENSIONS = (
    "session",
    "session_phase",
    "utc_weekday",
    "utc_clock_bucket_15m",
    "week_transition_state",
    "market_calendar_state",
    "observed_15m_state",
    "volatility_state",
    "event_proximity",
    "data_quality_state",
)

FACTOR_DIMENSION_GROUPS: dict[str, tuple[str, ...]] = {
    "time_participation": (
        "session",
        "session_phase",
        "utc_weekday",
        "utc_clock_bucket_15m",
        "week_transition_state",
        "market_calendar_state",
    ),
    "structure": (
        "observed_15m_state",
        "m5_direction",
        "m15_direction",
        "h1_direction",
        "h4_direction",
        "d1_direction",
    ),
    "movement": (
        "five_minute_distribution_state",
        "five_minute_range_state",
        "m60_direction",
    ),
    "location": (
        "nearest_reference",
        "nearest_reference_side",
        "nearest_reference_distance_band",
        "prior_day_zone",
        "asia_overnight_zone",
        "active_session_zone",
    ),
    "liquidity": (
        "liquidity_signature",
        "liquidity_intensity",
        "prior_day_breakout_state",
    ),
    "volatility": ("volatility_state", "jump_state"),
    "event": ("event_timing_state", "event_proximity"),
    "cross_market": (
        "cross_market_known_count",
        "cross_market_coverage",
        "cross_market_known_series",
        "cross_market_age_bands",
    ),
    "regime": ("compound_regime",),
    "data_quality": ("data_quality_state",),
}

SCOPE_HIERARCHY = (
    "liquidity_location",
    "location_structure",
    "session_liquidity",
    "volatility_move_regime",
    "session_state_event",
    "event_regime",
    "session_move_regime",
    "higher_timeframe",
    "session_state",
    "session_phase",
    "session",
    "global_core",
    "global",
)


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("environment timestamps must be timezone-aware")
    return parsed.astimezone(UTC)


def assert_no_hindsight_fields(value: Any, *, path: str) -> None:
    """Fail closed when outcome/future-labelled evidence enters the pre-decision contract."""

    if isinstance(value, Mapping):
        if value.get("future_values_used") is True:
            raise ValueError(f"future-valued evidence is forbidden at {path}")
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in FORBIDDEN_HINDSIGHT_KEYS:
                raise ValueError(f"hindsight field is forbidden at {path}.{key}")
            assert_no_hindsight_fields(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            assert_no_hindsight_fields(item, path=f"{path}[{index}]")


def week_transition_state(value: datetime | str) -> str:
    now = utc(value)
    if now.weekday() >= 5:
        return "calendar_weekend"
    if now.weekday() == 4:
        return "pre_weekend_day"
    if now.weekday() == 0:
        return "post_weekend_day"
    return "regular_weekday"


def market_calendar_state(*, as_of: datetime | str, session_code: str) -> str:
    now = utc(as_of)
    if session_code == "weekend" or now.weekday() >= 5:
        return "calendar_closed_weekend"
    if session_code == "off_hours":
        return "weekday_off_hours"
    return "weekday_session"


def utc_clock_bucket_15m(value: datetime | str) -> str:
    now = utc(value)
    minute = (now.minute // 15) * 15
    return f"{now.hour:02d}:{minute:02d}"


def classify_data_quality(
    *,
    semantic_context: Mapping[str, Any] | None,
    timeframe_states: Mapping[str, str],
) -> dict[str, Any]:
    semantic_context = semantic_context if isinstance(semantic_context, Mapping) else {}
    quality = semantic_context.get("data_quality")
    quality = quality if isinstance(quality, Mapping) else {}

    quote_freshness = str(quality.get("quote_freshness") or "unknown")
    quote_state = str(quality.get("quote_state") or "unknown")
    spread_state = str(quality.get("spread_state") or "unknown")
    flags = sorted(str(item) for item in (quality.get("flags") or []) if item)

    required = ("M5", "M15", "H1", "H4")
    missing_required = [
        timeframe
        for timeframe in required
        if str(timeframe_states.get(timeframe) or "unknown") != "known"
    ]

    if quote_freshness == "stale":
        state = "stale"
    elif missing_required:
        state = "partial"
    elif quote_state == "known" and quote_freshness == "fresh":
        state = "fresh"
    elif quality:
        state = "partial"
    else:
        state = "unknown"

    return {
        "state": state,
        "quote_state": quote_state,
        "quote_freshness": quote_freshness,
        "spread_state": spread_state,
        "missing_required_timeframes": missing_required,
        "flags": flags,
        "source_present": bool(quality),
    }


def complete_dimensions(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Return every registered global dimension, never silently omitting one."""

    result: dict[str, Any] = {}
    for spec in GLOBAL_ENVIRONMENT_DIMENSION_REGISTRY:
        name = spec["name"]
        value = raw.get(name, "unknown")
        if value is None or value == "":
            value = "unknown"
        result[name] = value
    return result


def dimension_registry_digest() -> str:
    return digest(GLOBAL_ENVIRONMENT_DIMENSION_REGISTRY)


def factor_payloads(dimensions: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        family: {name: dimensions.get(name, "unknown") for name in names}
        for family, names in FACTOR_DIMENSION_GROUPS.items()
    }


def factor_keys(dimensions: Mapping[str, Any]) -> dict[str, str]:
    return {
        family: f"factor_{family}_" + digest(payload)[:24]
        for family, payload in factor_payloads(dimensions).items()
    }


def global_core_payload(dimensions: Mapping[str, Any]) -> dict[str, Any]:
    return {name: dimensions.get(name, "unknown") for name in GLOBAL_CORE_DIMENSIONS}


def global_environment_key(dimensions: Mapping[str, Any]) -> str:
    """Stable core environment key; intentionally not a full cross-product."""

    return "envcore_" + digest(global_core_payload(dimensions))[:32]


def build_contract_metadata(dimensions: Mapping[str, Any]) -> dict[str, Any]:
    payloads = factor_payloads(dimensions)
    return {
        "schema_version": ENVIRONMENT_CONTRACT_SCHEMA_VERSION,
        "dimension_registry_digest": dimension_registry_digest(),
        "dimension_count": len(GLOBAL_ENVIRONMENT_DIMENSION_REGISTRY),
        "global_core_dimensions": list(GLOBAL_CORE_DIMENSIONS),
        "factor_dimension_groups": {
            family: list(names)
            for family, names in FACTOR_DIMENSION_GROUPS.items()
        },
        "factor_payloads": payloads,
        "factor_keys": {
            family: f"factor_{family}_" + digest(payload)[:24]
            for family, payload in payloads.items()
        },
        "scope_hierarchy": list(SCOPE_HIERARCHY),
        "monolithic_full_environment_key_used": False,
        "mini_environment_contract": {
            "state": "deferred_to_expert_gate_builds",
            "inherits_global_environment": True,
            "gate_specific_dimensions_required": True,
        },
    }


__all__ = [
    "ENVIRONMENT_CONTRACT_SCHEMA_VERSION",
    "FACTOR_DIMENSION_GROUPS",
    "FORBIDDEN_HINDSIGHT_KEYS",
    "GLOBAL_CORE_DIMENSIONS",
    "GLOBAL_ENVIRONMENT_DIMENSION_REGISTRY",
    "SCOPE_HIERARCHY",
    "assert_no_hindsight_fields",
    "build_contract_metadata",
    "classify_data_quality",
    "complete_dimensions",
    "dimension_registry_digest",
    "factor_keys",
    "global_core_payload",
    "global_environment_key",
    "market_calendar_state",
    "utc_clock_bucket_15m",
    "week_transition_state",
]
