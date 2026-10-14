"""Day14 order lifecycle tests run on saved quote/source fixtures."""
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest

from aidy.strategy_lab_bidask_execution import QuoteTape
from aidy.strategy_lab_broker_profile import BrokerProfile
from aidy.strategy_lab_order_lifecycle import OrderIntent, simulate_order

ROOT = Path(__file__).resolve().parents[1] / "research/strategy_lab/fixtures"
CLOSE = datetime(2026, 10, 14, 14, tzinfo=UTC)


def inputs():
    bs = (ROOT / "day11_illustrative_broker_observation.json").read_bytes()
    data = json.loads(bs)
    data.pop("evidence_kind")
    data.update(schema_version="aidy.broker_profile.v1",
                profile_id="synthetic_xauusd_standard", revision=1,
                provenance={"evidence_kind":"internal_fixture",
                            "source_reference":"day11_illustrative_broker_observation.json",
                            "source_sha256":sha256(bs).hexdigest(),
                            "captured_at_utc":"2026-10-14T14:10:00Z",
                            "evidence_label":"illustrative_not_live"})
    qp = (ROOT / "day12_illustrative_bidask_quotes.json").read_bytes()
    return BrokerProfile.from_wire(data), bs, QuoteTape.from_snapshot(
        qp, expected_sha256=sha256(qp).hexdigest()
    )


def order(action="buy", kind="market", limit=None, expiry=30):
    return OrderIntent("aidy-v1-" + "f" * 64, "signal_42", action, kind,
                       Decimal("0.10"), CLOSE, CLOSE + timedelta(seconds=expiry),
                       limit)


def run(intent):
    return simulate_order(*inputs(), intent)


@pytest.mark.parametrize("side,price", [("buy", "2650.10"), ("sell", "2650.00")])
def test_market_orders_choose_opposite_side_next_quote(side, price):
    result = run(order(side))
    assert result.state == "filled"
    assert [e.state for e in result.events] == ["created","pending","filled"]
    fill = result.events[-1]
    assert fill.at_utc == CLOSE + timedelta(seconds=1)
    assert fill.quote_index == 1
    assert fill.price == Decimal(price)
    assert fill.at_utc > CLOSE
    assert not result.broker_attested


@pytest.mark.parametrize("side,limit,expected", [
    ("buy","2650.10","filled"), ("buy","2650.00","expired"),
    ("sell","2650.00","filled"), ("sell","2650.11","expired"),
])
def test_limit_marketability_side_correct(side,limit,expected):
    actual = run(order(side,"limit",Decimal(limit)))
    assert actual.state == expected


def test_limit_waits_for_later_marketable_quote():
    profile, src, tape = inputs()
    x = OrderIntent("aidy-v1-"+"f"*64,"x","sell","limit",Decimal(".1"),
                    CLOSE,CLOSE+timedelta(minutes=6),Decimal("2651.00"))
    result = simulate_order(profile,src,tape,x)
    assert result.events[-1].quote_index == 2
    assert result.events[-1].at_utc == CLOSE+timedelta(minutes=5)
    assert result.events[-1].price == Decimal("2651.00")


def test_expiry_is_terminal_and_no_future_quote_leaks():
    result = run(order("buy","limit",Decimal("2640")))
    assert result.state == "expired"
    assert result.events[-1].at_utc == CLOSE+timedelta(seconds=30)
    assert result.events[-1].quote_index is None
    assert len(result.events) == 3


def test_no_same_timestamp_quote():
    result = run(order())
    assert result.events[-1].quote_index == 1
    assert result.events[-1].quote_index != 0


@pytest.mark.parametrize("part",[
    {"action":"wrong"},{"kind":"stop"},{"lots":Decimal(".015")},
    {"limit_price":Decimal("2650.00")},{"expires_at_utc":CLOSE},
    {"signal_closed_at_utc":CLOSE.replace(tzinfo=None)},
    {"strategy_version_id":"unregistered"},
])
def test_invalid_intents_rejected(part):
    intent=replace(order(),**part)
    with pytest.raises(ValueError):
        run(intent)


@pytest.mark.parametrize("limit",[
    Decimal("2650.001"),Decimal("-1"),Decimal("NaN"),None,
])
def test_invalid_limit_rejected(limit):
    with pytest.raises(ValueError):
        run(order("buy","limit",limit))


def test_frozen_order_identity_and_event_hashes_repeat():
    a,b=run(order()),run(order())
    assert a.to_json()==b.to_json()
    assert a.order_id==b.order_id
    assert len({e.id for e in a.events})==3
    assert all(len(e.id)==64 for e in a.events)


def test_modified_original_quote_bytes_rejected():
    profile,source,tape=inputs()
    forged=replace(tape,quotes=tuple(reversed(tape.quotes)))
    with pytest.raises(ValueError,match="tampered"):
        simulate_order(profile,source,forged,order())


def test_wrong_original_broker_evidence_rejected():
    profile,source,tape=inputs()
    with pytest.raises(ValueError):
        simulate_order(profile,source+b" ",tape,order())


def test_order_filled_at_expiry_inclusive():
    result=run(order(expiry=1))
    assert result.state=="filled"
    assert result.events[-1].at_utc==CLOSE+timedelta(seconds=1)


def test_research_only_no_stop_or_target_invention():
    data=run(order()).to_json()
    assert "profit" not in data
    assert '"broker_attested":false' in data
