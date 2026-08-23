from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from itertools import pairwise
from statistics import median
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

EVENT_INTELLIGENCE_VERSION = "aidy_macro_event_intelligence_v2"
EVENT_TIER_STUDY_VERSION = "aidy_j4_j15_event_tiers_v1"
PRE_EVENT_FEATURE_VERSION = "aidy_pre_event_structure_v1"
SURPRISE_CAPTURE_VERSION = "aidy_forward_macro_surprise_v1"
MIN_INDEPENDENT_EPISODES_PER_CLASS = 20

EVENT_CLASSES = (
    "initial_jobless_claims",
    "ism_manufacturing",
    "ism_services",
    "retail_sales",
    "fed_speech",
    "fed_chair_testimony",
    "fomc_minutes",
    "treasury_auction",
    "ecb_decision",
    "boj_decision",
    "boe_decision",
)

SOURCE_REGISTRY: dict[str, dict[str, Any]] = {
    "dol_initial_claims": {
        "institution": "US_DOL_ETA",
        "hosts": ("dol.gov", "www.dol.gov", "oui.doleta.gov"),
        "event_classes": ("initial_jobless_claims",),
    },
    "ism_reports": {
        "institution": "ISM",
        "hosts": ("ismworld.org", "www.ismworld.org"),
        "event_classes": ("ism_manufacturing", "ism_services"),
    },
    "census_economic_indicators": {
        "institution": "US_CENSUS",
        "hosts": ("census.gov", "www.census.gov"),
        "event_classes": ("retail_sales",),
    },
    "federal_reserve_calendar": {
        "institution": "FEDERAL_RESERVE_BOARD",
        "hosts": ("federalreserve.gov", "www.federalreserve.gov"),
        "event_classes": ("fed_speech", "fed_chair_testimony", "fomc_minutes"),
    },
    "treasury_fiscal_data": {
        "institution": "US_TREASURY",
        "hosts": ("fiscaldata.treasury.gov", "api.fiscaldata.treasury.gov"),
        "event_classes": ("treasury_auction",),
    },
    "ecb_calendar": {
        "institution": "ECB",
        "hosts": ("ecb.europa.eu", "www.ecb.europa.eu"),
        "event_classes": ("ecb_decision",),
    },
    "boj_calendar": {
        "institution": "BOJ",
        "hosts": ("boj.or.jp", "www.boj.or.jp"),
        "event_classes": ("boj_decision",),
    },
    "boe_calendar": {
        "institution": "BOE",
        "hosts": ("bankofengland.co.uk", "www.bankofengland.co.uk"),
        "event_classes": ("boe_decision",),
    },
}

TIER_WINDOWS = {
    "tier_1": {"minutes_before": 30, "minutes_after": 90},
    "tier_2": {"minutes_before": 60, "minutes_after": 180},
    "tier_3": {"minutes_before": 90, "minutes_after": 240},
}


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Macro-event timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _decimal(value: object) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Macro-event numeric values must be finite decimals.") from exc
    if not parsed.is_finite():
        raise ValueError("Macro-event numeric values must be finite decimals.")
    return parsed


def _quantized(value: float | Decimal, places: str = "0.000001") -> str:
    return str(Decimal(str(value)).quantize(Decimal(places)))


def _source_contract(source_key: str, event_class: str, source_url: str) -> dict[str, Any]:
    source = SOURCE_REGISTRY.get(source_key)
    if source is None:
        raise ValueError("Macro-event source is not registered.")
    if event_class not in source["event_classes"]:
        raise ValueError("Macro-event class is not permitted for this source.")
    parsed = urlparse(source_url)
    if parsed.scheme != "https" or parsed.hostname not in source["hosts"]:
        raise ValueError("Macro-event source URL is not on the official allowlist.")
    return source


def _local_to_utc(day: date, wall_time: time, timezone_name: str) -> datetime:
    timezone = ZoneInfo(timezone_name)
    local = datetime.combine(day, wall_time, tzinfo=timezone)
    # A round trip catches nonexistent DST wall times instead of silently normalizing them.
    if local.astimezone(UTC).astimezone(timezone).replace(fold=local.fold) != local:
        raise ValueError("Official schedule contains a nonexistent local wall time.")
    return local.astimezone(UTC)


