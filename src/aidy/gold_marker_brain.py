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

from aidy.gold_cycle_environment import (
    GOLD_CYCLE_ENVIRONMENT_VERSION,
    build_cycle_environment,
)

GOLD_MARKER_BRAIN_VERSION = "aidy_gold_contextual_marker_brain_v2"
ENVIRONMENT_VERSION = GOLD_CYCLE_ENVIRONMENT_VERSION
MARKER_SCORE_HORIZON_MINUTES = 15
_MIN_MULTIPLIER = Decimal("0.500000")
_MAX_MULTIPLIER = Decimal("1.500000")
_FULL_RELIABILITY_SAMPLE = Decimal(20)
_LARGE_MOVE_BPS = Decimal("5.000000")


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


def build_environment_fingerprint(
    *,
    as_of_utc: Any,
    target_window_start_utc: Any,
    session_code: str,
    observed_state: str,
    gold_state: Mapping[str, Any],
    semantic_context: Mapping[str, Any] | None,
    regime: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compatibility wrapper around the canonical cycle-start environment contract."""

    return build_cycle_environment(
        as_of_utc=as_of_utc,
        target_window_start_utc=target_window_start_utc,
        session_code=session_code,
        observed_state=observed_state,
        gold_state=gold_state,
        semantic_context=semantic_context,
        regime=regime,
    )


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
    normalized_mean = mean / Decimal(2)
    reliability = min(Decimal(1), Decimal(sample_n) / _FULL_RELIABILITY_SAMPLE)
    multiplier = Decimal(1) + (Decimal("0.5") * normalized_mean * reliability)
    return max(_MIN_MULTIPLIER, min(_MAX_MULTIPLIER, multiplier))


_SCOPE_MIN_SAMPLES: tuple[tuple[str, int], ...] = (
    ("full_environment", 10),
    ("liquidity_location", 8),
    ("location_structure", 8),
    ("session_liquidity", 7),
    ("session_state_event", 7),
    ("event_regime", 7),
    ("volatility_move_regime", 6),
    ("session_move_regime", 6),
    ("session_phase", 5),
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


def score_marker_vote(
    *,
    vote: str,
    realised_direction: str,
    realised_return_bps: Decimal | None,
) -> tuple[int, int | None]:
    if realised_direction not in {"bullish", "bearish", "neutral"}:
        return 0, None
    if vote not in {"bullish", "bearish", "neutral"}:
        return 0, None
    correct = int(vote == realised_direction)
    magnitude = abs(realised_return_bps or Decimal(0))
    impact = 2 if magnitude >= _LARGE_MOVE_BPS else 1
    return (impact if correct else -impact), correct


__all__ = [
    "ENVIRONMENT_VERSION",
    "GOLD_MARKER_BRAIN_VERSION",
    "MARKER_SCORE_HORIZON_MINUTES",
    "_LARGE_MOVE_BPS",
    "apply_learning_to_reasons",
    "build_environment_fingerprint",
    "learning_multiplier",
    "marker_id",
    "score_marker_vote",
    "select_score_profile",
    "toolbox_cycle_coverage",
]
