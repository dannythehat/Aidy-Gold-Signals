from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from hashlib import sha256
from itertools import pairwise
from typing import Any

from aidy.historical_backfill import RETROSPECTIVE_PROVENANCE
from aidy.market_sessions import session_code_at

FEATURE_DEFINITION_VERSION = "aidy_gold_features_v1"
PIT_PROVENANCE = "pit_observed"
FEATURE_SCALE = Decimal("0.000001")
TIMEFRAMES = ("M1", "M5", "M15", "H1", "H4", "D1")
_TIMEFRAME_ALIASES = {
    "M1": "M1",
    "1M": "M1",
    "1MIN": "M1",
    "M5": "M5",
    "5M": "M5",
    "5MIN": "M5",
    "M15": "M15",
    "15M": "M15",
    "15MIN": "M15",
    "H1": "H1",
    "1H": "H1",
    "H4": "H4",
    "4H": "H4",
    "D1": "D1",
    "1D": "D1",
}
_MAX_WINDOW = 2048


@dataclass(frozen=True, slots=True)
class Candle:
    timeframe: str
    open_time_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    identity: str
    provenance: dict[str, Any]


def _utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"Invalid timestamp: {value}") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise TypeError("Timestamp must be a timezone-aware datetime or ISO-8601 string.")
    if parsed.tzinfo is None:
        raise ValueError("Feature timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _decimal(value: Any, *, field: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{field} is required.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a finite decimal.") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be a finite decimal.")
    return parsed


def _canonical_timeframe(value: Any) -> str:
    raw = str(value or "").strip().upper().replace(" ", "")
    try:
        return _TIMEFRAME_ALIASES[raw]
    except KeyError as exc:
        raise ValueError(f"Unsupported feature timeframe: {value}") from exc


def _fmt(value: Decimal | None) -> str | None:
    if value is None:
        return None
    with localcontext() as ctx:
        ctx.prec = 34
        rounded = value.quantize(FEATURE_SCALE, rounding=ROUND_HALF_EVEN)
    if rounded == 0:
        return "0"
    text = format(rounded, "f").rstrip("0").rstrip(".")
    return text or "0"


