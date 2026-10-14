"""Day17 real SQLite cash and equity journal reconciliation."""
import sqlite3
from decimal import Decimal as D

import pytest

from aidy.strategy_lab_cash_ledger import CashJournal

T0="2026-10-14T14:00:00Z"
T1="2026-10-14T14:00:01Z"
T2="2026-10-14T14:05:01Z"
SOURCE="a"*64


def journal(tmp_path):
    j=CashJournal(tmp_path/"ledger.sqlite3",ounces_per_lot=D(100),
                  source_sha256=SOURCE)
    j.initialize()
    return j


def seeded(tmp_path):
    j=journal(tmp_path)
    j.append("fund",T0,"deposit",{"usd":"10000.00"})
    j.append("mark0",T0,"mark",{"bid":"2650.00","ask":"2650.10"})
    return j


def example(tmp_path):
    j=seeded(tmp_path)
    j.append("open1",T1,"open",{"id":"trade1","direction":"long","price":"2650.10","lots":"0.1"})
    j.append("entryfee",T1,"commission",{"usd":"-0.25"})
    j.append("entryslip",T1,"slippage",{"usd":"-0.10"})
    j.append("mark1",T2,"mark",{"bid":"2651.00","ask":"2651.10"})
    j.append("close1",T2,"close",{"id":"trade1","price":"2651.00","lots":"0.1"})
    j.append("exitfee",T2,"commission",{"usd":"-0.25"})
    j.append("exitslip",T2,"slippage",{"usd":"-0.10"})
    return j



def test_real_sqlite_reopen_and_10000_to_10008_30(tmp_path):
    j=example(tmp_path)
    a=j.view()
    assert a.cash_usd==D("10008.30")
    assert a.realized_usd==D("9.00")
    assert a.unrealized_usd==0
    assert a.equity_usd==D("10008.30")
    assert a.event_count==9
    assert len(a.tip_sha256)==64
    reopened=CashJournal(j.path,ounces_per_lot=D(100),source_sha256=SOURCE)
    assert reopened.view()==a


def test_before_close_equity_marks_unrealized(tmp_path):
    j=seeded(tmp_path)
    j.append("open",T1,"open",{"id":"one","direction":"long","price":"2650.10","lots":"0.1"})
    snap=j.view()
    assert snap.cash_usd==D(10000)
    assert snap.unrealized_usd==D("-1.00")
    assert snap.equity_usd==D("9999.00")
    assert len(snap.open_positions)==1


def test_short_mark_uses_ask_and_reconciles(tmp_path):
    j=seeded(tmp_path)
    j.append("open",T1,"open",{"id":"short","direction":"short","price":"2650","lots":"0.1"})
    assert j.view().unrealized_usd==D("-1.00")
    j.append("mark2",T2,"mark",{"bid":"2649","ask":"2649.10"})
    assert j.view().unrealized_usd==D("9.00")
    j.append("close",T2,"close",{"id":"short","price":"2649.10","lots":"0.1"})
    assert j.view().cash_usd==D(10009)


def test_partial_close_then_remaining_unrealized(tmp_path):
    j=seeded(tmp_path)
    j.append("open",T1,"open",{"id":"x","direction":"long","price":"2650","lots":"0.2"})
    j.append("mark2",T2,"mark",{"bid":"2651","ask":"2651.10"})
    j.append("half",T2,"close",{"id":"x","price":"2651","lots":"0.1"})
    v=j.view()
    assert v.realized_usd==D(10)
    assert v.unrealized_usd==D(10)
    assert v.equity_usd==D(10020)
    assert v.open_positions[0][3]==D(".1")


def test_identical_events_replay_exact_hash(tmp_path):
    a=example(tmp_path/"a")
    b=example(tmp_path/"b")
    assert a.view()==b.view()


@pytest.mark.parametrize("kind,data",[
    ("commission",{"usd":"1.00"}),("deposit",{"usd":"-1.00"}),
    ("deposit",{"usd":"1.001"}),("mark",{"bid":"2652","ask":"2651"}),
    ("open",{"id":"x","direction":"wrong","price":"2650","lots":"0.1"}),
    ("unknown",{}),
])
def test_invalid_cash_or_action_rejected_before_persist(tmp_path,kind,data):
    j=seeded(tmp_path)
    original=j.view()
    with pytest.raises(ValueError):
        j.append("bad",T1,kind,data)
    assert j.view()==original


def test_duplicate_key_and_chronology_rejected(tmp_path):
    j=seeded(tmp_path)
    with pytest.raises(ValueError):
        j.append("fund",T1,"deposit",{"usd":"50.00"})
    with pytest.raises(ValueError):
        j.append("older","2026-10-13T12:00:00Z","deposit",{"usd":"50.00"})


def test_missing_position_and_overclose_rejected(tmp_path):
    j=seeded(tmp_path)
    with pytest.raises(ValueError):
        j.append("close",T1,"close",{"id":"notfound","lots":"0.1","price":"2651"})
    j.append("open",T1,"open",{"id":"x","direction":"long","price":"2650","lots":"0.1"})
    with pytest.raises(ValueError):
        j.append("overclose",T2,"close",{"id":"x","lots":"0.2","price":"2651"})


def test_immutable_sqlite_update_and_delete_denied(tmp_path):
    j=example(tmp_path)
    with sqlite3.connect(j.path) as con:
        with pytest.raises(sqlite3.DatabaseError,match="append-only"):
            con.execute("UPDATE journal_events SET kind='deposit' WHERE seq=1")
        with pytest.raises(sqlite3.DatabaseError,match="append-only"):
            con.execute("DELETE FROM journal_events WHERE seq=1")


def test_database_tampering_detected_after_guard_repair(tmp_path):
    j=example(tmp_path)
    with sqlite3.connect(j.path) as con:
        con.execute("DROP TRIGGER events_no_update")
        con.execute("UPDATE journal_events SET payload_json='{}' WHERE seq=1")
    j.initialize()
    with pytest.raises(ValueError,match="tampering"):
        j.view()


def test_wrong_broker_digest_rejected_on_reopen(tmp_path):
    j=example(tmp_path)
    wrong=CashJournal(j.path,ounces_per_lot=D(100),source_sha256="f"*64)
    with pytest.raises(ValueError,match="source"):
        wrong.view()


def test_invalid_zero_equity_withdrawal_refused(tmp_path):
    j=seeded(tmp_path)
    with pytest.raises(ValueError,match="negative cash"):
        j.append("huge",T1,"withdrawal",{"usd":"-20000.00"})


def test_negative_source_or_bad_contract_refused(tmp_path):
    with pytest.raises(ValueError):
        CashJournal(tmp_path/"bad.db",ounces_per_lot=D(0),source_sha256=SOURCE)


def test_subcent_rounding_is_refused_for_cash_events(tmp_path):
    j=seeded(tmp_path)
    with pytest.raises(ValueError,match="cents"):
        j.append("fee",T1,"commission",{"usd":"-0.005"})

