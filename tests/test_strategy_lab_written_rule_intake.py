"""Day20 proof of explicit original-text bindings and independent closed-signal parity.

All cases are internally authored and are never external-platform parity.
"""
from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest

from aidy.strategy_lab_written_rule_intake import (
    RULE_BINDINGS,
    ClosedIndicatorSample,
    evaluate_closed_indicator_cross,
    intake_written_rules,
)

ROOT = Path(__file__).resolve().parents[1] / "research" / "strategy_lab" / "fixtures"
SOURCE_PATH = ROOT / "day20_internal_written_rules.txt"
SPEC_PATH = ROOT / "strategy_spec_v1_sample.json"
REF_PATH = "research/strategy_lab/fixtures/day20_internal_written_rules.txt"

EXCERPTS = {
    "identity": 'Strategy ID sample_ema_cross, revision 1. Candidate is a complete mechanical\n'
                'strategy, titled "Illustrative EMA(10/30) closed-bar crossover".',
    "origin": "The author is AIDY Strategy Lab illustrative fixture — not a third-party result.\n"
              "License: internal_fixture_only. No performance has been claimed.",
    "market": "Symbol XAUUSD. Use HistData Generic ASCII native M1 bid OHLC, in the\n"
              "fixed EST UTC-05 source clock, resampled to signal timeframe M5.",
    "warmup": "Require 50 fully closed M5 candles of warm-up.",
    "indicators": "EMA fast (10) and EMA slow (30) on M5 close, no additional indicator parameters.",
    "long_entry": "Long signal is enabled. Combine all long predicates (ALL). A long entry occurs\n"
                  "only when EMA(10) crosses above EMA(30): previous fast EMA <= previous slow EMA,\n"
                  "AND the current closed fast EMA > current closed slow EMA. Exactly one entry\n"
                  "predicate.",
    "long_stop": "Long protective stop is 120 broker-defined ticks from the entry.",
    "long_target": "Long take-profit is 240 broker-defined ticks from the entry.",
    "long_hold": "Maximum long holding period is 48 fully closed M5 bars.",
    "long_session_exit": "Exit at session end.",
    "long_opposite_exit": "Do NOT exit on an opposite signal.",
    "long_trailing": "NO trailing stop.",
    "long_partials": "NO partial exits.",
    "short_side": "No short entries; the short side is disabled and has no exits.",
    "sessions": "Allowed sessions: Monday, Tuesday, Wednesday, Thursday, Friday;\n"
                "all five days 07:00 inclusive to 21:00 exclusive UTC, with no excluded dates.\n"
                "Stay flat outside sessions. Sessions timezone is UTC.",
    "sizing": "Risk sizing is 1 percent of equity at the initial protective stop.",
    "portfolio": "Maximum one position; no hedging; no pyramiding. Total portfolio risk cap 2 percent.",
    "execution": "All signals are evaluated only on closed bars. Enter on the NEXT tradable quote",
}


def _get_pointer(data, pointer):
    obj = data
    for part in pointer.strip("/").split("/"):
        obj = obj[int(part)] if isinstance(obj, list) else obj[part]
    return obj


def inputs():
    source = SOURCE_PATH.read_bytes()
    spec = json.loads(SPEC_PATH.read_text())
    spec["origin"]["source_sha256"] = sha256(source).hexdigest()
    spec["origin"]["source_snapshot_ref"] = REF_PATH
    evidence = {
        group: {
            "source_excerpt": EXCERPTS[group],
            "declared_values": {
                path: copy.deepcopy(_get_pointer(spec, path)) for path in paths
            },
        }
        for group, paths in RULE_BINDINGS.items()
    }
    return source, spec, evidence


def admit(source=None, spec=None, evidence=None, hash_override=None):
    normal_source, normal_spec, normal_evidence = inputs()
    src = normal_source if source is None else source
    typed = normal_spec if spec is None else spec
    claims = normal_evidence if evidence is None else evidence
    return intake_written_rules(
        src, json.dumps(typed, sort_keys=True), claims,
        expected_source_sha256=(
            sha256(src).hexdigest() if hash_override is None else hash_override
        ),
        snapshot_ref=REF_PATH,
    )


