from __future__ import annotations

import json

from aidy.market_repository import _persisted_position_state_json


def test_known_empty_positions_remain_empty_list_json() -> None:
    snapshot = {
        "position_state_json": "[]",
        "data_availability_json": json.dumps({"positions": "available"}),
    }
    assert _persisted_position_state_json(snapshot) == "[]"


def test_known_populated_positions_remain_populated() -> None:
    positions = '[{"id":"123","symbol":"XAUUSD"}]'
    snapshot = {
        "position_state_json": positions,
        "data_availability_json": json.dumps({"positions": "available"}),
    }
    assert _persisted_position_state_json(snapshot) == positions


def test_failed_position_read_becomes_unknown() -> None:
    snapshot = {
        "position_state_json": "[]",
        "data_availability_json": json.dumps({"positions": "metaapi_timeout"}),
    }
    assert _persisted_position_state_json(snapshot) is None


def test_unattempted_position_read_becomes_unknown() -> None:
    snapshot = {
        "position_state_json": None,
        "data_availability_json": json.dumps({"quote": "available"}),
    }
    assert _persisted_position_state_json(snapshot) is None
