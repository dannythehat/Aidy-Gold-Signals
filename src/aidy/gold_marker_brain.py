"""Contextual marker scoring for AIDY's Gold-cycle research brain.

Every known toolbox capability is evaluated on every cycle. Directional, PIT-safe
surfaces become scoreable markers. Context-only surfaces describe the environment.
Unavailable/downstream-only capabilities remain explicit and receive no fabricated vote.

Resolved 15-minute outcomes score each marker +1/-1 and maintain multiple contextual
scorebooks. Learned weighting is deliberately gradual and bounded so a few observations
cannot overpower the original bootstrap priors.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

GOLD_MARKER_BRAIN_VERSION = "aidy_gold_contextual_marker_brain_v1"
ENVIRONMENT_VERSION = "aidy_gold_cycle_environment_v1"
MARKER_SCORE_HORIZON_MINUTES = 15
_MIN_MULTIPLIER = Decimal("0.500000")
_MAX_MULTIPLIER = Decimal("1.500000")
_FULL_RELIABILITY_SAMPLE = Decimal(20)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _fmt(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN), "f")


def marker_id(*, surface: str, source_path: str) -> str:
    identity = {"surface": surface, "source_path": source_path}
    return "marker_" + _digest(identity)[:24]


def _tf_direction(gold_state: Mapping[str, Any], timeframe: str) -> str:
    structure = gold_state.get("market_structure")
    structure = structure if isinstance(structure, Mapping) else {}
    timeframes = structure.get("timeframes")
    timeframes = timeframes if isinstance(timeframes, Mapping) else {}
    frame = timeframes.get(timeframe)
    frame = frame if isinstance(frame, Mapping) else {}
    raw = str(frame.get("net_close_direction") or "unknown").lower()
    return {
        "up": "bullish",
        "bullish": "bullish",
        "down": "bearish",
        "bearish": "bearish",
        "flat": "neutral",
        "neutral": "neutral",
    }.get(raw, "unknown")


def _movement_environment(gold_state: Mapping[str, Any]) -> dict[str, Any]:
    move = gold_state.get("move_observation")
    move = move if isinstance(move, Mapping) else {}
    return {
        "five_minute_distribution_state": str(
            move.get("five_minute_distribution_state") or "unknown"
        ),
        "five_minute_range_state": str(move.get("five_minute_range_state") or "unknown"),
        "m5_direction": _window_direction(move, "5m"),
        "m15_direction": _window_direction(move, "15m"),
        "m60_direction": _window_direction(move, "60m"),
    }


def _window_direction(move: Mapping[str, Any], horizon: str) -> str:
    windows = move.get("windows")
    windows = windows if isinstance(windows, Mapping) else {}
    payload = windows.get(horizon)
    payload = payload if isinstance(payload, Mapping) else {}
    raw = str(payload.get("direction") or "unknown").lower()
    return {
        "up": "bullish",
        "down": "bearish",
        "flat": "neutral",
    }.get(raw, raw if raw in {"bullish", "bearish", "neutral"} else "unknown")


def _event_environment(gold_state: Mapping[str, Any]) -> dict[str, str]:
    event = gold_state.get("scheduled_event_risk")
    event = event if isinstance(event, Mapping) else {}
    return {
        "state": str(event.get("state") or "unknown"),
        "timing_state": str(event.get("timing_state") or "unknown"),
    }


def _volatility_environment(gold_state: Mapping[str, Any]) -> dict[str, Any]:
    volatility = gold_state.get("volatility")
    volatility = volatility if isinstance(volatility, Mapping) else {}
    jump = volatility.get("jump_continuous")
    jump = jump if isinstance(jump, Mapping) else {}
    rv = volatility.get("realized_volatility")
    rv = rv if isinstance(rv, Mapping) else {}
    gvz = volatility.get("gvz")
    gvz = gvz if isinstance(gvz, Mapping) else {}
    return {
        "state": str(volatility.get("state") or "unknown"),
        "jump_state": str(jump.get("state") or "unknown"),
        "realized_volatility_state": str(rv.get("state") or "unknown"),
        "gvz_state": str(gvz.get("state") or "unknown"),
    }


def _liquidity_environment(gold_state: Mapping[str, Any]) -> dict[str, Any]:
    liquidity = gold_state.get("liquidity")
    liquidity = liquidity if isinstance(liquidity, Mapping) else {}
    proxies = liquidity.get("sweep_reclaim_proxies")
    proxies = proxies if isinstance(proxies, list) else []
    breakout = liquidity.get("prior_day_breakout")
    breakout = breakout if isinstance(breakout, Mapping) else {}
    return {
        "proxy_count": len(proxies),
        "prior_day_breakout_state": str(breakout.get("state") or "unknown"),
    }


def build_environment_fingerprint(
    *,
    session_code: str,
    observed_state: str,
    gold_state: Mapping[str, Any],
    regime: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Build a deterministic environment and several nested scoring scopes."""

    regime = regime if isinstance(regime, Mapping) else {}
    movement = _movement_environment(gold_state)
    volatility = _volatility_environment(gold_state)
    liquidity = _liquidity_environment(gold_state)
    event = _event_environment(gold_state)
    h1 = _tf_direction(gold_state, "H1")
    h4 = _tf_direction(gold_state, "H4")
    d1 = _tf_direction(gold_state, "D1")
    compound_regime = str(regime.get("compound_regime_key") or "unknown")

    environment = {
        "version": ENVIRONMENT_VERSION,
        "session": session_code,
        "observed_15m_state": observed_state,
        "movement": movement,
        "higher_timeframes": {"H1": h1, "H4": h4, "D1": d1},
        "volatility": volatility,
        "liquidity": liquidity,
        "scheduled_event": event,
        "compound_regime": compound_regime,
    }
    environment_key = "env_" + _digest(environment)[:32]

    scope_payloads = [
        ("global", {"global": "all"}),
        ("session", {"session": session_code}),
        (
            "session_state",
            {"session": session_code, "observed_15m_state": observed_state},
        ),
        (
            "higher_timeframe",
            {"H1": h1, "H4": h4, "D1": d1},
        ),
        (
            "session_move_regime",
            {
                "session": session_code,
                "distribution": movement["five_minute_distribution_state"],
                "range": movement["five_minute_range_state"],
            },
        ),
        (
            "session_state_event",
            {
                "session": session_code,
                "observed_15m_state": observed_state,
                "event_timing": event["timing_state"],
            },
        ),
        (
            "full_environment",
            {
                "session": session_code,
                "observed_15m_state": observed_state,
                "movement": movement,
                "higher_timeframes": {"H1": h1, "H4": h4, "D1": d1},
                "volatility": volatility,
                "liquidity": liquidity,
                "scheduled_event": event,
                "compound_regime": compound_regime,
            },
        ),
    ]
    scopes = [
        {
            "scope_type": scope_type,
            "scope_key": f"{scope_type}_" + _digest(payload)[:28],
            "payload": payload,
        }
        for scope_type, payload in scope_payloads
    ]
    return {
        "environment_version": ENVIRONMENT_VERSION,
        "environment_key": environment_key,
        "environment": environment,
        "scopes": scopes,
        "research_only": True,
        "live_money_execution_allowed": False,
    }


