from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from hashlib import sha256
from itertools import pairwise
from typing import Any
from zoneinfo import ZoneInfo

from aidy.feature_engine import FEATURE_DEFINITION_VERSION, Candle, normalize_candles
from aidy.historical_backfill import RETROSPECTIVE_PROVENANCE

PRICE_STRUCTURE_VERSION = "aidy_gold_price_structure_v2"
PRICE_STRUCTURE_SEMANTIC_VERSION = "aidy_gold_price_structure_semantics_v1"
FEED_HEALTH_VERSION = "aidy_gold_feed_health_v1"
PIT_PROVENANCE = "pit_observed"

_TIMEFRAME_SECONDS = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}
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
_SCALE = Decimal("0.000001")
_LONDON = ZoneInfo("Europe/London")
_NEW_YORK = ZoneInfo("America/New_York")
_TOKYO = ZoneInfo("Asia/Tokyo")
_SESSION_SPECS = {
    "asia": (_TOKYO, time(9), time(18)),
    "london": (_LONDON, time(8), time(17)),
    "new_york": (_NEW_YORK, time(8), time(17)),
}
_OPENING_RANGE_MINUTES = (15, 30, 60)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Day 26 timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _fmt(value: Decimal | None) -> str | None:
    if value is None:
        return None
    with localcontext() as ctx:
        ctx.prec = 34
        rounded = value.quantize(_SCALE, rounding=ROUND_HALF_EVEN)
    if rounded == 0:
        return "0"
    text = format(rounded, "f").rstrip("0").rstrip(".")
    return text or "0"


