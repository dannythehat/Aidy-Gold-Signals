"""Day09 real parser admission tests; internal source is deliberately illustrative."""
import copy
import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from aidy.strategy_lab_rule_validator import assess_rule_completeness
from aidy.strategy_lab_spec import StrategySpec

ROOT = Path(__file__).parents[1] / "research" / "strategy_lab" / "fixtures"
ORIGINAL = (ROOT / "day09_internal_source_rules.txt").read_bytes()
SOURCE_REF = "research/strategy_lab/fixtures/day09_internal_source_rules.txt"


def complete_wire():
    data = json.loads((ROOT / "strategy_spec_v1_sample.json").read_text())
    data["origin"]["source_snapshot_ref"] = SOURCE_REF
    data["origin"]["source_sha256"] = sha256(ORIGINAL).hexdigest()
    return data


def evaluate(data, source=ORIGINAL):
    return assess_rule_completeness(StrategySpec.from_wire(data), source_snapshot=source)


def issue_codes(result):
    return {issue.code for issue in result.issues}


def test_real_source_file_and_rule_complete_positive():
    result = evaluate(complete_wire())
    assert result.state == "RULES_COMPLETE_SOURCE_MATCHED", result.issues
    assert result.ready_for_later_reproduction
    assert result.source_sha256_verified
    assert len(result.spec_sha256) == 64
    assert result.issues == ()
    assert json.loads(result.to_json())["state"] == result.state


def test_same_spec_and_source_produce_identical_assessment():
    a = evaluate(complete_wire())
    b = evaluate(complete_wire())
    assert a.to_json() == b.to_json()
    assert a.spec_sha256 == b.spec_sha256


def test_day08_illustrative_fixture_must_not_claim_original_source_provenance():
    raw = json.loads((ROOT / "strategy_spec_v1_sample.json").read_text())
    result = evaluate(raw)
    assert not result.ready_for_later_reproduction
    assert "NO_SOURCE_SNAPSHOT_REFERENCE" in issue_codes(result)
    assert "SOURCE_HASH_MISMATCH" in issue_codes(result)


@pytest.mark.parametrize(("kind", "source", "expected"), [
    ("missing", None, "SOURCE_BYTES_NOT_CHECKED"),
    ("mismatch", b"not the pinned original", "SOURCE_HASH_MISMATCH"),
    ("empty", b"", "SOURCE_BYTES_INVALID"),
])
def test_source_bytes_are_mandatory_and_bound_to_sha(kind, source, expected):
    result = evaluate(complete_wire(), source)
    assert kind and result.state == "BLOCKED"
    assert expected in issue_codes(result)


@pytest.mark.parametrize(("mutator", "expected"), [
    (lambda d: d["origin"].update(unresolved_questions=["When does a session start?"]),
     "UNRESOLVED_INTERPRETATION"),
    (lambda d: d.update(candidate_type="partial_indicator"), "INCOMPLETE_CANDIDATE"),
    (lambda d: d["market"].update(price_basis="ask"), "UNQUALIFIED_DATA_CONTRACT"),
    (lambda d: d["market"].update(data_source="unknown"), "UNQUALIFIED_DATA_CONTRACT"),
    (lambda d: d["market"].update(signal_timeframe="D1"), "D1_SESSION_UNQUALIFIED"),
    (lambda d: d["long"]["exit"].update(stop_loss=None), "MISSING_PROTECTIVE_STOP"),
    (lambda d: d["long"]["exit"].update(
        take_profit=None, maximum_holding_bars=None, close_on_session_end=False),
     "MISSING_EXIT_POLICY"),
    (lambda d: d["long"]["exit"].update(close_on_opposite_signal=True), "IMPOSSIBLE_OPPOSITE_EXIT"),
    (lambda d: d["long"]["exit"].update(close_on_session_end=False), "SESSION_FLAT_CONTRADICTION"),
    (lambda d: d["long"]["exit"].update(
        trailing_stop={"mode": "ticks", "value": "40", "indicator_id": None}),
     "EXIT_PRIORITY_UNDEFINED"),
    (lambda d: d["long"]["exit"].update(partial_exits=[
        {"fraction_percent": "50", "target":
            {"mode": "ticks", "value": "50", "indicator_id": None}}]),
     "EXIT_PRIORITY_UNDEFINED"),
    (lambda d: d["indicators"][0].update(timeframe="H1"), "HTF_AVAILABILITY_UNQUALIFIED"),
    (lambda d: d["indicators"][0].update(
        additional_parameters={"smoothing": "2"}), "INDICATOR_PARAMETERS_UNSUPPORTED"),
    (lambda d: d["indicators"][0].update(kind="RSI"), "INDICATOR_SEMANTICS_UNRESOLVED"),
    (lambda d: d.update(warmup_closed_bars=20), "INSUFFICIENT_WARMUP"),
    (lambda d: d["portfolio"].update(max_positions=2), "POSITION_POLICY_NOT_FROZEN"),
    (lambda d: d["portfolio"].update(allow_hedging=True), "POSITION_POLICY_NOT_FROZEN"),
    (lambda d: d["portfolio"].update(max_total_risk_percent="0.5"),
     "RISK_LIMIT_CONTRADICTION"),
    (lambda d: d["sessions"].update(allowed=[]), "NO_SESSION_WINDOWS"),
    (lambda d: d["sessions"]["allowed"][0].update(
        start_hhmm="21:00", end_hhmm="07:00"), "OVERNIGHT_SESSION_AMBIGUOUS"),
    (lambda d: d["sessions"]["allowed"].append({
        "weekday": 0, "start_hhmm": "08:00", "end_hhmm": "10:00"}),
     "OVERLAPPING_SESSIONS"),
    (lambda d: d["long"]["entry"]["predicates"].append(
        copy.deepcopy(d["long"]["entry"]["predicates"][0])), "DUPLICATE_PREDICATE"),
    (lambda d: d["long"]["entry"]["predicates"][0].update(
        right=copy.deepcopy(d["long"]["entry"]["predicates"][0]["left"])),
     "SELF_COMPARISON"),
    (lambda d: d["long"]["entry"]["predicates"][0].update(
        right={"kind": "constant", "reference": "2650", "field": "value",
               "offset_closed_bars": 0}), "CROSS_SEMANTICS_UNQUALIFIED"),
    (lambda d: d["long"]["entry"].update(
        enabled=False, predicates=[]), "NO_ENABLED_ENTRIES"),
])
def test_ambiguous_or_incomplete_rule_is_blocked(mutator, expected):
    data = complete_wire()
    mutator(data)
    result = evaluate(data)
    assert result.state == "BLOCKED"
    assert not result.ready_for_later_reproduction
    assert expected in issue_codes(result), result.issues