def samples():
    start = datetime(2026, 10, 14, 8, tzinfo=UTC)
    values = []
    for i in range(58):
        fast, slow = Decimal(100), Decimal(101)
        if 50 <= i <= 51 or i >= 54:
            fast = Decimal(102)
        values.append(ClosedIndicatorSample(
            start + timedelta(minutes=5*i), fast, slow
        ))
    return tuple(values)


def oracle_cross(sample_trace, warmup):
    """Independent hand-coded oracle from the original textual >= constraints."""
    decisions = []
    for i in range(warmup, len(sample_trace)):
        before, now = sample_trace[i-1], sample_trace[i]
        if before.fast_ema <= before.slow_ema and now.fast_ema > now.slow_ema:
            decisions.append(now.closed_at_utc)
    return tuple(decisions)


def test_complete_explicit_source_map_and_canonical_spec_pass():
    source, spec, claims = inputs()
    assert len(claims) == 18
    assert set(claims) == set(RULE_BINDINGS)
    assert all(source.decode().count(excerpt) == 1 for excerpt in EXCERPTS.values())
    strategy, receipt = admit(source, spec, claims)
    assert strategy.strategy_id == "sample_ema_cross"
    assert receipt.completeness_state == "RULES_COMPLETE_SOURCE_MATCHED"
    assert receipt.source_sha256 == sha256(source).hexdigest()
    assert receipt.spec_sha256 == sha256(strategy.to_json().encode()).hexdigest()
    assert len(receipt.evidence_sha256) == 64
    assert len(receipt.evidence_groups) == 18
    assert receipt.internal_fixture_only
    assert not receipt.original_platform_parity_verified
    assert not receipt.independent_human_attestation_verified
    assert admit(source, spec, claims)[1].to_json() == receipt.to_json()


def test_true_closed_predicate_parity_against_independent_text_oracle():
    strategy, _ = admit()
    trace = samples()
    actual = evaluate_closed_indicator_cross(strategy, trace)
    expected = oracle_cross(trace, strategy.warmup_closed_bars)
    assert actual == expected
    assert actual == (trace[50].closed_at_utc, trace[54].closed_at_utc)


def test_prefix_independence_does_not_consult_future_bars():
    strategy, _ = admit()
    full = samples()
    early = evaluate_closed_indicator_cross(strategy, full[:53])
    all_signals = evaluate_closed_indicator_cross(strategy, full)
    assert early == all_signals[:1]
    changed = list(full)
    changed[-1] = ClosedIndicatorSample(changed[-1].closed_at_utc, Decimal(100), Decimal(101))
    assert evaluate_closed_indicator_cross(strategy, tuple(changed))[:1] == early


def test_equal_fast_slow_current_is_not_a_cross():
    strategy, _ = admit()
    v = list(samples())
    v[50] = ClosedIndicatorSample(v[50].closed_at_utc, Decimal(101), Decimal(101))
    signals = evaluate_closed_indicator_cross(strategy, tuple(v))
    assert v[50].closed_at_utc not in signals


def test_original_source_hash_mutation_rejected():
    source, spec, claims = inputs()
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        admit(source + b" \n", spec, claims, sha256(source).hexdigest())


def test_unqualified_source_text_cannot_reuse_old_spec_source_identity():
    source, spec, claims = inputs()
    mutated = source.replace(b"120 broker-defined ticks", b"180 broker-defined ticks")
    with pytest.raises(ValueError, match="source provenance"):
        admit(mutated, spec, claims)


def test_changed_spec_field_without_reviewed_evidence_rejected():
    source, spec, claims = inputs()
    spec["long"]["exit"]["stop_loss"]["value"] = "130"
    with pytest.raises(ValueError, match="contradicts confirmed mapping"):
        admit(source, spec, claims)


def test_relabelled_numeric_stop_with_updated_claim_still_rejected():
    source, spec, claims = inputs()
    spec["long"]["exit"]["stop_loss"]["value"] = "130"
    claims["long_stop"]["declared_values"]["/long/exit/stop_loss"]["value"] = "130"
    with pytest.raises(ValueError, match="source literal"):
        admit(source, spec, claims)


