"""Day19 real end-to-end synthetic XAUUSD Strategy Lab engineering fixture."""
import json
from hashlib import sha256
from pathlib import Path

import pytest

from aidy.strategy_lab_bidask_execution import QuoteTape
from aidy.strategy_lab_broker_profile import BrokerProfile
from aidy.strategy_lab_reference_run import run_internal_reference

ROOT=Path(__file__).parents[1]/"research/strategy_lab/fixtures"
BROKER=ROOT/"day11_illustrative_broker_observation.json"
QUOTE=ROOT/"day12_illustrative_bidask_quotes.json"
CANDLES=ROOT/"day19_internal_closed_m1.json"


def inputs():
    bs=BROKER.read_bytes()
    obj=json.loads(bs)
    obj.pop("evidence_kind")
    obj.update(schema_version="aidy.broker_profile.v1",
        profile_id="synthetic_xauusd_standard",revision=1,
        provenance={"evidence_kind":"internal_fixture","source_reference":str(BROKER),
                    "source_sha256":sha256(bs).hexdigest(),
                    "captured_at_utc":"2026-10-14T14:10:00Z",
                    "evidence_label":"illustrative_not_live"})
    quote=QUOTE.read_bytes()
    tape=QuoteTape.from_snapshot(quote,expected_sha256=sha256(quote).hexdigest())
    candle=CANDLES.read_bytes()
    return {"closed_bar_source":candle,
            "expected_closed_bar_sha256":sha256(candle).hexdigest(),
            "quote_tape":tape,
            "broker_profile":BrokerProfile.from_wire(obj),
            "broker_source_bytes":bs}


def test_complete_real_pipeline_produces_10008_30(tmp_path):
    a=run_internal_reference(**inputs(),sqlite_path=tmp_path/"ledger.sqlite3")
    assert str(a.gross_usd)=="9.00"
    assert str(a.commissions_usd)=="-0.50"
    assert str(a.slippage_usd)=="-0.20"
    assert str(a.swaps_usd)=="0"
    assert str(a.net_usd)=="8.30"
    assert str(a.opening_cash_usd)=="10000.00"
    assert str(a.closing_cash_usd)=="10008.30"
    assert a.entry_utc<a.exit_utc
    assert len(a.entry_order_id)==64 and len(a.exit_order_id)==64
    assert len(a.journal_tip_sha256)==64
    assert not a.actual_broker_attested


def test_same_frozen_originals_yield_identical_end_to_end_hashes(tmp_path):
    a=run_internal_reference(**inputs(),sqlite_path=tmp_path/"a.sqlite3")
    b=run_internal_reference(**inputs(),sqlite_path=tmp_path/"b.sqlite3")
    assert a==b
    # Same database replay must also be idempotent.
    c=run_internal_reference(**inputs(),sqlite_path=tmp_path/"a.sqlite3")
    assert a==c


def test_closed_bar_source_mutation_detected(tmp_path):
    kwargs=inputs()
    kwargs["closed_bar_source"]+=b" "
    with pytest.raises(ValueError,match="hash mismatched"):
        run_internal_reference(**kwargs,sqlite_path=tmp_path/"bad.db")


def test_source_bar_reordering_detected_without_hindsight(tmp_path):
    kwargs=inputs()
    obj=json.loads(kwargs["closed_bar_source"])
    obj["bars"][20],obj["bars"][21]=obj["bars"][21],obj["bars"][20]
    from hashlib import sha256
    raw=json.dumps(obj).encode()
    kwargs["closed_bar_source"]=raw
    kwargs["expected_closed_bar_sha256"]=sha256(raw).hexdigest()
    with pytest.raises(ValueError,match="missing or reordered"):
        run_internal_reference(**kwargs,sqlite_path=tmp_path/"bad.db")


def test_bad_broker_original_bytes_blocked(tmp_path):
    kwargs=inputs()
    kwargs["broker_source_bytes"]=b"fake source"
    with pytest.raises(ValueError):
        run_internal_reference(**kwargs,sqlite_path=tmp_path/"bad.db")


def test_no_quote_after_bar_close_blocks_fill(tmp_path):
    kwargs=inputs()
    raw=json.loads(kwargs["quote_tape"].snapshot_bytes)
    raw["quotes"]=raw["quotes"][:1]
    original=json.dumps(raw).encode()
    kwargs["quote_tape"]=QuoteTape.from_snapshot(original,expected_sha256=sha256(original).hexdigest())
    with pytest.raises(ValueError):
        run_internal_reference(**kwargs,sqlite_path=tmp_path/"bad.db")


def test_unsupported_alternative_rule_never_inferred(tmp_path):
    kwargs=inputs()
    obj=json.loads(kwargs["closed_bar_source"])
    obj["bars"][0]["close"]="2652.00"
    raw=json.dumps(obj).encode()
    kwargs.update(closed_bar_source=raw,expected_closed_bar_sha256=sha256(raw).hexdigest())
    with pytest.raises(ValueError,match="violates first-cross"):
        run_internal_reference(**kwargs,sqlite_path=tmp_path/"bad.db")
