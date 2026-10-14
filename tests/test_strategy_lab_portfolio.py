"""Day16 lot-grid/margin and partial exit adversarial reconciliation."""
import json
from decimal import Decimal as D
from hashlib import sha256
from pathlib import Path

import pytest

from aidy.strategy_lab_broker_profile import BrokerProfile
from aidy.strategy_lab_portfolio import Portfolio

FIXTURE=Path(__file__).parents[1]/"research/strategy_lab/fixtures/day11_illustrative_broker_observation.json"


def book(equity="10000", max_positions=2, max_risk="2"):
    bs=FIXTURE.read_bytes()
    obj=json.loads(bs)
    obj.pop("evidence_kind")
    obj.update(schema_version="aidy.broker_profile.v1",
        profile_id="synthetic_xauusd_standard",revision=1,
        provenance={"evidence_kind":"internal_fixture","source_reference":str(FIXTURE),
                    "source_sha256":sha256(bs).hexdigest(),
                    "captured_at_utc":"2026-10-14T14:10:00Z",
                    "evidence_label":"illustrative_not_live"})
    return Portfolio(BrokerProfile.from_wire(obj),bs,equity_usd=D(equity),
                     max_positions=max_positions,max_total_risk_percent=D(max_risk))


def test_exact_risk_grid_and_margin():
    p=book()
    assert p.size_for_risk(D(2650),D(2640),D(1))==D("0.10")
    trade=p.open("one","long",D(2650),D(2640),D(1))
    assert trade.lots_open==D("0.10")
    assert trade.risk_per_lot_usd==D(1000)
    assert p.risk_open_usd==D(100)
    assert p.reserved_margin_usd==D(265)
    assert p.free_margin_usd==D(9735)


def test_floor_risk_never_oversizes():
    p=book()
    assert p.size_for_risk(D(2650),D(2640),D("0.94"))==D("0.09")
    assert p.size_for_risk(D(2650),D(2640),D("0.11"))==D("0.01")


def test_two_positions_and_combined_risk_cap():
    p=book()
    p.open("a","long",D(2650),D(2640),D(1))
    p.open("b","short",D(2650),D(2660),D(1))
    assert p.risk_open_usd==D(200)
    with pytest.raises(ValueError,match="maximum positions"):
        p.open("c","long",D(2650),D(2640),D(1))


def test_combined_risk_rejected_before_trade():
    p=book(max_positions=3)
    p.open("a","long",D(2650),D(2640),D("1.5"))
    with pytest.raises(ValueError,match="combined position risk"):
        p.open("b","long",D(2650),D(2640),D(1))
    assert list(p.positions)==["a"]


def test_partial_exit_releases_margin_and_reconciles():
    p=book()
    p.open("a","long",D(2650),D(2640),D(1))
    assert p.reduce("a",D(".03"),D(2652))==D(6)
    assert p.positions["a"].lots_remaining==D(".07")
    assert p.reserved_margin_usd==D("185.5")
    assert p.reduce("a",D(".02"),D(2651))==D(2)
    assert p.positions["a"].lots_remaining==D(".05")
    assert p.reserved_margin_usd==D("132.5")
    assert p.reduce("a",D(".05"),D(2650))==D(0)
    assert p.positions=={}
    assert p.equity==D(10008)
    assert p.reserved_margin_usd==0
    assert p.realized_total==D(8)


def test_short_reduction_realizes_correct_negative_cash():
    p=book()
    p.open("s","short",D(2650),D(2660),D(1))
    assert p.reduce("s",D(".1"),D(2651))==D(-10)
    assert p.equity==D(9990)


@pytest.mark.parametrize("lots",["0","0.005","0.011","0.08"])
def test_invalid_or_oversized_partial_rejected(lots):
    p=book()
    p.open("a","long",D(2650),D(2640),D("0.05"))
    with pytest.raises(ValueError):
        p.reduce("a",D(lots),D(2652))


def test_low_equity_refuses_overmargin():
    p=book(equity="100",max_risk="100")
    with pytest.raises(ValueError,match="margin"):
        p.open("a","long",D(2650),D(2649),D(100))


def test_duplicate_id_and_stop_orientation_rejected():
    p=book()
    p.open("a","long",D(2650),D(2640),D(1))
    with pytest.raises(ValueError):
        p.open("a","long",D(2650),D(2640),D(1))
    with pytest.raises(ValueError):
        p.open("b","short",D(2650),D(2640),D(1))


def test_small_budget_below_minimum_lot_rejected():
    p=book()
    with pytest.raises(ValueError,match="minimum broker lot"):
        p.size_for_risk(D(2650),D(2640),D("0.05"))


def test_no_float_based_risk():
    p=book()
    with pytest.raises(ValueError):
        p.size_for_risk(2650.0,D(2640),D(1))


def test_reopen_after_full_exit_and_reuse_id():
    p=book()
    p.open("a","long",D(2650),D(2640),D(1))
    p.reduce("a",D(".10"),D(2653))
    new=p.open("a","long",D(2650),D(2640),D(1))
    assert new.lots_open==D(".10")
