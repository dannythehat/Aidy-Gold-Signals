"""Day18 deterministic manifest, SQLite replay, and malicious tamper vectors."""
import copy
import sqlite3
from decimal import Decimal as D
from hashlib import sha256

import pytest

from aidy.strategy_lab_deterministic_replay import canonical_events, replay_cash_events

SOURCE="a"*64
T0="2026-10-14T14:00:00Z"
T1="2026-10-14T14:00:01Z"
T2="2026-10-14T14:05:01Z"


def events():
    return [
        {"key":"fund","at_utc":T0,"kind":"deposit","data":{"usd":"10000.00"}},
        {"key":"mark0","at_utc":T0,"kind":"mark","data":{"bid":"2650.00","ask":"2650.10"}},
        {"key":"open","at_utc":T1,"kind":"open","data":{"id":"x","direction":"long","price":"2650.10","lots":"0.1"}},
        {"key":"fee0","at_utc":T1,"kind":"commission","data":{"usd":"-0.25"}},
        {"key":"slip0","at_utc":T1,"kind":"slippage","data":{"usd":"-0.10"}},
        {"key":"mark1","at_utc":T2,"kind":"mark","data":{"bid":"2651.00","ask":"2651.10"}},
        {"key":"close","at_utc":T2,"kind":"close","data":{"id":"x","price":"2651.00","lots":"0.1"}},
        {"key":"fee1","at_utc":T2,"kind":"commission","data":{"usd":"-0.25"}},
        {"key":"slip1","at_utc":T2,"kind":"slippage","data":{"usd":"-0.10"}},
    ]


def digest(source):
    return sha256(canonical_events(source,SOURCE)).hexdigest()


def replay(path,source=None,hash=None):
    source=events() if source is None else source
    return replay_cash_events(path,source,source_sha256=SOURCE,
                              ounces_per_lot=D(100),
                              expected_manifest_sha256=digest(source) if hash is None else hash)


def test_frozen_replay_two_databases_identical(tmp_path):
    a,b=replay(tmp_path/"a.sqlite3"),replay(tmp_path/"b.sqlite3")
    assert a==b
    assert a.cash_usd==D("10008.30")
    assert a.equity_usd==D("10008.30")
    assert a.unrealized_usd==0
    assert a.journal_event_count==9
    assert a.idempotent_events==0


def test_repeat_exact_manifest_does_not_duplicate(tmp_path):
    target=tmp_path/"one.sqlite3"
    a=replay(target)
    b=replay(target)
    assert a.journal_tip_sha256==b.journal_tip_sha256
    assert b.idempotent_events==9 and a.idempotent_events==0
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT COUNT(*) FROM journal_events").fetchone()[0]==9


def test_changed_event_cannot_reuse_frozen_manifest_digest(tmp_path):
    original=events()
    frozen=digest(original)
    altered=copy.deepcopy(original)
    altered[3]["data"]["usd"]="-0.50"
    with pytest.raises(ValueError,match="digest mismatch"):
        replay(tmp_path/"x.db",altered,frozen)
    assert not (tmp_path/"x.db").exists()


def test_conflicting_event_fails_even_with_new_approved_manifest(tmp_path):
    target=tmp_path/"ledger.db"
    replay(target)
    altered=events()
    altered[3]["data"]["usd"]="-0.50"
    with pytest.raises(ValueError,match="conflicting replay event identity"):
        replay(target,altered)
    assert replay(target).equity_usd==D("10008.30")


def test_reordering_cannot_use_old_frozen_hash(tmp_path):
    original=events()
    revised=copy.deepcopy(original)
    revised[3],revised[4]=revised[4],revised[3]
    with pytest.raises(ValueError,match="digest mismatch"):
        replay(tmp_path/"reordered.db",revised,digest(original))


def test_duplicate_or_unknown_fields_rejected():
    source=events()
    source.append(copy.deepcopy(source[0]))
    with pytest.raises(ValueError,match="duplicate"):
        canonical_events(source,SOURCE)
    bad=events()
    bad[0]["unknown"]="code"
    with pytest.raises(ValueError,match="schema"):
        canonical_events(bad,SOURCE)


def test_tampered_disk_chain_rejected_on_replay(tmp_path):
    path=tmp_path/"journal.db"
    replay(path)
    with sqlite3.connect(path) as con:
        con.execute("DROP TRIGGER events_no_update")
        con.execute("UPDATE journal_events SET payload_json='{}' WHERE seq=2")
    with pytest.raises(ValueError,match="tampering"):
        replay(path)


def test_extra_unrelated_event_is_not_included_silently(tmp_path):
    path=tmp_path/"journal.db"
    a=events()
    a.append({"key":"extra","at_utc":T2,"kind":"swap","data":{"usd":"-0.10"}})
    replay(path,a)
    with pytest.raises(ValueError,match="conflicting replay|extras"):
        replay(path,events())


def test_failed_cash_event_prevented_on_replay(tmp_path):
    source=events()
    source[0]["data"]["usd"]="0.001"
    with pytest.raises(ValueError,match="cents"):
        replay(tmp_path/"fail.db",source)


def test_source_hash_changes_manifest_domain():
    source=events()
    first=sha256(canonical_events(source,SOURCE)).hexdigest()
    next_one=sha256(canonical_events(source,"b"*64)).hexdigest()
    assert first!=next_one


def test_empty_manifest_rejected():
    with pytest.raises(ValueError):
        canonical_events([],SOURCE)
