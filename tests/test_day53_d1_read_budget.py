from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from aidy.private_forward_context import _decision_candles

ROOT = Path(__file__).resolve().parents[1]


class _Rows:
    def __init__(self) -> None:
        self.results: list[dict[str, object]] = []


class _Statement:
    def __init__(self, owner: _D1, sql: str) -> None:
        self.owner = owner
        self.sql = sql
        self.binds: tuple[object, ...] = ()

    def bind(self, *values: object) -> _Statement:
        self.binds = values
        return self

    async def all(self) -> _Rows:
        self.owner.calls.append((self.sql, self.binds))
        return _Rows()


class _D1:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def prepare(self, sql: str) -> _Statement:
        return _Statement(self, sql)


@pytest.mark.asyncio
async def test_private_forward_candle_reads_are_bounded_and_timeframe_specific() -> None:
    d1 = _D1()
    as_of = datetime(2026, 9, 3, 9, 0, tzinfo=UTC)

    assert await _decision_candles(d1, as_of=as_of) == []
    assert len(d1.calls) == 6

    m1_sql, m1_binds = d1.calls[0]
    assert "twelve_data_decision_admitted_m1_v1" in m1_sql
    assert m1_binds[0] == "2026-09-01T09:00:00+00:00"

    aggregate_calls = d1.calls[1:]
    assert [call[1][2] for call in aggregate_calls] == ["5m", "15m", "1h", "4h", "1d"]
    assert "latest_m5_id=c.id" in aggregate_calls[0][0]
    assert aggregate_calls[0][1][-1] == 256
    for sql, _ in aggregate_calls[1:]:
        assert "c.open_time_utc>=?" in sql
        assert "json_extract(s.data_availability_json,'$.request_kind')='scheduled_capture'" in sql
        assert "json_extract(s.data_availability_json,'$.request_ledger_status')='succeeded'" in sql
    assert "c.id IN (" not in "\n".join(sql for sql, _ in aggregate_calls)


def test_recorder_reuses_one_admitted_m1_history_read_for_all_aggregates() -> None:
    text = (ROOT / "src" / "aidy" / "twelve_data_recorder.py").read_text(encoding="utf-8")
    assert text.count("self._market_store.latest_m1_bars(") == 1
    assert "one_bounded_read_reused_across_aggregate_timeframes" in text


def test_storage_uses_single_pass_revision_ranking() -> None:
    text = (ROOT / "src" / "aidy" / "twelve_data_storage.py").read_text(encoding="utf-8")
    assert "ROW_NUMBER() OVER" in text
    assert "WHERE revision_rank=1" in text
    assert "SELECT 1 FROM admitted newer" not in text


def test_read_budget_migration_indexes_every_hot_admission_lookup() -> None:
    text = (ROOT / "migrations" / "d1" / "0011_d1_read_budget_indexes.sql").read_text(
        encoding="utf-8"
    )
    for required in (
        "idx_twelve_data_request_ledger_admission",
        "idx_twelve_data_bootstrap_requests_admission_window",
        "idx_market_snapshots_latest_m5_admission",
        "idx_market_snapshots_latest_m15_admission",
        "idx_market_snapshots_latest_h1_admission",
        "idx_market_snapshots_latest_h4_admission",
        "idx_market_snapshots_latest_d1_admission",
        "ix_aidy_forward_evaluations_proof_poll",
    ):
        assert required in text
