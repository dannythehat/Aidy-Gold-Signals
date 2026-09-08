from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from aidy.twelve_data_market import TwelveDataFetch, TwelveDataM1Bar, latest_completed_bucket
from aidy.twelve_data_recorder import aggregate_evidence_as_of


def _fetch(*, fetched_at: datetime, latest_open: datetime) -> TwelveDataFetch:
    bar = TwelveDataM1Bar(
        open_time_utc=latest_open,
        open=Decimal("4500"),
        high=Decimal("4501"),
        low=Decimal("4499"),
        close=Decimal("4500.5"),
    )
    return TwelveDataFetch(
        fetched_at_utc=fetched_at,
        meta={"symbol": "XAU/USD", "interval": "1min"},
        credit_headers={},
        response_digest="a" * 64,
        closed_bars=(bar,),
        raw_bar_count=1,
        forming_bar_count=0,
        off_session_bar_count=0,
        latest_closed_bar_open_utc=bar.open_time_utc,
        latest_closed_bar_close_utc=bar.close_time_utc,
        open_session_lag_seconds=(fetched_at - bar.close_time_utc).total_seconds(),
        session_open_at_fetch=True,
    )


def test_delayed_fresh_vendor_bar_does_not_select_unobservable_current_5m_bucket() -> None:
    fetched_at = datetime(2026, 9, 8, 12, 50, 24, 332000, tzinfo=UTC)
    fetch = _fetch(
        fetched_at=fetched_at,
        latest_open=datetime(2026, 9, 8, 12, 48, tzinfo=UTC),
    )

    wall_clock_window = latest_completed_bucket(fetched_at, "5m")
    observed_window = latest_completed_bucket(aggregate_evidence_as_of(fetch), "5m")

    assert wall_clock_window == (
        datetime(2026, 9, 8, 12, 45, tzinfo=UTC),
        datetime(2026, 9, 8, 12, 50, tzinfo=UTC),
    )
    assert observed_window == (
        datetime(2026, 9, 8, 12, 40, tzinfo=UTC),
        datetime(2026, 9, 8, 12, 45, tzinfo=UTC),
    )
    assert observed_window[1] <= fetch.latest_closed_bar_close_utc


def test_exact_boundary_bar_makes_just_completed_bucket_eligible_without_future_data() -> None:
    fetched_at = datetime(2026, 9, 8, 12, 50, 40, tzinfo=UTC)
    fetch = _fetch(
        fetched_at=fetched_at,
        latest_open=datetime(2026, 9, 8, 12, 49, tzinfo=UTC),
    )

    aggregate_as_of = aggregate_evidence_as_of(fetch)
    window = latest_completed_bucket(aggregate_as_of, "5m")

    assert aggregate_as_of > fetch.latest_closed_bar_close_utc
    assert aggregate_as_of < fetched_at
    assert window == (
        datetime(2026, 9, 8, 12, 45, tzinfo=UTC),
        datetime(2026, 9, 8, 12, 50, tzinfo=UTC),
    )
    assert window[1] == fetch.latest_closed_bar_close_utc


def test_no_closed_vendor_bar_falls_back_to_fetch_time_but_cannot_create_m1_identity() -> None:
    fetched_at = datetime(2026, 9, 8, 12, 50, 40, tzinfo=UTC)
    fetch = TwelveDataFetch(
        fetched_at_utc=fetched_at,
        meta={"symbol": "XAU/USD", "interval": "1min"},
        credit_headers={},
        response_digest="b" * 64,
        closed_bars=(),
        raw_bar_count=0,
        forming_bar_count=0,
        off_session_bar_count=0,
        latest_closed_bar_open_utc=None,
        latest_closed_bar_close_utc=None,
        open_session_lag_seconds=None,
        session_open_at_fetch=True,
    )

    assert aggregate_evidence_as_of(fetch) == fetched_at
