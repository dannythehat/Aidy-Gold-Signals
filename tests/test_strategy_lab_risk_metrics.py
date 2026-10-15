"""Day24 adversarial verification of real SQLite journal-based risk measurements."""
from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest

from aidy.strategy_lab_cash_ledger import CashJournal
from aidy.strategy_lab_deterministic_replay import canonical_events, replay_cash_events
from aidy.strategy_lab_risk_metrics import (
    compute_ledger_metrics,
    qualified_daily_sharpe,
)

SOURCE_SHA = "a" * 64
FIXTURE = (Path(__file__).resolve().parents[1] /
           "research/strategy_lab/fixtures/day24_known_answer_journal.json")


def sample(tmp_path):
    fixture = json.loads(FIXTURE.read_bytes())
    events = fixture["events"]
    manifest = sha256(canonical_events(events, SOURCE_SHA)).hexdigest()
    path = tmp_path / "day24.sqlite3"
    replay = replay_cash_events(path, events, source_sha256=SOURCE_SHA,
                                ounces_per_lot=Decimal(1),
                                expected_manifest_sha256=manifest)
    return path, replay.journal_tip_sha256, events


def run(path, tip, ounces=Decimal(1), source=SOURCE_SHA):
    return compute_ledger_metrics(path, source_sha256=source,
                                  ounces_per_lot=ounces,
                                  expected_tip_sha256=tip)


def test_exact_four_trade_net_expectancy_pf_monthly_and_equity(tmp_path):
    path, tip, events = sample(tmp_path)
    got = run(path, tip)
    assert len(events) == 21
    assert got.journal_event_count == 21
    assert got.verified_journal_tip_sha256 == tip
    assert [x.net_usd for x in got.trades] == [
        Decimal("9.50"), Decimal("-5.50"), Decimal("14.50"),
        Decimal("-5.50")
    ]
    assert got.closed_trades == 4 and got.wins == 2 and got.losses == 2
    assert got.breakeven == 0
    assert got.win_rate_percent == Decimal("50")
    assert got.expectancy_net_usd_per_trade == Decimal("3.25")
    assert got.profit_factor == Decimal(24) / Decimal(11)
    assert got.profit_factor_status == "DEFINED"
    assert got.realized_gross_usd == Decimal("15")
    assert got.transaction_costs_usd == Decimal("-2")
    assert got.net_profit_usd == Decimal("13")
    assert got.final_cash_usd == got.final_equity_usd == Decimal("10013")
    assert got.max_observed_drawdown_usd == Decimal("6")
    assert Decimal("0.05") < got.max_observed_drawdown_percent < Decimal("0.07")
    assert [(v.month_utc, v.net_usd) for v in got.monthly] == [
        ("2026-09", Decimal("4.00")), ("2026-10", Decimal("9.00"))
    ]
    assert got.sharpe_annualized is None
    assert not got.original_broker_trades_verified
    assert not got.historical_strategy_profitability_qualified
    assert json.loads(got.to_json())["max_drawdown_type"] == (
        "EVENT_SAMPLED_MARK_TO_MARKET_NOT_INTRABAR"
    )


def test_identical_reopen_and_different_source_rejected(tmp_path):
    path, tip, _ = sample(tmp_path)
    assert run(path, tip) == run(path, tip)
    with pytest.raises(ValueError, match="journal tip"):
        run(path, "b" * 64)
    with pytest.raises(ValueError, match="source"):
        run(path, tip, source="b" * 64)
    with pytest.raises(ValueError, match="journal"):
        run(tmp_path / "does_not_exist.db", tip)


