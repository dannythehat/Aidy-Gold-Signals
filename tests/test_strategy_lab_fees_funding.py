"""Day13 independent XAUUSD cash leg tests using only source-matched internal fixtures."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest

from aidy.strategy_lab_bidask_execution import (
    QuoteTape, SpreadScenario, research_round_trip,
)
from aidy.strategy_lab_broker_profile import BrokerProfile
from aidy.strategy_lab_fees_funding import (
    _rollover_utc, apply_research_costs,
)

ROOT = Path(__file__).parents[1] / "research" / "strategy_lab" / "fixtures"
BROKER_PATH = ROOT / "day11_illustrative_broker_observation.json"
QUOTE_PATH = ROOT / "day12_illustrative_bidask_quotes.json"
START = datetime(2026, 10, 14, 14, tzinfo=UTC)


def broker():
    original = BROKER_PATH.read_bytes()
    data = json.loads(original)
    data.pop("evidence_kind")
    data.update({
        "schema_version": "aidy.broker_profile.v1",
        "profile_id": "synthetic_xauusd_standard", "revision": 1,
        "provenance": {
            "evidence_kind": "internal_fixture",
            "source_reference": str(BROKER_PATH),
            "source_sha256": sha256(original).hexdigest(),
            "captured_at_utc": "2026-10-14T14:10:00Z",
            "evidence_label": "illustrative_not_live",
        },
    })
    return BrokerProfile.from_wire(data), original


def tape(raw=None):
    raw = QUOTE_PATH.read_bytes() if raw is None else raw
    return QuoteTape.from_snapshot(raw, expected_sha256=sha256(raw).hexdigest())


def intraday(direction="long", lots="0.1", scenario=None):
    profile, source = broker()
    quotes = tape()
    trip = research_round_trip(
        profile, source, quotes, direction=direction, lots=lots,
        entry_signal_closed_at_utc=START,
        exit_signal_closed_at_utc=START + timedelta(minutes=5),
        scenario=scenario,
    )
    return apply_research_costs(profile, source, quotes, trip)


def overnight(direction="long", lots="0.1", *, start=None, end=None):
    # Server clock in this fixture: fixed UTC+02; rollover 22:00 local
    # = 20:00 UTC. Tue 13 Oct and Wed 14 Oct (3x) each incur funding.
    opened = start or datetime(2026, 10, 13, 19, 59, tzinfo=UTC)
    closed = end or datetime(2026, 10, 14, 20, 1, tzinfo=UTC)
    timestamps = (opened, opened + timedelta(seconds=1),
                  closed, closed + timedelta(seconds=1))
    quote_rows = [
        {"time_utc": t.isoformat().replace("+00:00", "Z"),
         "bid": "2650.00", "ask": "2650.10"}
        for t in timestamps
    ]
    frozen = {
        "schema_version": "aidy.quote_tape.v1",
        "source_class": "internal_fixture", "symbol": "XAUUSD",
        "source_clock": "UTC", "source_archive_sha256": "f" * 64,
        "source_identity": "day13_internal_rollover_fixture",
        "quotes": quote_rows,
    }
    raw = json.dumps(frozen, sort_keys=True, separators=(",", ":")).encode()
    quotes = tape(raw)
    profile, source = broker()
    trip = research_round_trip(
        profile, source, quotes, direction=direction, lots=lots,
        entry_signal_closed_at_utc=opened, exit_signal_closed_at_utc=closed,
    )
    return apply_research_costs(profile, source, quotes, trip)


def kinds(record):
    return [event.kind for event in record.events]


def test_intraday_long_known_answer():
    item = intraday()
    assert item.quote_gross_usd == Decimal("9.00")
    assert item.commission_usd == Decimal("-0.50")
    assert item.slippage_usd == Decimal("-0.20")
    assert item.funding_usd == 0
    assert item.net_usd == Decimal("8.30")
    assert len(item.events) == 4
    assert item.net_usd == item.quote_gross_usd + sum(
        (event.usd for event in item.events), Decimal(0)
    )


def test_intraday_short_known_answer():
    item = intraday("short")
    assert item.quote_gross_usd == Decimal("-11.00")
    assert item.commission_usd == Decimal("-0.50")
    assert item.slippage_usd == Decimal("-0.20")
    assert item.funding_usd == 0
    assert item.net_usd == Decimal("-11.70")
    assert item.broker_attested is False
    assert item.provider_calendar_qualified is False


@pytest.mark.parametrize("direction,expected", [("long", "7.90"), ("short", "-12.10")])
def test_spread_stress_is_never_charged_twice(direction, expected):
    item = intraday(direction, scenario=SpreadScenario(2))
    assert item.net_usd == Decimal(expected)
    assert item.slippage_usd == Decimal("-0.20")
    assert sum(x.kind == "slippage_scenario" for x in item.events) == 2


def test_rollover_and_triple_swap_long_wednesday():
    item = overnight()
    assert item.quote_gross_usd == Decimal("-1.00")
    assert item.commission_usd == Decimal("-0.50")
    assert item.slippage_usd == Decimal("-0.20")
    assert item.funding_usd == Decimal("-0.60")
    assert item.net_usd == Decimal("-2.30")
    swaps = [e for e in item.events if e.kind == "swap_debit"]
    assert len(swaps) == 2
    assert [e.multiplier for e in swaps] == [1, 3]
    assert [e.usd for e in swaps] == [Decimal("-0.15"), Decimal("-0.45")]
    assert [e.at_utc.weekday() for e in swaps] == [1, 2]
    assert all(e.at_utc.hour == 20 for e in swaps)


def test_rollover_and_triple_swap_short_credit():
    item = overnight("short")
    assert item.quote_gross_usd == Decimal("-1.00")
    assert item.funding_usd == Decimal("0.31")
    assert item.net_usd == Decimal("-1.39")
    swaps = [e for e in item.events if e.kind == "swap_credit"]
    assert [e.usd for e in swaps] == [Decimal("0.08"), Decimal("0.23")]


def test_individual_cash_legs_use_half_up_cent_rounding():
    item = intraday(lots="0.01")
    assert item.quote_gross_usd == Decimal("0.90")
    assert item.commission_usd == Decimal("-0.06")
    assert item.slippage_usd == Decimal("-0.02")
    assert item.net_usd == Decimal("0.82")
    assert [e.usd for e in item.events if e.kind == "commission"] == [
        Decimal("-0.03"), Decimal("-0.03"),
    ]


def test_deterministic_fingerprints_and_auditable_event_rows():
    a = intraday()
    b = intraday()
    assert a.to_json() == b.to_json()
    assert a.to_wire()["net_usd"] == "8.30"
    assert a.original_round_trip_sha256 and len(a.original_round_trip_sha256) == 64
    assert a.quote_snapshot_sha256 == sha256(QUOTE_PATH.read_bytes()).hexdigest()
    assert json.loads(a.to_json())["provider_calendar_qualified"] is False


def test_tampered_day12_fill_must_not_be_accepted():
    profile, source = broker()
    quotes = tape()
    trip = research_round_trip(
        profile, source, quotes, direction="long", lots="0.1",
        entry_signal_closed_at_utc=START,
        exit_signal_closed_at_utc=START + timedelta(minutes=5),
    )
    tampered = replace(trip, gross_quote_side_usd=Decimal("99999"))
    with pytest.raises(ValueError, match="replay"):
        apply_research_costs(profile, source, quotes, tampered)


def test_tampered_trade_flags_and_source_identity_denied():
    profile, source = broker()
    quotes = tape()
    trip = research_round_trip(
        profile, source, quotes, direction="long", lots="0.1",
        entry_signal_closed_at_utc=START,
        exit_signal_closed_at_utc=START + timedelta(minutes=5),
    )
    with pytest.raises(ValueError):
        apply_research_costs(profile, source, quotes, replace(trip, costs_included=True))
    with pytest.raises(ValueError):
        apply_research_costs(profile, b"altered", quotes, trip)
    with pytest.raises(ValueError):
        apply_research_costs(profile, source, tape(QUOTE_PATH.read_bytes()+b" "), trip)


def test_missing_cost_terms_are_blocked_not_guessed():
    profile, source = broker()
    missing = replace(profile, costs=replace(
        profile.costs, commission_usd_per_lot_per_side=None
    ))
    quotes = tape()
    with pytest.raises(ValueError):
        trip = research_round_trip(
            missing, source, quotes, direction="long", lots="0.1",
            entry_signal_closed_at_utc=START,
            exit_signal_closed_at_utc=START + timedelta(minutes=5),
        )
        apply_research_costs(missing, source, quotes, trip)


def test_source_clock_dst_ambiguous_or_skipped_fails_closed():
    profile, _ = broker()
    london = replace(profile, clock=replace(
        profile.clock, clock_model="iana_timezone", zone="Europe/London"
    ), costs=replace(profile.costs, rollover_hhmm="01:30"))
    with pytest.raises(ValueError, match="DST"):
        _rollover_utc(london, date(2026, 10, 25))
    with pytest.raises(ValueError, match="DST"):
        _rollover_utc(london, date(2026, 3, 29))


def test_rollover_exactly_equal_fill_refuses_order_guess():
    profile, source = broker()
    entry = datetime(2026, 10, 13, 19, 59, 59, tzinfo=UTC)
    exit_at = datetime(2026, 10, 13, 20, 2, tzinfo=UTC)
    quote_times = [datetime(2026, 10, 13, 20, tzinfo=UTC),
                   datetime(2026, 10, 13, 20, 2, 1, tzinfo=UTC)]
    data = {
        "schema_version": "aidy.quote_tape.v1",
        "source_class": "internal_fixture", "symbol": "XAUUSD",
        "source_clock": "UTC", "source_archive_sha256": "f" * 64,
        "source_identity": "exact_rollover_boundary",
        "quotes": [
            {"time_utc": t.isoformat().replace("+00:00", "Z"),
             "bid": "2650", "ask": "2650.1"}
            for t in quote_times
        ],
    }
    raw = json.dumps(data).encode()
    tape_obj = tape(raw)
    trip = research_round_trip(
        profile, source, tape_obj, direction="long", lots="0.1",
        entry_signal_closed_at_utc=entry, exit_signal_closed_at_utc=exit_at,
    )
    with pytest.raises(ValueError, match="coincides"):
        apply_research_costs(profile, source, tape_obj, trip)


def test_held_above_thirty_one_days_fails_closed():
    profile, _ = broker()
    from aidy.strategy_lab_fees_funding import _funding_events
    with pytest.raises(ValueError, match="31 days"):
        _funding_events(profile, START, START + timedelta(days=32),
                        "long", Decimal("0.1"))
