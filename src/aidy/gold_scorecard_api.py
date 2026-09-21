from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from aidy.gold_marker_brain import MARKER_SCORE_HORIZON_MINUTES
from aidy.provider_context_api import _authorized

GOLD_SCORECARD_API_VERSION = "aidy_gold_scorecard_api_v1"


def _row(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    try:
        return dict(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise TypeError("Unexpected D1 row shape.") from exc


def _results(value: object) -> list[dict[str, Any]]:
    rows = getattr(value, "results", None)
    if rows is None and isinstance(value, dict):
        rows = value.get("results")
    if rows is None:
        return []
    return [row for item in rows if (row := _row(item)) is not None]


def _json_mapping(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _mapping_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _build_scorecard_payload(
    *,
    latest: Mapping[str, Any],
    global_scores: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    evidence = _json_mapping(latest.get("evidence_json"))
    environment = _json_mapping(latest.get("environment_json"))
    dimensions = environment.get("learning_dimensions")
    dimensions = dict(dimensions) if isinstance(dimensions, Mapping) else {}

    trace = _mapping_list(evidence.get("tool_reasoning_trace"))
    reasons = _mapping_list(evidence.get("all_directional_reasons"))
    status_counts: dict[str, int] = {}
    action_counts: dict[str, int] = {}
    for item in trace:
        status = str(item.get("status") or "unknown")
        action = str(item.get("reasoning_action") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        action_counts[action] = action_counts.get(action, 0) + 1

    calculators = [
        {
            "tool": str(item.get("surface") or ""),
            "vote": str(item.get("vote") or "neutral"),
            "base_weight": item.get("base_weight"),
            "learned_multiplier": item.get("learned_multiplier"),
            "effective_weight": item.get("effective_weight"),
            "selected_scope": str(item.get("selected_score_scope") or "bootstrap_prior"),
            "selected_context": str(
                item.get("selected_score_context") or "bootstrap_prior"
            ),
            "sample_n": int(item.get("selected_score_sample_n") or 0),
            "net_score": int(item.get("selected_score_net") or 0),
            "accuracy": item.get("selected_score_accuracy"),
        }
        for item in reasons
    ]

    return {
        "api_version": GOLD_SCORECARD_API_VERSION,
        "cycle": {
            "cycle_view_id": str(latest.get("cycle_view_id") or ""),
            "window_start_utc": latest.get("window_start_utc"),
            "window_end_utc": latest.get("window_end_utc"),
            "decided_at_utc": latest.get("decided_at_utc"),
            "observed_state": latest.get("observed_state"),
            "view_direction": latest.get("view_direction"),
            "view_confidence": latest.get("view_confidence"),
            "realised_direction": latest.get("realised_direction"),
            "return_bps": latest.get("return_bps"),
            "exact_direction_correct": latest.get("exact_direction_correct"),
            "resolved_at_utc": latest.get("resolved_at_utc"),
        },
        "environment": {
            "environment_version": latest.get("environment_version"),
            "session": dimensions.get("session"),
            "session_phase": dimensions.get("session_phase"),
            "liquidity_intensity": dimensions.get("liquidity_intensity"),
            "liquidity_signature": dimensions.get("liquidity_signature"),
            "nearest_reference": dimensions.get("nearest_reference"),
            "nearest_reference_side": dimensions.get("nearest_reference_side"),
            "nearest_reference_distance_band": dimensions.get(
                "nearest_reference_distance_band"
            ),
            "h1_direction": dimensions.get("h1_direction"),
            "h4_direction": dimensions.get("h4_direction"),
            "volatility_state": dimensions.get("volatility_state"),
            "event_proximity": dimensions.get("event_proximity"),
            "compound_regime": dimensions.get("compound_regime"),
        },
        "toolbox": {
            "known_count": len(trace),
            "status_counts": status_counts,
            "reasoning_action_counts": action_counts,
            "tools": trace,
        },
        "active_directional_calculators": calculators,
        "global_scorebook": [dict(row) for row in global_scores],
        "research_only": True,
        "future_values_used": bool(latest.get("future_values_used")),
        "live_money_execution_allowed": False,
    }


async def build_gold_scorecard(d1: Any) -> dict[str, Any] | None:
    latest = _row(
        await d1.prepare(
            """
            SELECT
                v.cycle_view_id,v.window_start_utc,v.window_end_utc,v.decided_at_utc,
                v.observed_state,v.view_direction,v.view_confidence,v.evidence_json,
                v.future_values_used,v.live_money_execution_allowed,
                e.environment_json,e.environment_version,
                o.realised_direction,o.return_bps,o.exact_direction_correct,o.resolved_at_utc
            FROM aidy_gold_cycle_views v
            LEFT JOIN aidy_gold_cycle_environments e
              ON e.cycle_view_id=v.cycle_view_id
            LEFT JOIN aidy_gold_cycle_outcomes o
              ON o.cycle_view_id=v.cycle_view_id
            ORDER BY v.window_start_utc DESC
            LIMIT 1
            """
        ).first()
    )
    if latest is None:
        return None

    score_result = await d1.prepare(
        """
        SELECT
            marker_id,surface,source_path,sample_n,correct_n,incorrect_n,neutral_n,
            net_score,score_mean,accuracy,last_resolved_at_utc
        FROM aidy_gold_marker_context_scores
        WHERE scope_type='global' AND horizon_minutes=?
        ORDER BY sample_n DESC,net_score DESC,surface,marker_id
        """
    ).bind(MARKER_SCORE_HORIZON_MINUTES).all()
    return _build_scorecard_payload(
        latest=latest,
        global_scores=_results(score_result),
    )


async def gold_scorecard_response(request: Any, env: Any) -> Any:
    """Return AIDY's latest private read-only Gold learning scorecard."""

    from workers import Response

    if request.method != "GET":
        return Response("Method not allowed", status=405)
    if not _authorized(request, env):
        return Response("Unauthorized", status=401)

    payload = await build_gold_scorecard(env.AIDY_OPS)
    if payload is None:
        return Response.json(
            {"ok": False, "error": "no_gold_cycle_scorecard"},
            status=404,
        )
    return Response.json({"ok": True, "scorecard": payload})


__all__ = [
    "GOLD_SCORECARD_API_VERSION",
    "_build_scorecard_payload",
    "build_gold_scorecard",
    "gold_scorecard_response",
]