def toolbox_cycle_coverage(
    *,
    toolbox_manifest: Mapping[str, Any],
    marker_reasons: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Record all toolbox items and whether they produced a scoreable marker."""

    by_surface: dict[str, list[str]] = {}
    for reason in marker_reasons:
        surface = str(reason.get("surface") or "")
        if not surface:
            continue
        marker = marker_id(
            surface=surface,
            source_path=str(reason.get("source_path") or ""),
        )
        by_surface.setdefault(surface, []).append(marker)

    capabilities = toolbox_manifest.get("capabilities")
    capabilities = capabilities if isinstance(capabilities, list) else []
    result: list[dict[str, Any]] = []
    for item in capabilities:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "")
        status = str(item.get("status") or "known_unknown")
        ids = sorted(set(by_surface.get(name, [])))
        if ids:
            role = "directional_marker"
            scoreable = True
        elif status == "live_here":
            role = "environment_or_context_marker"
            scoreable = False
        elif status == "super_signals_runtime_resolves":
            role = "downstream_context_not_available_in_standalone_cycle"
            scoreable = False
        elif status == "research_exists_not_live_connected":
            role = "known_but_not_live_connected"
            scoreable = False
        else:
            role = "known_unknown"
            scoreable = False
        result.append(
            {
                "name": name,
                "category": str(item.get("category") or "unknown"),
                "status": status,
                "role_this_cycle": role,
                "directional_marker_ids": ids,
                "scoreable_this_cycle": scoreable,
            }
        )
    return result


def learning_multiplier(*, sample_n: int, net_score: int) -> Decimal:
    """Return a small, bounded trust adjustment that strengthens with evidence."""

    if sample_n <= 0:
        return Decimal(1)
    mean = Decimal(net_score) / Decimal(sample_n)
    reliability = min(Decimal(1), Decimal(sample_n) / _FULL_RELIABILITY_SAMPLE)
    multiplier = Decimal(1) + (Decimal("0.5") * mean * reliability)
    return max(_MIN_MULTIPLIER, min(_MAX_MULTIPLIER, multiplier))


_SCOPE_MIN_SAMPLES: tuple[tuple[str, int], ...] = (
    ("full_environment", 8),
    ("session_state_event", 7),
    ("session_move_regime", 6),
    ("higher_timeframe", 5),
    ("session_state", 5),
    ("session", 4),
    ("global", 1),
)


def select_score_profile(
    *,
    score_rows: Sequence[Mapping[str, Any]],
    scopes: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Choose the most specific sufficiently-sampled scorebook, falling back globally."""

    by_key = {str(row.get("scope_key")): row for row in score_rows}
    scopes_by_type = {
        str(scope.get("scope_type")): str(scope.get("scope_key"))
        for scope in scopes
    }
    selected: Mapping[str, Any] | None = None
    selected_type = "bootstrap_prior"
    for scope_type, minimum in _SCOPE_MIN_SAMPLES:
        key = scopes_by_type.get(scope_type)
        row = by_key.get(str(key or ""))
        if row is not None and int(row.get("sample_n") or 0) >= minimum:
            selected = row
            selected_type = scope_type
            break

    if selected is None:
        return {
            "selected_scope_type": "bootstrap_prior",
            "selected_scope_key": None,
            "sample_n": 0,
            "correct_n": 0,
            "incorrect_n": 0,
            "net_score": 0,
            "accuracy": None,
            "learned_multiplier": "1.000000",
        }

    sample_n = int(selected.get("sample_n") or 0)
    net_score = int(selected.get("net_score") or 0)
    return {
        "selected_scope_type": selected_type,
        "selected_scope_key": str(selected.get("scope_key") or ""),
        "sample_n": sample_n,
        "correct_n": int(selected.get("correct_n") or 0),
        "incorrect_n": int(selected.get("incorrect_n") or 0),
        "net_score": net_score,
        "accuracy": selected.get("accuracy"),
        "learned_multiplier": _fmt(
            learning_multiplier(sample_n=sample_n, net_score=net_score)
        ),
    }


def apply_learning_to_reasons(
    *,
    reasons: Sequence[Mapping[str, Any]],
    profiles: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Apply learned trust while preserving the immutable bootstrap weight."""

    adjusted: list[dict[str, Any]] = []
    for reason in reasons:
        item = dict(reason)
        surface = str(item.get("surface") or "")
        source_path = str(item.get("source_path") or "")
        mid = marker_id(surface=surface, source_path=source_path)
        base = _decimal(item.get("weight")) or Decimal(0)
        profile = dict(profiles.get(mid) or {})
        multiplier = _decimal(profile.get("learned_multiplier")) or Decimal(1)
        effective = base * multiplier
        item.update(
            {
                "marker_id": mid,
                "base_weight": _fmt(base),
                "learned_multiplier": _fmt(multiplier),
                "effective_weight": _fmt(effective),
                "selected_score_scope": str(
                    profile.get("selected_scope_type") or "bootstrap_prior"
                ),
                "selected_score_sample_n": int(profile.get("sample_n") or 0),
                "selected_score_net": int(profile.get("net_score") or 0),
                "selected_score_accuracy": profile.get("accuracy"),
            }
        )
        adjusted.append(item)
    return adjusted


def score_marker_vote(*, vote: str, realised_direction: str) -> tuple[int, int | None]:
    if realised_direction not in {"bullish", "bearish", "neutral"}:
        return 0, None
    if vote not in {"bullish", "bearish", "neutral"}:
        return 0, None
    correct = int(vote == realised_direction)
    return (1 if correct else -1), correct


__all__ = [
    "ENVIRONMENT_VERSION",
    "GOLD_MARKER_BRAIN_VERSION",
    "MARKER_SCORE_HORIZON_MINUTES",
    "apply_learning_to_reasons",
    "build_environment_fingerprint",
    "learning_multiplier",
    "marker_id",
    "score_marker_vote",
    "select_score_profile",
    "toolbox_cycle_coverage",
]
