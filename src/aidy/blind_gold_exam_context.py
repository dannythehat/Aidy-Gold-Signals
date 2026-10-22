from __future__ import annotations

from typing import Any, Mapping


def _obj(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return None


def frozen_exam_context(episode: Mapping[str, Any]) -> dict[str, Any]:
    """Extract only context already frozen into the immutable AIDY episode.

    This never derives state from the future outcome. Missing dimensions remain
    unknown so the exam cannot manufacture apparent intelligence retrospectively.
    """
    evidence = _obj(episode.get("evidence"))
    regime = _obj(evidence.get("regime_state"))
    setup = _obj(evidence.get("setup_state"))
    summary = _obj(episode.get("context_summary"))

    structure = _text(
        regime.get("trend_structure"), regime.get("market_structure"),
        regime.get("structure"), setup.get("trend_structure")
    )
    volatility = _text(
        regime.get("volatility_state"), regime.get("volatility_regime"),
        regime.get("volatility"), setup.get("volatility_state")
    )
    liquidity = _text(
        regime.get("liquidity_state"), regime.get("liquidity_regime"),
        regime.get("spread_condition"), setup.get("liquidity_state")
    )
    session = _text(
        regime.get("session"), regime.get("session_state"), setup.get("session")
    )
    event = _text(
        regime.get("event_timing"), regime.get("event_state"),
        setup.get("event_timing"), setup.get("event_state")
    )

    # Difficulty is determined exclusively from frozen features.
    difficulty = 1
    if any(value and any(token in value for token in ("transition", "expansion", "contraction", "overlap")) for value in (session, volatility)):
        difficulty = max(difficulty, 2)
    if structure and any(token in structure for token in ("breakout", "sweep", "reversal", "mixed", "uncertain")):
        difficulty = max(difficulty, 3)
    if event and event not in {"none", "normal", "clear", "no_event"}:
        difficulty = max(difficulty, 4)

    known = {k: v for k, v in {
        "market_structure": structure,
        "volatility_state": volatility,
        "liquidity_state": liquidity,
        "session": session,
        "event_state": event,
    }.items() if v is not None}
    return {
        **known,
        "difficulty": difficulty,
        "context_dimension_count": len(known),
        "market_mid": summary.get("market_mid"),
        "as_of_utc": summary.get("as_of_utc"),
        "pit_only": True,
    }
