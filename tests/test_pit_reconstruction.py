from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aidy.pit_reconstruction import (
    KNOWN,
    QUERY_VERSION,
    UNKNOWN,
    query_contract,
    reconstruction_bundle,
    select_latest_candles_as_of,
    select_latest_events_as_of,
    select_latest_revisions_as_of,
    select_snapshot_as_of,
)

BASE = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)


def _candle(
    *,
    revision: int,
    observed_at: datetime,
    close: str,
    open_time: datetime | None = None,
    timeframe: str = "M1",
) -> dict[str, object]:
    logical_open = open_time or (BASE - timedelta(minutes=1))
    return {
        "load_identity": f"candle-load-{revision}-{logical_open.isoformat()}",
        "schema_version": 1,
        "record_type": "candle",
        "evidence_id": f"candle-evidence-{revision}",
        "archive_key": f"archive/candle/{revision}.json",
        "payload_digest": f"candle-digest-{revision}",
        "revision_index": revision,
        "source": "fixture_source",
        "symbol": "XAUUSD",
        "timeframe": timeframe,
        "open_time_utc": logical_open,
        "first_observed_at": observed_at,
        "open": "100",
        "high": "102",
        "low": "99",
        "close": close,
    }


def _event(*, revision: int, observed_at: datetime, headline: str) -> dict[str, object]:
    return {
        "load_identity": f"event-load-{revision}",
        "schema_version": 1,
        "record_type": "event",
        "evidence_id": f"event-evidence-{revision}",
        "archive_key": f"archive/event/{revision}.json",
        "payload_digest": f"event-digest-{revision}",
        "revision_index": revision,
        "source": "fixture_calendar",
        "external_id": "event-123",
        "event_type": "macro",
        "first_observed_at": observed_at,
        "headline": headline,
        "structured_data": {"value": revision},
    }


def _snapshot(*, captured_at: datetime, mid: str = "2000") -> dict[str, object]:
    return {
        "load_identity": f"snapshot-load-{captured_at.isoformat()}",
        "schema_version": 2,
        "record_type": "snapshot",
        "evidence_id": f"snapshot-{captured_at.isoformat()}",
        "archive_key": "archive/snapshot.json",
        "payload_digest": "snapshot-digest",
        "captured_at": captured_at,
        "symbol": "XAUUSD",
        "capture_status": "complete",
        "mid": mid,
        "session_code": "london",
        "data_availability": {"market_data_source": "fixture", "quote": "available"},
    }


def test_candle_revision_does_not_leak_before_first_observed_time() -> None:
    rows = [
        _candle(revision=1, observed_at=BASE, close="100"),
        _candle(revision=2, observed_at=BASE + timedelta(minutes=5), close="101"),
    ]
    before_revision = select_latest_revisions_as_of(
        rows,
        as_of=BASE + timedelta(minutes=4, seconds=59),
        key_fields=("source", "symbol", "timeframe", "open_time_utc"),
    )
    assert len(before_revision) == 1
    assert before_revision[0]["revision_index"] == 1
    assert before_revision[0]["close"] == "100"


def test_candle_revision_becomes_visible_at_its_first_observed_time() -> None:
    rows = [
        _candle(revision=1, observed_at=BASE, close="100"),
        _candle(revision=2, observed_at=BASE + timedelta(minutes=5), close="101"),
    ]
    after_revision = select_latest_revisions_as_of(
        rows,
        as_of=BASE + timedelta(minutes=5),
        key_fields=("source", "symbol", "timeframe", "open_time_utc"),
    )
    assert len(after_revision) == 1
    assert after_revision[0]["revision_index"] == 2
    assert after_revision[0]["close"] == "101"


def test_latest_candle_is_selected_only_from_candles_known_by_cutoff() -> None:
    rows = [
        _candle(
            revision=1,
            observed_at=BASE,
            close="100",
            open_time=BASE - timedelta(minutes=1),
        ),
        _candle(
            revision=1,
            observed_at=BASE + timedelta(minutes=2),
            close="102",
            open_time=BASE + timedelta(minutes=1),
        ),
    ]
    selected = select_latest_candles_as_of(rows, as_of=BASE, symbol="XAUUSD")
    assert len(selected) == 1
    assert selected[0]["close"] == "100"


def test_event_revision_does_not_leak_backwards() -> None:
    rows = [
        _event(revision=1, observed_at=BASE, headline="initial"),
        _event(revision=2, observed_at=BASE + timedelta(minutes=10), headline="revised"),
    ]
    before = select_latest_events_as_of(rows, as_of=BASE + timedelta(minutes=9))
    after = select_latest_events_as_of(rows, as_of=BASE + timedelta(minutes=10))
    assert before[0]["headline"] == "initial"
    assert before[0]["revision_index"] == 1
    assert after[0]["headline"] == "revised"
    assert after[0]["revision_index"] == 2


