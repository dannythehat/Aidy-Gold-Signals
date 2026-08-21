from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from typing import Any
from zoneinfo import ZoneInfo

from aidy.market_sessions import session_code_at

MARKET_STRUCTURE_CONTEXT_VERSION = "aidy_gold_market_structure_context_v1"
MARKET_STRUCTURE_EPOCH_VERSION = "aidy_gold_market_structure_epoch_v1"
NAMED_WINDOW_VERSION = "aidy_gold_named_liquidity_windows_v1"
LIQUIDITY_CALENDAR_VERSION = "aidy_gold_liquidity_calendar_v1"
SCHEDULE_RECORD_VERSION = "aidy_official_schedule_record_v1"

POST_2022_BOUNDARY_UTC = datetime(2022, 2, 24, tzinfo=UTC)
ONE_OZ_24X7_EFFECTIVE_DATE = "2026-07-24"
ONE_OZ_24X7_BOUNDARY_UTC = datetime(2026, 7, 24, 21, 30, tzinfo=UTC)

_LONDON = ZoneInfo("Europe/London")
_NEW_YORK = ZoneInfo("America/New_York")
_CHICAGO = ZoneInfo("America/Chicago")
_TOKYO = ZoneInfo("Asia/Tokyo")

_ALLOWED_SCHEDULE_KINDS = {
    "cme_gold_options_expiry",
    "exchange_half_day",
    "exchange_holiday",
    "special_maintenance",
    "thin_liquidity",
}


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Day 25 structural timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _local_interval(
    *,
    day: date,
    zone: ZoneInfo,
    start: time,
    end: time,
) -> tuple[datetime, datetime]:
    start_local = datetime.combine(day, start, tzinfo=zone)
    end_local = datetime.combine(day, end, tzinfo=zone)
    if end_local <= start_local:
        end_local += timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def _window(
    *,
    name: str,
    category: str,
    zone: ZoneInfo,
    local_day: date,
    start: time,
    end: time,
    now: datetime,
    source_basis: str,
) -> dict[str, Any]:
    start_utc, end_utc = _local_interval(day=local_day, zone=zone, start=start, end=end)
    return {
        "name": name,
        "category": category,
        "timezone": zone.key,
        "local_date": local_day.isoformat(),
        "local_start": start.isoformat(),
        "local_end": end.isoformat(),
        "start_utc": start_utc.isoformat(),
        "end_utc": end_utc.isoformat(),
        "active": start_utc <= now < end_utc,
        "source_basis": source_basis,
    }


def market_structure_epoch_at(value: datetime | str) -> dict[str, Any]:
    now = _utc(value)
    if now < POST_2022_BOUNDARY_UTC:
        epoch = "pre_2022_architecture_regime"
        boundary_kind = "architecture_preregistered_regime"
        boundary_utc = None
    elif now < ONE_OZ_24X7_BOUNDARY_UTC:
        epoch = "post_2022_pre_1oz_24x7"
        boundary_kind = "architecture_preregistered_regime"
        boundary_utc = POST_2022_BOUNDARY_UTC.isoformat()
    else:
        epoch = "post_1oz_24x7"
        boundary_kind = "official_cme_market_structure_change"
        boundary_utc = ONE_OZ_24X7_BOUNDARY_UTC.isoformat()

    result = {
        "epoch_version": MARKET_STRUCTURE_EPOCH_VERSION,
        "market_structure_epoch": epoch,
        "as_of_utc": now.isoformat(),
        "active_boundary_kind": boundary_kind,
        "active_boundary_utc": boundary_utc,
        "boundaries": [
            {
                "name": "post_feb_2022_architecture_regime",
                "boundary_utc": POST_2022_BOUNDARY_UTC.isoformat(),
                "boundary_kind": "architecture_preregistered_regime",
                "official_venue_rule_change_claimed": False,
            },
            {
                "name": "cme_1oz_gold_24x7",
                "effective_date": ONE_OZ_24X7_EFFECTIVE_DATE,
                "boundary_utc": ONE_OZ_24X7_BOUNDARY_UTC.isoformat(),
                "boundary_kind": "official_cme_market_structure_change",
                "source_reference": "CME SER-9766 and July 13 2026 Globex notice",
            },
        ],
    }
    result["epoch_digest"] = _digest(result)
    return result


def _broad_liquidity_windows(now: datetime) -> list[dict[str, Any]]:
    london_day = now.astimezone(_LONDON).date()
    new_york_day = now.astimezone(_NEW_YORK).date()
    tokyo_day = now.astimezone(_TOKYO).date()
    return [
        _window(
            name="asia_liquidity",
            category="aidy_liquidity_window",
            zone=_TOKYO,
            local_day=tokyo_day,
            start=time(9),
            end=time(18),
            now=now,
            source_basis="accepted_aidy_session_semantics",
        ),
        _window(
            name="london_liquidity",
            category="aidy_liquidity_window",
            zone=_LONDON,
            local_day=london_day,
            start=time(8),
            end=time(17),
            now=now,
            source_basis="accepted_aidy_session_semantics",
        ),
        _window(
            name="new_york_liquidity",
            category="aidy_liquidity_window",
            zone=_NEW_YORK,
            local_day=new_york_day,
            start=time(8),
            end=time(17),
            now=now,
            source_basis="accepted_aidy_session_semantics",
        ),
    ]


