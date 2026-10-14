"""Day20 genuine written-source intake and independent closed-EMA signal parity.

This fixtures a synthetic machine-review declaration. The fixture is NOT the
user's personal sign-off, not a claim of provider/source-platform parity.
"""
from __future__ import annotations

import json
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest

from aidy.strategy_lab_written_rule_intake import (
    admit_written_rules,
    read_supported_written_rules,
    strategy_spec_signal_indices,
    written_source_signal_indices,
)

ROOT = Path(__file__).parents[1] / "research" / "strategy_lab" / "fixtures"
SOURCE = ROOT / "day09_internal_source_rules.txt"
TEMPLATE = ROOT / "strategy_spec_v1_sample.json"
PRICE_SOURCE = ROOT / "day20_closed_ema_parity_prices.json"


def original_source() -> bytes:
    return SOURCE.read_bytes()


def review_wire(source: bytes | None = None) -> dict:
    data = json.loads(TEMPLATE.read_text())
    source = original_source() if source is None else source
    digest = sha256(source).hexdigest()
    source_ref = "research/strategy_lab/fixtures/day09_internal_source_rules.txt"
    data["origin"]["source_sha256"] = digest
    data["origin"]["source_snapshot_ref"] = source_ref
    data["origin"]["interpretation_notes"] = [
        "SYNTHETIC test-only review example, not owner or third-party approval",
    ]
    return {
        "schema_version": "aidy.written_rule_review.v1",
        "reviewer": "SYNTHETIC_TEST_REVIEWER_NOT_OWNER_APPROVAL",
        "confirmed_at_utc": "2026-10-14T12:00:00Z",
        "source_snapshot_ref": source_ref,
        "source_sha256": digest,
        "approved_spec": data,
    }


def admission(review: dict | None = None, original: bytes | None = None):
    original = original_source() if original is None else original
    review = review_wire(original) if review is None else review
    return admit_written_rules(
        original, json.dumps(review, sort_keys=True, separators=(",", ":")).encode()
    )


def close_prices() -> tuple[Decimal, ...]:
    raw = json.loads(PRICE_SOURCE.read_text())
    assert raw["schema_version"] == "aidy.closed_close_price_fixture.v1"
    assert raw["source_class"] == "internal_synthetic_not_broker_quotes"
    assert raw["timeframe"] == "M5"
    return tuple(Decimal(p) for p in raw["closed_prices"])


def test_source_exactly_parsed_with_explicit_all_values():
    parsed = read_supported_written_rules(original_source())
    assert parsed["fast_period"] == 10
    assert parsed["slow_period"] == 30
    assert parsed["warmup_closed_bars"] == 50
    assert parsed["session_start"] == "07:00"
    assert parsed["session_end"] == "21:00"
    assert parsed["stop_ticks"] == 120
    assert parsed["target_ticks"] == 240
    assert parsed["hold_bars"] == 48
    assert parsed["risk_percent"] == 1
    assert parsed["max_total_risk_percent"] == 2


def test_full_human_review_shape_source_sha_and_spec_rule_admission():
    result = admission()
    assert result.ready_for_later_reproduction
    assert not result.source_platform_parity_verified
    assert len(result.spec_sha256) == 64
    assert len(result.review_sha256) == 64
    assert result.source_sha256 == sha256(original_source()).hexdigest()
    assert result.spec.origin.source_snapshot_ref == (
        "research/strategy_lab/fixtures/day09_internal_source_rules.txt"
    )
    assert json.loads(result.to_json())["source_platform_parity_verified"] is False


def test_independent_closed_price_series_signals_equal_original_source():
    result = admission()
    prices = close_prices()
    written = written_source_signal_indices(original_source(), prices)
    candidate = strategy_spec_signal_indices(result.spec, prices)
    assert len(prices) == 160
    assert written == candidate
    assert len(written) == 2
    assert all(index >= 49 for index in written)
    # Strict cross: never signal on the first candle of the confirmed warmup.
    assert 49 not in written


def test_non_crossing_flat_market_emits_no_signals():
    flat = tuple(Decimal(2650) for _ in range(90))
    assert written_source_signal_indices(original_source(), flat) == ()
    assert strategy_spec_signal_indices(admission().spec, flat) == ()


def test_signal_parity_deterministic_across_repeated_runs():
    a = admission()
    b = admission()
    assert a.to_json() == b.to_json()
    assert written_source_signal_indices(original_source(), close_prices()) == (
        written_source_signal_indices(original_source(), close_prices())
    )


