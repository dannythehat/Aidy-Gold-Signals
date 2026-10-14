"""Day12 executable bid/ask test vectors: never assume broker executable prices."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest

from aidy.strategy_lab_bidask_execution import (
    QuoteTape,
    SpreadScenario,
    research_round_trip,
)
from aidy.strategy_lab_broker_profile import BrokerProfile

ROOT = Path(__file__).parents[1] / "research" / "strategy_lab" / "fixtures"
QUOTE_FILE = ROOT / "day12_illustrative_bidask_quotes.json"
BROKER_FILE = ROOT / "day11_illustrative_broker_observation.json"
START = datetime(2026, 10, 14, 14, tzinfo=UTC)
END = START + timedelta(minutes=5)


def quote_snapshot() -> bytes:
    return QUOTE_FILE.read_bytes()


def quote_wire() -> dict:
    return json.loads(quote_snapshot())


def tape(raw: bytes | None = None) -> QuoteTape:
    original = quote_snapshot() if raw is None else raw
    return QuoteTape.from_snapshot(original, expected_sha256=sha256(original).hexdigest())


def broker_source() -> bytes:
    return BROKER_FILE.read_bytes()


def broker() -> BrokerProfile:
    original = broker_source()
    raw = json.loads(original)
    raw.pop("evidence_kind")
    raw.update({
        "schema_version": "aidy.broker_profile.v1",
        "profile_id": "synthetic_xauusd_standard", "revision": 1,
        "provenance": {
            "evidence_kind": "internal_fixture",
            "source_reference": str(BROKER_FILE.relative_to(Path(__file__).parents[1])),
            "source_sha256": sha256(original).hexdigest(),
            "captured_at_utc": "2026-10-14T14:10:00Z",
            "evidence_label": "illustrative_not_live",
        },
    })
    return BrokerProfile.from_wire(raw)


def run(direction="long", *, scenario=None, quotes=None, profile=None,
        broker_bytes=None, entry=START, exit_at=END, lots="0.1", max_lag=60):
    return research_round_trip(
        broker() if profile is None else profile,
        broker_source() if broker_bytes is None else broker_bytes,
        tape() if quotes is None else quotes,
        direction=direction, lots=lots,
        entry_signal_closed_at_utc=entry, exit_signal_closed_at_utc=exit_at,
        scenario=scenario, max_lag_seconds=max_lag,
    )


def test_long_independent_known_answer_exact_bid_ask():
    trade = run()
    assert trade.entry.transaction_side == "buy"
    assert trade.entry.fill_price == Decimal("2650.10")
    assert trade.entry.filled_at_utc == START + timedelta(seconds=1)
    assert trade.entry.quote_index == 1
    assert trade.exit.transaction_side == "sell"
    assert trade.exit.fill_price == Decimal("2651.00")
    assert trade.exit.filled_at_utc == END + timedelta(seconds=1)
    assert trade.exit.quote_index == 3
    assert trade.gross_quote_side_usd == Decimal("9.00")
    assert trade.gross_ticks == Decimal(90)
    assert trade.entry.observed_spread == Decimal("0.10")
    assert not trade.costs_included and not trade.real_broker_terms_qualified


def test_short_independent_known_answer_exact_bid_ask():
    trade = run("short")
    assert trade.entry.transaction_side == "sell"
    assert trade.entry.fill_price == Decimal("2650.00")
    assert trade.exit.transaction_side == "buy"
    assert trade.exit.fill_price == Decimal("2651.10")
    assert trade.gross_quote_side_usd == Decimal("-11.00")
    assert trade.gross_ticks == Decimal(-110)
    assert trade.entry.quote_index == 1 and trade.exit.quote_index == 3


def test_both_sides_reconcile_to_spread_paid_on_round_trip():
    long = run("long")
    short = run("short")
    # Identical mark-to-mid path, 0.10 cost at entry and at exit for
    # round-trip compared with friction-free mid: USD1 per side for 0.1 lots.
    assert long.gross_quote_side_usd + short.gross_quote_side_usd == Decimal("-2.00")
    assert long.entry.effective_ask - short.entry.effective_bid == Decimal("0.10")
    assert short.exit.effective_ask - long.exit.effective_bid == Decimal("0.10")


@pytest.mark.parametrize("direction,original,expected", [
    ("long", "9", "8.60"),
    ("short", "-11", "-11.40"),
])
def test_explicit_adverse_spread_stress_is_worse_for_both_directions(
    direction, original, expected
):
    baseline = run(direction)
    stressed = run(direction, scenario=SpreadScenario(extra_ticks_per_side=2))
    assert stressed.gross_quote_side_usd == Decimal(expected)
    assert baseline.gross_quote_side_usd == Decimal(original)
    assert stressed.entry.effective_spread == Decimal("0.14")
    assert stressed.entry.observed_spread == Decimal("0.10")
    assert stressed.scenario_extra_ticks_per_side == 2


def test_quote_snapshot_pinned_deterministic_replay():
    one = run("long")
    two = run("long")
    assert one.to_json() == two.to_json()
    assert one.observed_quote_snapshot_sha256 == sha256(quote_snapshot()).hexdigest()
    assert len(one.entry.broker_profile_sha256) == 64
    assert one.quote_source_class == "internal_fixture"
    assert one.broker_source_state == "ILLUSTRATIVE_SOURCE_MATCHED"
    assert json.loads(one.to_json())["real_broker_terms_qualified"] is False


def test_snapshot_rejects_wrong_digest_and_modified_data():
    raw = quote_snapshot()
    with pytest.raises(ValueError, match="SHA256"):
        QuoteTape.from_snapshot(raw + b" ", expected_sha256=sha256(raw).hexdigest())
    bad = tape()
    changed = replace(bad, snapshot_sha256="f" * 64)
    with pytest.raises(ValueError):
        run(quotes=changed)


def test_manual_forged_quote_tape_is_not_trusted():
    original = tape()
    modified_quote = replace(original.quotes[1], ask=Decimal(2660))
    forged = replace(original, quotes=(
        original.quotes[0], modified_quote, *original.quotes[2:]
    ))
    with pytest.raises(ValueError, match="pinned original"):
        run(quotes=forged)


def test_exact_close_time_quote_is_never_a_same_timestamp_fill():
    long = run()
    assert long.entry.filled_at_utc > START
    assert long.exit.filled_at_utc > END
    assert long.entry.base_bid == Decimal(2650)
    assert long.exit.base_bid == Decimal(2651)


@pytest.mark.parametrize("direction", ["LONG", "sell", "", "buy"])
def test_invalid_direction_fails(direction):
    with pytest.raises(ValueError):
        run(direction)


@pytest.mark.parametrize("lots", ["0", "0.015", "1000", "-1", "NaN", "1.001"])
def test_off_grid_quantity_fails(lots):
    with pytest.raises(ValueError):
        run(lots=lots)


@pytest.mark.parametrize("ticks", [-1, True, 1.5, 10001, "2"])
def test_noninteger_or_negative_spread_stress_fails(ticks):
    with pytest.raises(ValueError):
        run(scenario=SpreadScenario(ticks))


@pytest.mark.parametrize("bad_time", [
    datetime(2026, 10, 14, 14),
    START.replace(tzinfo=None),
    START + timedelta(minutes=6),
])
def test_invalid_or_future_entry_signal_fails(bad_time):
    with pytest.raises(ValueError):
        run(entry=bad_time)


def test_exit_signal_before_entry_or_before_fill_fails():
    with pytest.raises(ValueError):
        run(exit_at=START - timedelta(minutes=1))
    with pytest.raises(ValueError):
        run(exit_at=START)


def test_no_quote_after_signal_fails_closed():
    with pytest.raises(ValueError, match="no quote"):
        run(entry=END + timedelta(minutes=1))


def test_quote_stale_at_weekend_or_market_gap_fails():
    with pytest.raises(ValueError, match="stale"):
        run(entry=START + timedelta(seconds=2))


@pytest.mark.parametrize("lag", [0, -1, True, 301, "60", 60.0])
def test_invalid_quote_freshness_limit_fails(lag):
    with pytest.raises(ValueError):
        run(max_lag=lag)


def test_source_evidence_wrong_or_empty_fails_before_execution():
    with pytest.raises(ValueError, match="source-matched"):
        run(broker_bytes=b"made up")
    obj = broker()
    fake = replace(obj, provenance=replace(obj.provenance, source_sha256="a" * 64))
    with pytest.raises(ValueError):
        run(profile=fake)


@pytest.mark.parametrize(("key", "value"), [
    ("source_class", "anonymous_feed"),
    ("symbol", "EURUSD"),
    ("source_clock", "America/New_York"),
    ("source_archive_sha256", "fake"),
    ("source_identity", ""),
    ("schema_version", "v2"),
])
def test_source_scope_mismatch_rejects_file(key, value):
    raw = quote_wire()
    raw[key] = value
    original = json.dumps(raw).encode()
    with pytest.raises(ValueError):
        tape(original)


@pytest.mark.parametrize(("column", "value"), [
    ("bid", "0"), ("bid", "NaN"), ("ask", "-1"),
    ("bid", "2651.00"), ("ask", True),
    ("time_utc", "2026-10-14T14:00:01+03:00"),
    ("time_utc", "not a clock"),
])
def test_corrupt_or_crossed_quote_fails_closed(column, value):
    raw = quote_wire()
    raw["quotes"][1][column] = value
    with pytest.raises(ValueError):
        tape(json.dumps(raw).encode())


@pytest.mark.parametrize("kind", ["duplicate", "reverse", "empty", "extraneous"])
def test_bad_quote_order_or_shape_denied(kind):
    raw = quote_wire()
    if kind == "duplicate":
        raw["quotes"][2]["time_utc"] = raw["quotes"][1]["time_utc"]
    elif kind == "reverse":
        raw["quotes"][1], raw["quotes"][2] = raw["quotes"][2], raw["quotes"][1]
    elif kind == "empty":
        raw["quotes"] = []
    else:
        raw["quotes"][1]["mid"] = "2650.00"
    with pytest.raises(ValueError):
        tape(json.dumps(raw).encode())


def test_missing_ask_must_not_be_synthesized():
    raw = quote_wire()
    del raw["quotes"][1]["ask"]
    with pytest.raises(ValueError):
        tape(json.dumps(raw).encode())


def test_negative_stress_resulting_in_nonpositive_bid_denied():
    raw = quote_wire()
    for q in raw["quotes"]:
        q["bid"] = "0.01"
        q["ask"] = "0.02"
    with pytest.raises(ValueError, match="non-positive bid"):
        run(quotes=tape(json.dumps(raw).encode()),
            scenario=SpreadScenario(extra_ticks_per_side=2))


def test_duplicate_raw_json_keys_rejected():
    raw = quote_snapshot().replace(b'"symbol": "XAUUSD",',
                                   b'"symbol": "XAUUSD", "symbol": "XAGUSD",')
    with pytest.raises(ValueError, match="duplicate"):
        tape(raw)


def test_multiple_realistic_spread_regimes_and_no_made_up_spreads():
    raw = quote_wire()
    raw["quotes"][1]["ask"] = "2650.50"
    raw["quotes"][3]["ask"] = "2651.30"
    observed = tape(json.dumps(raw).encode())
    long = run(quotes=observed)
    short = run("short", quotes=observed)
    assert long.entry.fill_price == Decimal("2650.50")
    assert long.gross_quote_side_usd == Decimal("5.00")
    assert short.exit.fill_price == Decimal("2651.30")
    assert short.gross_quote_side_usd == Decimal("-13.00")
    assert long.entry.observed_spread == Decimal("0.50")
    assert short.exit.observed_spread == Decimal("0.30")


def test_internal_fixture_not_promoted_to_real_broker_results():
    trade = run("long")
    assert trade.quote_source_class == "internal_fixture"
    assert not trade.entry.derived_from_real_broker
    assert not trade.exit.derived_from_real_broker
    assert not trade.costs_included
    assert not trade.real_broker_terms_qualified
