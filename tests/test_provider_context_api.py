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


def _snapshot(*, status: str = "complete", d1: bool = True) -> dict[str, object]:
    return {
        "id": "snapshot-1",
        "captured_at": "2026-09-04T12:00:00+00:00",
        "symbol": "XAUUSD",
        "capture_status": status,
        "market_data_source": "twelve_data",
        "session_code": "new_york",
        "snapshot_digest": "a" * 64,
        "archive_key": "gold/snapshots/2026/09/04/snapshot-1.json",
        "data_availability_json": '{"freshness_state":"fresh"}',
        "latest_m1_id": "m1",
        "latest_m5_id": "m5",
        "latest_m15_id": "m15",
        "latest_h1_id": "h1",
        "latest_h4_id": "h4",
        "latest_d1_id": "d1" if d1 else None,
    }


@pytest.mark.asyncio
async def test_snapshot_selection_is_strictly_pit_scheduled_and_fresh() -> None:
    d1 = _D1(_snapshot())
    as_of = datetime(2026, 9, 4, 12, 4, tzinfo=UTC)
    row = await api._snapshot_at_or_before(d1, as_of=as_of)
    assert row == _snapshot()
    assert d1.statement is not None
    assert "captured_at<=?" in d1.statement.sql
    assert "market_data_source='twelve_data'" in d1.statement.sql
    assert "capture_status IN ('complete','partial')" in d1.statement.sql
    assert "request_kind')='scheduled_capture'" in d1.statement.sql
    assert "request_ledger_status')='succeeded'" in d1.statement.sql
    assert "freshness_state')='fresh'" in d1.statement.sql
    for field in ("latest_m1_id", "latest_m5_id", "latest_m15_id", "latest_h1_id", "latest_h4_id"):
        assert f"{field} IS NOT NULL" in d1.statement.sql
    assert "ORDER BY captured_at DESC,id DESC" in d1.statement.sql
    assert d1.statement.binds[-1] == as_of.isoformat()


@pytest.mark.asyncio
async def test_fresh_partial_snapshot_is_provider_eligible_only_when_d1_is_missing() -> None:
    snapshot = _snapshot(status="partial", d1=False)
    d1 = _D1(snapshot)
    as_of = datetime(2026, 9, 4, 12, 4, tzinfo=UTC)
    row = await api._snapshot_at_or_before(d1, as_of=as_of)
    assert row == snapshot
    grade, missing = api._provider_context_evidence(snapshot)
    assert grade == "intraday_complete_d1_missing"
    assert missing == ["1d"]


def test_partial_snapshot_missing_intraday_timeframe_is_rejected() -> None:
    snapshot = _snapshot(status="partial", d1=False)
    snapshot["latest_h4_id"] = None
    with pytest.raises(ValueError, match="provider_context_intraday_stack_incomplete"):
        api._provider_context_evidence(snapshot)


def test_complete_snapshot_must_really_contain_all_timeframes() -> None:
    snapshot = _snapshot(status="complete", d1=False)
    with pytest.raises(ValueError, match="provider_context_complete_snapshot_missing_timeframe"):
        api._provider_context_evidence(snapshot)


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
    assert packet["snapshot"]["provider_context_evidence_grade"] == "complete"
    assert packet["snapshot"]["provider_context_missing_timeframes"] == []
    assert packet["provenance"]["private_forward_only"] is True
    assert packet["provenance"]["provider_context_observational_only"] is True
    assert packet["provenance"]["formal_forward_complete_snapshot_required"] is True
    assert packet["provenance"]["live_money_execution_allowed"] is False


def test_partial_d1_packet_is_explicitly_degraded_and_non_executable() -> None:
    snapshot = _snapshot(status="partial", d1=False)
    inputs = {
        "adapter_version": "adapter-v1",
        "as_of_utc": snapshot["captured_at"],
        "regime": {"compound_regime_key": "mixed"},
        "context": {"context_hash": "hash", "session": {}, "data_quality": {}, "gold": {}},
    }
    packet = api._compact_join_packet(inputs, snapshot=snapshot)
    assert packet["snapshot"]["capture_status"] == "partial"
    assert packet["snapshot"]["provider_context_evidence_grade"] == "intraday_complete_d1_missing"
    assert packet["snapshot"]["provider_context_missing_timeframes"] == ["1d"]
    assert packet["provenance"]["provider_context_observational_only"] is True
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


def test_provider_endpoint_remains_read_only_bounded_and_non_authoritative() -> None:
    source = (ROOT / "src" / "aidy" / "provider_context_api.py").read_text(encoding="utf-8")
    wrapper = (ROOT / "src" / "provider_entry.py").read_text(encoding="utf-8")
    formal = (ROOT / "src" / "aidy" / "forward_live_observer.py").read_text(encoding="utf-8")
    assert "captured_at<=?" in source
    assert "MAX_CONTEXT_LAG = timedelta(minutes=10)" in source
    assert "build_private_forward_decision_inputs" in source
    assert '"provider_context_observational_only": True' in source
    assert '"formal_forward_complete_snapshot_required": True' in source
    assert '"live_money_execution_allowed": False' in source
    assert "INSERT INTO" not in source
    assert "UPDATE " not in source
    assert "DELETE FROM" not in source
    assert 'path == "/provider/context"' in wrapper
    assert 'if status != "complete":' in formal
    assert 'return "market_reference_not_complete"' in formal
