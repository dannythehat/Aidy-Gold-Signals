from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy.context_packet import CONTEXT_PACKET_VERSION, verify_context_hash

REGIME_DEFINITION_VERSION = "aidy_gold_regime_v1"
REGIME_DIGEST_ALGORITHM = "sha256"
SUPPORTED_SYMBOL = "XAUUSD"
TREND_TIMEFRAMES = ("M15", "H1", "H4")
VOLATILITY_TIMEFRAME = "H1"
VOLATILITY_LOW_LT_BPS = Decimal(20)
VOLATILITY_HIGH_GTE_BPS = Decimal(50)

_DIRECTION_VALUES = {"bullish", "bearish", "flat"}
_SESSION_VALUES = {
    "asia",
    "london",
    "new_york",
    "london_new_york_overlap",
    "off_hours",
    "weekend",
}
_EVENT_VALUES = {"inside_high_impact_window", "clear_current_window", "unknown"}
_LABEL_ORDER = (
    "trend_structure",
    "volatility_band",
    "session",
    "quote_spread_condition",
    "event_timing",
)
_FORBIDDEN_HINDSIGHT_KEYS = {
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
}


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"Invalid regime timestamp: {value}") from exc
    else:
        raise TypeError("Regime timestamps must be timezone-aware datetime or ISO-8601 text.")
    if parsed.tzinfo is None:
        raise ValueError("Regime timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("Volatility values must be finite non-negative decimals.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Volatility values must be finite non-negative decimals.") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError("Volatility values must be finite non-negative decimals.")
    return parsed


def _assert_no_hindsight_fields(value: Any, *, path: str = "context") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_HINDSIGHT_KEYS:
                raise ValueError(f"Hindsight field is forbidden at {path}.{key}.")
            _assert_no_hindsight_fields(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_no_hindsight_fields(item, path=f"{path}[{index}]")


def classify_trend_structure(directions: Mapping[str, Any]) -> str:
    """Classify M15/H1/H4 direction votes without inventing missing evidence."""

    votes = [
        str(directions.get(timeframe) or "unknown")
        for timeframe in TREND_TIMEFRAMES
    ]
    known = [value for value in votes if value in _DIRECTION_VALUES]
    if len(known) < 2:
        return "unknown"

    bullish = sum(value == "bullish" for value in known)
    bearish = sum(value == "bearish" for value in known)
    flat = sum(value == "flat" for value in known)
    if bullish >= 2 and bearish == 0:
        return "bullish_trend"
    if bearish >= 2 and bullish == 0:
        return "bearish_trend"
    if flat >= 2 and bullish == 0 and bearish == 0:
        return "range"
    return "mixed"


def classify_volatility_band(atr_14_bps: Any) -> str:
    """Classify H1 ATR(14) into fixed Day 11 Gold descriptive buckets."""

    value = _decimal_or_none(atr_14_bps)
    if value is None:
        return "unknown"
    if value < VOLATILITY_LOW_LT_BPS:
        return "low"
    if value >= VOLATILITY_HIGH_GTE_BPS:
        return "high"
    return "normal"


def _quote_spread_condition(data_quality: Mapping[str, Any]) -> str:
    quote_state = str(data_quality.get("quote_state") or "unknown")
    freshness = str(data_quality.get("quote_freshness") or "unknown")
    spread_state = str(data_quality.get("spread_state") or "unknown")
    if quote_state != "known" or freshness == "unknown":
        return "unknown"
    if freshness == "stale":
        return "stale_quote"
    if freshness != "fresh":
        return "unknown"
    if spread_state == "known":
        return "fresh_quote_spread_known"
    return "fresh_quote_spread_unknown"


def _event_timing(event_risk: Mapping[str, Any]) -> str:
    if event_risk.get("evidence_state") != "known":
        return "unknown"
    timing = str(event_risk.get("timing_state") or "unknown")
    return timing if timing in _EVENT_VALUES else "unknown"


def _session(session: Mapping[str, Any]) -> str:
    value = str(session.get("computed_session_code") or "unknown")
    return value if value in _SESSION_VALUES else "unknown"


def _trend_evidence(gold: Mapping[str, Any]) -> tuple[dict[str, str], str]:
    timeframes = gold.get("timeframes")
    timeframes = timeframes if isinstance(timeframes, Mapping) else {}
    directions: dict[str, str] = {}
    for timeframe in TREND_TIMEFRAMES:
        payload = timeframes.get(timeframe)
        payload = payload if isinstance(payload, Mapping) else {}
        if payload.get("state") != "known":
            directions[timeframe] = "unknown"
            continue
        direction = str(payload.get("return_5_direction") or "unknown")
        directions[timeframe] = direction if direction in _DIRECTION_VALUES else "unknown"
    return directions, classify_trend_structure(directions)


def _volatility_evidence(gold: Mapping[str, Any]) -> tuple[Any, str]:
    timeframes = gold.get("timeframes")
    timeframes = timeframes if isinstance(timeframes, Mapping) else {}
    payload = timeframes.get(VOLATILITY_TIMEFRAME)
    payload = payload if isinstance(payload, Mapping) else {}
    if payload.get("state") != "known":
        return None, "unknown"
    value = payload.get("atr_14_bps")
    return value, classify_volatility_band(value)


def _validate_context(context: Mapping[str, Any]) -> tuple[datetime, str]:
    if context.get("context_packet_version") != CONTEXT_PACKET_VERSION:
        raise ValueError("Day 11 requires aidy_market_context_v1 input.")
    if context.get("objective_only") is not True:
        raise ValueError("Day 11 accepts objective-only context packets.")
    if context.get("retrospective_history_included") is not False:
        raise ValueError("Retrospective history cannot enter Day 11 regime classification.")
    if context.get("broker_follower_state_included") is not False:
        raise ValueError("Broker/follower state cannot enter Day 11 regime classification.")
    _assert_no_hindsight_fields(context)
    if not verify_context_hash(context):
        raise ValueError("Context hash does not match Day 10 packet contents.")
    symbol = str(context.get("symbol") or "")
    if symbol != SUPPORTED_SYMBOL:
        raise ValueError(f"Day 11 Gold regimes support only {SUPPORTED_SYMBOL}.")
    return _utc(context.get("as_of_utc")), symbol


def compute_regime_digest(packet: Mapping[str, Any]) -> str:
    body = dict(packet)
    body.pop("regime_digest", None)
    return _digest(body)


def verify_regime_digest(packet: Mapping[str, Any]) -> bool:
    supplied = str(packet.get("regime_digest") or "")
    return bool(supplied) and supplied == compute_regime_digest(packet)


def classify_gold_regime(context: Mapping[str, Any]) -> dict[str, Any]:
    """Build one deterministic, PIT-safe Gold regime description from Day 10 context."""

    as_of, symbol = _validate_context(context)
    gold = context.get("gold")
    gold = gold if isinstance(gold, Mapping) else {}
    data_quality = context.get("data_quality")
    data_quality = data_quality if isinstance(data_quality, Mapping) else {}
    session = context.get("session")
    session = session if isinstance(session, Mapping) else {}
    event_risk = context.get("event_risk")
    event_risk = event_risk if isinstance(event_risk, Mapping) else {}

    directions, trend_label = _trend_evidence(gold)
    atr_value, volatility_label = _volatility_evidence(gold)
    labels = {
        "trend_structure": trend_label,
        "volatility_band": volatility_label,
        "session": _session(session),
        "quote_spread_condition": _quote_spread_condition(data_quality),
        "event_timing": _event_timing(event_risk),
    }
    unknown_labels = [name for name in _LABEL_ORDER if labels[name] == "unknown"]
    compound_key = "|".join(f"{name}={labels[name]}" for name in _LABEL_ORDER)

    packet: dict[str, Any] = {
        "regime_definition_version": REGIME_DEFINITION_VERSION,
        "regime_digest_algorithm": REGIME_DIGEST_ALGORITHM,
        "source_context_packet_version": CONTEXT_PACKET_VERSION,
        "source_context_hash": context.get("context_hash"),
        "as_of_utc": as_of.isoformat(),
        "symbol": symbol,
        "objective_only": True,
        "causal_claims_included": False,
        "hindsight_outcomes_included": False,
        "labels": labels,
        "unknown_labels": unknown_labels,
        "all_labels_known": not unknown_labels,
        "compound_regime_key": compound_key,
        "rule_evidence": {
            "trend_structure": {
                "source": "gold.timeframes.{M15,H1,H4}.return_5_direction",
                "directions": directions,
                "rule": (
                    "at least two known votes; >=2 bullish with no bearish => bullish_trend; "
                    ">=2 bearish with no bullish => bearish_trend; >=2 flat with no "
                    "bullish/bearish => range; otherwise mixed"
                ),
            },
            "volatility_band": {
                "source": "gold.timeframes.H1.atr_14_bps",
                "atr_14_bps": atr_value,
                "thresholds_bps": {
                    "low_lt": str(VOLATILITY_LOW_LT_BPS),
                    "normal_gte": str(VOLATILITY_LOW_LT_BPS),
                    "normal_lt": str(VOLATILITY_HIGH_GTE_BPS),
                    "high_gte": str(VOLATILITY_HIGH_GTE_BPS),
                },
                "threshold_basis": "fixed_v1_gold_descriptive_not_outcome_calibrated",
            },
            "session": {
                "source": "session.computed_session_code",
                "value": session.get("computed_session_code"),
            },
            "quote_spread_condition": {
                "source": "data_quality",
                "quote_state": data_quality.get("quote_state"),
                "quote_freshness": data_quality.get("quote_freshness"),
                "spread_state": data_quality.get("spread_state"),
            },
            "event_timing": {
                "source": "event_risk",
                "evidence_state": event_risk.get("evidence_state"),
                "timing_state": event_risk.get("timing_state"),
            },
        },
    }
    packet["regime_digest"] = compute_regime_digest(packet)
    return packet


def regime_distribution(regime_packets: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Return a deterministic label/compound-key count report with no outcome statistics."""

    label_counts = {name: Counter() for name in _LABEL_ORDER}
    compound_counts: Counter[str] = Counter()
    packet_count = 0
    for packet in regime_packets:
        if packet.get("regime_definition_version") != REGIME_DEFINITION_VERSION:
            raise ValueError("Distribution input contains an unsupported regime version.")
        if not verify_regime_digest(packet):
            raise ValueError("Distribution input contains a bad regime digest.")
        labels = packet.get("labels")
        if not isinstance(labels, Mapping):
            raise TypeError("Distribution input labels must be an object.")
        for name in _LABEL_ORDER:
            label_counts[name][str(labels.get(name) or "unknown")] += 1
        compound_counts[str(packet.get("compound_regime_key") or "unknown")] += 1
        packet_count += 1

    return {
        "regime_definition_version": REGIME_DEFINITION_VERSION,
        "packet_count": packet_count,
        "label_counts": {
            name: dict(sorted(counts.items()))
            for name, counts in label_counts.items()
        },
        "compound_regime_counts": dict(sorted(compound_counts.items())),
        "outcome_statistics_included": False,
    }
