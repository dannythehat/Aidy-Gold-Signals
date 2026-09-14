"""Pin the M1 publication-lag sampling defect observed in production on 2026-09-14.

Twelve Data publishes each closed M1 bar roughly 64 seconds after it closes. Sampling a
just-closed aggregate bucket at the boundary therefore always misses that bucket's final
minute. In production every capture reported 5m coverage 0.800 with observed lag
63.8-64.0s, so ``all_timeframes_ready`` was never true, every snapshot stayed ``partial``,
every forward evaluation was ``pre_model_blocked`` with ``market_reference_not_complete``,
and AIDY never executed a single decision cycle.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aidy.runtime import MARKET_PUBLICATION_LAG_OFFSET_SECONDS, interval_due
from aidy.twelve_data_market import latest_completed_bucket

OBSERVED_VENDOR_PUBLICATION_LAG_SECONDS = 64.0
POLL_SECONDS = 300


def _bar_published_by(bar_open: datetime) -> datetime:
    """Wall-clock time at which the vendor has published the bar opening at ``bar_open``."""
    return bar_open + timedelta(minutes=1, seconds=OBSERVED_VENDOR_PUBLICATION_LAG_SECONDS)


def _capture_times(day: datetime, *, offset_seconds: int) -> list[datetime]:
    """Every minute tick of an hour on which market capture would be due."""
    return [
        tick
        for minute in range(60)
        if interval_due(
            (tick := day + timedelta(minutes=minute, seconds=3)),
            POLL_SECONDS,
            offset_seconds=offset_seconds,
        )
    ]


def test_boundary_sampling_always_misses_the_final_minute_of_the_bucket() -> None:
    """The old boundary-aligned behaviour is reproduced as a failing data condition."""
    capture_at = datetime(2026, 9, 14, 11, 15, 3, tzinfo=UTC)
    assert interval_due(capture_at, POLL_SECONDS, offset_seconds=0)

    bucket_start, bucket_end = latest_completed_bucket(capture_at, "5m")
    assert (bucket_start, bucket_end) == (
        datetime(2026, 9, 14, 11, 10, tzinfo=UTC),
        datetime(2026, 9, 14, 11, 15, tzinfo=UTC),
    )

    final_bar_open = bucket_end - timedelta(minutes=1)
    assert _bar_published_by(final_bar_open) > capture_at, (
        "regression guard: the defect requires the final bar to be unpublished at capture"
    )


def test_offset_sampling_sees_every_minute_of_the_bucket() -> None:
    """With the publication-lag offset the whole bucket is available when sampled."""
    capture_at = datetime(2026, 9, 14, 11, 17, 3, tzinfo=UTC)
    assert interval_due(
        capture_at, POLL_SECONDS, offset_seconds=MARKET_PUBLICATION_LAG_OFFSET_SECONDS
    )

    bucket_start, bucket_end = latest_completed_bucket(capture_at, "5m")
    assert (bucket_start, bucket_end) == (
        datetime(2026, 9, 14, 11, 10, tzinfo=UTC),
        datetime(2026, 9, 14, 11, 15, tzinfo=UTC),
    )

    minute = bucket_start
    while minute < bucket_end:
        assert _bar_published_by(minute) <= capture_at, f"bar {minute:%H:%M} unpublished"
        minute += timedelta(minutes=1)


def test_offset_preserves_the_five_minute_cadence() -> None:
    """The offset shifts the due window; it must not change how often capture runs."""
    day = datetime(2026, 9, 14, 11, 0, tzinfo=UTC)
    baseline = _capture_times(day, offset_seconds=0)
    shifted = _capture_times(day, offset_seconds=MARKET_PUBLICATION_LAG_OFFSET_SECONDS)

    assert len(baseline) == 12
    assert len(shifted) == 12
    assert [t.minute for t in shifted] == [(t.minute + 2) % 60 for t in baseline]


def test_offset_requires_a_per_minute_cron() -> None:
    """A boundary-aligned Cron cannot serve the shifted window.

    This is why the fix is two coupled changes. With the previous schedule half the
    shifted due windows had no tick at all, which would have silently halved capture
    instead of repairing it.
    """
    boundary_aligned = set(range(0, 60, 2)) | {5, 15, 25, 35, 45, 55}
    per_minute = set(range(60))

    day = datetime(2026, 9, 14, 11, 0, tzinfo=UTC)
    shifted = {t.minute for t in _capture_times(day, offset_seconds=MARKET_PUBLICATION_LAG_OFFSET_SECONDS)}

    assert shifted - boundary_aligned, "the old Cron would have dropped due windows"
    assert not shifted - per_minute, "a per-minute Cron serves every due window"


def test_non_market_tasks_keep_boundary_alignment() -> None:
    """Only market capture is offset; macro, Fed and cross-market cadences are unchanged."""
    capture_at = datetime(2026, 9, 14, 11, 15, 3, tzinfo=UTC)
    assert interval_due(capture_at, POLL_SECONDS)
    assert not interval_due(
        capture_at, POLL_SECONDS, offset_seconds=MARKET_PUBLICATION_LAG_OFFSET_SECONDS
    )
