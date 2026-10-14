"""Day11 golden tests: exact broker contract maths, source binding and clock safety.

All prices/fees/volumes are labelled SYNTHETIC, never Vantage terms.
"""
from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest

from aidy.strategy_lab_broker_profile import (
    BrokerProfile,
    clock_server_time,
    qualify_broker_profile,
)

FIXTURE = (Path(__file__).parents[1] / "research" / "strategy_lab"
           / "fixtures" / "day11_illustrative_broker_observation.json")


def observation():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def source():
    return FIXTURE.read_bytes()


def example():
    doc = observation()
    doc.pop("evidence_kind")
    doc.update({
        "schema_version": "aidy.broker_profile.v1",
        "profile_id": "synthetic_xauusd_standard",
        "revision": 1,
        "provenance": {
            "evidence_kind": "internal_fixture",
            "source_reference": "research/strategy_lab/fixtures/day11_illustrative_broker_observation.json",
            "source_sha256": sha256(source()).hexdigest(),
            "captured_at_utc": "2026-10-14T14:10:00Z",
            "evidence_label": "illustrative_not_live",
        },
    })
    return doc


def profile():
    return BrokerProfile.from_wire(example())


def modify(path, value):
    data = copy.deepcopy(example())
    current = data
    for part in path[:-1]:
        current = current[part]
    current[path[-1]] = value
    return data


def test_schema_and_source_exact_canonical_roundtrip():
    wire = example()
    obj = BrokerProfile.from_wire(wire)
    assert obj.to_wire() == wire
    assert BrokerProfile.from_json(obj.to_json()) == obj
    assert BrokerProfile.from_json(obj.to_json()).to_json() == obj.to_json()
    assert len(sha256(obj.to_json().encode()).hexdigest()) == 64


def test_exact_100_ounce_contract_and_reference_values():
    obj = profile()
    assert obj.contract.contract_ounces_per_lot == Decimal(100)
    assert obj.contract.tick_size == Decimal("0.01")
    assert obj.contract.tick_value_profit_currency_per_lot == Decimal("1.00")
    assert obj.usd_per_tick("1.00") == Decimal("1.00")
    assert obj.usd_per_tick("0.1") == Decimal("0.100")
    assert obj.initial_margin_usd("2650.00", "0.1") == Decimal("265.000")
    assert obj.initial_margin_usd("2650.00", "1") == Decimal("2650.00")
    assert obj.costs.commission_usd_per_lot_per_side == Decimal("2.50")
    assert obj.costs.swap_long_usd_per_lot_per_rollover == Decimal("-1.50")


def test_fixture_evidence_and_source_are_matched_but_not_broker_attested():
    outcome = qualify_broker_profile(profile(), source())
    assert outcome.state == "ILLUSTRATIVE_SOURCE_MATCHED"
    assert outcome.evidence_sha256 == sha256(source()).hexdigest()
    assert outcome.evidence_fields_matched
    assert not outcome.real_broker_terms_qualified
    assert not outcome.issues
    assert json.loads(outcome.to_json())["real_broker_terms_qualified"] is False


@pytest.mark.parametrize("value", ["0.01", "0.02", "0.03", "1", "99.99", "100.00"])
def test_lot_grid_accepts_valid_quantities(value):
    assert profile().is_valid_lot(value)


@pytest.mark.parametrize("value", [
    "0", "-1", "0.001", "0.015", "100.01", "1000", "NaN",
    "Infinity", True, 0.01, None,
])
def test_lot_grid_rejects_invalid_quantities(value):
    obj = profile()
    assert not obj.is_valid_lot(value)
    with pytest.raises(ValueError):
        obj.usd_per_tick(value)
    with pytest.raises(ValueError):
        obj.initial_margin_usd("2650", value)