def build_schedule_observation(
    *,
    event_class: str,
    source_key: str,
    external_id: str,
    scheduled_date: date | str,
    scheduled_time: time | str | None,
    timezone_name: str | None,
    first_observed_at: datetime | str,
    source_url: str,
    provenance_class: str = "pit_observed",
) -> dict[str, Any]:
    if event_class not in EVENT_CLASSES:
        raise ValueError("Unsupported Day 29 macro-event class.")
    source = _source_contract(source_key, event_class, source_url)
    day = scheduled_date if isinstance(scheduled_date, date) else date.fromisoformat(scheduled_date)
    observed = _utc(first_observed_at)
    if provenance_class not in {"pit_observed", "retrospective_official_schedule"}:
        raise ValueError("Unsupported schedule provenance class.")

    scheduled_at: str | None = None
    precision = "date_only"
    if scheduled_time is not None:
        if timezone_name is None:
            raise ValueError("A scheduled wall time requires an explicit IANA timezone.")
        wall = (
            scheduled_time
            if isinstance(scheduled_time, time)
            else time.fromisoformat(str(scheduled_time))
        )
        scheduled_at = _local_to_utc(day, wall, timezone_name).isoformat()
        precision = "minute"

    record: dict[str, Any] = {
        "schedule_version": EVENT_INTELLIGENCE_VERSION,
        "event_class": event_class,
        "institution": source["institution"],
        "source_key": source_key,
        "external_id": external_id,
        "scheduled_date": day.isoformat(),
        "scheduled_at": scheduled_at,
        "scheduled_time_precision": precision,
        "timezone_name": timezone_name,
        "first_observed_at": observed.isoformat(),
        "source_url": source_url,
        "provenance_class": provenance_class,
        "decision_input_allowed": provenance_class == "pit_observed",
        "future_derived": False,
    }
    record["schedule_digest"] = digest(record)
    return record


def verify_schedule_observation(record: Mapping[str, Any]) -> bool:
    body = dict(record)
    supplied = str(body.pop("schedule_digest", ""))
    if not supplied or supplied != digest(body):
        return False
    if body.get("schedule_version") != EVENT_INTELLIGENCE_VERSION:
        return False
    try:
        _source_contract(
            str(body["source_key"]), str(body["event_class"]), str(body["source_url"])
        )
        _utc(str(body["first_observed_at"]))
    except (KeyError, TypeError, ValueError):
        return False
    return body.get("future_derived") is False


def select_schedule_as_of(
    records: Iterable[Mapping[str, Any]], *, as_of: datetime | str
) -> list[dict[str, Any]]:
    cutoff = _utc(as_of)
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for value in records:
        record = dict(value)
        if not verify_schedule_observation(record):
            raise ValueError("Invalid schedule observation.")
        if record["provenance_class"] != "pit_observed":
            continue
        observed = _utc(str(record["first_observed_at"]))
        if observed > cutoff:
            continue
        key = (str(record["source_key"]), str(record["external_id"]))
        current = latest.get(key)
        if current is None or _utc(str(current["first_observed_at"])) < observed:
            latest[key] = record
    return sorted(
        latest.values(),
        key=lambda item: (
            str(item.get("scheduled_at") or "9999-12-31T23:59:59+00:00"),
            str(item["event_class"]),
            str(item["external_id"]),
        ),
    )


def _candle_time(row: Mapping[str, Any]) -> datetime:
    return _utc(str(row.get("open_time_utc") or ""))


