"""Deterministic Day 3 capture-continuity and archive-health auditing.

The auditor is deliberately provider-agnostic. It evaluates only evidence that
was committed to D1 and verifies a bounded, explicitly reported sample of D1
archive pointers against R2. It never reads broker positions or mutates trading
accounts.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise

_MAX_CONTINUITY_WINDOW = timedelta(hours=24)
_MAX_CONTINUITY_SNAPSHOT_ROWS = 1600
_MAX_CONTINUITY_CANDLE_ROWS = 10000

TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}

_NON_ERROR_AVAILABILITY = {
    "available",
    "open",
    "closed_or_stale",
    "point_in_time_linked",
    "not_configured_phase0",
    "fed_rss_separate_loop",
    "not_captured_phase0",
}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("AIDY continuity audit requires timezone-aware datetimes.")
    return value.astimezone(UTC)


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("AIDY continuity evidence contains an invalid timestamp.")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    parsed = datetime.fromisoformat(raw)
    return _utc(parsed)


def _row_value(row: object, key: str, default: object = None) -> object:
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]  # type: ignore[index]
    except (KeyError, TypeError, IndexError):
        return getattr(row, key, default)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


@dataclass(frozen=True, slots=True)
class SnapshotObservation:
    captured_at: datetime
    capture_status: str
    quote_age_seconds: float | None
    data_availability: dict[str, object]


@dataclass(frozen=True, slots=True)
class CandleObservation:
    source: str
    timeframe: str
    open_time_utc: datetime
    revision_index: int


@dataclass(frozen=True, slots=True)
class ArchiveObservation:
    status: str
    attempts: int
    last_error: str | None
    object_key: str
    object_exists: bool | None


@dataclass(frozen=True, slots=True)
class ContinuityPolicy:
    expected_source: str
    capture_enabled: bool
    ownership_confirmed: bool
    required_timeframes: tuple[str, ...] = ("1m", "5m")
    expected_cycle_seconds: int = 60
    stale_quote_seconds: float = 300.0
    max_missing_cycle_ratio: float = 0.0
    max_stale_quote_ratio: float = 0.0
    max_partial_ratio: float = 0.0
    max_unavailable_ratio: float = 0.0


@dataclass(frozen=True, slots=True)
class TimeframeAudit:
    observed_candles: int
    revision_rows: int
    gap_count: int
    missing_intervals: int
    max_gap_seconds: int


@dataclass(frozen=True, slots=True)
class ContinuityReport:
    window_start: str
    window_end: str
    passed: bool
    failure_reasons: tuple[str, ...]
    expected_source: str
    observed_sources: tuple[str, ...]
    expected_cycles: int
    observed_cycles: int
    missing_cycles: int
    missing_cycle_ratio: float
    max_capture_gap_seconds: int
    snapshots_complete: int
    snapshots_partial: int
    snapshots_unavailable: int
    quote_age_p50_seconds: float | None
    quote_age_p95_seconds: float | None
    quote_age_max_seconds: float | None
    stale_quote_count: int
    source_error_counts: dict[str, int]
    timeframe_audits: dict[str, TimeframeAudit]
    archive_population: int
    archive_checked: int
    archive_pending: int
    archive_retry_attempts: int
    archive_failed_rows: int
    archive_missing_objects: int
    archive_unverified_rows: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def audit_continuity(
    *,
    start: datetime,
    end: datetime,
    snapshots: list[SnapshotObservation],
    candles: list[CandleObservation],
    archives: list[ArchiveObservation],
    archive_population: int,
    policy: ContinuityPolicy,
) -> ContinuityReport:
    """Evaluate one fixed point-in-time window and fail closed on bad evidence."""

    window_start = _utc(start)
    window_end = _utc(end)
    if window_end <= window_start:
        raise ValueError("AIDY continuity audit end must be after start.")
    if policy.expected_cycle_seconds <= 0:
        raise ValueError("AIDY continuity cycle must be positive.")
    if not policy.expected_source.strip():
        raise ValueError("AIDY continuity audit requires an expected source.")

    expected_cycles = int((window_end - window_start).total_seconds()) // policy.expected_cycle_seconds
    observed_buckets: set[int] = set()
    snapshot_times: list[datetime] = []
    status_counts: Counter[str] = Counter()
    quote_ages: list[float] = []
    stale_quote_count = 0
    source_errors: Counter[str] = Counter()

    for snapshot in snapshots:
        captured = _utc(snapshot.captured_at)
        if not window_start <= captured < window_end:
            continue
        bucket = int((captured - window_start).total_seconds()) // policy.expected_cycle_seconds
        if 0 <= bucket < expected_cycles:
            observed_buckets.add(bucket)
            snapshot_times.append(captured)
        status_counts[snapshot.capture_status] += 1
        if snapshot.quote_age_seconds is not None:
            age = max(0.0, float(snapshot.quote_age_seconds))
            quote_ages.append(age)
            if age > policy.stale_quote_seconds:
                stale_quote_count += 1
        elif snapshot.capture_status == "complete":
            stale_quote_count += 1
        for value in snapshot.data_availability.values():
            if isinstance(value, str) and value not in _NON_ERROR_AVAILABILITY:
                source_errors[value] += 1

    observed_cycles = len(observed_buckets)
    missing_cycles = max(0, expected_cycles - observed_cycles)
    missing_ratio = missing_cycles / expected_cycles if expected_cycles else 1.0
    ordered_buckets = sorted(observed_buckets)
    max_bucket_gap = 0
    previous = -1
    for bucket in ordered_buckets + [expected_cycles]:
        max_bucket_gap = max(max_bucket_gap, bucket - previous - 1)
        previous = bucket
    max_capture_gap_seconds = max_bucket_gap * policy.expected_cycle_seconds

    timeframe_rows: dict[str, list[CandleObservation]] = defaultdict(list)
    observed_sources: set[str] = set()
    for candle in candles:
        opened = _utc(candle.open_time_utc)
        if not window_start <= opened < window_end:
            continue
        observed_sources.add(candle.source)
        if candle.timeframe in TIMEFRAME_SECONDS:
            timeframe_rows[candle.timeframe].append(candle)

    timeframe_audits: dict[str, TimeframeAudit] = {}
    for timeframe, seconds in TIMEFRAME_SECONDS.items():
        rows = timeframe_rows.get(timeframe, [])
        unique_times = sorted({_utc(row.open_time_utc) for row in rows})
        gap_count = 0
        missing_intervals = 0
        max_gap_seconds = 0
        for previous_time, current_time in pairwise(unique_times):
            gap_seconds = int((current_time - previous_time).total_seconds())
            if gap_seconds > seconds:
                gap_count += 1
                missing_intervals += max(0, gap_seconds // seconds - 1)
                max_gap_seconds = max(max_gap_seconds, gap_seconds)
        timeframe_audits[timeframe] = TimeframeAudit(
            observed_candles=len(unique_times),
            revision_rows=sum(1 for row in rows if row.revision_index > 1),
            gap_count=gap_count,
            missing_intervals=missing_intervals,
            max_gap_seconds=max_gap_seconds,
        )

    archive_pending = sum(1 for row in archives if row.status == "pending")
    archive_retry_attempts = sum(max(0, row.attempts) for row in archives)
    archive_failed_rows = sum(
        1 for row in archives if row.attempts > 0 or row.last_error is not None
    )
    archive_missing_objects = sum(
        1 for row in archives if row.status == "archived" and row.object_exists is False
    )
    archive_unverified_rows = sum(
        1 for row in archives if row.status == "archived" and row.object_exists is None
    )

    total_snapshots = sum(status_counts.values())
    partial_ratio = status_counts["partial"] / total_snapshots if total_snapshots else 1.0
    unavailable_ratio = (
        status_counts["unavailable"] / total_snapshots if total_snapshots else 1.0
    )
    stale_ratio = stale_quote_count / total_snapshots if total_snapshots else 1.0
    failures: list[str] = []
    if not policy.capture_enabled:
        failures.append("capture_disabled")
    if not policy.ownership_confirmed:
        failures.append("market_data_ownership_unconfirmed")
    if observed_sources != {policy.expected_source}:
        failures.append("unexpected_or_missing_market_data_source")
    if missing_ratio > policy.max_missing_cycle_ratio:
        failures.append("material_capture_cycles_missing")
    if stale_ratio > policy.max_stale_quote_ratio:
        failures.append("stale_quotes_present")
    if partial_ratio > policy.max_partial_ratio:
        failures.append("partial_snapshots_present")
    if unavailable_ratio > policy.max_unavailable_ratio:
        failures.append("unavailable_snapshots_present")
    if source_errors:
        failures.append("market_source_errors_present")
    if any(item.gap_count > 0 for item in timeframe_audits.values()):
        failures.append("timeframe_candle_gaps_present")
    if any(
        timeframe_audits.get(timeframe, TimeframeAudit(0, 0, 0, 0, 0)).observed_candles
        == 0
        for timeframe in policy.required_timeframes
    ):
        failures.append("required_timeframe_missing")
    if archive_pending:
        failures.append("archive_backlog_present")
    if archive_failed_rows:
        failures.append("archive_retries_or_failures_present")
    if archive_missing_objects:
        failures.append("d1_r2_archive_mismatch")
    if archive_unverified_rows:
        failures.append("archive_objects_unverified")

    return ContinuityReport(
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        passed=not failures,
        failure_reasons=tuple(failures),
        expected_source=policy.expected_source,
        observed_sources=tuple(sorted(observed_sources)),
        expected_cycles=expected_cycles,
        observed_cycles=observed_cycles,
        missing_cycles=missing_cycles,
        missing_cycle_ratio=missing_ratio,
        max_capture_gap_seconds=max_capture_gap_seconds,
        snapshots_complete=status_counts["complete"],
        snapshots_partial=status_counts["partial"],
        snapshots_unavailable=status_counts["unavailable"],
        quote_age_p50_seconds=_percentile(quote_ages, 0.50),
        quote_age_p95_seconds=_percentile(quote_ages, 0.95),
        quote_age_max_seconds=max(quote_ages) if quote_ages else None,
        stale_quote_count=stale_quote_count,
        source_error_counts=dict(sorted(source_errors.items())),
        timeframe_audits=timeframe_audits,
        archive_population=max(0, archive_population),
        archive_checked=len(archives),
        archive_pending=archive_pending,
        archive_retry_attempts=archive_retry_attempts,
        archive_failed_rows=archive_failed_rows,
        archive_missing_objects=archive_missing_objects,
        archive_unverified_rows=archive_unverified_rows,
    )


class D1R2ContinuityReader:
    """Read aggregate Day 3 inputs through Cloudflare D1/R2 bindings."""

    def __init__(self, database: object, bucket: object) -> None:
        self._db = database
        self._bucket = bucket

    def _stmt(self, sql: str, *params: object) -> object:
        values = [value.isoformat() if isinstance(value, datetime) else value for value in params]
        return self._db.prepare(sql).bind(*values)

    async def _rows(self, sql: str, *params: object) -> list[object]:
        result = await self._stmt(sql, *params).all()
        return list(_row_value(result, "results", []) or [])

    async def load_and_audit(
        self,
        *,
        start: datetime,
        end: datetime,
        policy: ContinuityPolicy,
        archive_limit: int = 40,
    ) -> ContinuityReport:
        if not 1 <= archive_limit <= 40:
            raise ValueError("AIDY archive reconciliation limit must be between 1 and 40.")
        window_start = _utc(start)
        window_end = _utc(end)
        if window_end <= window_start:
            raise ValueError("AIDY continuity audit end must be after start.")
        if window_end - window_start > _MAX_CONTINUITY_WINDOW:
            raise ValueError("AIDY continuity audit window is capped at 24 hours.")
        snapshot_rows = await self._rows(
            """
            SELECT captured_at,capture_status,quote_age_seconds,data_availability_json
            FROM market_snapshots
            WHERE captured_at>=? AND captured_at<?
            ORDER BY captured_at
            LIMIT ?
            """,
            window_start,
            window_end,
            _MAX_CONTINUITY_SNAPSHOT_ROWS + 1,
        )
        if len(snapshot_rows) > _MAX_CONTINUITY_SNAPSHOT_ROWS:
            raise RuntimeError("AIDY continuity snapshot row bound exceeded.")
        candle_rows = await self._rows(
            """
            SELECT source,timeframe,open_time_utc,revision_index
            FROM market_candles
            WHERE open_time_utc>=? AND open_time_utc<?
            ORDER BY timeframe,open_time_utc,revision_index
            LIMIT ?
            """,
            window_start,
            window_end,
            _MAX_CONTINUITY_CANDLE_ROWS + 1,
        )
        if len(candle_rows) > _MAX_CONTINUITY_CANDLE_ROWS:
            raise RuntimeError("AIDY continuity candle row bound exceeded.")
        archive_count_row = await self._stmt(
            """
            SELECT COUNT(*) AS count
            FROM archive_outbox
            WHERE created_at>=? AND created_at<?
            """,
            window_start,
            window_end,
        ).first()
        archive_population = int(_row_value(archive_count_row, "count", 0))
        archive_rows = await self._rows(
            """
            SELECT status,attempts,last_error,archive_key
            FROM archive_outbox
            WHERE (created_at>=? AND created_at<?) OR status='pending'
            ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END,created_at DESC,id DESC
            LIMIT ?
            """,
            window_start,
            window_end,
            archive_limit,
        )

        snapshots: list[SnapshotObservation] = []
        for row in snapshot_rows:
            raw_availability = _row_value(row, "data_availability_json", "{}")
            try:
                availability = json.loads(str(raw_availability))
            except (TypeError, ValueError):
                availability = {"audit": "invalid_data_availability_json"}
            if not isinstance(availability, dict):
                availability = {"audit": "invalid_data_availability_json"}
            raw_age = _row_value(row, "quote_age_seconds")
            snapshots.append(
                SnapshotObservation(
                    captured_at=_parse_utc(_row_value(row, "captured_at")),
                    capture_status=str(_row_value(row, "capture_status")),
                    quote_age_seconds=float(raw_age) if raw_age is not None else None,
                    data_availability=availability,
                )
            )

        candles = [
            CandleObservation(
                source=str(_row_value(row, "source")),
                timeframe=str(_row_value(row, "timeframe")),
                open_time_utc=_parse_utc(_row_value(row, "open_time_utc")),
                revision_index=int(_row_value(row, "revision_index", 1)),
            )
            for row in candle_rows
        ]
        archives: list[ArchiveObservation] = []
        for row in archive_rows:
            status = str(_row_value(row, "status"))
            object_key = str(_row_value(row, "archive_key"))
            object_exists: bool | None = None
            if status == "archived":
                object_exists = await self._bucket.head(object_key) is not None
            archives.append(
                ArchiveObservation(
                    status=status,
                    attempts=int(_row_value(row, "attempts", 0)),
                    last_error=(
                        str(_row_value(row, "last_error"))
                        if _row_value(row, "last_error") is not None
                        else None
                    ),
                    object_key=object_key,
                    object_exists=object_exists,
                )
            )

        return audit_continuity(
            start=window_start,
            end=window_end,
            snapshots=snapshots,
            candles=candles,
            archives=archives,
            archive_population=archive_population,
            policy=policy,
        )


def audit_window(*, end: datetime, minutes: int) -> tuple[datetime, datetime]:
    if not 5 <= minutes <= 1440:
        raise ValueError("AIDY continuity window must be between 5 and 1440 minutes.")
    window_end = _utc(end).replace(second=0, microsecond=0)
    return window_end - timedelta(minutes=minutes), window_end
