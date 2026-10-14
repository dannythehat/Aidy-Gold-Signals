"""Day22: bounded Pine v6 source, frozen signal trace and provenance gates."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest
from test_strategy_lab_written_rule_intake import inputs, samples

from aidy.strategy_lab_pine_adapter import (
    admit_pine_subset,
    compare_pine_reference,
    compare_pine_to_spec,
    pine_predicate_signals,
)

FIXTURE = Path(__file__).parents[1] / "research" / "strategy_lab" / "fixtures" / "day22_internal_pine_v6.pine.txt"
SOURCE_REF = "research/strategy_lab/fixtures/day22_internal_pine_v6.pine.txt"


def source() -> bytes:
    return FIXTURE.read_bytes()


def make_spec(original: bytes | None = None):
    source_bytes = source() if original is None else original
    _, raw, _ = inputs()
    raw["origin"]["source_language"] = "pine"
    raw["origin"]["source_sha256"] = sha256(source_bytes).hexdigest()
    raw["origin"]["source_snapshot_ref"] = SOURCE_REF
    raw["origin"]["interpretation_notes"] = [
        "Internal Pine signal-fragment example only, other exit/size rules "
        "not in this Pine source and never automatically ported."
    ]
    return raw


def admitted(original: bytes | None = None, spec=None):
    original = source() if original is None else original
    spec = make_spec(original) if spec is None else spec
    return admit_pine_subset(
        original, source_sha256=sha256(original).hexdigest(),
        source_ref=SOURCE_REF, spec_json=json.dumps(spec, sort_keys=True),
    )


def reference(origin="internal_synthetic", original: bytes | None = None):
    original = source() if original is None else original
    trace = samples()
    signals = {trace[50].closed_at_utc, trace[54].closed_at_utc}
    rows = [
        {
            "closed_at_utc": row.closed_at_utc.isoformat().replace("+00:00", "Z"),
            "fast_ema": format(row.fast_ema, "f"),
            "slow_ema": format(row.slow_ema, "f"),
            "long_signal": row.closed_at_utc in signals,
        }
        for row in trace
    ]
    return {
        "schema": "aidy.pine_signal_trace.v1",
        "origin": origin,
        "original_source_sha256": sha256(original).hexdigest(),
        "chart_symbol": "XAUUSD",
        "chart_timeframe": "M5",
        "captured_reference": "INTERNAL SYNTHETIC TEST VECTORS - NOT TRADINGVIEW",
        "bars": rows,
    }


def compare(reference_obj=None, obj=None):
    ref = reference() if reference_obj is None else reference_obj
    original = json.dumps(ref, sort_keys=True, separators=(",", ":")).encode()
    return compare_pine_reference(
        admitted() if obj is None else obj, original,
        expected_reference_sha256=sha256(original).hexdigest(),
    )


def test_parser_frozen_pine_v6_and_exact_typed_mapping():
    script = admitted()
    assert script.pine_version == 6
    assert script.fast_period == 10
    assert script.slow_period == 30
    assert script.next_tick_execution
    assert not script.complete_strategy_ported
    assert not script.original_platform_parity_verified
    assert script.original_sha256 == sha256(source()).hexdigest()
    assert script.spec_sha256 == sha256(script.spec_json.encode()).hexdigest()


def test_closed_bar_signal_parity_with_day20_independent_spec_oracle():
    script = admitted()
    trace = samples()
    actual = compare_pine_to_spec(script, trace)
    assert actual == (
        trace[50].closed_at_utc,
        trace[54].closed_at_utc,
    )
    assert pine_predicate_signals(script, trace[:53]) == actual[:1]


def test_frozen_internal_reference_matches_but_never_provider_verified():
    matched = compare()
    assert matched.status == "INTERNAL_FIXTURE_PARITY_ONLY"
    assert matched.signal_count == 2
    assert matched.matched
    assert not matched.real_tradingview_capture_qualified
    assert not matched.complete_strategy_parity_qualified


def test_user_labelled_tv_export_is_not_automatically_authenticated():
    result = compare(reference("tradingview_user_export_unattested"))
    assert result.status == "USER_REFERENCE_MATCHED_BUT_NOT_PROVIDER_AUTHENTICATED"
    assert not result.real_tradingview_capture_qualified


def test_replayed_source_and_reference_has_deterministic_identity():
    a, b = admitted(), admitted()
    assert a.to_json() == b.to_json()
    assert compare() == compare()


@pytest.mark.parametrize(("before", "after"), [
    ("//@version=6", "//@version=5"),
    ("process_orders_on_close=false", "process_orders_on_close=true"),
    ("calc_on_every_tick=false", "calc_on_every_tick=true"),
    ("calc_on_order_fills=false", "calc_on_order_fills=true"),
    ("pyramiding=0", "pyramiding=10"),
    ("ta.crossover(fastEma, slowEma)", "ta.crossunder(fastEma, slowEma)"),
    ("barstate.isconfirmed and ", ""),
    ("ta.ema(close, 10)", "ta.ema(high, 10)"),
    ("ta.ema(close, 30)", "ta.ema(close, 300)"),
    ("strategy.long", "strategy.short"),
    ('strategy.entry("Long", strategy.long)', 'strategy.entry("Short", strategy.long)'),
    ("if longSignal", "if not longSignal"),
    ("ta.ema(close, 10)", "ta.ema(close[1], 10)"),
    ("strategy(", "indicator("),
])
def test_unsafe_or_unsupported_source_setting_blocked(before, after):
    original = source().replace(before.encode(), after.encode())
    assert original != source()
    with pytest.raises(ValueError):
        admitted(original)


@pytest.mark.parametrize("addition", [
    "\nrequest.security(syminfo.tickerid, 'D', high, lookahead=barmerge.lookahead_on)\n",
    "\nstrategy.close('Long', immediately=true)\n",
    "\nstrategy.exit('bracket', 'Long', stop=100, limit=200)\n",
    "\nalert('hello')\n",
    "\n//@version=6\n",
    "\nvarip float x = close\n",
    "\nfoo = eval('anything')\n",
])
def test_unknown_commands_and_unpinned_extra_lines_blocked(addition):
    with pytest.raises(ValueError, match="UNSUPPORTED_PINE"):
        admitted(source() + addition.encode())


def test_source_identity_fails_before_parsing_modified_script():
    original = source()
    changed = original.replace(b"strategy.long", b"strategy.short")
    with pytest.raises(ValueError, match="SHA256"):
        admit_pine_subset(
            changed, source_sha256=sha256(original).hexdigest(),
            source_ref=SOURCE_REF, spec_json=json.dumps(make_spec()),
        )


@pytest.mark.parametrize(("path", "changed"), [
    (("origin", "source_language"), "written_rules"),
    (("market", "signal_timeframe"), "H1"),
    (("market", "symbol"), "XAGUSD"),
    (("indicators", 0, "period"), 12),
    (("indicators", 1, "period"), 24),
    (("long", "entry", "predicates", 0, "operator"), "cross_below"),
    (("execution", "entry_execution"), "signal_close"),
])
def test_strategy_spec_drift_blocks_admission(path, changed):
    spec = make_spec()
    current = spec
    for item in path[:-1]:
        current = current[item]
    current[path[-1]] = changed
    with pytest.raises(ValueError):
        admitted(spec=spec)


@pytest.mark.parametrize("field", [
    "source_bytes", "original_sha256", "spec_json", "spec_sha256",
    "fast_period", "complete_strategy_ported", "original_platform_parity_verified",
])
def test_forged_admitted_object_cannot_bypass_original_revalidation(field):
    original = admitted()
    replacements = {
        "source_bytes": original.source_bytes + b" ",
        "original_sha256": "f" * 64,
        "spec_json": original.spec_json + " ",
        "spec_sha256": "f" * 64,
        "fast_period": 1,
        "complete_strategy_ported": True,
        "original_platform_parity_verified": True,
    }
    with pytest.raises(ValueError):
        pine_predicate_signals(replace(original, **{field: replacements[field]}), samples())


def test_short_or_missing_warmup_and_disordered_trace_blocked():
    script = admitted()
    with pytest.raises(ValueError, match="not enough"):
        pine_predicate_signals(script, samples()[:50])
    v = list(samples())
    v[51] = replace(v[51], closed_at_utc=v[50].closed_at_utc)
    with pytest.raises(ValueError, match="chronology"):
        pine_predicate_signals(script, tuple(v))


@pytest.mark.parametrize("mutator", [
    lambda r: r["bars"][50].update(long_signal=False),
    lambda r: r["bars"][49].update(long_signal=True),
    lambda r: r["bars"][54].update(long_signal=False),
    lambda r: r["bars"][51].update(fast_ema="NaN"),
    lambda r: r["bars"][51].update(slow_ema="-1"),
    lambda r: r["bars"][51].update(closed_at_utc=r["bars"][50]["closed_at_utc"]),
    lambda r: r.update(chart_timeframe="H1"),
    lambda r: r.update(original_source_sha256="f"*64),
])
def test_reference_signal_drift_corrupt_numbers_and_clock_rejected(mutator):
    ref = reference()
    mutator(ref)
    with pytest.raises(ValueError):
        compare(ref)


def test_reference_original_bytes_digest_required():
    payload = json.dumps(reference()).encode()
    with pytest.raises(ValueError, match="SHA256"):
        compare_pine_reference(admitted(), payload + b" ", expected_reference_sha256=sha256(payload).hexdigest())


def test_bad_reference_duplicate_json_fields_blocked():
    raw = json.dumps(reference()).encode()
    altered = raw.replace(b'"chart_symbol": "XAUUSD",', b'"chart_symbol": "XAUUSD", "chart_symbol":"XAGUSD",')
    with pytest.raises(ValueError):
        compare_pine_reference(admitted(), altered, expected_reference_sha256=sha256(altered).hexdigest())


def test_unknown_script_and_python_injection_are_only_data(tmp_path):
    sentinel = tmp_path / "should_not_be_written"
    malicious = source() + (
        "\n" + "__import__('os').system('touch " + str(sentinel) + "')"
    ).encode()
    with pytest.raises(ValueError):
        admitted(malicious)
    assert not sentinel.exists()


def test_flat_trace_does_not_generate_signals():
    script = admitted()
    empty = tuple(replace(x,fast_ema=Decimal(100),slow_ema=Decimal(100)) for x in samples())
    assert compare_pine_to_spec(script, empty) == ()