def test_tampered_record_rejected_by_real_ledger_chain(tmp_path):
    path, tip, _ = sample(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("DROP TRIGGER events_no_update")
        db.execute("UPDATE journal_events SET kind='swap' WHERE seq=5")
    with pytest.raises(ValueError, match="guards"):
        run(path, tip)


def test_repeated_external_deposit_refused(tmp_path):
    path, tip, _ = sample(tmp_path)
    journal = CashJournal(path, ounces_per_lot=Decimal(1),
                          source_sha256=SOURCE_SHA)
    view = journal.append("external_topup", "2026-10-01T11:05:00Z",
                          "deposit", {"usd": "500.00"})
    with pytest.raises(ValueError, match="external funding"):
        run(path, view.tip_sha256)
    assert tip != view.tip_sha256


def test_open_position_does_not_silently_count_unrealized_as_trade(tmp_path):
    j = CashJournal(tmp_path / "unclosed.db", ounces_per_lot=Decimal(1),
                    source_sha256=SOURCE_SHA)
    j.initialize()
    j.append("fund", "2026-09-30T11:00:00Z", "deposit", {"usd": "10000.00"})
    j.append("mark", "2026-09-30T11:00:01Z",
             "mark", {"bid": "100", "ask": "101"})
    end = j.append("open", "2026-09-30T11:00:02Z",
                   "open", {"id": "x", "direction": "long", "price": "101", "lots": "1"})
    with pytest.raises(ValueError, match="open positions"):
        run(j.path, end.tip_sha256)


def test_unattributed_cost_refused(tmp_path):
    j = CashJournal(tmp_path / "loose_fee.db", ounces_per_lot=Decimal(1),
                    source_sha256=SOURCE_SHA)
    j.initialize()
    j.append("fund", "2026-09-30T11:00:00Z", "deposit", {"usd": "10000.00"})
    end = j.append("fee", "2026-09-30T11:00:01Z",
                   "commission", {"usd": "-0.50"})
    with pytest.raises(ValueError, match="unattributed"):
        run(j.path, end.tip_sha256)


def test_overlap_source_is_refused_instead_of_allocating_ambiguous_costs(tmp_path):
    j = CashJournal(tmp_path / "overlap.db", ounces_per_lot=Decimal(1),
                    source_sha256=SOURCE_SHA)
    j.initialize()
    j.append("fund", "2026-09-30T11:00:00Z", "deposit", {"usd": "10000.00"})
    j.append("mark", "2026-09-30T11:00:01Z", "mark", {"bid": "100", "ask": "100"})
    j.append("open1", "2026-09-30T11:00:02Z",
             "open", {"id": "x", "direction": "long", "price": "100", "lots": "1"})
    end = j.append("open2", "2026-09-30T11:00:03Z",
                   "open", {"id": "y", "direction": "long", "price": "100", "lots": "1"})
    with pytest.raises(ValueError, match="overlapping"):
        run(j.path, end.tip_sha256)


def test_day17_original_single_trade_cent_reconciliation(tmp_path):
    j = CashJournal(tmp_path / "day17.db", ounces_per_lot=Decimal(100),
                    source_sha256=SOURCE_SHA)
    j.initialize()
    for key, stamp, kind, data in [
        ("fund", "2026-10-14T14:00:00Z", "deposit", {"usd": "10000.00"}),
        ("mark0", "2026-10-14T14:00:00Z", "mark",
         {"bid": "2650.00", "ask": "2650.10"}),
        ("open", "2026-10-14T14:00:01Z", "open",
         {"id": "one", "direction": "long", "price": "2650.10", "lots": "0.1"}),
        ("comm1", "2026-10-14T14:00:01Z", "commission", {"usd": "-0.25"}),
        ("slip1", "2026-10-14T14:00:01Z", "slippage", {"usd": "-0.10"}),
        ("mark1", "2026-10-14T14:05:01Z", "mark",
         {"bid": "2651.00", "ask": "2651.10"}),
        ("close", "2026-10-14T14:05:01Z", "close",
         {"id": "one", "price": "2651.00", "lots": "0.1"}),
        ("comm2", "2026-10-14T14:05:01Z", "commission", {"usd": "-0.25"}),
        ("slip2", "2026-10-14T14:05:01Z", "slippage", {"usd": "-0.10"}),
    ]:
        last = j.append(key, stamp, kind, data)
    got = run(j.path, last.tip_sha256, ounces=Decimal(100))
    assert got.net_profit_usd == Decimal("8.30")
    assert got.final_cash_usd == Decimal("10008.30")
    assert got.realized_gross_usd == Decimal("9.00")
    assert got.transaction_costs_usd == Decimal("-0.70")
    assert got.max_observed_drawdown_usd == Decimal("1.35")
    assert got.profit_factor is None
    assert got.profit_factor_status == "UNDEFINED_NO_LOSSES"


def test_flat_without_trades_is_not_invented_win_rate_or_sharpe(tmp_path):
    j = CashJournal(tmp_path / "empty.db", ounces_per_lot=Decimal(1),
                    source_sha256=SOURCE_SHA)
    j.initialize()
    snap = j.append("capital", "2026-10-14T14:00:00Z",
                    "deposit", {"usd": "10000.00"})
    got = run(j.path, snap.tip_sha256)
    assert got.closed_trades == 0
    assert got.net_profit_usd == Decimal(0)
    assert got.win_rate_percent is None
    assert got.expectancy_net_usd_per_trade is None
    assert got.profit_factor is None
    assert got.sharpe_annualized is None
    assert got.profit_factor_status == "NO_TRADES"


def test_sharpe_only_when_daily_calendar_evidence_and_sample_size_present():
    values = tuple(Decimal("0.01") if i % 2 == 0 else Decimal("-0.01")
                   for i in range(30))
    assert qualified_daily_sharpe(
        values, session_calendar_independently_verified=False
    ) is None
    assert qualified_daily_sharpe(
        values[:29], session_calendar_independently_verified=True
    ) is None
    assert qualified_daily_sharpe(
        values, session_calendar_independently_verified=True
    ) == Decimal(0)
    assert qualified_daily_sharpe(
        (Decimal("0.01"),) * 30,
        session_calendar_independently_verified=True,
    ) is None
    with pytest.raises(ValueError, match="finite"):
        qualified_daily_sharpe(
            values[:-1] + (Decimal("NaN"),),
            session_calendar_independently_verified=True,
        )
