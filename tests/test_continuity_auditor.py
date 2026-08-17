from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aidy.continuity_auditor import (
    ArchiveObservation,
    CandleObservation,
    ContinuityPolicy,
    SnapshotObservation,
    audit_continuity,
    audit_window,
)

START = datetime(2026, 8, 17, 8, 0, tzinfo=UTC)
END = START + timedelta(minutes=5)


def _snapshots() -> list[SnapshotObservation]:
    return [
        SnapshotObservation(
            captured_at=START + timedelta(minutes=index),
            capture_status="complete",
            quote_age_seconds=1.0 + index,
            data_availability={
                "quote": "available",
                "candles_1m": "available",
                "candles_5m": "available",
                "market_state": "open",
            },
        )
        for index in range(5)
    ]


def _candles(*, source: str = "metaapi") -> list[CandleObservation]:
    rows = [
        CandleObservation(
            source=source,
            timeframe="1m",
            open_time_utc=START + timedelta(minutes=index),
            revision_index=1,
        )
        for index in range(5)
    ]
    rows.append(
        CandleObservation(
            source=source,
            timeframe="5m",
            open_time_utc=START,
            revision_index=1,
        )
    )
    return rows


def _archives() -> list[ArchiveObservation]:
    return [
        ArchiveObservation(
            status="archived",
            attempts=0,
            last_error=None,
            object_key=f"gold/test/{index}.json",
            object_exists=True,
        )
        for index in range(3)
    ]


def _policy(**overrides) -> ContinuityPolicy:
    values = {
        "expected_source": "metaapi",
        "capture_enabled": True,
        "ownership_confirmed": True,
        "stale_quote_seconds": 30.0,
    }
    values.update(overrides)
    return ContinuityPolicy(**values)


def _audit(
    *,
    snapshots: list[SnapshotObservation] | None = None,
    candles: list[CandleObservation] | None = None,
    archives: list[ArchiveObservation] | None = None,
    policy: ContinuityPolicy | None = None,
):
    archive_rows = _archives() if archives is None else archives
    return audit_continuity(
        start=START,
        end=END,
        snapshots=_snapshots() if snapshots is None else snapshots,
        candles=_candles() if candles is None else candles,
        archives=archive_rows,
        archive_population=len(archive_rows),
        policy=policy or _policy(),
    )


def test_complete_continuity_window_passes() -> None:
    report = _audit()
    assert report.passed is True
    assert report.failure_reasons == ()
    assert report.expected_cycles == 5
    assert report.observed_cycles == 5
    assert report.missing_cycles == 0
    assert report.quote_age_p95_seconds == 5.0
    assert report.timeframe_audits["1m"].gap_count == 0
    assert report.archive_checked == 3


def test_injected_capture_gap_fails_closed() -> None:
    snapshots = _snapshots()
    del snapshots[2]
    report = _audit(snapshots=snapshots)
    assert report.passed is False
    assert report.missing_cycles == 1
    assert "material_capture_cycles_missing" in report.failure_reasons


def test_stale_partial_unavailable_and_source_errors_are_visible() -> None:
    snapshots = _snapshots()
    snapshots[0] = SnapshotObservation(
        captured_at=snapshots[0].captured_at,
        capture_status="partial",
        quote_age_seconds=90.0,
        data_availability={"quote": "metaapi_timeout"},
    )
    snapshots[1] = SnapshotObservation(
        captured_at=snapshots[1].captured_at,
        capture_status="unavailable",
        quote_age_seconds=None,
        data_availability={"region": "metaapi_temporarily_unavailable"},
    )
    report = _audit(snapshots=snapshots)
    assert report.passed is False
    assert report.snapshots_partial == 1
    assert report.snapshots_unavailable == 1
    assert report.stale_quote_count == 1
    assert report.source_error_counts == {
        "metaapi_temporarily_unavailable": 1,
        "metaapi_timeout": 1,
    }
    assert "market_source_errors_present" in report.failure_reasons


def test_injected_timeframe_gap_and_missing_required_timeframe_fail() -> None:
    one_minute_gap = [
        row for row in _candles() if row.open_time_utc != START + timedelta(minutes=2)
    ]
    report = _audit(candles=one_minute_gap)
    assert report.timeframe_audits["1m"].missing_intervals == 1
    assert "timeframe_candle_gaps_present" in report.failure_reasons

    no_five_minute = [row for row in _candles() if row.timeframe == "1m"]
    report = _audit(candles=no_five_minute)
    assert "required_timeframe_missing" in report.failure_reasons


def test_wrong_source_disabled_capture_and_unconfirmed_ownership_fail() -> None:
    report = _audit(
        candles=_candles(source="super_signals_shared"),
        policy=_policy(capture_enabled=False, ownership_confirmed=False),
    )
    assert report.passed is False
    assert "capture_disabled" in report.failure_reasons
    assert "market_data_ownership_unconfirmed" in report.failure_reasons
    assert "unexpected_or_missing_market_data_source" in report.failure_reasons


def test_archive_backlog_retry_and_missing_r2_object_fail() -> None:
    archives = [
        ArchiveObservation("pending", 2, "archive_error:Timeout", "pending.json", None),
        ArchiveObservation("archived", 0, None, "missing.json", False),
    ]
    report = _audit(archives=archives)
    assert report.passed is False
    assert report.archive_pending == 1
    assert report.archive_retry_attempts == 2
    assert report.archive_missing_objects == 1
    assert "archive_backlog_present" in report.failure_reasons
    assert "archive_retries_or_failures_present" in report.failure_reasons
    assert "d1_r2_archive_mismatch" in report.failure_reasons


def test_complete_snapshot_without_quote_age_is_stale() -> None:
    snapshots = _snapshots()
    snapshots[0] = SnapshotObservation(
        captured_at=snapshots[0].captured_at,
        capture_status="complete",
        quote_age_seconds=None,
        data_availability={"quote": "available"},
    )
    report = _audit(snapshots=snapshots)
    assert report.stale_quote_count == 1
    assert "stale_quotes_present" in report.failure_reasons


def test_window_bounds_are_strict() -> None:
    assert audit_window(end=END + timedelta(seconds=59), minutes=5) == (START, END)
    with pytest.raises(ValueError):
        audit_window(end=END, minutes=4)
