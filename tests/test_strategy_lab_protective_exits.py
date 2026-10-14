"""Day15 independent adversarial stop/target/gap fixtures."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from aidy.strategy_lab_protective_exits import (
    ProtectedPosition,
    QuoteBar,
    resolve_protective_exit,
)

FRI=datetime(2026,10,16,20,tzinfo=UTC)
MON=datetime(2026,10,19,9,tzinfo=UTC)


def pos(direction="long"):
    if direction=="long":
        return ProtectedPosition("long",FRI,D(2650),D(2640),D(2670))
    return ProtectedPosition("short",FRI,D(2650),D(2660),D(2630))


def bar(*, start=None,bopen=2650,bhigh=2655,blow=2645,bclose=2651,spread=1):
    start=start or FRI+timedelta(minutes=1)
    return QuoteBar(start,start+timedelta(minutes=1),
        D(str(bopen)),D(str(bhigh)),D(str(blow)),D(str(bclose)),
        D(str(bopen+spread)),D(str(bhigh+spread)),
        D(str(blow+spread)),D(str(bclose+spread)))


@pytest.mark.parametrize("direction,barargs,reason,fill",[
    ("long",{"blow":2639},"stop","2640"),
    ("long",{"bhigh":2671},"target","2670"),
    ("long",{"blow":2639,"bhigh":2671},"stop_ambiguous","2640"),
    ("short",{"bhigh":2660},"stop","2660"),
    ("short",{"blow":2628},"target","2630"),
    ("short",{"bhigh":2660,"blow":2628},"stop_ambiguous","2660"),
])
def test_intrabar_directions_are_adverse_first(direction,barargs,reason,fill):
    outcome=resolve_protective_exit(pos(direction),(bar(**barargs),))
    assert outcome.reason==reason
    assert outcome.fill_price==D(fill)
    assert outcome.ambiguous==(reason=="stop_ambiguous")


@pytest.mark.parametrize("direction,args,reason,price",[
    ("long",{"bopen":2625,"bhigh":2635,"blow":2620,"bclose":2630},"stop_gap","2625"),
    ("long",{"bopen":2685,"bhigh":2690,"blow":2680,"bclose":2682},"target_gap","2670"),
    ("short",{"bopen":2670,"bhigh":2675,"blow":2665,"bclose":2671},"stop_gap","2671"),
    ("short",{"bopen":2620,"bhigh":2625,"blow":2615,"bclose":2621},"target_gap","2630"),
])
def test_weekend_gap_exit_gap_rule(direction,args,reason,price):
    outcome=resolve_protective_exit(pos(direction),(bar(start=MON,**args),))
    assert outcome.gap_at_open
    assert outcome.reason==reason
    assert outcome.fill_price==D(price)


def test_no_trigger_returns_none_without_future_peek():
    assert resolve_protective_exit(pos(),(bar(),)) is None


def test_first_trigger_ends_lookahead():
    seq=(bar(blow=2630),bar(start=FRI+timedelta(minutes=2),bhigh=2680))
    out=resolve_protective_exit(pos(),seq)
    assert out.bar_index==0 and out.reason=="stop"


def test_identical_source_outputs_identical_hash():
    x=resolve_protective_exit(pos(),(bar(blow=2639),))
    y=resolve_protective_exit(pos(),(bar(blow=2639),))
    assert x==y
    assert len(x.audit_sha256)==64


@pytest.mark.parametrize("alter",[
    {"bid_open":D(-1)},{"bid_high":D(2640)},{"bid_low":D(2660)},
    {"ask_open":D(2640)},{"bid_close":D("NaN")},
    {"close_at_utc":FRI},
])
def test_bad_ohlc_rejected(alter):
    with pytest.raises(ValueError):
        resolve_protective_exit(pos(),(replace(bar(),**alter),))


def test_wrong_position_protection_rejected():
    with pytest.raises(ValueError):
        resolve_protective_exit(replace(pos(),stop_price=D(2660)),(bar(),))


def test_overlapping_or_preentry_bars_rejected():
    first=bar()
    second=bar(start=FRI+timedelta(seconds=30))
    with pytest.raises(ValueError):
        resolve_protective_exit(pos(),(first,second))
    with pytest.raises(ValueError):
        resolve_protective_exit(pos(),(bar(start=FRI-timedelta(minutes=2)),))


def test_missing_bars_rejected():
    with pytest.raises(ValueError):
        resolve_protective_exit(pos(),())


def test_exact_open_gap_stop_priority():
    out=resolve_protective_exit(pos(),(bar(bopen=2635,bhigh=2680,blow=2630,bclose=2660),))
    assert out.reason=="stop_gap" and out.fill_price==D(2635)


def test_no_prebar_market_quote_fill_claim():
    out=resolve_protective_exit(pos(),(bar(blow=2635),))
    assert out.bar_close_utc>FRI
    assert out.reason=="stop"
