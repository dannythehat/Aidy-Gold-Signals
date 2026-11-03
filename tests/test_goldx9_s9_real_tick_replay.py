"""Mechanics-only synthetic tests. Never historical performance evidence."""
import csv
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.strategy_lab.goldx9_s9_real_tick_replay import S9Replay, ordered_quotes


def t(hour=12, minute=15, second=0):
    return int(datetime(2022, 1, 3, hour, minute, second, tzinfo=UTC).timestamp())


def test_confirmed_fractal_requires_five_closed_newer_h1_bars():
    s = S9Replay()
    s.bars = [(i * 3600, 99.0, 90.0) for i in range(5)]
    s.bars += [(5*3600, 110.0, 80.0)]
    s.bars += [(i * 3600, 100.0, 85.0) for i in range(6, 10)]
    s.last_hour, s.current_high, s.current_low = 10*3600, 100, 85
    s._finish_hour()
    assert s.swing_high == (110, 5*3600)
    assert s.swing_low == (80, 5*3600)


def test_pending_fill_exit_accounting_and_spread():
    s = S9Replay(commission_per_lot_roundtrip=7.0)
    s.on_tick(t(), 1800.0, 1800.2)
    s.swing_high = (1810.0, t(6))
    s.on_tick(t(12, 30), 1801.0, 1801.2)
    assert 1 in s.pending
    assert s.pending[1].level > 1801.2
    s.on_tick(t(12, 30, 1), 1808.5, 1808.7)
    assert len(s.positions) == 1
    price = s.positions[0].entry
    s.on_tick(t(12, 30, 2), price + 13.0, price + 13.2)
    assert len(s.positions) == 0
    assert s.report([])["closed_trades"] == 1
    assert s.trades[0]["net_usd"] > 0
    assert s.report([])["account_reconciles"]
    assert s.trades[0]["commission_usd"] == 0.07


def test_broker_stop_on_each_tick_not_only_minute():
    s = S9Replay()
    s.on_tick(t(), 1800.0, 1800.2)
    s.swing_low = (1790.0, t(5))
    s.on_tick(t(12, 30), 1800.0, 1800.2)
    assert -1 in s.pending
    s.on_tick(t(12, 30, 1), 1787.9, 1788.1)
    assert len(s.positions) == 1
    p = s.positions[0]
    s.on_tick(t(12, 30, 2), p.stop+0.1, p.stop+0.2)
    assert s.trades[-1]["exit_reason"] == "stop_or_breakeven"
    assert s.trades[-1]["net_usd"] < 0


def test_actual_source_csv_timestamp_sorting_preserves_ticks(tmp_path: Path):
    archive = tmp_path / "HISTDATA_COM_ASCII_XAUUSD_T_202201.zip"
    rows = [
        ["20220103 070001000", "1801.1", "1801.3", "0"],
        ["20220103 070000000", "1800.0", "1800.2", "0"],
        ["20220103 070002000", "1802.0", "1802.2", "0"],
    ]
    with zipfile.ZipFile(archive, "w") as z:
        from io import StringIO
        buf = StringIO()
        csv.writer(buf).writerows(rows)
        z.writestr("XAUUSD_tick.csv", buf.getvalue())
    audit = {}
    ticks = list(ordered_quotes(archive, "202201", audit, chunk_size=2))
    assert [x[2] for x in ticks] == [1800.0, 1801.1, 1802.0]
    assert audit["source_order_inversions"] == 1
    assert audit["original_ticks"] == 3
    assert len(audit["source_zip_sha256"]) == 64


def test_no_pending_created_when_spread_exceeds_points():
    s = S9Replay(point=0.01, max_spread_points=50)
    s.on_tick(t(), 1800, 1800.2)
    s.swing_high = (1810, t(6))
    s.on_tick(t(12, 30), 1801, 1802)
    assert not s.pending
    assert s.blocked_spread >= 1
