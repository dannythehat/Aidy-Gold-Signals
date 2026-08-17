from __future__ import annotations

from aidy.market_repository import _persisted_position_state_json


def test_legacy_repository_discards_known_empty_positions() -> None:
    snapshot = {
        "position_state_json": "[]",
        "data_availability_json": '{"positions":"available"}',
    }
    assert _persisted_position_state_json(snapshot) is None


def test_legacy_repository_discards_populated_positions() -> None:
    positions = '[{"id":"123","symbol":"XAUUSD"}]'
    snapshot = {
        "position_state_json": positions,
        "data_availability_json": '{"positions":"available"}',
    }
    assert _persisted_position_state_json(snapshot) is None


def test_failed_position_read_becomes_unknown() -> None:
    snapshot = {
        "position_state_json": "[]",
        "data_availability_json": '{"positions":"metaapi_timeout"}',
    }
    assert _persisted_position_state_json(snapshot) is None


def test_unattempted_position_read_becomes_unknown() -> None:
    snapshot = {
        "position_state_json": None,
        "data_availability_json": '{"quote":"available"}',
    }
    assert _persisted_position_state_json(snapshot) is None
