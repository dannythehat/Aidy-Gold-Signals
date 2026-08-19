from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from aidy.bigquery_exporter import (
    EXPORT_MANIFEST,
    MARKET_CANDLES,
    MARKET_EVENT_OBSERVATIONS,
    MARKET_SNAPSHOTS,
    ArchivedEvidence,
    analytical_row,
    load_identity,
    manifest_row,
    merge_sql,
)


def _snapshot() -> dict[str, object]:
    return {
        "schema_version": 2,
        "record_type": "snapshot",
        "evidence_id": "11111111-1111-4111-8111-111111111111",
        "archive_key": "gold/snapshots/2026/08/19/example.json",
        "payload_digest": "a" * 64,
        "payload": {
            "captured_at": "2026-08-19T09:54:18.171000+00:00",
            "symbol": "XAUUSD",
            "capture_status": "complete",
            "bid": None,
            "ask": None,
            "mid": "4360.600098",
            "spread": None,
            "quote_time": "2026-08-19T09:54:00+00:00",
            "quote_age_seconds": 18.171,
            "session_code": "london",
            "data_availability": {
                "market_data_source": "gold_api",
                "quote": "available",
            },
            "event_observation_ids": ["22222222-2222-4222-8222-222222222222"],
            "latest_m1_id": None,
            "latest_m5_id": None,
            "latest_m15_id": None,
            "latest_h1_id": None,
            "latest_h4_id": None,
            "latest_d1_id": None,
        },
    }


def _candle() -> dict[str, object]:
    return {
        "schema_version": 1,
        "record_type": "candle",
        "evidence_id": "33333333-3333-4333-8333-333333333333",
        "archive_key": "gold/candles/2026/08/17/XAUUSD/1m/example.json",
        "payload_digest": "b" * 64,
        "revision_index": 2,
        "payload": {
            "symbol": "XAUUSD",
            "timeframe": "1m",
            "open_time_utc": "2026-08-17T06:03:00+00:00",
            "broker_open_time": "2026-08-17T06:03:00+00:00",
            "open": "3330.1",
            "high": "3331.2",
            "low": "3329.8",
            "close": "3330.9",
            "tick_volume": "72",
            "spread": "18",
            "volume": "0",
            "source": "historical_day2_metaapi",
            "first_observed_at": "2026-08-17T06:04:43+00:00",
        },
    }


def _event() -> dict[str, object]:
    return {
        "schema_version": 1,
        "record_type": "event",
        "evidence_id": "44444444-4444-4444-8444-444444444444",
        "archive_key": "gold/events/2026/08/17/fed/example.json",
        "payload_digest": "c" * 64,
        "revision_index": 1,
        "payload": {
            "source": "federal_reserve_rss",
            "external_id": "fed-1",
            "event_type": "fed_release",
            "published_at": "2026-08-17T05:00:00Z",
            "first_observed_at": "2026-08-17T05:01:00+00:00",
            "headline": "Example release",
            "structured_data": {"category": "press_release"},
            "raw_payload": {"large": "r2-only"},
        },
    }


def test_table_contracts_preserve_required_partitioning_and_clustering() -> None:
    assert MARKET_CANDLES.partition_field == "open_time_utc"
    assert MARKET_CANDLES.clustering_fields == ("symbol", "timeframe", "source")
    assert MARKET_SNAPSHOTS.partition_field == "captured_at"
    assert MARKET_SNAPSHOTS.clustering_fields == ("symbol", "capture_status", "session_code")
    assert MARKET_EVENT_OBSERVATIONS.partition_field == "first_observed_at"
    assert MARKET_EVENT_OBSERVATIONS.clustering_fields == ("source", "event_type")
    assert EXPORT_MANIFEST.partition_field == "exported_at"


def test_load_identity_is_stable_and_uses_archive_key_plus_digest() -> None:
    first = load_identity("gold/snapshots/a.json", "abc")
    assert first == load_identity("gold/snapshots/a.json", "abc")
    assert first != load_identity("gold/snapshots/a.json", "def")
    assert first != load_identity("gold/snapshots/b.json", "abc")


def test_snapshot_export_preserves_exact_mid_and_excludes_broker_state() -> None:
    evidence = ArchivedEvidence.from_json(json.dumps(_snapshot()))
    row = analytical_row(evidence)

    assert row["mid"] == "4360.600098"
    assert row["bid"] is None
    assert row["ask"] is None
    assert row["market_data_source"] == "gold_api"
    assert row["event_observation_ids"] == ["22222222-2222-4222-8222-222222222222"]
    assert "position_state_json" not in row
    assert "positions" not in row
    assert row["archive_key"] == _snapshot()["archive_key"]
    assert row["payload_digest"] == "a" * 64


def test_candle_export_keeps_revision_and_point_in_time_observation() -> None:
    evidence = ArchivedEvidence.from_json(json.dumps(_candle()))
    row = analytical_row(evidence)

    assert row["revision_index"] == 2
    assert row["open"] == "3330.1"
    assert row["close"] == "3330.9"
    assert row["source"] == "historical_day2_metaapi"
    assert row["first_observed_at"] == "2026-08-17T06:04:43+00:00"


def test_event_export_keeps_structured_data_but_raw_payload_remains_r2_only() -> None:
    evidence = ArchivedEvidence.from_json(json.dumps(_event()))
    row = analytical_row(evidence)

    assert row["structured_data"] == {"category": "press_release"}
    assert "raw_payload" not in row
    assert row["archive_key"].startswith("gold/events/")


def test_manifest_carries_provenance_and_successful_load_identity() -> None:
    evidence = ArchivedEvidence.from_json(json.dumps(_snapshot()))
    row = manifest_row(
        evidence,
        exported_at=datetime(2026, 8, 19, 10, 0, tzinfo=UTC),
        run_id="run-1",
        load_job_id="load-1:merge-1",
    )

    assert row["load_identity"] == evidence.load_identity
    assert row["archive_key"] == evidence.archive_key
    assert row["payload_digest"] == evidence.payload_digest
    assert row["destination_table"] == "market_snapshots"
    assert row["run_id"] == "run-1"
    assert row["status"] == "success"


def test_merge_sql_is_insert_only_and_idempotent_by_load_identity() -> None:
    sql = merge_sql(
        project="aidy-test",
        dataset="aidy_analytics_test",
        destination=MARKET_SNAPSHOTS,
    )
    assert "MERGE `aidy-test.aidy_analytics_test.market_snapshots`" in sql
    assert "ON T.load_identity = S.load_identity" in sql
    assert "WHEN NOT MATCHED THEN" in sql
    assert "WHEN MATCHED" not in sql
    assert "WHERE _export_run_id = @run_id" in sql


def test_unsupported_or_wrong_schema_archive_fails_closed() -> None:
    wrong = _snapshot()
    wrong["schema_version"] = 1
    with pytest.raises(ValueError, match="expected 2"):
        ArchivedEvidence.from_json(json.dumps(wrong))

    unsupported = _snapshot()
    unsupported["record_type"] = "decision"
    with pytest.raises(ValueError, match="Unsupported analytical"):
        ArchivedEvidence.from_json(json.dumps(unsupported))


def test_archived_timestamps_must_be_timezone_aware() -> None:
    bad = _snapshot()
    payload = bad["payload"]
    assert isinstance(payload, dict)
    payload["captured_at"] = "2026-08-19T09:54:18"
    evidence = ArchivedEvidence.from_json(json.dumps(bad))
    with pytest.raises(ValueError, match="timezone-aware"):
        analytical_row(evidence)