def _ratio_bps(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == 0:
        return None
    with localcontext() as ctx:
        ctx.prec = 34
        return numerator / denominator * Decimal(10000)


def _source_provenance(row: Mapping[str, Any], *, mode: str) -> tuple[str, dict[str, Any]]:
    if mode == "retrospective":
        if str(row.get("provenance_class") or "") != RETROSPECTIVE_PROVENANCE:
            raise ValueError("Retrospective feature rows require retrospective_history provenance.")
        if row.get("pit_eligible") is not False:
            raise ValueError("Retrospective feature rows must be pit_eligible=false.")
        identity = str(row.get("research_identity") or "").strip()
        if not identity:
            raise ValueError("Retrospective feature rows require research_identity.")
        return identity, {
            "identity": identity,
            "provenance_class": RETROSPECTIVE_PROVENANCE,
            "pit_eligible": False,
            "source": row.get("source"),
            "source_file_sha256": row.get("source_file_sha256"),
            "source_payload_sha256": row.get("source_payload_sha256"),
            "derivation_version": row.get("derivation_version"),
        }

    if mode != "pit":
        raise ValueError("Feature mode must be 'pit' or 'retrospective'.")
    if row.get("provenance_class") == RETROSPECTIVE_PROVENANCE or row.get("pit_eligible") is False:
        raise ValueError("Retrospective-only evidence cannot enter a PIT feature packet.")
    identity = str(row.get("load_identity") or "").strip()
    if not identity:
        raise ValueError("PIT candle rows require load_identity.")
    return identity, {
        "identity": identity,
        "provenance_class": PIT_PROVENANCE,
        "pit_eligible": True,
        "evidence_id": row.get("evidence_id"),
        "archive_key": row.get("archive_key"),
        "payload_digest": row.get("payload_digest"),
        "source": row.get("source"),
    }


def _candle_from_row(
    row: Mapping[str, Any],
    *,
    as_of: datetime,
    symbol: str,
    mode: str,
) -> Candle | None:
    if str(row.get("symbol") or "") != symbol:
        return None
    if mode == "pit" and (
        row.get("provenance_class") == RETROSPECTIVE_PROVENANCE
        or row.get("pit_eligible") is False
    ):
        raise ValueError("Retrospective-only evidence cannot enter a PIT feature packet.")
    open_time = _utc(row.get("open_time_utc"))
    if open_time > as_of:
        return None
    if mode == "pit":
        observed = _utc(row.get("first_observed_at"))
        if observed > as_of:
            return None
    timeframe = _canonical_timeframe(row.get("timeframe"))
    open_price = _decimal(row.get("open"), field="open")
    high = _decimal(row.get("high"), field="high")
    low = _decimal(row.get("low"), field="low")
    close = _decimal(row.get("close"), field="close")
    if high < low or high < open_price or high < close or low > open_price or low > close:
        raise ValueError("Candle OHLC geometry is invalid.")
    identity, provenance = _source_provenance(row, mode=mode)
    return Candle(timeframe, open_time, open_price, high, low, close, identity, provenance)


def normalize_candles(
    rows: Iterable[Mapping[str, Any]],
    *,
    as_of: datetime | str,
    symbol: str,
    mode: str,
) -> dict[str, list[Candle]]:
    cutoff = _utc(as_of)
    if not symbol.strip():
        raise ValueError("symbol is required.")
    grouped = {timeframe: [] for timeframe in TIMEFRAMES}
    seen: set[tuple[str, datetime]] = set()
    for row in rows:
        candle = _candle_from_row(row, as_of=cutoff, symbol=symbol, mode=mode)
        if candle is None:
            continue
        logical_key = (candle.timeframe, candle.open_time_utc)
        if logical_key in seen:
            raise ValueError("Feature input contains duplicate logical candles.")
        seen.add(logical_key)
        grouped[candle.timeframe].append(candle)
    for timeframe in TIMEFRAMES:
        grouped[timeframe].sort(key=lambda item: item.open_time_utc)
        if len(grouped[timeframe]) > _MAX_WINDOW:
            grouped[timeframe] = grouped[timeframe][-_MAX_WINDOW:]
    return grouped


def _return_bps(current: Decimal, previous: Decimal) -> Decimal | None:
    return _ratio_bps(current - previous, previous)


def _atr_bps(candles: list[Candle], period: int = 14) -> Decimal | None:
    if len(candles) < period + 1:
        return None
    sample = candles[-(period + 1):]
    true_ranges: list[Decimal] = []
    for previous, current in pairwise(sample):
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    with localcontext() as ctx:
        ctx.prec = 34
        average = sum(true_ranges, Decimal(0)) / Decimal(period)
    return _ratio_bps(average, sample[-1].close)


def _realized_vol_bps(candles: list[Candle], period: int = 20) -> Decimal | None:
    if len(candles) < period + 1:
        return None
    sample = candles[-(period + 1):]
    returns: list[Decimal] = []
    for previous, current in pairwise(sample):
        if previous.close == 0:
            return None
        with localcontext() as ctx:
            ctx.prec = 34
            returns.append(current.close / previous.close - Decimal(1))
    with localcontext() as ctx:
        ctx.prec = 34
        mean = sum(returns, Decimal(0)) / Decimal(period)
        variance = sum(((item - mean) ** 2 for item in returns), Decimal(0)) / Decimal(period)
        return variance.sqrt() * Decimal(10000)


def _recent_extremes(candles: list[Candle], period: int = 20) -> dict[str, str | None]:
    if len(candles) < period:
        return {
            "recent_high_20": None,
            "recent_low_20": None,
            "distance_to_high_20_bps": None,
            "distance_from_low_20_bps": None,
            "range_position_20": None,
        }
    sample = candles[-period:]
    high = max(item.high for item in sample)
    low = min(item.low for item in sample)
    close = sample[-1].close
    span = high - low
    with localcontext() as ctx:
        ctx.prec = 34
        position = None if span == 0 else (close - low) / span
    return {
        "recent_high_20": _fmt(high),
        "recent_low_20": _fmt(low),
        "distance_to_high_20_bps": _fmt(_ratio_bps(high - close, close)),
        "distance_from_low_20_bps": _fmt(_ratio_bps(close - low, close)),
        "range_position_20": _fmt(position),
    }


def _confirmed_swing(
    candles: list[Candle],
    *,
    high: bool,
    wing: int = 2,
) -> dict[str, str] | None:
    if len(candles) < wing * 2 + 1:
        return None
    for index in range(len(candles) - wing - 1, wing - 1, -1):
        candidate = candles[index]
        neighbors = candles[index - wing:index] + candles[index + 1:index + wing + 1]
        if high:
            if all(candidate.high > item.high for item in neighbors):
                return {"open_time_utc": candidate.open_time_utc.isoformat(), "price": _fmt(candidate.high)}
        elif all(candidate.low < item.low for item in neighbors):
            return {"open_time_utc": candidate.open_time_utc.isoformat(), "price": _fmt(candidate.low)}
    return None


def _timeframe_features(candles: list[Candle]) -> dict[str, Any]:
    if not candles:
        return {
            "state": "unknown",
            "bars_available": 0,
            "source_identities": [],
            "latest_open_time_utc": None,
            "latest_close": None,
            "return_1_bps": None,
            "return_5_bps": None,
            "return_5_direction": "unknown",
            "body_bps": None,
            "range_bps": None,
            "close_location": None,
            "atr_14_bps": None,
            "realized_vol_20_bps": None,
            "recent_high_20": None,
            "recent_low_20": None,
            "distance_to_high_20_bps": None,
            "distance_from_low_20_bps": None,
            "range_position_20": None,
            "confirmed_swing_high": None,
            "confirmed_swing_low": None,
            "seconds_since_previous_bar": None,
        }
    latest = candles[-1]
    previous = candles[-2] if len(candles) >= 2 else None
    return_1 = None if previous is None else _return_bps(latest.close, previous.close)
    return_5 = None
    if len(candles) >= 6:
        return_5 = _return_bps(latest.close, candles[-6].close)
    direction = "unknown"
    if return_5 is not None:
        direction = "bullish" if return_5 > 0 else "bearish" if return_5 < 0 else "flat"
    span = latest.high - latest.low
    close_location = None
    if span != 0:
        with localcontext() as ctx:
            ctx.prec = 34
            close_location = (latest.close - latest.low) / span
    elapsed = None
    if previous is not None:
        elapsed = int((latest.open_time_utc - previous.open_time_utc).total_seconds())
    result: dict[str, Any] = {
        "state": "known",
        "bars_available": len(candles),
        "source_identities": [item.identity for item in candles[-21:]],
        "latest_open_time_utc": latest.open_time_utc.isoformat(),
        "latest_close": _fmt(latest.close),
        "return_1_bps": _fmt(return_1),
        "return_5_bps": _fmt(return_5),
        "return_5_direction": direction,
        "body_bps": _fmt(_ratio_bps(latest.close - latest.open, latest.open)),
        "range_bps": _fmt(_ratio_bps(span, latest.open)),
        "close_location": _fmt(close_location),
        "atr_14_bps": _fmt(_atr_bps(candles)),
        "realized_vol_20_bps": _fmt(_realized_vol_bps(candles)),
        "confirmed_swing_high": _confirmed_swing(candles, high=True),
        "confirmed_swing_low": _confirmed_swing(candles, high=False),
        "seconds_since_previous_bar": elapsed,
    }
    result.update(_recent_extremes(candles))
    return result


def _range_context(candles: list[Candle], *, as_of: datetime) -> dict[str, Any]:
    if not candles:
        return {
            "utc_day": {
                "state": "unknown",
                "bars": 0,
                "high": None,
                "low": None,
                "position": None,
                "source_identities": [],
            },
            "session": {
                "state": "unknown",
                "code": session_code_at(as_of),
                "bars": 0,
                "high": None,
                "low": None,
                "position": None,
                "source_identities": [],
            },
        }
    current = candles[-1].close
    day_rows = [item for item in candles if item.open_time_utc.date() == as_of.date()]
    current_session = session_code_at(as_of)
    session_rows: list[Candle] = []
    for item in reversed(candles):
        if item.open_time_utc.date() != as_of.date() or session_code_at(item.open_time_utc) != current_session:
            if session_rows:
                break
            continue
        session_rows.append(item)
    session_rows.reverse()

    def summarize(rows: list[Candle], code: str | None = None) -> dict[str, Any]:
        if not rows:
            output: dict[str, Any] = {
                "state": "unknown",
                "bars": 0,
                "high": None,
                "low": None,
                "position": None,
                "source_identities": [],
            }
        else:
            high = max(item.high for item in rows)
            low = min(item.low for item in rows)
            span = high - low
            position = None
            if span != 0:
                with localcontext() as ctx:
                    ctx.prec = 34
                    position = (current - low) / span
            output = {
                "state": "known",
                "bars": len(rows),
                "high": _fmt(high),
                "low": _fmt(low),
                "position": _fmt(position),
                "source_identities": [item.identity for item in rows],
            }
        if code is not None:
            output["code"] = code
        return output

    return {
        "utc_day": summarize(day_rows),
        "session": summarize(session_rows, current_session),
    }


def _snapshot_context(
    snapshot: Mapping[str, Any] | None,
    *,
    as_of: datetime,
    mode: str,
) -> dict[str, Any]:
    computed_session = session_code_at(as_of)
    if snapshot is None:
        return {
            "state": "unknown",
            "capture_status": None,
            "quote_state": "unknown",
            "quote_age_seconds": None,
            "quote_time": None,
            "bid": None,
            "ask": None,
            "mid": None,
            "spread": None,
            "recorded_session_code": None,
            "computed_session_code": computed_session,
            "session_code_consistent": None,
            "source_identity": None,
        }
    if mode != "pit":
        raise ValueError("Retrospective feature packets cannot mix in a PIT snapshot.")
    captured_at = _utc(snapshot.get("captured_at"))
    if captured_at > as_of:
        raise ValueError("Snapshot was captured after the feature as-of time.")
    if snapshot.get("provenance_class") == RETROSPECTIVE_PROVENANCE:
        raise ValueError("Retrospective evidence cannot be used as a PIT quote snapshot.")
    identity = str(snapshot.get("load_identity") or "").strip()
    if not identity:
        raise ValueError("PIT snapshot requires load_identity.")
    availability = snapshot.get("data_availability")
    if not isinstance(availability, Mapping):
        availability = {}
    recorded_session = str(snapshot.get("session_code") or "") or None
    quote_time = snapshot.get("quote_time")
    return {
        "state": "known",
        "capture_status": snapshot.get("capture_status"),
        "quote_state": availability.get("quote", "unknown"),
        "quote_age_seconds": snapshot.get("quote_age_seconds"),
        "quote_time": None if quote_time in (None, "") else _utc(quote_time).isoformat(),
        "bid": None if snapshot.get("bid") is None else str(snapshot.get("bid")),
        "ask": None if snapshot.get("ask") is None else str(snapshot.get("ask")),
        "mid": None if snapshot.get("mid") is None else str(snapshot.get("mid")),
        "spread": None if snapshot.get("spread") is None else str(snapshot.get("spread")),
        "recorded_session_code": recorded_session,
        "computed_session_code": computed_session,
        "session_code_consistent": None if recorded_session is None else recorded_session == computed_session,
        "source_identity": identity,
    }


def _alignment(timeframe_features: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    directions = {
        timeframe: str(features.get("return_5_direction") or "unknown")
        for timeframe, features in timeframe_features.items()
    }
    known = {key: value for key, value in directions.items() if value in {"bullish", "bearish", "flat"}}
    bullish = sum(value == "bullish" for value in known.values())
    bearish = sum(value == "bearish" for value in known.values())
    flat = sum(value == "flat" for value in known.values())
    if len(known) < 2:
        state = "insufficient"
    elif bullish == len(known):
        state = "all_bullish"
    elif bearish == len(known):
        state = "all_bearish"
    elif flat == len(known):
        state = "all_flat"
    else:
        state = "mixed"
    return {
        "state": state,
        "known_timeframes": len(known),
        "bullish_timeframes": bullish,
        "bearish_timeframes": bearish,
        "flat_timeframes": flat,
        "directions": directions,
    }


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_feature_packet(
    *,
    as_of: datetime | str,
    symbol: str,
    candle_rows: Iterable[Mapping[str, Any]],
    mode: str,
    snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    cutoff = _utc(as_of)
    grouped = normalize_candles(candle_rows, as_of=cutoff, symbol=symbol, mode=mode)
    timeframe_features = {
        timeframe: _timeframe_features(grouped[timeframe])
        for timeframe in TIMEFRAMES
    }
    m1_context = _range_context(grouped["M1"], as_of=cutoff)
    quote_context = _snapshot_context(snapshot, as_of=cutoff, mode=mode)

    if mode == "pit":
        provenance_class = PIT_PROVENANCE
        pit_eligible = True
    elif mode == "retrospective":
        provenance_class = RETROSPECTIVE_PROVENANCE
        pit_eligible = False
    else:
        raise ValueError("Feature mode must be 'pit' or 'retrospective'.")

    source_links: dict[str, list[dict[str, Any]]] = {}
    for timeframe, candles in grouped.items():
        source_links[timeframe] = [item.provenance for item in candles[-21:]]

    packet: dict[str, Any] = {
        "feature_definition_version": FEATURE_DEFINITION_VERSION,
        "as_of_utc": cutoff.isoformat(),
        "symbol": symbol,
        "mode": mode,
        "provenance_class": provenance_class,
        "pit_eligible": pit_eligible,
        "timeframes": timeframe_features,
        "range_context": m1_context,
        "quote_context": quote_context,
        "multi_timeframe_alignment": _alignment(timeframe_features),
        "source_links": source_links,
    }
    packet["feature_packet_digest"] = sha256(_canonical_json(packet).encode()).hexdigest()
    return packet
