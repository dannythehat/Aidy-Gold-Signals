from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

import aidy.provider_context_api as api

ROOT = Path(__file__).resolve().parents[1]


class _Statement:
    def __init__(self, row: dict[str, object] | None) -> None:
        self.row = row
        self.sql = ""
        self.binds: tuple[object, ...] = ()

    def bind(self, *values: object) -> "_Statement":
        self.binds = values
        return self

    async def first(self):
        return self.row


class _D1:
    def __init__(self, row: dict[str, object] | None) -> None:
        self.row = row
        self.statement: _Statement | None = None

    def prepare(self, sql: str) -> _Statement:
        self.statement = _Statement(self.row)
        self.statement.sql = sql
        return self.statement


def _snapshot() -> dict[str, object]:
    return {
        "id": "snapshot-1",
        "captured_at": "2026-09-04T12:00:00+00:00",
        "symbol": "XAUUSD",
        "capture_status": "complete",
        "market_data_source": "twelve_data",
        "session_code": "new_york",
        "snapshot_digest": "a" * 64,
        "archive_key": "gold/snapshots/2026/09/04/snapshot-1.json",
        "data_availability_json": "{}",
    }


@pytest.mark.asyncio
async def test_snapshot_selection_is_strictly_pit_and_scheduled_capture_only() -> None:
    d1 = _D1(_snapshot())
    as_of = datetime(2026, 9, 4, 12, 4, tzinfo=UTC)
    row = await api._snapshot_at_or_before(d1, as_of=as_of)
    assert row == _snapshot()
    assert d1.statement is not None
    assert "captured_at<=?" in d1.statement.sql
    assert "market_data_source='twelve_data'" in d1.statement.sql
    assert "capture_status='complete'" in d1.statement.sql
    assert "request_kind')='scheduled_capture'" in d1.statement.sql
    assert "request_ledger_status')='succeeded'" in d1.statement.sql
    assert "ORDER BY captured_at DESC,id DESC" in d1.statement.sql
    assert d1.statement.binds[-1] == as_of.isoformat()


def test_compact_packet_preserves_canonical_context_and_provenance() -> None:
    snapshot = _snapshot()
    inputs = {
        "adapter_version": "aidy_private_forward_context_adapter_v1",
        "as_of_utc": snapshot["captured_at"],
        "regime": {"compound_regime_key": "trend|normal"},
        "context": {
            "context_hash": "context-hash",
            "session": {"computed_session_code": "new_york"},
            "data_quality": {"state": "good"},
            "gold": {"quote_context": {"mid": "3500.0"}},
            "source_contract_versions": {"semantic_context": "v1"},
            "architecture_v2_extensions": {
                "extension_digest": "extension-digest",
                "price_structure_context": {"structure_semantic_digest": "structure-digest"},
            },
        },
    }
    packet = api._compact_join_packet(inputs, snapshot=snapshot)
    assert packet["context_as_of_utc"] == "2026-09-04T12:00:00+00:00"
    assert packet["context_hash"] == "context-hash"
    assert packet["regime"]["compound_regime_key"] == "trend|normal"
    assert packet["session"]["computed_session_code"] == "new_york"
    assert packet["snapshot"]["id"] == "snapshot-1"
    assert packet["provenance"]["private_forward_only"] is True
    assert packet["provenance"]["live_money_execution_allowed"] is False


def test_compact_packet_rejects_context_from_different_timestamp() -> None:
    snapshot = _snapshot()
    with pytest.raises(RuntimeError, match="canonical_context_snapshot_timestamp_mismatch"):
        api._compact_join_packet(
            {
                "adapter_version": "v1",
                "as_of_utc": "2026-09-04T12:01:00+00:00",
                "regime": {},
                "context": {},
            },
            snapshot=snapshot,
        )


@pytest.mark.asyncio
async def test_context_cache_is_keyed_by_immutable_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    api._CONTEXT_CACHE.clear()
    calls = 0

    async def fake_builder(*, d1, snapshot_id):
        nonlocal calls
        del d1
        calls += 1
        assert snapshot_id == "snapshot-1"
        return {
            "adapter_version": "adapter-v1",
            "as_of_utc": "2026-09-04T12:00:00+00:00",
            "regime": {"compound_regime_key": "range"},
            "context": {"context_hash": "hash", "session": {}, "data_quality": {}, "gold": {}},
        }

    monkeypatch.setattr(api, "build_private_forward_decision_inputs", fake_builder)
    snapshot = _snapshot()
    first = await api._context_for_snapshot(object(), snapshot=snapshot)
    second = await api._context_for_snapshot(object(), snapshot=snapshot)
    assert calls == 1
    assert first == second


def test_day9_endpoint_contract_is_read_only_bounded_and_does_not_grant_authority() -> None:
    source = (ROOT / "src" / "aidy" / "provider_context_api.py").read_text(encoding="utf-8")
    wrapper = (ROOT / "src" / "provider_entry.py").read_text(encoding="utf-8")
    assert "captured_at<=?" in source
    assert "MAX_CONTEXT_LAG = timedelta(minutes=10)" in source
    assert "build_private_forward_decision_inputs" in source
    assert '"private_forward_only": True' in source
    assert '"live_money_execution_allowed": False' in source
    assert "INSERT INTO" not in source
    assert "UPDATE " not in source
    assert "DELETE FROM" not in source
    assert 'path == "/provider/context"' in wrapper
