"""B03 margin-stopout gate: genuine code tests, SYNTHETIC prices and broker fixtures."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest

from aidy.strategy_lab_bidask_execution import QuoteTape
from aidy.strategy_lab_broker_profile import BrokerProfile
from aidy.strategy_lab_margin_stopout import (
    StopOutScenario,
    replay_margin_path,
)

FIXTURES = Path(__file__).resolve().parents[1] / "research/strategy_lab/fixtures"
BROKER = FIXTURES / "day11_illustrative_broker_observation.json"
BASE = datetime(2026, 10, 14, 14, tzinfo=UTC)


def profile():
    raw = BROKER.read_bytes()
    doc = json.loads(raw)
    doc.pop("evidence_kind")
    doc.update({
        "schema_version": "aidy.broker_profile.v1",
        "profile_id": "synthetic_xauusd_standard",
        "revision": 1,
        "provenance": {
            "evidence_kind": "internal_fixture",
            "source_reference": str(BROKER),
            "source_sha256": sha256(raw).hexdigest(),
            "captured_at_utc": "2026-10-14T14:10:00Z",
            "evidence_label": "illustrative_not_live",
        },
    })
    return BrokerProfile.from_wire(doc), raw


def tape(bids, *, start=BASE, step=60):
    data = {
        "schema_version": "aidy.quote_tape.v1",
        "source_class": "internal_fixture",
        "symbol": "XAUUSD",
        "source_clock": "UTC",
        "source_archive_sha256": "f" * 64,
        "source_identity": "margin_stopout_unit_test_no_live_quotes",
        "quotes": [
            {
                "time_utc": (start+timedelta(seconds=i*step+1)).isoformat().replace(
                    "+00:00", "Z"
                ),
                "bid": format(Decimal(str(v)), "f"),
                "ask": format(Decimal(str(v))+Decimal("0.10"), "f"),
            }
            for i, v in enumerate(bids)
        ],
    }
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return QuoteTape.from_snapshot(raw, expected_sha256=sha256(raw).hexdigest())


TERMS = StopOutScenario(Decimal(100), Decimal(50), "unit_test_declared_not_broker")


def simulate_path(bids, *, cash="500", threshold=TERMS, step=60):
    broker, source = profile()
    return replay_margin_path(
        broker, source, tape(bids, step=step), threshold,
        direction="long", lots="0.1",
        entry_signal_closed_at_utc=BASE,
        planned_exit_signal_closed_at_utc=BASE+timedelta(minutes=(len(bids)-1)*step//60),
        initial_cash_usd=cash,
    )


def test_normal_healthy_market_exit_reconciles_real_quote_sides_and_costs():
    got = simulate_path(["2650", "2651", "2652", "2653"], cash="500")
    assert got.status == "RESEARCH_NORMAL_EXIT"
    assert not got.stopout_triggered
    assert got.quote_source_class == "internal_fixture"
    assert got.broker_execution_verified is False
    assert got.stopout_rules_broker_attested is False
    assert Decimal(got.ending_cash_usd) > Decimal(got.initial_cash_usd)
    assert Decimal(got.realised_net_pnl_usd) == (
        Decimal(got.ending_cash_usd)-Decimal(got.initial_cash_usd)
    )


def test_true_first_stopout_cancels_profitable_later_recovery():
    got = simulate_path(["2650", "2610", "2800", "2900"])
    assert got.stopout_triggered is True
    assert got.status == "RESEARCH_FORCED_STOPOUT"
    assert got.exit_utc == (BASE+timedelta(minutes=1,seconds=1)).isoformat()
    assert Decimal(got.ending_cash_usd) < 500
    assert len(got.event_log)==2
    assert got.event_log[-1].event=="FORCED_STOPOUT"
    assert got.to_json()==simulate_path(["2650","2610","2800","2900"]).to_json()


def test_long_liquidation_reads_bid_not_ask():
    got=simulate_path(["2650","2610","2900"])
    assert Decimal(got.exit_price)==Decimal("2610")
    assert Decimal(got.entry_price)>Decimal("2650")
    assert Decimal(got.funding_cash_usd)==0


def test_missing_stopout_terms_or_forged_attestation_fail_closed():
    bad=[
        StopOutScenario(Decimal(100),Decimal(0),"test"),
        StopOutScenario(Decimal(50),Decimal(100),"test"),
        StopOutScenario(Decimal(100),Decimal(50),"test",True),
        StopOutScenario(Decimal(100),Decimal(50)," "),
    ]
    for scenario in bad:
        with pytest.raises(ValueError):
            simulate_path(["2650","2651","2652"],threshold=scenario)


def test_unobserved_quote_gaps_cannot_be_assumed_safe():
    with pytest.raises(ValueError,match="quote gap"):
        simulate_path(["2650","2651","2652"],step=3601)


def test_tampered_broker_source_refused():
    broker, original=profile()
    with pytest.raises(ValueError,match="source-matched"):
        replay_margin_path(
            broker,original+b"tampered",tape(["2650","2610","2900"]),
            TERMS,direction="long",lots="0.1",
            entry_signal_closed_at_utc=BASE,
            planned_exit_signal_closed_at_utc=BASE+timedelta(minutes=2),
            initial_cash_usd="500",
        )


def test_missing_funding_and_fees_cannot_be_zeroed_silently():
    broker,original=profile()
    broker=replace(broker,costs=replace(
        broker.costs,swap_long_usd_per_lot_per_rollover=None,
        swap_short_usd_per_lot_per_rollover=None,
        rollover_hhmm=None,triple_swap_weekday=None))
    with pytest.raises(ValueError):
        replay_margin_path(
            broker,original,tape(["2650","2651","2652"]),TERMS,
            direction="long",lots="0.1",
            entry_signal_closed_at_utc=BASE,
            planned_exit_signal_closed_at_utc=BASE+timedelta(minutes=2),
            initial_cash_usd="500",
        )


def test_risk_rejects_insufficient_initial_collateral():
    with pytest.raises(ValueError,match="insufficient broker margin"):
        simulate_path(["2650","2651","2652"],cash="10")


def test_untrusted_quote_source_mutation_is_blocked():
    broker,original=profile()
    original_tape=tape(["2650","2651","2652"])
    invalid=replace(original_tape,quotes=original_tape.quotes[:-1])
    with pytest.raises(ValueError,match="unaltered"):
        replay_margin_path(
            broker,original,invalid,TERMS,
            direction="long",lots="0.1",
            entry_signal_closed_at_utc=BASE,
            planned_exit_signal_closed_at_utc=BASE+timedelta(minutes=2),
            initial_cash_usd="500",
        )