@pytest.mark.parametrize(("path", "bad"), [
    (("market", "source_clock"), "UTC"),
    (("market", "price_basis"), "ask"),
    (("market", "signal_timeframe"), "H1"),
    (("warmup_closed_bars",), 60),
    (("indicators", 0, "period"), 12),
    (("indicators", 1, "price_field"), "high"),
    (("long", "entry", "predicates", 0, "operator"), "cross_below"),
    (("long", "exit", "stop_loss", "value"), "140"),
    (("long", "exit", "take_profit", "value"), "300"),
    (("long", "exit", "maximum_holding_bars"), 20),
    (("sessions", "allowed", 0, "end_hhmm"), "20:00"),
    (("sessions", "excluded_dates"), ["2026-10-14"]),
    (("sizing", "risk_percent_equity"), "1.5"),
    (("portfolio", "max_total_risk_percent"), "3"),
    (("portfolio", "allow_pyramiding"), True),
    (("execution", "entry_execution"), "signal_close"),
])
def test_review_cannot_change_explicit_written_rule(path, bad):
    review = review_wire()
    cursor = review["approved_spec"]
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = bad
    with pytest.raises(ValueError):
        admission(review)


@pytest.mark.parametrize(("field", "bad"), [
    ("reviewer", ""),
    ("confirmed_at_utc", "2026-10-14T12:00:00"),
    ("source_sha256", "f" * 64),
    ("source_snapshot_ref", ""),
    ("schema_version", "aidy.fake_review.v2"),
])
def test_missing_wrong_confirmation_rejected(field, bad):
    review = review_wire()
    review[field] = bad
    with pytest.raises(ValueError):
        admission(review)


def test_review_original_source_spec_reference_mismatch_denied():
    r = review_wire()
    r["approved_spec"]["origin"]["source_snapshot_ref"] = "other.txt"
    with pytest.raises(ValueError, match="not bound"):
        admission(r)


@pytest.mark.parametrize("extra", [
    "\nAlso enter shorts when RSI(14)>70.\n",
    "\nMove stop to breakeven at +40 ticks.\n",
    "\nEnter early based on unfinished M5 candles.\n",
    "\nIgnore all Thursday signals.\n",
])
def test_unsupported_extra_prose_rejected_not_silently_ignored(extra):
    with pytest.raises(ValueError, match="UNSUPPORTED_WRITTEN_RULES"):
        admission(original=original_source() + extra.encode())


def test_ema_reference_contradiction_in_written_text_rejected():
    original = original_source().replace(
        b"EMA(10) crosses above EMA(30)",
        b"EMA(12) crosses above EMA(30)",
    )
    with pytest.raises(ValueError, match="contradiction"):
        admission(original=original)


def test_review_must_follow_revised_writing_and_source_hash():
    original = original_source().replace(b"EMA(10)", b"EMA(12)")
    with pytest.raises(ValueError):
        admission(original=original)
    updated = review_wire(original)
    updated["approved_spec"]["indicators"][0]["period"] = 12
    parsed = admission(updated, original)
    assert parsed.parsed_rules["fast_period"] == 12
    assert parsed.spec.indicators[0].period == 12
    assert written_source_signal_indices(original, close_prices()) == (
        strategy_spec_signal_indices(parsed.spec, close_prices())
    )


def test_duplicate_confirmation_keys_rejected_without_parsing_override():
    review = json.dumps(review_wire(), separators=(",", ":")).encode()
    bogus = b'{"schema_version":"aidy.written_rule_review.v1","schema_version":"fake",'
    with pytest.raises(ValueError, match="duplicate"):
        admit_written_rules(original_source(), bogus + review[1:])


def test_broken_source_sha_must_fail_before_signal_production():
    corrupted = original_source().replace(b"120 broker-defined ticks", b"121 broker-defined ticks")
    with pytest.raises(ValueError, match="SHA|source"):
        admission(review_wire(), corrupted)


def test_unreviewed_source_file_or_unreviewed_spec_cannot_be_admitted():
    with pytest.raises(ValueError):
        admit_written_rules(original_source(), b"")
    r=review_wire()
    r["approved_spec"]["origin"]["unresolved_questions"] = ["What is the EMA seed?"]
    with pytest.raises(ValueError):
        admission(r)


def test_source_is_data_not_executed_even_when_it_contains_code():
    hacked = original_source() + b"\n__import__('os').system('echo unsafe')\n"
    with pytest.raises(ValueError, match="UNSUPPORTED_WRITTEN_RULES"):
        read_supported_written_rules(hacked)
