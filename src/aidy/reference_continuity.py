"""Day 3 continuity auditing for broker-free reference-price capture."""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime


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
class ReferenceContinuityPolicy:
    expected_source: str
    capture_enabled: bool
    ownership_confirmed: bool
    expected_cycle_seconds: int = 60
    stale_quote_seconds: float = 300.0


@dataclass(frozen=True, slots=True)
class ReferenceContinuityReport:
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
    timeframe_audits: dict[str, object]
    archive_population: int
    archive_checked: int
    archive_pending: int
    archive_retry_attempts: int
    archive_failed_rows: int
    archive_missing_objects: int
    archive_unverified_rows: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class D1R2ReferenceContinuityReader:
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
        policy: ReferenceContinuityPolicy,
        archive_limit: int = 40,
    ) -> ReferenceContinuityReport:
        if not 1 <= archive_limit <= 40:
            raise ValueError("AIDY archive reconciliation limit must be between 1 and 40.")
        window_start = _utc(start)
        window_end = _utc(end)
        if window_end <= window_start:
            raise ValueError("AIDY continuity audit end must be after start.")

        snapshot_rows = await self._rows(
            """
            SELECT captured_at,capture_status,quote_age_seconds,data_availability_json
            FROM market_snapshots
            WHERE captured_at>=? AND captured_at<?
            ORDER BY captured_at
            """,
            window_start,
            window_end,
        )
        archive_count_row = await self._stmt(
            """
            SELECT COUNT(*) AS count FROM archive_outbox
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

        expected_cycles = int((window_end - window_start).total_seconds()) // policy.expected_cycle_seconds
        observed_buckets: set[int] = set()
        status_counts: Counter[str] = Counter()
        quote_ages: list[float] = []
        stale_quote_count = 0
        source_errors: Counter[str] = Counter()
        observed_sources: set[str] = set()

        for row in snapshot_rows:
            captured = _parse_utc(_row_value(row, "captured_at"))
            bucket = int((captured - window_start).total_seconds()) // policy.expected_cycle_seconds
            if 0 <= bucket < expected_cycles:
                observed_buckets.add(bucket)
            status = str(_row_value(row, "capture_status"))
            status_counts[status] += 1
            raw_age = _row_value(row, "quote_age_seconds")
            if raw_age is not None:
                age = max(0.0, float(raw_age))
                quote_ages.append(age)
                if age > policy.stale_quote_seconds:
                    stale_quote_count += 1
            elif status == "complete":
                stale_quote_count += 1
            raw_availability = _row_value(row, "data_availability_json", "{}")
            try:
                availability = json.loads(str(raw_availability))
            except (TypeError, ValueError):
                availability = {"quote": "invalid_data_availability_json"}
            if not isinstance(availability, dict):
                availability = {"quote": "invalid_data_availability_json"}
            source = availability.get("market_data_source")
            if isinstance(source, str) and source:
                observed_sources.add(source)
            quote_state = availability.get("quote")
            if isinstance(quote_state, str) and quote_state != "available":
                source_errors[quote_state] += 1

        observed_cycles = len(observed_buckets)
        missing_cycles = max(0, expected_cycles - observed_cycles)
        missing_ratio = missing_cycles / expected_cycles if expected_cycles else 1.0
        ordered_buckets = sorted(observed_buckets)
        max_bucket_gap = 0
        previous = -1
        for bucket in ordered_buckets + [expected_cycles]:
            max_bucket_gap = max(max_bucket_gap, bucket - previous - 1)
            previous = bucket

        archive_pending = 0
        archive_retry_attempts = 0
        archive_failed_rows = 0
        archive_missing_objects = 0
        archive_unverified_rows = 0
        for row in archive_rows:
            status = str(_row_value(row, "status"))
            attempts = int(_row_value(row, "attempts", 0))
            last_error = _row_value(row, "last_error")
            archive_retry_attempts += max(0, attempts)
            if status == "pending":
                archive_pending += 1
            if attempts > 0 or last_error is not None:
                archive_failed_rows += 1
            if status == "archived":
                object_key = str(_row_value(row, "archive_key"))
                exists = await self._bucket.head(object_key)
                if exists is None:
                    archive_missing_objects += 1
            else:
                archive_unverified_rows += int(status not in {"pending", "archived"})

        failures: list[str] = []
        if not policy.capture_enabled:
            failures.append("capture_disabled")
        if not policy.ownership_confirmed:
            failures.append("market_data_ownership_unconfirmed")
        if observed_sources != {policy.expected_source}:
            failures.append("unexpected_or_missing_market_data_source")
        if missing_cycles:
            failures.append("material_capture_cycles_missing")
        if stale_quote_count:
            failures.append("stale_quotes_present")
        if status_counts["partial"]:
            failures.append("partial_snapshots_present")
        if status_counts["unavailable"]:
            failures.append("unavailable_snapshots_present")
        if source_errors:
            failures.append("market_source_errors_present")
        if archive_pending:
            failures.append("archive_backlog_present")
        if archive_failed_rows:
            failures.append("archive_retries_or_failures_present")
        if archive_missing_objects:
            failures.append("d1_r2_archive_mismatch")
        if archive_unverified_rows:
            failures.append("archive_objects_unverified")

        return ReferenceContinuityReport(
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
            max_capture_gap_seconds=max_bucket_gap * policy.expected_cycle_seconds,
            snapshots_complete=status_counts["complete"],
            snapshots_partial=status_counts["partial"],
            snapshots_unavailable=status_counts["unavailable"],
            quote_age_p50_seconds=_percentile(quote_ages, 0.50),
            quote_age_p95_seconds=_percentile(quote_ages, 0.95),
            quote_age_max_seconds=max(quote_ages) if quote_ages else None,
            stale_quote_count=stale_quote_count,
            source_error_counts=dict(sorted(source_errors.items())),
            timeframe_audits={},
            archive_population=archive_population,
            archive_checked=len(archive_rows),
            archive_pending=archive_pending,
            archive_retry_attempts=archive_retry_attempts,
            archive_failed_rows=archive_failed_rows,
            archive_missing_objects=archive_missing_objects,
            archive_unverified_rows=archive_unverified_rows,
        )
