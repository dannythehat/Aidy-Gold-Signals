from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy.cross_market_asof import (
    CROSS_MARKET_QUERY_VERSION,
    reconstruct_cross_market_as_of,
)
from aidy.feature_engine import FEATURE_DEFINITION_VERSION, PIT_PROVENANCE, TIMEFRAMES
from aidy.macro_event_windows import WINDOW_VERSION, event_class_of
from aidy.market_sessions import session_code_at
from aidy.pit_reconstruction import QUERY_VERSION, normalize_as_of, select_latest_events_as_of

CONTEXT_PACKET_VERSION = "aidy_market_context_v1"
CONTEXT_HASH_ALGORITHM = "sha256"
EVENT_RISK_VERSION = "aidy_event_timing_risk_v1"
AIDY_SIGNAL_STATE_VERSION = "aidy_signal_lifecycle_context_v1"

HIGH_IMPACT_EVENT_CLASSES = (
    "fomc_decision",
    "fomc_press_conference",
    "cpi",
    "ppi",
    "employment_situation",
    "jolts",
    "employment_cost_index",
    "gdp",
    "personal_income_outlays_pce",
    "international_trade",
)

_SIGNAL_STATE_KEYS = {
    "lifecycle_version",
    "state",
    "as_of_utc",
    "last_decision_id",
    "active_signals",
}
_SIGNAL_KEYS = {
    "aidy_signal_id",
    "originating_decision_id",
    "status",
    "direction",
    "entry_type",
    "entry_price",
    "stop_loss",
    "targets",
    "opened_at_utc",
    "updated_at_utc",
}
_FORBIDDEN_STATE_KEYS = {
    "account",
    "account_id",
    "account_state",
    "balance",
    "broker",
    "broker_account",
    "equity",
    "follower",
    "follower_id",
    "free_margin",
    "margin",
    "metaapi",
    "mt5",
    "order",
    "order_id",
    "position",
    "position_id",
    "super_signals",
    "ticket",
    "vantage",
}
_FORBIDDEN_DECISION_KEYS = {
    "available_after_utc",
    "counterfactual_digest",
    "counterfactual_version",
    "future_return",
    "future_returns",
    "horizon_assessments",
    "mae",
    "mfe",
    "move_bundle",
    "move_bundle_version",
    "outcome",
    "outcome_label",
    "outcome_state",
    "outcomes",
    "path_class",
    "pnl",
    "primary_classification",
    "realized_pnl",
    "stop_hit",
    "target_hit",
    "trade_outcome_bundle",
    "trade_outcome_bundle_version",
}


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _decimal_text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        raise ValueError("Price values must be finite decimals.")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Price values must be finite decimals.") from exc
    if not number.is_finite():
        raise ValueError("Price values must be finite decimals.")
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("Context datetimes must be timezone-aware.")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _assert_clean_decision_evidence(value: Any, *, path: str) -> None:
    """Reject future/evaluation data and retrospective lineage from PIT decision evidence."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_DECISION_KEYS:
                raise ValueError(f"Future/outcome field is forbidden at {path}.{key}.")
            if normalized == "future_derived" and item is not False:
                raise ValueError(f"Future-derived evidence is forbidden at {path}.{key}.")
            if normalized == "evaluation_only" and item is not False:
                raise ValueError(f"Evaluation-only evidence is forbidden at {path}.{key}.")
            if normalized == "provenance_class" and str(item) == "retrospective_history":
                raise ValueError(f"Retrospective-only evidence is forbidden at {path}.{key}.")
            if normalized == "pit_eligible" and item is False:
                raise ValueError(f"Non-PIT evidence is forbidden at {path}.{key}.")
            _assert_clean_decision_evidence(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_clean_decision_evidence(item, path=f"{path}[{index}]")


def _validate_feature_packet(
    packet: Mapping[str, Any],
    *,
    as_of: datetime,
    symbol: str,
) -> dict[str, Any]:
    normalized = _json_safe(dict(packet))
    if normalized.get("feature_definition_version") != FEATURE_DEFINITION_VERSION:
        raise ValueError("Unsupported Gold feature packet version.")
    if normalized.get("mode") != "pit":
        raise ValueError("Day 10 context accepts PIT Gold features only.")
    if (
        normalized.get("provenance_class") != PIT_PROVENANCE
        or normalized.get("pit_eligible") is not True
    ):
        raise ValueError("Retrospective or non-PIT Gold features cannot enter Day 10 context.")
    if normalize_as_of(str(normalized.get("as_of_utc"))) != as_of:
        raise ValueError("Gold feature packet as-of timestamp does not match context as-of.")
    if str(normalized.get("symbol") or "") != symbol:
        raise ValueError("Gold feature packet symbol does not match context symbol.")

    supplied_digest = str(normalized.get("feature_packet_digest") or "")
    digest_body = dict(normalized)
    digest_body.pop("feature_packet_digest", None)
    if not supplied_digest or supplied_digest != _digest(digest_body):
        raise ValueError("Gold feature packet digest does not match its contents.")
    _assert_clean_decision_evidence(normalized, path="feature_packet")
    return normalized


def _structured_event(row: Mapping[str, Any]) -> dict[str, Any]:
    value = row.get("structured_data")
    if isinstance(value, Mapping):
        return dict(value)
    value = row.get("structured_data_json")
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _optional_utc(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return normalize_as_of(value)
    except (TypeError, ValueError):
        return None


def _event_record(row: Mapping[str, Any], *, as_of: datetime) -> dict[str, Any] | None:
    event_class = event_class_of(row)
    if event_class not in HIGH_IMPACT_EVENT_CLASSES:
        return None

    structured = _structured_event(row)
    observed = _optional_utc(row.get("first_observed_at"))
    if observed is None or observed > as_of:
        return None
    scheduled = _optional_utc(structured.get("scheduled_at"))
    published = _optional_utc(row.get("published_at"))
    minutes_to_scheduled = (
        None
        if scheduled is None
        else int((scheduled - as_of).total_seconds() / 60)
    )

    provenance = {
        "source": row.get("source"),
        "external_id": row.get("external_id"),
        "evidence_id": row.get("evidence_id"),
        "load_identity": row.get("load_identity"),
        "archive_key": row.get("archive_key"),
        "payload_digest": row.get("payload_digest"),
        "source_url": structured.get("source_url"),
        "revision_index": int(row.get("revision_index") or 0),
        "first_observed_at": observed.isoformat(),
    }
    return {
        "event_class": event_class,
        "phase": structured.get("phase"),
        "headline": row.get("headline"),
        "scheduled_at": scheduled.isoformat() if scheduled else None,
        "published_at": published.isoformat() if published else None,
        "first_observed_at": observed.isoformat(),
        "minutes_to_scheduled": minutes_to_scheduled,
        "provenance": provenance,
    }


def _build_event_risk(
    rows: Iterable[Mapping[str, Any]],
    *,
    as_of: datetime,
    evidence_state: str,
    minutes_before: int,
    minutes_after: int,
) -> dict[str, Any]:
    if evidence_state not in {"known", "unknown"}:
        raise ValueError("macro_evidence_state must be 'known' or 'unknown'.")
    if minutes_before < 0 or minutes_after < 0:
        raise ValueError("Macro event-window minutes must be non-negative.")

    records = [
        record
        for row in select_latest_events_as_of(rows, as_of=as_of)
        if (record := _event_record(row, as_of=as_of)) is not None
    ]
    records.sort(
        key=lambda item: (
            item["scheduled_at"] or "9999",
            item["first_observed_at"],
            item["event_class"],
            str(item["provenance"].get("source") or ""),
            str(item["provenance"].get("external_id") or ""),
        )
    )

    in_window: list[dict[str, Any]] = []
    for record in records:
        scheduled = _optional_utc(record["scheduled_at"])
        published = _optional_utc(record["published_at"])
        observed = _optional_utc(record["first_observed_at"])

        scheduled_in_window = False
        if scheduled is not None:
            delta = (scheduled - as_of).total_seconds() / 60
            scheduled_in_window = -minutes_after <= delta <= minutes_before

        phase = str(record.get("phase") or "").lower()
        release_in_window = False
        if scheduled is None or phase == "released":
            release_in_window = any(
                candidate is not None
                and -minutes_after <= (candidate - as_of).total_seconds() / 60 <= 0
                for candidate in (published, observed)
            )

        if scheduled_in_window or release_in_window:
            in_window.append(record)

    upcoming = [
        record
        for record in records
        if record["scheduled_at"] is not None
        and _optional_utc(record["scheduled_at"]) >= as_of
    ]
    if evidence_state == "unknown":
        timing_state = "unknown"
    elif in_window:
        timing_state = "inside_high_impact_window"
    else:
        timing_state = "clear_current_window"

    return {
        "risk_version": EVENT_RISK_VERSION,
        "source_window_version": WINDOW_VERSION,
        "evidence_state": evidence_state,
        "timing_state": timing_state,
        "minutes_before": minutes_before,
        "minutes_after": minutes_after,
        "high_impact_event_classes": list(HIGH_IMPACT_EVENT_CLASSES),
        "observations_considered": len(records),
        "events_in_window": in_window,
        "next_scheduled_event": upcoming[0] if upcoming else None,
    }


def _reject_external_account_state(value: Any, *, path: str = "aidy_signal_state") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_STATE_KEYS:
                raise ValueError(f"Forbidden broker/follower state field at {path}.{key}.")
            _reject_external_account_state(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_external_account_state(item, path=f"{path}[{index}]")


def _normalize_aidy_signal_state(
    value: Mapping[str, Any] | None,
    *,
    as_of: datetime,
) -> dict[str, Any]:
    if value is None:
        state = {
            "state_version": AIDY_SIGNAL_STATE_VERSION,
            "evidence_state": "unknown",
            "lifecycle_state": "unknown",
            "lifecycle_version": None,
            "as_of_utc": as_of.isoformat(),
            "last_decision_id": None,
            "active_signals": [],
        }
        state["state_digest"] = _digest(state)
        return state

    _reject_external_account_state(value)
    unknown_top = set(value) - _SIGNAL_STATE_KEYS
    if unknown_top:
        raise ValueError(f"Unsupported AIDY signal-state fields: {sorted(unknown_top)}")
    if value.get("as_of_utc") is not None and normalize_as_of(value["as_of_utc"]) != as_of:
        raise ValueError("AIDY signal lifecycle as-of does not match context as-of.")

    raw_signals = value.get("active_signals") or []
    if not isinstance(raw_signals, (list, tuple)):
        raise TypeError("active_signals must be a list.")

    active_signals: list[dict[str, Any]] = []
    for raw in raw_signals:
        if not isinstance(raw, Mapping):
            raise TypeError("Each active AIDY signal must be an object.")
        unknown = set(raw) - _SIGNAL_KEYS
        if unknown:
            raise ValueError(f"Unsupported AIDY active-signal fields: {sorted(unknown)}")

        signal_id = str(raw.get("aidy_signal_id") or "").strip()
        if not signal_id:
            raise ValueError("Each active AIDY signal requires aidy_signal_id.")

        opened_at = _optional_utc(raw.get("opened_at_utc"))
        updated_at = _optional_utc(raw.get("updated_at_utc"))
        if raw.get("opened_at_utc") is not None and opened_at is None:
            raise ValueError("opened_at_utc must be timezone-aware.")
        if raw.get("updated_at_utc") is not None and updated_at is None:
            raise ValueError("updated_at_utc must be timezone-aware.")
        if (opened_at and opened_at > as_of) or (updated_at and updated_at > as_of):
            raise ValueError("AIDY signal lifecycle cannot contain future state.")

        active_signals.append(
            {
                "aidy_signal_id": signal_id,
                "originating_decision_id": raw.get("originating_decision_id"),
                "status": raw.get("status"),
                "direction": raw.get("direction"),
                "entry_type": raw.get("entry_type"),
                "entry_price": (
                    None
                    if raw.get("entry_price") is None
                    else _decimal_text(raw.get("entry_price"))
                ),
                "stop_loss": (
                    None
                    if raw.get("stop_loss") is None
                    else _decimal_text(raw.get("stop_loss"))
                ),
                "targets": [_decimal_text(target) for target in (raw.get("targets") or [])],
                "opened_at_utc": opened_at.isoformat() if opened_at else None,
                "updated_at_utc": updated_at.isoformat() if updated_at else None,
            }
        )
    active_signals.sort(key=lambda item: item["aidy_signal_id"])

    state = {
        "state_version": AIDY_SIGNAL_STATE_VERSION,
        "evidence_state": "known",
        "lifecycle_state": str(value.get("state") or ("active" if active_signals else "none")),
        "lifecycle_version": value.get("lifecycle_version"),
        "as_of_utc": as_of.isoformat(),
        "last_decision_id": value.get("last_decision_id"),
        "active_signals": active_signals,
    }
    state["state_digest"] = _digest(state)
    return state


def _build_data_quality(
    *,
    feature_packet: Mapping[str, Any],
    event_risk: Mapping[str, Any],
    cross_market: Mapping[str, Any],
    signal_state: Mapping[str, Any],
    quote_stale_after_seconds: int,
) -> dict[str, Any]:
    timeframes = feature_packet.get("timeframes")
    timeframes = timeframes if isinstance(timeframes, Mapping) else {}
    missing_timeframes = [
        timeframe
        for timeframe in TIMEFRAMES
        if not isinstance(timeframes.get(timeframe), Mapping)
        or timeframes[timeframe].get("state") != "known"
    ]

    quote = feature_packet.get("quote_context")
    quote = quote if isinstance(quote, Mapping) else {}
    quote_state = str(quote.get("quote_state") or "unknown")
    quote_age = (
        int(quote["quote_age_seconds"])
        if quote.get("quote_age_seconds") is not None
        else None
    )
    if quote_state != "known" or quote_age is None:
        quote_freshness = "unknown"
    elif quote_age > quote_stale_after_seconds:
        quote_freshness = "stale"
    else:
        quote_freshness = "fresh"

    series = cross_market.get("series")
    series = series if isinstance(series, Mapping) else {}
    missing_cross_market = sorted(
        series_id
        for series_id, payload in series.items()
        if not isinstance(payload, Mapping) or payload.get("state") != "known"
    )
    cross_market_ages = {
        series_id: payload.get("observation_age_days")
        for series_id, payload in sorted(series.items())
        if isinstance(payload, Mapping)
    }

    spread_state = "known" if quote.get("spread") is not None else "unknown"
    flags: list[str] = []
    if missing_timeframes:
        flags.append("gold_timeframes_missing")
    if quote_freshness != "fresh":
        flags.append(f"quote_{quote_freshness}")
    if spread_state == "unknown":
        flags.append("spread_unknown")
    if event_risk.get("evidence_state") != "known":
        flags.append("macro_evidence_unknown")
    if missing_cross_market:
        flags.append("cross_market_series_missing")
    if signal_state.get("evidence_state") != "known":
        flags.append("aidy_signal_state_unknown")

    return {
        "quote_stale_after_seconds": quote_stale_after_seconds,
        "missing_gold_timeframes": missing_timeframes,
        "quote_state": quote_state,
        "quote_age_seconds": quote_age,
        "quote_freshness": quote_freshness,
        "spread_state": spread_state,
        "macro_evidence_state": event_risk.get("evidence_state"),
        "cross_market_missing_series": missing_cross_market,
        "cross_market_observation_age_days": cross_market_ages,
        "aidy_signal_state": signal_state.get("evidence_state"),
        "flags": flags,
    }


def compute_context_hash(packet: Mapping[str, Any]) -> str:
    body = _json_safe(dict(packet))
    body.pop("context_hash", None)
    return _digest(body)


def verify_context_hash(packet: Mapping[str, Any]) -> bool:
    supplied = str(packet.get("context_hash") or "")
    return bool(supplied) and supplied == compute_context_hash(packet)


def build_context_packet(
    *,
    as_of: datetime | str,
    symbol: str,
    feature_packet: Mapping[str, Any],
    event_rows: Iterable[Mapping[str, Any]],
    macro_evidence_state: str,
    cross_market_rows: Iterable[Mapping[str, Any]],
    aidy_signal_state: Mapping[str, Any] | None = None,
    quote_stale_after_seconds: int = 300,
    event_minutes_before: int = 60,
    event_minutes_after: int = 180,
) -> dict[str, Any]:
    cutoff = normalize_as_of(as_of)
    if not symbol.strip():
        raise ValueError("symbol is required.")
    if quote_stale_after_seconds < 0:
        raise ValueError("quote_stale_after_seconds must be non-negative.")

    gold = _validate_feature_packet(feature_packet, as_of=cutoff, symbol=symbol)
    event_risk = _build_event_risk(
        event_rows,
        as_of=cutoff,
        evidence_state=macro_evidence_state,
        minutes_before=event_minutes_before,
        minutes_after=event_minutes_after,
    )
    cross_market = reconstruct_cross_market_as_of(cross_market_rows, as_of=cutoff)
    signal_state = _normalize_aidy_signal_state(aidy_signal_state, as_of=cutoff)
    data_quality = _build_data_quality(
        feature_packet=gold,
        event_risk=event_risk,
        cross_market=cross_market,
        signal_state=signal_state,
        quote_stale_after_seconds=quote_stale_after_seconds,
    )
    quote = gold.get("quote_context")
    quote = quote if isinstance(quote, Mapping) else {}

    packet: dict[str, Any] = {
        "context_packet_version": CONTEXT_PACKET_VERSION,
        "context_hash_algorithm": CONTEXT_HASH_ALGORITHM,
        "as_of_utc": cutoff.isoformat(),
        "symbol": symbol,
        "objective_only": True,
        "retrospective_history_included": False,
        "broker_follower_state_included": False,
        "source_contract_versions": {
            "pit_query": QUERY_VERSION,
            "gold_features": FEATURE_DEFINITION_VERSION,
            "macro_event_window": WINDOW_VERSION,
            "cross_market_query": CROSS_MARKET_QUERY_VERSION,
        },
        "gold": gold,
        "session": {
            "computed_session_code": session_code_at(cutoff),
            "recorded_session_code": quote.get("recorded_session_code"),
            "session_code_consistent": quote.get("session_code_consistent"),
        },
        "event_risk": event_risk,
        "cross_market": cross_market,
        "aidy_signal_lifecycle": signal_state,
        "data_quality": data_quality,
        "provenance": {
            "gold_feature_packet_digest": gold.get("feature_packet_digest"),
            "gold_source_links": gold.get("source_links"),
            "macro_event_provenance": [
                item["provenance"] for item in event_risk["events_in_window"]
            ],
            "next_macro_event_provenance": (
                None
                if event_risk["next_scheduled_event"] is None
                else event_risk["next_scheduled_event"]["provenance"]
            ),
            "cross_market_series": {
                series_id: payload.get("provenance")
                for series_id, payload in sorted(cross_market["series"].items())
            },
            "aidy_signal_state_digest": signal_state["state_digest"],
        },
    }
    packet["context_hash"] = compute_context_hash(packet)
    return packet