@pytest.mark.parametrize(("path", "value"), [
    (("schema_version",), "aidy.broker_profile.v999"),
    (("profile_id",), "Vantage!"),
    (("revision",), 0),
    (("revision",), True),
    (("broker_id",), ""),
    (("account_currency",), "EUR"),
    (("contract", "symbol"), "XAGUSD"),
    (("contract", "profit_currency"), "EUR"),
    (("contract", "margin_currency"), "EUR"),
    (("contract", "quote_currency"), "GBP"),
    (("contract", "contract_ounces_per_lot"), "0"),
    (("contract", "contract_ounces_per_lot"), float("inf")),
    (("contract", "tick_size"), "0"),
    (("contract", "tick_size"), "0.013"),
    (("contract", "point_size"), "0.003"),
    (("contract", "price_digits"), -1),
    (("contract", "price_digits"), True),
    (("contract", "tick_value_profit_currency_per_lot"), "0.99"),
    (("contract", "volume_min_lots"), "0"),
    (("contract", "volume_max_lots"), "0.009"),
    (("contract", "volume_step_lots"), "0.012"),
    (("contract", "stops_level_ticks"), -1),
    (("contract", "freeze_level_ticks"), True),
    (("margin", "calculation"), "net_notional_unknown"),
    (("margin", "leverage_ratio"), "0"),
    (("margin", "leverage_ratio"), "10001"),
    (("costs", "commission_usd_per_lot_per_side"), "-1"),
    (("costs", "commission_usd_per_lot_per_side"), 2.5),
    (("costs", "swap_long_usd_per_lot_per_rollover"), "NaN"),
    (("costs", "triple_swap_weekday"), 7),
    (("costs", "rollover_hhmm"), "24:00"),
    (("costs", "slippage_scenario_ticks"), "-0.1"),
    (("clock", "clock_model"), "guess_dst"),
    (("clock", "zone"), "UTC+15:00"),
    (("clock", "observed_utc"), "2026-10-14T14:00:00"),
    (("clock", "observed_server_hhmm"), "17:00"),
    (("provenance", "evidence_kind"), "unsigned_spread_sheet"),
    (("provenance", "source_sha256"), "123"),
    (("provenance", "source_reference"), ""),
    (("provenance", "captured_at_utc"), "2026-10-14T13:00:00Z"),
    (("provenance", "evidence_label"), "live_data"),
])
def test_unqualified_contract_or_clock_rejected(path, value):
    with pytest.raises(ValueError):
        BrokerProfile.from_wire(modify(path, value))


@pytest.mark.parametrize(("path", "value"), [
    (("costs", "swap_long_usd_per_lot_per_rollover"), None),
    (("costs", "swap_short_usd_per_lot_per_rollover"), None),
    (("costs", "triple_swap_weekday"), None),
    (("costs", "rollover_hhmm"), None),
])
def test_partial_swap_bundle_cannot_hide_unknown_costs(path, value):
    with pytest.raises(ValueError):
        BrokerProfile.from_wire(modify(path, value))


def test_all_swap_terms_unknown_are_explicit_but_not_cost_complete():
    obj = example()
    for key in ("swap_long_usd_per_lot_per_rollover",
                "swap_short_usd_per_lot_per_rollover",
                "triple_swap_weekday", "rollover_hhmm"):
        obj["costs"][key] = None
    parsed = BrokerProfile.from_wire(obj)
    result = qualify_broker_profile(parsed, source())
    assert result.state == "BLOCKED"
    assert "COST_TERMS_INCOMPLETE" in result.issues


def test_source_bytes_missing_or_wrong_are_blocked():
    obj = profile()
    for raw, expected in ((None, "SOURCE_BYTES_MISSING"),
                          (b"bogus", "SOURCE_SHA_MISMATCH"),
                          (b"", "SOURCE_BYTES_MISSING")):
        result = qualify_broker_profile(obj, raw)
        assert result.state == "BLOCKED"
        assert expected in result.issues
        assert not result.real_broker_terms_qualified


def test_relabelled_contract_with_same_evidence_is_blocked():
    obj = example()
    obj["costs"]["commission_usd_per_lot_per_side"] = "3"
    candidate = BrokerProfile.from_wire(obj)
    result = qualify_broker_profile(candidate, source())
    assert "SOURCE_FIELDS_MISMATCH" in result.issues


