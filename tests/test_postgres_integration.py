from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from aidy.market_repository import AidyMarketRepository

_TARGET_TABLES = {
    "market_candles",
    "market_snapshots",
    "market_event_observations",
}


def _scratch_database_url() -> str:
    raw = os.getenv("AIDY_TEST_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("AIDY_TEST_DATABASE_URL is not configured")
    parsed = make_url(raw)
    database = (parsed.database or "").lower()
    if not (database.endswith("_scratch") or database.endswith("_test")):
        pytest.fail(
            "Refusing destructive migration test: AIDY_TEST_DATABASE_URL database name "
            "must end with _scratch or _test"
        )
    return raw


def _alembic_config(database_url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def scratch_engine():
    database_url = _scratch_database_url()
    old_database_url = os.environ.get("AIDY_DATABASE_URL")
    os.environ["AIDY_DATABASE_URL"] = database_url
    config = _alembic_config(database_url)

    command.downgrade(config, "base")
    empty_engine = create_engine(database_url, pool_pre_ping=True)
    try:
        assert _TARGET_TABLES.isdisjoint(inspect(empty_engine).get_table_names())
    finally:
        empty_engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(database_url, pool_pre_ping=True)
    assert _TARGET_TABLES.issubset(set(inspect(engine).get_table_names()))

    try:
        yield engine
    finally:
        engine.dispose()
        command.downgrade(config, "base")
        verify_engine = create_engine(database_url, pool_pre_ping=True)
        try:
            assert _TARGET_TABLES.isdisjoint(inspect(verify_engine).get_table_names())
        finally:
            verify_engine.dispose()
        if old_database_url is None:
            os.environ.pop("AIDY_DATABASE_URL", None)
        else:
            os.environ["AIDY_DATABASE_URL"] = old_database_url


def _snapshot(*, captured_at: datetime, availability: dict[str, object], positions: object) -> dict[str, object]:
    return {
        "captured_at": captured_at,
        "symbol": "XAUUSD",
        "capture_status": "partial",
        "bid": None,
        "ask": None,
        "mid": None,
        "spread": None,
        "quote_time": None,
        "quote_age_seconds": None,
        "session_code": "off_hours",
        "position_state_json": json.dumps(positions) if positions is not None else None,
        "data_availability_json": json.dumps(availability),
        "event_observation_ids_json": "[]",
        "latest_m1_id": None,
        "latest_m5_id": None,
        "latest_m15_id": None,
        "latest_h1_id": None,
        "latest_h4_id": None,
        "latest_d1_id": None,
        "snapshot_digest": "0" * 64,
    }


def test_schema_preserves_unknown_position_truth(scratch_engine) -> None:
    columns = {column["name"]: column for column in inspect(scratch_engine).get_columns("market_snapshots")}
    assert columns["position_state_json"]["nullable"] is True
    assert columns["spread"]["nullable"] is True

    candle_columns = {
        column["name"]: column
        for column in inspect(scratch_engine).get_columns("market_candles")
    }
    assert candle_columns["spread"]["nullable"] is True


def test_legacy_repository_discards_all_broker_position_states(scratch_engine) -> None:
    factory = sessionmaker(bind=scratch_engine, expire_on_commit=False)
    repository = AidyMarketRepository(factory)
    base = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)

    ids = [
        repository.store_snapshot(
            _snapshot(
                captured_at=base,
                availability={"positions": "available"},
                positions=[],
            )
        ),
        repository.store_snapshot(
            _snapshot(
                captured_at=base + timedelta(seconds=1),
                availability={"positions": "available"},
                positions=[{"id": "123", "symbol": "XAUUSD"}],
            )
        ),
        repository.store_snapshot(
            _snapshot(
                captured_at=base + timedelta(seconds=2),
                availability={"positions": "metaapi_timeout"},
                positions=[],
            )
        ),
        repository.store_snapshot(
            _snapshot(
                captured_at=base + timedelta(seconds=3),
                availability={"quote": "available"},
                positions=None,
            )
        ),
    ]

    with scratch_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, position_state_json FROM market_snapshots "
                "WHERE id = ANY(:ids) ORDER BY captured_at"
            ),
            {"ids": ids},
        ).mappings().all()

    assert all(row["position_state_json"] is None for row in rows)


def test_candle_revisions_are_idempotent_and_append_only(scratch_engine) -> None:
    factory = sessionmaker(bind=scratch_engine, expire_on_commit=False)
    repository = AidyMarketRepository(factory)
    opened = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
    observed = opened + timedelta(minutes=5)
    candle = {
        "symbol": "XAUUSD",
        "timeframe": "5m",
        "open_time_utc": opened,
        "broker_open_time": None,
        "open": "4350",
        "high": "4355",
        "low": "4348",
        "close": "4353",
        "tick_volume": 100,
        "spread": "0.20",
        "volume": None,
        "source": "metaapi",
        "payload_digest": "1" * 64,
        "first_observed_at": observed,
    }

    first_id, first_revision, first_created = repository.store_candle(candle)
    same_id, same_revision, same_created = repository.store_candle(candle)
    second_id, second_revision, second_created = repository.store_candle(
        {**candle, "close": "4354", "payload_digest": "2" * 64}
    )

    assert first_created is True
    assert first_revision == 1
    assert same_created is False
    assert same_id == first_id
    assert same_revision == 1
    assert second_created is True
    assert second_id != first_id
    assert second_revision == 2


def test_event_revisions_respect_point_in_time_truth(scratch_engine) -> None:
    factory = sessionmaker(bind=scratch_engine, expire_on_commit=False)
    repository = AidyMarketRepository(factory)
    first_seen = datetime(2026, 8, 16, 7, 0, tzinfo=UTC)
    revised_seen = first_seen + timedelta(minutes=10)

    first_id, first_revision, first_created = repository.store_event_observation(
        source="federal_reserve_rss",
        external_id="fed_speeches:test-event",
        event_type="fed_speeches",
        published_at=first_seen,
        first_observed_at=first_seen,
        headline="Initial headline",
        structured_data_json="{}",
        raw_payload_json='{"version":1}',
        payload_digest="a" * 64,
    )
    same_id, same_revision, same_created = repository.store_event_observation(
        source="federal_reserve_rss",
        external_id="fed_speeches:test-event",
        event_type="fed_speeches",
        published_at=first_seen,
        first_observed_at=first_seen + timedelta(minutes=1),
        headline="Initial headline",
        structured_data_json="{}",
        raw_payload_json='{"version":1}',
        payload_digest="a" * 64,
    )
    second_id, second_revision, second_created = repository.store_event_observation(
        source="federal_reserve_rss",
        external_id="fed_speeches:test-event",
        event_type="fed_speeches",
        published_at=first_seen,
        first_observed_at=revised_seen,
        headline="Revised headline",
        structured_data_json="{}",
        raw_payload_json='{"version":2}',
        payload_digest="b" * 64,
    )

    assert first_created is True
    assert first_revision == 1
    assert same_created is False
    assert same_id == first_id
    assert same_revision == 1
    assert second_created is True
    assert second_revision == 2

    before_revision = repository.event_observation_ids_known_at(
        captured_at=first_seen + timedelta(minutes=5)
    )
    after_revision = repository.event_observation_ids_known_at(
        captured_at=revised_seen + timedelta(minutes=1)
    )

    assert first_id in before_revision
    assert second_id not in before_revision
    assert second_id in after_revision
    assert first_id not in after_revision