def build_pre_event_features(
    *,
    schedule: Mapping[str, Any],
    candle_rows: Iterable[Mapping[str, Any]],
    as_of: datetime | str,
) -> dict[str, Any]:
    if not verify_schedule_observation(schedule):
        raise ValueError("Pre-event features require a valid schedule observation.")
    if schedule.get("scheduled_at") is None:
        result = {
            "feature_version": PRE_EVENT_FEATURE_VERSION,
            "state": "unknown_release_time",
            "event_class": schedule["event_class"],
            "schedule_digest": schedule["schedule_digest"],
            "future_values_used": False,
            "predictive_edge_claimed": False,
        }
        result["feature_digest"] = digest(result)
        return result

    event_at = _utc(str(schedule["scheduled_at"]))
    cutoff = _utc(as_of)
    if cutoff > event_at:
        raise ValueError("Pre-event features cannot be built after the scheduled release.")

    eligible: dict[datetime, Mapping[str, Any]] = {}
    for row in candle_rows:
        if str(row.get("symbol") or "") != "XAUUSD" or str(row.get("timeframe") or "") != "M1":
            continue
        stamp = _candle_time(row)
        if stamp + timedelta(minutes=1) <= cutoff:
            eligible[stamp] = row

    recent_start = event_at - timedelta(minutes=60)
    baseline_start = event_at - timedelta(minutes=300)
    recent = [eligible[t] for t in sorted(eligible) if recent_start <= t < event_at]
    baseline = [eligible[t] for t in sorted(eligible) if baseline_start <= t < recent_start]
    recent_coverage = len(recent) / 60
    baseline_coverage = len(baseline) / 240
    if recent_coverage < 0.8 or baseline_coverage < 0.8:
        result = {
            "feature_version": PRE_EVENT_FEATURE_VERSION,
            "state": "unknown_insufficient_pre_event_coverage",
            "event_class": schedule["event_class"],
            "schedule_digest": schedule["schedule_digest"],
            "recent_observed_minutes": len(recent),
            "baseline_observed_minutes": len(baseline),
            "future_values_used": False,
            "predictive_edge_claimed": False,
        }
        result["feature_digest"] = digest(result)
        return result

    def prices(rows: list[Mapping[str, Any]]) -> tuple[list[float], list[float], list[float]]:
        closes = [float(_decimal(row["close"])) for row in rows]
        highs = [float(_decimal(row["high"])) for row in rows]
        lows = [float(_decimal(row["low"])) for row in rows]
        if any(value <= 0 for value in closes + highs + lows):
            raise ValueError("Pre-event Gold prices must be positive.")
        return closes, highs, lows

    recent_close, recent_high, recent_low = prices(recent)
    baseline_close, _, _ = prices(baseline)

    def realized_vol(values: list[float]) -> float:
        returns = [math.log(right / left) * 10_000 for left, right in pairwise(values)]
        if len(returns) < 2:
            return 0.0
        mean = sum(returns) / len(returns)
        return math.sqrt(sum((item - mean) ** 2 for item in returns) / (len(returns) - 1))

    recent_vol = realized_vol(recent_close)
    baseline_vol = realized_vol(baseline_close)
    result = {
        "feature_version": PRE_EVENT_FEATURE_VERSION,
        "state": "known",
        "event_class": schedule["event_class"],
        "schedule_digest": schedule["schedule_digest"],
        "as_of_utc": cutoff.isoformat(),
        "release_at_utc": event_at.isoformat(),
        "recent_window_minutes": 60,
        "baseline_window_minutes": 240,
        "recent_observed_minutes": len(recent),
        "baseline_observed_minutes": len(baseline),
        "pre_event_drift_bps": _quantized(math.log(recent_close[-1] / recent_close[0]) * 10_000),
        "pre_event_range_bps": _quantized(
            (max(recent_high) - min(recent_low)) / recent_close[0] * 10_000
        ),
        "recent_realized_vol_bps": _quantized(recent_vol),
        "baseline_realized_vol_bps": _quantized(baseline_vol),
        "volatility_compression_ratio": (
            None if baseline_vol == 0 else _quantized(recent_vol / baseline_vol)
        ),
        "future_values_used": False,
        "predictive_edge_claimed": False,
    }
    result["feature_digest"] = digest(result)
    return result