def test_changed_fee_and_modified_source_digest_change_identity():
    base = profile()
    changed = observation()
    changed["costs"]["commission_usd_per_lot_per_side"] = "3"
    altered = json.dumps(changed, indent=2).encode()
    spec = example()
    spec["costs"]["commission_usd_per_lot_per_side"] = "3"
    spec["provenance"]["source_sha256"] = sha256(altered).hexdigest()
    candidate = BrokerProfile.from_wire(spec)
    q = qualify_broker_profile(candidate, altered)
    assert q.state == "ILLUSTRATIVE_SOURCE_MATCHED"
    assert q.profile_sha256 != qualify_broker_profile(base, source()).profile_sha256


def test_spoofed_terminal_export_is_never_real_broker_qualified():
    obj = example()
    obj["provenance"]["evidence_kind"] = "broker_terminal_export"
    candidate = BrokerProfile.from_wire(obj)
    bad = qualify_broker_profile(candidate, source())
    assert "SOURCE_KIND_MISMATCH" in bad.issues
    payload = observation()
    payload["evidence_kind"] = "broker_terminal_export"
    new_bytes = json.dumps(payload, indent=2).encode()
    obj["provenance"]["source_sha256"] = sha256(new_bytes).hexdigest()
    candidate = BrokerProfile.from_wire(obj)
    matched = qualify_broker_profile(candidate, new_bytes)
    assert matched.state == "BROKER_EVIDENCE_MATCHED_UNATTESTED"
    assert not matched.real_broker_terms_qualified


def test_direct_bad_dataclass_cannot_bypass_strict_validator():
    invalid = replace(profile(), account_currency="EUR")
    assert qualify_broker_profile(invalid, source()).state == "BLOCKED"


def test_forged_source_json_or_missing_original_field_denied():
    obj = profile()
    for bogus in (b"{}", b"not JSON", json.dumps({"evidence_kind": 42}).encode()):
        matching = replace(obj, provenance=replace(obj.provenance,
                           source_sha256=sha256(bogus).hexdigest()))
        assert qualify_broker_profile(matching, bogus).state == "BLOCKED"


def test_unsupported_precision_and_price_rejected_before_margin_math():
    with pytest.raises(ValueError):
        profile().initial_margin_usd("NaN", "1")
    with pytest.raises(ValueError):
        profile().initial_margin_usd(-2, "1")
    with pytest.raises(ValueError):
        profile().initial_margin_usd(1.1, "1")


def test_server_clock_fixed_offset_from_real_utc_instant():
    obj = profile()
    dt = datetime(2026, 10, 14, 14, 0, tzinfo=UTC)
    assert clock_server_time(obj.clock, dt).strftime("%Y-%m-%d %H:%M") == "2026-10-14 16:00"
    with pytest.raises(ValueError):
        clock_server_time(obj.clock, datetime(2026, 10, 14, 14))


def test_iana_clock_can_handle_dst_but_is_not_inferred_from_vantage():
    data = example()
    data["clock"]["clock_model"] = "iana_timezone"
    data["clock"]["zone"] = "Europe/London"
    data["clock"]["observed_server_hhmm"] = "15:00"
    london = BrokerProfile.from_wire(data)
    assert clock_server_time(london.clock, datetime(2026, 1, 14, 12, tzinfo=UTC)).hour == 12
    assert clock_server_time(london.clock, datetime(2026, 7, 14, 12, tzinfo=UTC)).hour == 13
    assert not qualify_broker_profile(london, source()).evidence_fields_matched


def test_extra_or_missing_key_and_duplicate_json_keys_denied():
    data = example()
    data["unknown_execution_rule"] = "call MT5"
    with pytest.raises(ValueError):
        BrokerProfile.from_wire(data)
    data = example()
    del data["contract"]["tick_size"]
    with pytest.raises(ValueError):
        BrokerProfile.from_wire(data)
    text = profile().to_json().replace('"revision":1,', '"revision":1,"revision":2,')
    with pytest.raises(ValueError, match="duplicate"):
        BrokerProfile.from_json(text)