def test_unknown_event_remains_unknown_before_first_observation() -> None:
    rows = [_event(revision=1, observed_at=BASE, headline="later-known")]
    selected = select_latest_events_as_of(rows, as_of=BASE - timedelta(microseconds=1))
    assert selected == []


def test_unknown_snapshot_remains_unknown_before_first_capture() -> None:
    selected = select_snapshot_as_of(
        [_snapshot(captured_at=BASE)],
        as_of=BASE - timedelta(microseconds=1),
        symbol="XAUUSD",
    )
    assert selected is None


def test_latest_snapshot_at_or_before_cutoff_is_selected() -> None:
    rows = [
        _snapshot(captured_at=BASE, mid="2000"),
        _snapshot(captured_at=BASE + timedelta(minutes=1), mid="2001"),
    ]
    selected = select_snapshot_as_of(
        rows,
        as_of=BASE + timedelta(seconds=30),
        symbol="XAUUSD",
    )
    assert selected is not None
    assert selected["mid"] == "2000"


def test_bundle_preserves_unknown_snapshot_and_availability() -> None:
    bundle = reconstruction_bundle(
        as_of=BASE - timedelta(microseconds=1),
        symbol="XAUUSD",
        candle_rows=[],
        event_rows=[],
        snapshot_rows=[_snapshot(captured_at=BASE)],
    )
    assert bundle["snapshot"]["state"] == UNKNOWN
    assert bundle["snapshot"]["fact"] is None
    assert bundle["availability"] == {"state": UNKNOWN, "data": None}
    assert bundle["candles"] == []
    assert bundle["events"] == []


def test_bundle_carries_query_version_and_immutable_provenance() -> None:
    snapshot = _snapshot(captured_at=BASE)
    bundle = reconstruction_bundle(
        as_of=BASE,
        symbol="XAUUSD",
        candle_rows=[_candle(revision=1, observed_at=BASE, close="100")],
        event_rows=[_event(revision=1, observed_at=BASE, headline="known")],
        snapshot_rows=[snapshot],
        query_ids={"candles": "c", "events": "e", "snapshot": "s"},
    )
    assert bundle["query_version"] == QUERY_VERSION
    assert bundle["snapshot"]["state"] == KNOWN
    assert bundle["snapshot"]["provenance"]["load_identity"] == snapshot["load_identity"]
    assert bundle["snapshot"]["provenance"]["archive_key"] == snapshot["archive_key"]
    assert bundle["query_ids"] == {"candles": "c", "events": "e", "snapshot": "s"}
    assert bundle["retrospective_history_included"] is False


def test_query_contract_filters_cutoff_before_revision_ranking() -> None:
    queries = query_contract(project="aidy-signals", dataset="aidy_analytics_test")
    candle_sql = queries["candles"].sql
    event_sql = queries["events"].sql
    assert "first_observed_at <= @as_of" in candle_sql
    assert "first_observed_at <= @as_of" in event_sql
    assert "revision_rank = 1" in candle_sql
    assert "revision_rank = 1" in event_sql


def test_snapshot_query_filters_capture_time_before_ordering() -> None:
    sql = query_contract(project="aidy-signals", dataset="aidy_analytics_test")["snapshot"].sql
    assert "captured_at <= @as_of" in sql
    assert "ORDER BY captured_at DESC" in sql
    assert "LIMIT 1" in sql


def test_pit_queries_structurally_exclude_retrospective_research_table() -> None:
    queries = query_contract(project="aidy-signals", dataset="aidy_analytics_test")
    joined = "\n".join(query.sql.lower() for query in queries.values())
    assert "research_candles" not in joined
    assert "retrospective_history" not in joined
    assert "market_candles" in joined
    assert "market_snapshots" in joined
    assert "market_event_observations" in joined


def test_day6_runtime_module_does_not_import_google_client() -> None:
    source = Path("src/aidy/pit_reconstruction.py").read_text(encoding="utf-8").lower()
    assert "google.cloud" not in source
    assert "google.oauth2" not in source


def test_as_of_requires_timezone_awareness() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        select_latest_events_as_of([], as_of=datetime(2026, 8, 19, 10, 0))


def test_equal_observation_time_uses_revision_index_deterministically() -> None:
    rows = [
        _event(revision=1, observed_at=BASE, headline="first"),
        _event(revision=2, observed_at=BASE, headline="second"),
    ]
    selected = select_latest_events_as_of(rows, as_of=BASE)
    assert selected[0]["revision_index"] == 2
    assert selected[0]["headline"] == "second"