def build_consensus_observation(
    *,
    schedule: Mapping[str, Any],
    value: object,
    unit: str,
    captured_at: datetime | str,
    source_url: str,
    source_qualification: str,
) -> dict[str, Any]:
    if not verify_schedule_observation(schedule) or schedule.get("scheduled_at") is None:
        raise ValueError("Consensus capture requires a valid minute-precision schedule.")
    captured = _utc(captured_at)
    if captured > _utc(str(schedule["scheduled_at"])):
        raise ValueError("Consensus must be captured no later than the scheduled release.")
    if source_qualification != "timestamped_immutable_approved":
        raise ValueError("Consensus source has not passed the immutable-source contract.")
    parsed = urlparse(source_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Consensus source URL must be HTTPS.")
    record: dict[str, Any] = {
        "surprise_capture_version": SURPRISE_CAPTURE_VERSION,
        "observation_type": "consensus",
        "schedule_digest": schedule["schedule_digest"],
        "event_class": schedule["event_class"],
        "value": str(_decimal(value)),
        "unit": unit,
        "captured_at": captured.isoformat(),
        "source_url": source_url,
        "source_qualification": source_qualification,
        "forward_capture_only": True,
        "historical_backfill_allowed": False,
    }
    record["observation_digest"] = digest(record)
    return record


def build_actual_observation(
    *,
    schedule: Mapping[str, Any],
    value: object,
    unit: str,
    first_observed_at: datetime | str,
    published_at: datetime | str | None,
    source_url: str,
    revision_index: int,
    previous_value: object | None = None,
) -> dict[str, Any]:
    if not verify_schedule_observation(schedule):
        raise ValueError("Actual capture requires a valid schedule observation.")
    if revision_index < 0:
        raise ValueError("Revision index cannot be negative.")
    observed = _utc(first_observed_at)
    published = None if published_at is None else _utc(published_at)
    if published is not None and observed < published:
        raise ValueError("AIDY cannot observe an official actual before publication.")
    record: dict[str, Any] = {
        "surprise_capture_version": SURPRISE_CAPTURE_VERSION,
        "observation_type": "actual",
        "schedule_digest": schedule["schedule_digest"],
        "event_class": schedule["event_class"],
        "value": str(_decimal(value)),
        "unit": unit,
        "first_observed_at": observed.isoformat(),
        "published_at": None if published is None else published.isoformat(),
        "source_url": source_url,
        "revision_index": revision_index,
        "print_type": "first_print" if revision_index == 0 else "revision",
        "previous_value": None if previous_value is None else str(_decimal(previous_value)),
        "forward_capture_only": True,
    }
    record["observation_digest"] = digest(record)
    return record


def build_surprise_state(
    *,
    schedule: Mapping[str, Any],
    consensus_observations: Iterable[Mapping[str, Any]],
    actual_observations: Iterable[Mapping[str, Any]],
    as_of: datetime | str,
) -> dict[str, Any]:
    if not verify_schedule_observation(schedule):
        raise ValueError("Surprise state requires a valid schedule observation.")
    cutoff = _utc(as_of)
    consensus = [
        dict(item)
        for item in consensus_observations
        if item.get("schedule_digest") == schedule["schedule_digest"]
        and _utc(str(item["captured_at"])) <= cutoff
    ]
    actuals = [
        dict(item)
        for item in actual_observations
        if item.get("schedule_digest") == schedule["schedule_digest"]
        and _utc(str(item["first_observed_at"])) <= cutoff
    ]
    consensus.sort(key=lambda item: str(item["captured_at"]))
    actuals.sort(key=lambda item: (int(item["revision_index"]), str(item["first_observed_at"])))
    chosen_consensus = consensus[-1] if consensus else None
    first_print = next((item for item in actuals if int(item["revision_index"]) == 0), None)
    latest_actual = actuals[-1] if actuals else None

    state = "unknown"
    surprise = None
    if chosen_consensus is not None and first_print is not None:
        if chosen_consensus["unit"] != first_print["unit"]:
            raise ValueError("Consensus and actual units differ.")
        state = "known"
        surprise = str(_decimal(first_print["value"]) - _decimal(chosen_consensus["value"]))
    result: dict[str, Any] = {
        "surprise_capture_version": SURPRISE_CAPTURE_VERSION,
        "event_class": schedule["event_class"],
        "schedule_digest": schedule["schedule_digest"],
        "as_of_utc": cutoff.isoformat(),
        "consensus_state": "known" if chosen_consensus is not None else "unknown",
        "first_print_state": "known" if first_print is not None else "unknown",
        "latest_actual_state": "known" if latest_actual is not None else "unknown",
        "surprise_state": state,
        "surprise_value": surprise,
        "consensus_observation_digest": (
            None if chosen_consensus is None else chosen_consensus["observation_digest"]
        ),
        "first_print_observation_digest": (
            None if first_print is None else first_print["observation_digest"]
        ),
        "latest_revision_index": (
            None if latest_actual is None else int(latest_actual["revision_index"])
        ),
        "historical_consensus_backfilled": False,
        "predictive_edge_claimed": False,
        "trading_gate_created": False,
    }
    result["surprise_digest"] = digest(result)
    return result


def _quantiles(values: list[Decimal]) -> dict[str, str | None]:
    if not values:
        return {"min": None, "median": None, "max": None}
    ordered = sorted(values)
    return {
        "min": str(ordered[0]),
        "median": str(median(ordered)),
        "max": str(ordered[-1]),
    }


def run_j4_j15_descriptive(episodes: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    forbidden = ("pnl", "profit", "win_rate", "trade_result", "loss")
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in episodes:
        if any(name in raw for name in forbidden):
            raise ValueError("J4/J15 event tiering cannot use trade P/L or win/loss fields.")
        item = dict(raw)
        event_class = str(item.get("event_class") or "")
        if event_class not in EVENT_CLASSES:
            raise ValueError("J4/J15 episode has an unsupported event class.")
        episode_id = str(item.get("independent_episode_id") or "")
        if not episode_id:
            raise ValueError("J4/J15 requires an independent episode identity.")
        item["post_abs_return_bps"] = str(_decimal(item["post_abs_return_bps"]))
        item["post_realized_vol_bps"] = str(_decimal(item["post_realized_vol_bps"]))
        item["outcome_return_bps"] = str(_decimal(item["outcome_return_bps"]))
        key = (event_class, episode_id)
        if key in unique and unique[key] != item:
            raise ValueError("Conflicting rows share a J4/J15 independent episode identity.")
        unique[key] = item

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in unique.values():
        grouped[str(item["event_class"])].append(item)

    class_results: dict[str, dict[str, Any]] = {}
    tier_counts: Counter[str] = Counter()
    for event_class in EVENT_CLASSES:
        rows = grouped[event_class]
        moves = [_decimal(item["post_abs_return_bps"]) for item in rows]
        vols = [_decimal(item["post_realized_vol_bps"]) for item in rows]
        outcomes = [_decimal(item["outcome_return_bps"]) for item in rows]
        tier = "unclassified_insufficient_evidence"
        if len(rows) >= MIN_INDEPENDENT_EPISODES_PER_CLASS:
            impact = Decimal(str(median(moves))) + Decimal(str(median(vols)))
            if impact >= Decimal(30):
                tier = "tier_3"
            elif impact >= Decimal(15):
                tier = "tier_2"
            else:
                tier = "tier_1"
        tier_counts[tier] += 1
        class_results[event_class] = {
            "independent_episode_n": len(rows),
            "tier_state": tier,
            "post_abs_return_bps_distribution": _quantiles(moves),
            "post_realized_vol_bps_distribution": _quantiles(vols),
            "outcome_return_bps_distribution": _quantiles(outcomes),
            "window": TIER_WINDOWS.get(tier),
        }

    result: dict[str, Any] = {
        "study_version": EVENT_TIER_STUDY_VERSION,
        "preregistered_min_independent_episodes_per_class": MIN_INDEPENDENT_EPISODES_PER_CLASS,
        "tier_thresholds": {
            "metric": "median_post_abs_return_bps_plus_median_post_realized_vol_bps",
            "tier_3_gte": "30",
            "tier_2_gte": "15",
            "tier_1_lt": "15",
        },
        "independent_episode_count": len(unique),
        "class_results": class_results,
        "tier_state_counts": dict(sorted(tier_counts.items())),
        "trade_pnl_used": False,
        "directional_prediction_tested": False,
        "descriptive_only": True,
        "null_or_pruning_outcome_allowed": True,
        "predictive_edge_claimed": False,
        "trading_gate_created": False,
    }
    result["study_digest"] = digest(result)
    return result


def verify_j4_j15_study(study: Mapping[str, Any]) -> bool:
    body = dict(study)
    supplied = str(body.pop("study_digest", ""))
    return (
        bool(supplied)
        and supplied == digest(body)
        and body.get("study_version") == EVENT_TIER_STUDY_VERSION
        and body.get("trade_pnl_used") is False
        and body.get("descriptive_only") is True
        and body.get("predictive_edge_claimed") is False
        and body.get("trading_gate_created") is False
    )


def build_event_intelligence_state(
    *,
    as_of: datetime | str,
    schedule_records: Iterable[Mapping[str, Any]],
    tier_study: Mapping[str, Any],
) -> dict[str, Any]:
    if not verify_j4_j15_study(tier_study):
        raise ValueError("Event intelligence requires a valid J4/J15 descriptive study.")
    cutoff = _utc(as_of)
    schedules = select_schedule_as_of(schedule_records, as_of=cutoff)
    timed = [item for item in schedules if item.get("scheduled_at") is not None]
    timed.sort(key=lambda item: str(item["scheduled_at"]))
    upcoming = next((item for item in timed if _utc(str(item["scheduled_at"])) >= cutoff), None)
    current: list[dict[str, Any]] = []
    unknown_severity_nearby = False
    for schedule in timed:
        event_at = _utc(str(schedule["scheduled_at"]))
        class_result = tier_study["class_results"][str(schedule["event_class"])]
        tier = str(class_result["tier_state"])
        window = TIER_WINDOWS.get(tier)
        if window is None:
            if abs((event_at - cutoff).total_seconds()) <= 4 * 60 * 60:
                unknown_severity_nearby = True
            continue
        start = event_at - timedelta(minutes=window["minutes_before"])
        end = event_at + timedelta(minutes=window["minutes_after"])
        if start <= cutoff <= end:
            current.append(
                {
                    "event_class": schedule["event_class"],
                    "external_id": schedule["external_id"],
                    "scheduled_at": schedule["scheduled_at"],
                    "tier": tier,
                    "window": window,
                    "schedule_digest": schedule["schedule_digest"],
                }
            )
    timing_state = "inside_tiered_window" if current else "clear_tiered_windows"
    if unknown_severity_nearby:
        timing_state = "unknown_severity_nearby"
    result: dict[str, Any] = {
        "event_intelligence_version": EVENT_INTELLIGENCE_VERSION,
        "as_of_utc": cutoff.isoformat(),
        "timing_state": timing_state,
        "events_in_window": current,
        "next_scheduled_event": (
            None
            if upcoming is None
            else {
                "event_class": upcoming["event_class"],
                "external_id": upcoming["external_id"],
                "scheduled_at": upcoming["scheduled_at"],
                "tier_state": tier_study["class_results"][str(upcoming["event_class"])][
                    "tier_state"
                ],
                "schedule_digest": upcoming["schedule_digest"],
            }
        ),
        "known_pit_schedule_count": len(schedules),
        "date_only_schedule_count": sum(item.get("scheduled_at") is None for item in schedules),
        "tier_study_digest": tier_study["study_digest"],
        "one_size_window_used": False,
        "historical_consensus_backfilled": False,
        "predictive_edge_claimed": False,
        "trading_gate_created": False,
    }
    result["event_intelligence_digest"] = digest(result)
    return result


def verify_event_intelligence_state(state: Mapping[str, Any]) -> bool:
    body = dict(state)
    supplied = str(body.pop("event_intelligence_digest", ""))
    return (
        bool(supplied)
        and supplied == digest(body)
        and body.get("event_intelligence_version") == EVENT_INTELLIGENCE_VERSION
        and body.get("one_size_window_used") is False
        and body.get("historical_consensus_backfilled") is False
        and body.get("predictive_edge_claimed") is False
        and body.get("trading_gate_created") is False
    )