@pytest.mark.parametrize("group", list(RULE_BINDINGS))
def test_missing_any_mandatory_evidence_group_blocks_admission(group):
    source, spec, claims = inputs()
    claims.pop(group)
    with pytest.raises(ValueError, match="evidence groups"):
        admit(source, spec, claims)


@pytest.mark.parametrize("group", ["indicators", "long_entry", "short_side", "sessions"])
def test_missing_or_fake_original_text_quote_is_rejected(group):
    source, spec, claims = inputs()
    claims[group]["source_excerpt"] = "Definitely profitable with future bars"
    with pytest.raises(ValueError, match="written-source quote"):
        admit(source, spec, claims)


def test_additional_unreviewed_claim_does_not_sneak_in():
    source, spec, claims = inputs()
    claims["invented_stop"] = claims["long_stop"]
    with pytest.raises(ValueError, match="evidence groups"):
        admit(source, spec, claims)


def test_missing_subfield_and_false_value_rejected():
    source, spec, claims = inputs()
    claims["market"]["declared_values"].pop("/market")
    with pytest.raises(ValueError, match="field bindings"):
        admit(source, spec, claims)
    source, spec, claims = inputs()
    claims["long_opposite_exit"]["declared_values"]["/long/exit/close_on_opposite_signal"] = True
    with pytest.raises(ValueError, match="contradicts confirmed mapping"):
        admit(source, spec, claims)


def test_incomplete_stop_or_unresolved_interpretation_blocked():
    source, spec, claims = inputs()
    spec["origin"]["unresolved_questions"] = ["Unknown stop priority"]
    claims["origin"]["declared_values"]["/origin/unresolved_questions"] = ["Unknown stop priority"]
    with pytest.raises(ValueError, match="interpretation not qualified"):
        admit(source, spec, claims)


def test_signal_adapter_rejects_changed_long_direction_or_rule_operator():
    source, spec, claims = inputs()
    spec["long"]["entry"]["predicates"][0]["operator"] = "cross_below"
    claims["long_entry"]["declared_values"]["/long/entry"]["predicates"][0]["operator"] = "cross_below"
    with pytest.raises(ValueError, match="unsupported"):
        admit(source, spec, claims)


def test_nonfinite_or_time_disordered_trace_rejected():
    strategy, _ = admit()
    trace = samples()
    damaged = list(trace)
    damaged[51] = ClosedIndicatorSample(trace[50].closed_at_utc, Decimal(101), Decimal(102))
    with pytest.raises(ValueError, match="timestamps"):
        evaluate_closed_indicator_cross(strategy, tuple(damaged))
    damaged = list(trace)
    damaged[51] = ClosedIndicatorSample(trace[51].closed_at_utc, Decimal("NaN"), Decimal(102))
    with pytest.raises(ValueError, match="finite"):
        evaluate_closed_indicator_cross(strategy, tuple(damaged))


def test_before_warmup_or_wrong_timeframe_does_not_generate_signals():
    strategy, _ = admit()
    with pytest.raises(ValueError, match="not enough"):
        evaluate_closed_indicator_cross(strategy, samples()[:50])
    v = list(samples())
    v[51] = ClosedIndicatorSample(v[51].closed_at_utc + timedelta(minutes=1),
                                  v[51].fast_ema, v[51].slow_ema)
    with pytest.raises(ValueError, match="timestamps"):
        evaluate_closed_indicator_cross(strategy, tuple(v))


def test_human_confirmation_cannot_be_inferred_from_fixture():
    _, receipt = admit()
    data = json.loads(receipt.to_json())
    assert data["internal_fixture_only"] is True
    assert data["independent_human_attestation_verified"] is False
    assert data["original_platform_parity_verified"] is False
    assert "profit" not in receipt.to_json()


def test_day20_no_execute_or_import_untrusted_code():
    _, receipt = admit()
    assert receipt.signal_adapter_type == "closed_ema_indicator_cross_above.v1"
    assert "python" not in receipt.signal_adapter_type
    source, spec, claims = inputs()
    spec["origin"]["source_language"] = "python"
    with pytest.raises(ValueError, match="source provenance"):
        admit(source, spec, claims)