def _bps(delta: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == 0:
        return None
    with localcontext() as ctx:
        ctx.prec = 34
        return delta / denominator * Decimal(10000)


def _canonical_timeframe(value: Any) -> str | None:
    raw = str(value or "").strip().upper().replace(" ", "")
    return _TIMEFRAME_ALIASES.get(raw)


def _completed(grouped: Mapping[str, list[Candle]], as_of: datetime) -> dict[str, list[Candle]]:
    result: dict[str, list[Candle]] = {}
    for timeframe, candles in grouped.items():
        duration = timedelta(seconds=_TIMEFRAME_SECONDS[timeframe])
        result[timeframe] = [
            candle for candle in candles if candle.open_time_utc + duration <= as_of
        ]
    return result


def _source_ids(candles: Iterable[Candle]) -> list[str]:
    return [candle.identity for candle in candles]


def _period_payload(candles: list[Candle], *, period_key: str) -> dict[str, Any]:
    if not candles:
        return {
            "state": "unknown",
            "period_key": period_key,
            "bars": 0,
            "high": None,
            "low": None,
            "close": None,
            "first_open_time_utc": None,
            "last_open_time_utc": None,
            "source_identities": [],
        }
    ordered = sorted(candles, key=lambda item: item.open_time_utc)
    return {
        "state": "known",
        "period_key": period_key,
        "bars": len(ordered),
        "high": _fmt(max(item.high for item in ordered)),
        "low": _fmt(min(item.low for item in ordered)),
        "close": _fmt(ordered[-1].close),
        "first_open_time_utc": ordered[0].open_time_utc.isoformat(),
        "last_open_time_utc": ordered[-1].open_time_utc.isoformat(),
        "source_identities": _source_ids(ordered),
    }


def _prior_periods(d1: list[Candle], *, as_of: datetime) -> dict[str, Any]:
    before_today = [candle for candle in d1 if candle.open_time_utc.date() < as_of.date()]
    if before_today:
        latest = max(before_today, key=lambda item: item.open_time_utc)
        prior_day = _period_payload([latest], period_key=latest.open_time_utc.date().isoformat())
    else:
        prior_day = _period_payload([], period_key="unknown")

    current_iso = as_of.date().isocalendar()
    prior_week_rows = [
        candle
        for candle in d1
        if (
            candle.open_time_utc.date().isocalendar().year,
            candle.open_time_utc.date().isocalendar().week,
        )
        != (current_iso.year, current_iso.week)
        and candle.open_time_utc.date() < as_of.date()
    ]
    if prior_week_rows:
        latest_week_row = max(prior_week_rows, key=lambda item: item.open_time_utc)
        iso = latest_week_row.open_time_utc.date().isocalendar()
        key = (iso.year, iso.week)
        selected = [
            item
            for item in prior_week_rows
            if (
                item.open_time_utc.date().isocalendar().year,
                item.open_time_utc.date().isocalendar().week,
            )
            == key
        ]
        prior_week = _period_payload(selected, period_key=f"{key[0]}-W{key[1]:02d}")
    else:
        prior_week = _period_payload([], period_key="unknown")

    current_month = (as_of.year, as_of.month)
    prior_month_rows = [
        candle
        for candle in d1
        if (candle.open_time_utc.year, candle.open_time_utc.month) != current_month
        and candle.open_time_utc.date() < as_of.date()
    ]
    if prior_month_rows:
        latest_month_row = max(prior_month_rows, key=lambda item: item.open_time_utc)
        key = (latest_month_row.open_time_utc.year, latest_month_row.open_time_utc.month)
        selected = [
            item
            for item in prior_month_rows
            if (item.open_time_utc.year, item.open_time_utc.month) == key
        ]
        prior_month = _period_payload(selected, period_key=f"{key[0]}-{key[1]:02d}")
    else:
        prior_month = _period_payload([], period_key="unknown")

    return {
        "definition": "completed_d1_prior_trading_periods_v1",
        "prior_day": prior_day,
        "prior_week": prior_week,
        "prior_month": prior_month,
    }


def _local_interval(day: date, zone: ZoneInfo, start: time, end: time) -> tuple[datetime, datetime]:
    start_local = datetime.combine(day, start, tzinfo=zone)
    end_local = datetime.combine(day, end, tzinfo=zone)
    if end_local <= start_local:
        end_local += timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def _window_rows(m1: list[Candle], *, start: datetime, end: datetime) -> list[Candle]:
    one_minute = timedelta(minutes=1)
    return [
        candle
        for candle in m1
        if start <= candle.open_time_utc and candle.open_time_utc + one_minute <= end
    ]


def _asia_overnight_range(m1: list[Candle], *, as_of: datetime) -> dict[str, Any]:
    zone, start_time, end_time = _SESSION_SPECS["asia"]
    local_now = as_of.astimezone(zone)
    local_day = (
        local_now.date() if local_now.time() >= start_time else local_now.date() - timedelta(days=1)
    )
    start_utc, end_utc = _local_interval(local_day, zone, start_time, end_time)
    expected = int((end_utc - start_utc).total_seconds() // 60)
    base = {
        "definition": "asia_09_18_tokyo_completed_window_v1",
        "timezone": zone.key,
        "local_date": local_day.isoformat(),
        "start_utc": start_utc.isoformat(),
        "end_utc": end_utc.isoformat(),
        "expected_m1_bars": expected,
    }
    if as_of < start_utc:
        return {
            **base,
            "state": "not_started",
            "observed_m1_bars": 0,
            "high": None,
            "low": None,
            "source_identities": [],
        }
    if as_of < end_utc:
        observed = _window_rows(m1, start=start_utc, end=min(as_of, end_utc))
        return {
            **base,
            "state": "forming",
            "observed_m1_bars": len(observed),
            "high": None,
            "low": None,
            "source_identities": _source_ids(observed),
        }
    rows = _window_rows(m1, start=start_utc, end=end_utc)
    if len(rows) != expected:
        return {
            **base,
            "state": "incomplete",
            "observed_m1_bars": len(rows),
            "high": None,
            "low": None,
            "source_identities": _source_ids(rows),
        }
    return {
        **base,
        "state": "known",
        "observed_m1_bars": len(rows),
        "high": _fmt(max(item.high for item in rows)),
        "low": _fmt(min(item.low for item in rows)),
        "source_identities": _source_ids(rows),
    }


def _opening_range(
    m1: list[Candle],
    *,
    as_of: datetime,
    session: str,
    minutes: int,
) -> dict[str, Any]:
    zone, session_start, _ = _SESSION_SPECS[session]
    local_day = as_of.astimezone(zone).date()
    start_utc = datetime.combine(local_day, session_start, tzinfo=zone).astimezone(UTC)
    end_utc = start_utc + timedelta(minutes=minutes)
    base = {
        "definition": "accepted_liquidity_open_completed_m1_v1",
        "session": session,
        "minutes": minutes,
        "timezone": zone.key,
        "local_date": local_day.isoformat(),
        "start_utc": start_utc.isoformat(),
        "end_utc": end_utc.isoformat(),
        "expected_m1_bars": minutes,
    }
    if as_of <= start_utc:
        return {
            **base,
            "state": "not_started",
            "observed_m1_bars": 0,
            "high": None,
            "low": None,
            "source_identities": [],
        }
    rows = _window_rows(m1, start=start_utc, end=min(as_of, end_utc))
    if as_of < end_utc:
        return {
            **base,
            "state": "forming",
            "observed_m1_bars": len(rows),
            "high": None,
            "low": None,
            "source_identities": _source_ids(rows),
        }
    rows = _window_rows(m1, start=start_utc, end=end_utc)
    if len(rows) != minutes:
        return {
            **base,
            "state": "incomplete",
            "observed_m1_bars": len(rows),
            "high": None,
            "low": None,
            "source_identities": _source_ids(rows),
        }
    return {
        **base,
        "state": "known",
        "observed_m1_bars": len(rows),
        "high": _fmt(max(item.high for item in rows)),
        "low": _fmt(min(item.low for item in rows)),
        "source_identities": _source_ids(rows),
    }


def _opening_ranges(m1: list[Candle], *, as_of: datetime) -> dict[str, Any]:
    result: dict[str, Any] = {
        "definition": "accepted_day25_liquidity_opening_ranges_v1",
    }
    result.update(
        {
            session: {
                f"{minutes}m": _opening_range(
                    m1,
                    as_of=as_of,
                    session=session,
                    minutes=minutes,
                )
                for minutes in _OPENING_RANGE_MINUTES
            }
            for session in _SESSION_SPECS
        }
    )
    return result


def _session_extreme(m1: list[Candle], *, as_of: datetime, session: str) -> dict[str, Any]:
    zone, start_time, end_time = _SESSION_SPECS[session]
    local_day = as_of.astimezone(zone).date()
    start_utc, end_utc = _local_interval(local_day, zone, start_time, end_time)
    full_expected = int((end_utc - start_utc).total_seconds() // 60)
    base = {
        "definition": "completed_m1_elapsed_session_extreme_v1",
        "session": session,
        "timezone": zone.key,
        "local_date": local_day.isoformat(),
        "start_utc": start_utc.isoformat(),
        "end_utc": end_utc.isoformat(),
        "full_session_expected_m1_bars": full_expected,
    }
    if as_of <= start_utc:
        return {
            **base,
            "state": "not_started",
            "elapsed_expected_m1_bars": 0,
            "observed_m1_bars": 0,
            "high": None,
            "low": None,
            "source_identities": [],
        }
    observation_end = min(as_of, end_utc)
    elapsed_expected = max(0, int((observation_end - start_utc).total_seconds() // 60))
    rows = _window_rows(m1, start=start_utc, end=observation_end)
    if not rows and elapsed_expected > 0:
        state = "unknown"
    elif len(rows) < elapsed_expected:
        state = "partial"
    elif as_of >= end_utc:
        state = "complete"
    else:
        state = "observed_so_far"
    return {
        **base,
        "state": state,
        "elapsed_expected_m1_bars": elapsed_expected,
        "observed_m1_bars": len(rows),
        "high": None if not rows else _fmt(max(item.high for item in rows)),
        "low": None if not rows else _fmt(min(item.low for item in rows)),
        "source_identities": _source_ids(rows),
    }


def _session_extremes(m1: list[Candle], *, as_of: datetime) -> dict[str, Any]:
    result: dict[str, Any] = {
        "definition": "accepted_day25_named_session_extremes_v1",
    }
    result.update(
        {session: _session_extreme(m1, as_of=as_of, session=session) for session in _SESSION_SPECS}
    )
    return result


def _utc_day_gap(
    m1: list[Candle], *, as_of: datetime, prior_day: Mapping[str, Any]
) -> dict[str, Any]:
    prior_close = _decimal(prior_day.get("close")) if prior_day.get("state") == "known" else None
    today = [item for item in m1 if item.open_time_utc.date() == as_of.date()]
    if prior_close is None or not today:
        return {
            "definition": "prior_trading_day_close_to_first_completed_utc_day_m1_open_v1",
            "state": "unknown",
            "prior_close": _fmt(prior_close),
            "current_utc_day_open": None,
            "gap_bps": None,
            "direction": "unknown",
            "fill_state": "unknown",
            "source_identities": [],
        }
    ordered = sorted(today, key=lambda item: item.open_time_utc)
    current_open = ordered[0].open
    size = _bps(current_open - prior_close, prior_close)
    if current_open > prior_close:
        direction = "up"
        filled = any(item.low <= prior_close for item in ordered)
    elif current_open < prior_close:
        direction = "down"
        filled = any(item.high >= prior_close for item in ordered)
    else:
        direction = "flat"
        filled = True
    return {
        "definition": "prior_trading_day_close_to_first_completed_utc_day_m1_open_v1",
        "state": "known",
        "prior_close": _fmt(prior_close),
        "current_utc_day_open": _fmt(current_open),
        "gap_bps": _fmt(size),
        "direction": direction,
        "fill_state": "not_applicable"
        if direction == "flat"
        else "filled"
        if filled
        else "unfilled",
        "first_completed_m1_open_time_utc": ordered[0].open_time_utc.isoformat(),
        "source_identities": _source_ids(ordered),
    }


def _trend_persistence(m15: list[Candle]) -> dict[str, Any]:
    if len(m15) < 5:
        return {
            "definition": "five_completed_m15_close_persistence_acceleration_v1",
            "state": "insufficient",
            "bars": len(m15),
            "direction": "unknown",
            "persistence_ratio": None,
            "first_half_return_bps": None,
            "second_half_return_bps": None,
            "absolute_acceleration_bps": None,
            "source_identities": _source_ids(m15),
        }
    sample = m15[-5:]
    changes = [sample[index].close - sample[index - 1].close for index in range(1, 5)]
    net = sample[-1].close - sample[0].close
    if net > 0:
        direction = "up"
        matching = sum(item > 0 for item in changes)
    elif net < 0:
        direction = "down"
        matching = sum(item < 0 for item in changes)
    else:
        direction = "flat"
        matching = sum(item == 0 for item in changes)
    with localcontext() as ctx:
        ctx.prec = 34
        persistence = Decimal(matching) / Decimal(4)
    first_half = _bps(sample[2].close - sample[0].close, sample[0].close)
    second_half = _bps(sample[4].close - sample[2].close, sample[2].close)
    acceleration = None
    if first_half is not None and second_half is not None:
        acceleration = abs(second_half) - abs(first_half)
    return {
        "definition": "five_completed_m15_close_persistence_acceleration_v1",
        "state": "known",
        "bars": 5,
        "direction": direction,
        "persistence_ratio": _fmt(persistence),
        "first_half_return_bps": _fmt(first_half),
        "second_half_return_bps": _fmt(second_half),
        "absolute_acceleration_bps": _fmt(acceleration),
        "source_identities": _source_ids(sample),
    }


def _breakout_state(
    m1: list[Candle], *, as_of: datetime, prior_day: Mapping[str, Any]
) -> dict[str, Any]:
    prior_high = _decimal(prior_day.get("high")) if prior_day.get("state") == "known" else None
    prior_low = _decimal(prior_day.get("low")) if prior_day.get("state") == "known" else None
    today = [item for item in m1 if item.open_time_utc.date() == as_of.date()]
    if prior_high is None or prior_low is None or not today:
        return {
            "definition": "prior_day_literal_penetration_latest_close_reversion_v1",
            "state": "unknown",
            "upside": None,
            "downside": None,
            "source_identities": _source_ids(today),
        }
    ordered = sorted(today, key=lambda item: item.open_time_utc)
    max_high = max(item.high for item in ordered)
    min_low = min(item.low for item in ordered)
    latest_close = ordered[-1].close
    up = max_high > prior_high
    down = min_low < prior_low
    up_reverted = up and latest_close <= prior_high
    down_reverted = down and latest_close >= prior_low
    if up and down:
        state = "two_sided"
    elif up:
        state = "upside_failed" if up_reverted else "upside_hold"
    elif down:
        state = "downside_failed" if down_reverted else "downside_hold"
    else:
        state = "none"
    return {
        "definition": "prior_day_literal_penetration_latest_close_reversion_v1",
        "state": state,
        "prior_day_high": _fmt(prior_high),
        "prior_day_low": _fmt(prior_low),
        "latest_completed_close": _fmt(latest_close),
        "upside": {
            "penetrated": up,
            "max_penetration_bps": _fmt(_bps(max(max_high - prior_high, Decimal(0)), prior_high)),
            "reverted_inside": up_reverted,
        },
        "downside": {
            "penetrated": down,
            "max_penetration_bps": _fmt(_bps(max(prior_low - min_low, Decimal(0)), prior_low)),
            "reverted_inside": down_reverted,
        },
        "source_identities": _source_ids(ordered),
    }


def _wick_footprint(m15: list[Candle]) -> dict[str, Any]:
    if not m15:
        return {
            "definition": "latest_completed_m15_wick_geometry_v1",
            "state": "unknown",
            "open_time_utc": None,
            "body_bps": None,
            "upper_wick_bps": None,
            "lower_wick_bps": None,
            "range_bps": None,
            "close_location": None,
            "source_identities": [],
        }
    candle = m15[-1]
    upper = candle.high - max(candle.open, candle.close)
    lower = min(candle.open, candle.close) - candle.low
    body = abs(candle.close - candle.open)
    total = candle.high - candle.low
    close_location = None
    if total != 0:
        with localcontext() as ctx:
            ctx.prec = 34
            close_location = (candle.close - candle.low) / total
    return {
        "definition": "latest_completed_m15_wick_geometry_v1",
        "state": "known",
        "open_time_utc": candle.open_time_utc.isoformat(),
        "body_bps": _fmt(_bps(body, candle.open)),
        "upper_wick_bps": _fmt(_bps(upper, candle.open)),
        "lower_wick_bps": _fmt(_bps(lower, candle.open)),
        "range_bps": _fmt(_bps(total, candle.open)),
        "close_location": _fmt(close_location),
        "source_identities": [candle.identity],
    }


def _latest_confirmed_swing(
    candles: list[Candle], *, high: bool, wing: int = 2
) -> tuple[int, Candle] | None:
    if len(candles) < wing * 2 + 1:
        return None
    for index in range(len(candles) - wing - 1, wing - 1, -1):
        candidate = candles[index]
        neighbors = candles[index - wing : index] + candles[index + 1 : index + wing + 1]
        if high and all(candidate.high > item.high for item in neighbors):
            return index, candidate
        if not high and all(candidate.low < item.low for item in neighbors):
            return index, candidate
    return None


def _swing_side(m15: list[Candle], *, high: bool, wing: int = 2) -> dict[str, Any]:
    found = _latest_confirmed_swing(m15, high=high, wing=wing)
    side = "high" if high else "low"
    if found is None:
        return {
            "state": "unknown",
            "side": side,
            "swing_open_time_utc": None,
            "swing_price": None,
            "penetrated": False,
            "max_penetration_bps": None,
            "reverted": False,
            "source_identities": [],
        }
    index, swing = found
    price = swing.high if high else swing.low
    later = m15[index + wing + 1 :]
    if high:
        max_price = max((item.high for item in later), default=price)
        magnitude = max(max_price - price, Decimal(0))
        penetrated = magnitude > 0
        reverted = penetrated and bool(m15) and m15[-1].close <= price
    else:
        min_price = min((item.low for item in later), default=price)
        magnitude = max(price - min_price, Decimal(0))
        penetrated = magnitude > 0
        reverted = penetrated and bool(m15) and m15[-1].close >= price
    sources = m15[max(0, index - wing) :]
    return {
        "state": "known",
        "side": side,
        "wing": wing,
        "swing_open_time_utc": swing.open_time_utc.isoformat(),
        "swing_price": _fmt(price),
        "penetrated": penetrated,
        "max_penetration_bps": _fmt(_bps(magnitude, price)),
        "reverted": reverted,
        "source_identities": _source_ids(sources),
    }


def _swing_penetration(m15: list[Candle]) -> dict[str, Any]:
    return {
        "definition": "confirmed_m15_wing2_post_confirmation_penetration_reversion_v1",
        "high_side": _swing_side(m15, high=True),
        "low_side": _swing_side(m15, high=False),
    }


def _latency_values(
    raw_rows: list[Mapping[str, Any]],
    *,
    as_of: datetime,
    timeframe: str,
) -> list[int]:
    values: list[int] = []
    for row in raw_rows:
        if _canonical_timeframe(row.get("timeframe")) != timeframe:
            continue
        if (
            row.get("provenance_class") == RETROSPECTIVE_PROVENANCE
            or row.get("pit_eligible") is False
        ):
            continue
        first_observed = row.get("first_observed_at")
        opened = row.get("open_time_utc")
        if first_observed is None or opened is None:
            continue
        opened_at = _utc(opened)
        observed_at = _utc(first_observed)
        if observed_at > as_of:
            continue
        if opened_at + timedelta(seconds=_TIMEFRAME_SECONDS[timeframe]) > as_of:
            continue
        values.append(int((observed_at - opened_at).total_seconds()))
    return sorted(values)


def _timeframe_feed_health(
    candles: list[Candle],
    *,
    raw_rows: list[Mapping[str, Any]],
    as_of: datetime,
    timeframe: str,
    mode: str,
) -> dict[str, Any]:
    duration = _TIMEFRAME_SECONDS[timeframe]
    recent = candles[-256:]
    gaps = [
        int((right.open_time_utc - left.open_time_utc).total_seconds())
        for left, right in pairwise(recent)
    ]
    excess = [gap for gap in gaps if gap > duration]
    latest = recent[-1] if recent else None
    latest_end = None if latest is None else latest.open_time_utc + timedelta(seconds=duration)
    if mode == "pit":
        latencies = _latency_values(raw_rows, as_of=as_of, timeframe=timeframe)
        latency = {
            "state": "observed" if latencies else "unknown",
            "sample_n": len(latencies),
            "min_first_observed_delay_from_open_seconds": None if not latencies else min(latencies),
            "median_first_observed_delay_from_open_seconds": None
            if not latencies
            else latencies[(len(latencies) - 1) // 2],
            "max_first_observed_delay_from_open_seconds": None if not latencies else max(latencies),
        }
    else:
        latency = {
            "state": "unknown",
            "sample_n": 0,
            "min_first_observed_delay_from_open_seconds": None,
            "median_first_observed_delay_from_open_seconds": None,
            "max_first_observed_delay_from_open_seconds": None,
        }
    return {
        "state": "observed" if latest is not None else "unknown",
        "expected_interval_seconds": duration,
        "sample_bars": len(recent),
        "latest_completed_bar_open_utc": None
        if latest is None
        else latest.open_time_utc.isoformat(),
        "latest_completed_bar_end_utc": None if latest_end is None else latest_end.isoformat(),
        "last_observation_age_seconds": None
        if latest_end is None
        else int((as_of - latest_end).total_seconds()),
        "interbar_gap_count": len(excess),
        "max_interbar_gap_seconds": None if not gaps else max(gaps),
        "arrival_observation": latency,
        "source_identities": _source_ids(recent),
    }


def _quote_feed_health(
    snapshot: Mapping[str, Any] | None,
    *,
    as_of: datetime,
    mode: str,
) -> dict[str, Any]:
    if snapshot is None:
        return {
            "state": "unknown",
            "capture_status": None,
            "quote_state": "unknown",
            "quote_time_utc": None,
            "quote_age_seconds": None,
            "source_identity": None,
        }
    if mode != "pit":
        raise ValueError("Retrospective Day 26 packets cannot mix in PIT quote snapshots.")
    captured = _utc(snapshot.get("captured_at"))
    if captured > as_of:
        raise ValueError("Day 26 quote snapshot was captured after T.")
    if snapshot.get("provenance_class") == RETROSPECTIVE_PROVENANCE:
        raise ValueError("Retrospective evidence cannot enter Day 26 PIT quote telemetry.")
    availability = snapshot.get("data_availability")
    availability_map = availability if isinstance(availability, Mapping) else {}
    quote_time_value = snapshot.get("quote_time")
    quote_time = None if quote_time_value in (None, "") else _utc(quote_time_value)
    supplied_age = _decimal(snapshot.get("quote_age_seconds"))
    age = supplied_age
    if age is None and quote_time is not None:
        age = Decimal(str((as_of - quote_time).total_seconds()))
    identity = str(snapshot.get("load_identity") or "").strip() or None
    return {
        "state": "observed",
        "capture_status": snapshot.get("capture_status"),
        "quote_state": availability_map.get("quote", "unknown"),
        "quote_time_utc": None if quote_time is None else quote_time.isoformat(),
        "quote_age_seconds": None if age is None else _fmt(age),
        "source_identity": identity,
    }


def _semantic_view(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _semantic_view(item)
            for key, item in value.items()
            if key not in {"source_identities", "source_identity"}
        }
    if isinstance(value, list):
        return [_semantic_view(item) for item in value]
    return value


def build_price_structure_packet(
    *,
    as_of: datetime | str,
    symbol: str,
    candle_rows: Iterable[Mapping[str, Any]],
    mode: str,
    snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    cutoff = _utc(as_of)
    raw_rows = [dict(row) for row in candle_rows]
    grouped = normalize_candles(raw_rows, as_of=cutoff, symbol=symbol, mode=mode)
    completed = _completed(grouped, cutoff)
    prior = _prior_periods(completed["D1"], as_of=cutoff)

    structure = {
        "prior_periods": prior,
        "asia_overnight_range": _asia_overnight_range(completed["M1"], as_of=cutoff),
        "opening_ranges": _opening_ranges(completed["M1"], as_of=cutoff),
        "session_extremes": _session_extremes(completed["M1"], as_of=cutoff),
        "utc_day_gap": _utc_day_gap(completed["M1"], as_of=cutoff, prior_day=prior["prior_day"]),
        "trend_persistence_acceleration": _trend_persistence(completed["M15"]),
        "prior_day_breakout": _breakout_state(
            completed["M1"], as_of=cutoff, prior_day=prior["prior_day"]
        ),
        "wick_footprint": _wick_footprint(completed["M15"]),
        "swing_extreme_penetration_with_reversion": _swing_penetration(completed["M15"]),
    }

    if mode == "pit":
        provenance_class = PIT_PROVENANCE
        pit_eligible = True
    elif mode == "retrospective":
        provenance_class = RETROSPECTIVE_PROVENANCE
        pit_eligible = False
    else:
        raise ValueError("Day 26 mode must be pit or retrospective.")

    feed_health = {
        "feed_health_version": FEED_HEALTH_VERSION,
        "timeframes": {
            timeframe: _timeframe_feed_health(
                completed[timeframe],
                raw_rows=raw_rows,
                as_of=cutoff,
                timeframe=timeframe,
                mode=mode,
            )
            for timeframe in _TIMEFRAME_SECONDS
        },
        "quote": _quote_feed_health(snapshot, as_of=cutoff, mode=mode),
        "threshold_based_health_classification": False,
        "historical_spread_inference_included": False,
    }

    semantic = {
        "price_structure_semantic_version": PRICE_STRUCTURE_SEMANTIC_VERSION,
        "as_of_utc": cutoff.isoformat(),
        "symbol": symbol,
        "structure": _semantic_view(structure),
    }
    packet: dict[str, Any] = {
        "price_structure_version": PRICE_STRUCTURE_VERSION,
        "price_structure_semantic_version": PRICE_STRUCTURE_SEMANTIC_VERSION,
        "source_feature_definition_version": FEATURE_DEFINITION_VERSION,
        "as_of_utc": cutoff.isoformat(),
        "symbol": symbol,
        "mode": mode,
        "provenance_class": provenance_class,
        "pit_eligible": pit_eligible,
        "completed_bar_policy": "open_time_plus_nominal_duration_lte_as_of",
        "timeframe_durations_seconds": dict(_TIMEFRAME_SECONDS),
        "structure": structure,
        "feed_health": feed_health,
        "structure_semantic_digest": _digest(semantic),
        "future_values_used": False,
        "predictive_edge_claimed": False,
    }
    packet["price_structure_digest"] = _digest(packet)
    return packet


def verify_price_structure_packet(packet: Mapping[str, Any]) -> bool:
    if packet.get("price_structure_version") != PRICE_STRUCTURE_VERSION:
        return False
    body = dict(packet)
    supplied = str(body.pop("price_structure_digest", ""))
    if not supplied or supplied != _digest(body):
        return False
    structure = packet.get("structure")
    if not isinstance(structure, Mapping):
        return False
    semantic = {
        "price_structure_semantic_version": PRICE_STRUCTURE_SEMANTIC_VERSION,
        "as_of_utc": packet.get("as_of_utc"),
        "symbol": packet.get("symbol"),
        "structure": _semantic_view(structure),
    }
    return str(packet.get("structure_semantic_digest") or "") == _digest(semantic)