def _official_daily_windows(now: datetime) -> list[dict[str, Any]]:
    london_day = now.astimezone(_LONDON).date()
    new_york_day = now.astimezone(_NEW_YORK).date()
    chicago_day = now.astimezone(_CHICAGO).date()
    windows = [
        _window(
            name="lbma_gold_price_am",
            category="official_benchmark_window",
            zone=_LONDON,
            local_day=london_day,
            start=time(10, 30),
            end=time(10, 31),
            now=now,
            source_basis="LBMA Gold Price 10:30 London",
        ),
        _window(
            name="lbma_gold_price_pm",
            category="official_benchmark_window",
            zone=_LONDON,
            local_day=london_day,
            start=time(15),
            end=time(15, 1),
            now=now,
            source_basis="LBMA Gold Price 15:00 London",
        ),
        _window(
            name="legacy_comex_open_liquidity_reference",
            category="legacy_official_open_outcry_reference",
            zone=_NEW_YORK,
            local_day=new_york_day,
            start=time(8, 20),
            end=time(8, 21),
            now=now,
            source_basis="legacy COMEX Gold open-outcry 08:20 ET",
        ),
        _window(
            name="cme_gold_settlement_observation",
            category="official_settlement_window",
            zone=_NEW_YORK,
            local_day=new_york_day,
            start=time(13, 29),
            end=time(13, 30),
            now=now,
            source_basis="CME Gold active-month settlement 13:29-13:30 ET",
        ),
        _window(
            name="gc_globex_daily_maintenance",
            category="official_venue_maintenance_reference",
            zone=_CHICAGO,
            local_day=chicago_day,
            start=time(16),
            end=time(17),
            now=now,
            source_basis="regular Gold Globex daily maintenance reference",
        ),
    ]
    if now >= ONE_OZ_24X7_BOUNDARY_UTC:
        windows.append(
            _window(
                name="one_oz_weekday_maintenance",
                category="official_1oz_maintenance",
                zone=_CHICAGO,
                local_day=chicago_day,
                start=time(16),
                end=time(16, 2),
                now=now,
                source_basis="CME SER-9766 weekday 1OZ maintenance",
            )
        )
        if now.astimezone(_CHICAGO).weekday() == 5:
            windows.append(
                _window(
                    name="one_oz_saturday_maintenance",
                    category="official_1oz_maintenance",
                    zone=_CHICAGO,
                    local_day=chicago_day,
                    start=time(2),
                    end=time(4),
                    now=now,
                    source_basis="CME SER-9766 Saturday 1OZ maintenance",
                )
            )
    return windows


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    delta = (weekday - first.weekday()) % 7
    return first + timedelta(days=delta + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        cursor = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        cursor = date(year, month + 1, 1) - timedelta(days=1)
    return cursor - timedelta(days=(cursor.weekday() - weekday) % 7)


def _easter_sunday(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _observed_fixed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _calendar_holiday_name(day: date) -> str | None:
    year = day.year
    candidates = {
        _observed_fixed(date(year, 1, 1)): "new_year",
        _nth_weekday(year, 1, 0, 3): "martin_luther_king_jr_day",
        _nth_weekday(year, 2, 0, 3): "presidents_day",
        _easter_sunday(year) - timedelta(days=2): "good_friday",
        _last_weekday(year, 5, 0): "memorial_day",
        _observed_fixed(date(year, 6, 19)): "juneteenth",
        _observed_fixed(date(year, 7, 4)): "independence_day",
        _nth_weekday(year, 9, 0, 1): "labor_day",
        _nth_weekday(year, 11, 3, 4): "thanksgiving",
        _observed_fixed(date(year, 12, 25)): "christmas",
    }
    return candidates.get(day)


def _normalize_schedule_records(
    records: Iterable[Mapping[str, Any]], *, as_of: datetime
) -> list[dict[str, Any]]:
    visible: list[dict[str, Any]] = []
    for raw in records:
        if raw.get("record_version") != SCHEDULE_RECORD_VERSION:
            raise ValueError("Unsupported Day 25 official schedule-record version.")
        event_kind = str(raw.get("event_kind") or "")
        if event_kind not in _ALLOWED_SCHEDULE_KINDS:
            raise ValueError(f"Unsupported Day 25 schedule event kind: {event_kind}")
        known_at = _utc(str(raw.get("known_at_utc") or ""))
        start = _utc(str(raw.get("start_utc") or ""))
        end = _utc(str(raw.get("end_utc") or ""))
        if end <= start:
            raise ValueError("Official schedule record end must be after start.")
        event_id = str(raw.get("event_id") or "").strip()
        source = str(raw.get("source") or "").strip()
        if not event_id or not source:
            raise ValueError("Official schedule records require event_id and source.")
        if known_at > as_of:
            continue
        visible.append(
            {
                "record_version": SCHEDULE_RECORD_VERSION,
                "event_id": event_id,
                "event_kind": event_kind,
                "known_at_utc": known_at.isoformat(),
                "start_utc": start.isoformat(),
                "end_utc": end.isoformat(),
                "source": source,
                "source_reference": raw.get("source_reference"),
                "active": start <= as_of < end,
            }
        )
    return sorted(visible, key=lambda item: (item["start_utc"], item["event_id"]))


def one_oz_weekend_state_at(value: datetime | str) -> str:
    now = _utc(value)
    if now < ONE_OZ_24X7_BOUNDARY_UTC:
        return "not_applicable_pre_24x7"
    local = now.astimezone(_CHICAGO)
    weekday = local.weekday()
    if weekday == 5 and time(2) <= local.time() < time(4):
        return "weekend_maintenance"
    if weekday >= 5:
        return "weekend_24x7_active"
    if time(16) <= local.time() < time(16, 2):
        return "weekday_maintenance"
    return "weekday_24x7_active"


def build_market_structure_context(
    *,
    as_of: datetime | str,
    official_schedule_records: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    now = _utc(as_of)
    epoch = market_structure_epoch_at(now)
    broad = _broad_liquidity_windows(now)
    official = _official_daily_windows(now)
    schedule = _normalize_schedule_records(official_schedule_records, as_of=now)
    active_schedule = [item for item in schedule if item["active"]]

    chicago_day = now.astimezone(_CHICAGO).date()
    holiday_name = _calendar_holiday_name(chicago_day)
    active_kinds = {item["event_kind"] for item in active_schedule}
    if "exchange_holiday" in active_kinds:
        liquidity_state = "official_exchange_holiday"
        special_hours_state = "known_from_official_schedule"
    elif "exchange_half_day" in active_kinds:
        liquidity_state = "official_exchange_half_day"
        special_hours_state = "known_from_official_schedule"
    elif "special_maintenance" in active_kinds:
        liquidity_state = "official_special_maintenance"
        special_hours_state = "known_from_official_schedule"
    elif "thin_liquidity" in active_kinds:
        liquidity_state = "official_thin_liquidity_window"
        special_hours_state = "known_from_official_schedule"
    elif holiday_name is not None:
        liquidity_state = "holiday_date_known_hours_unconfirmed"
        special_hours_state = "unknown"
    elif one_oz_weekend_state_at(now) == "weekend_24x7_active":
        liquidity_state = "weekend_1oz_active"
        special_hours_state = "not_special"
    else:
        liquidity_state = "regular_calendar_state"
        special_hours_state = "not_special"

    result: dict[str, Any] = {
        "context_version": MARKET_STRUCTURE_CONTEXT_VERSION,
        "epoch_version": MARKET_STRUCTURE_EPOCH_VERSION,
        "named_window_version": NAMED_WINDOW_VERSION,
        "liquidity_calendar_version": LIQUIDITY_CALENDAR_VERSION,
        "as_of_utc": now.isoformat(),
        "future_derived": False,
        "pit_eligible": True,
        "market_structure_epoch": epoch["market_structure_epoch"],
        "epoch": epoch,
        "accepted_session_code": session_code_at(now),
        "active_liquidity_windows": sorted(
            item["name"] for item in broad if item["active"]
        ),
        "active_named_market_windows": sorted(
            item["name"] for item in official if item["active"]
        ),
        "liquidity_windows": broad,
        "named_market_windows": official,
        "one_oz_weekend_state": one_oz_weekend_state_at(now),
        "calendar": {
            "calendar_date_chicago": chicago_day.isoformat(),
            "calendar_holiday_name": holiday_name,
            "liquidity_calendar_state": liquidity_state,
            "special_hours_state": special_hours_state,
            "known_official_schedule_records": schedule,
            "active_official_schedule_records": active_schedule,
            "future_known_records_excluded": True,
        },
        "options_expiry_state": (
            "inside_known_official_window"
            if "cme_gold_options_expiry" in active_kinds
            else "no_active_known_window"
        ),
        "source_policy": {
            "official_window_basis": "CME/LBMA published schedules",
            "exact_special_hours_require_known_at_no_later_than_as_of": True,
            "unknown_special_hours_are_not_assumed_normal": True,
            "legacy_comex_open_is_not_modern_globex_open": True,
        },
    }
    result["context_digest"] = _digest(result)
    return result


def verify_market_structure_context(value: Mapping[str, Any]) -> bool:
    supplied = str(value.get("context_digest") or "")
    body = dict(value)
    body.pop("context_digest", None)
    return bool(supplied) and supplied == _digest(body)