def test_two_sides_enter_at_identical_time_without_conflict_resolution():
    data = complete_wire()
    data["short"] = copy.deepcopy(data["long"])
    result = evaluate(data)
    assert "SIMULTANEOUS_LONG_SHORT" in issue_codes(result)


def test_impossible_same_price_numeric_bounds_are_rejected():
    data = complete_wire()
    lhs = {"kind": "price", "reference": "XAUUSD", "field": "close",
           "offset_closed_bars": 0}
    data["long"]["entry"]["predicates"] = [
        {"left": lhs, "operator": op,
         "right": {"kind": "constant", "reference": number, "field": "value",
                   "offset_closed_bars": 0}}
        for op, number in (("gt", "2700"), ("lt", "2600"))
    ]
    result = evaluate(data)
    assert "IMPOSSIBLE_PRICE_BOUNDS" in issue_codes(result)


def test_strict_boundary_rejects_equality_at_open_bound():
    data = complete_wire()
    lhs = {"kind": "price", "reference": "XAUUSD", "field": "close",
           "offset_closed_bars": 0}
    data["long"]["entry"]["predicates"] = [
        {"left": lhs, "operator": op,
         "right": {"kind": "constant", "reference": "2700", "field": "value",
                   "offset_closed_bars": 0}}
        for op in ("gt", "lte")
    ]
    assert "IMPOSSIBLE_PRICE_BOUNDS" in issue_codes(evaluate(data))


def test_noncontradictory_bounds_may_pass():
    data = complete_wire()
    lhs = {"kind": "price", "reference": "XAUUSD", "field": "close",
           "offset_closed_bars": 0}
    data["long"]["entry"]["predicates"] = [
        {"left": lhs, "operator": op,
         "right": {"kind": "constant", "reference": number, "field": "value",
                   "offset_closed_bars": 0}}
        for op, number in (("gt", "2600"), ("lt", "2700"))
    ]
    assert evaluate(data).state == "RULES_COMPLETE_SOURCE_MATCHED"


def test_unvalidated_dataclass_construction_cannot_bypass_parser():
    parsed = StrategySpec.from_wire(complete_wire())
    illegal = replace(parsed, warmup_closed_bars=-99)
    result = assess_rule_completeness(illegal, source_snapshot=ORIGINAL)
    assert result.state == "BLOCKED"
    assert "SCHEMA_INVALID" in issue_codes(result)


def test_no_future_bar_offsets_can_be_parsed():
    data = complete_wire()
    data["long"]["entry"]["predicates"][0]["left"]["offset_closed_bars"] = -1
    with pytest.raises(ValueError):
        StrategySpec.from_wire(data)


def test_blocker_record_is_deterministically_sorted_and_contains_no_returns():
    data = complete_wire()
    data["origin"]["unresolved_questions"] = ["Unknown fee behaviour"]
    data["long"]["exit"]["stop_loss"] = None
    first = evaluate(data)
    second = evaluate(data)
    assert first.to_json() == second.to_json()
    assert sorted(first.issues) == list(first.issues)
    assert "profit" not in first.to_json()
    assert "verified_returns" not in first.to_json()
