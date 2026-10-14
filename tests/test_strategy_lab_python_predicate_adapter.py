"""Day21: exact-source AST-only Python signal adapter and hostile-source refusal."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest

from aidy.strategy_lab_python_predicate_adapter import (
    ADAPTER_VERSION,
    admit_python_predicate,
    compare_python_with_spec,
    evaluate_restricted_python,
)
from aidy.strategy_lab_written_rule_intake import ClosedIndicatorSample
from test_strategy_lab_written_rule_intake import inputs, samples

FIXTURE = (Path(__file__).parents[1] / "research" / "strategy_lab"
           / "fixtures" / "day21_internal_python_signal.py.txt")
SOURCE_REF = "research/strategy_lab/fixtures/day21_internal_python_signal.py.txt"


def source() -> bytes:
    return FIXTURE.read_bytes()


def candidate(source_bytes: bytes | None = None):
    code = source() if source_bytes is None else source_bytes
    _, spec, _ = inputs()
    spec["origin"]["source_language"] = "python"
    spec["origin"]["source_sha256"] = sha256(code).hexdigest()
    spec["origin"]["source_snapshot_ref"] = SOURCE_REF
    spec["origin"]["interpretation_notes"] = [
        "Day21 INTERNAL signal-only Python fixture; remaining exit and sizing rules "
        "come from separately reviewed StrategySpec; no original-platform parity."
    ]
    return spec


def accepted(raw: bytes | None = None, spec: dict | None = None):
    original = source() if raw is None else raw
    spec = candidate(original) if spec is None else spec
    return admit_python_predicate(
        original, json.dumps(spec, sort_keys=True),
        expected_source_sha256=sha256(original).hexdigest(),
        source_snapshot_ref=SOURCE_REF,
    )


def test_source_bound_adapter_and_explicit_execution_labels():
    adapter = accepted()
    obj = json.loads(adapter.to_json())
    assert obj["grammar"] == ADAPTER_VERSION
    assert obj["source_sha256"] == sha256(source()).hexdigest()
    assert obj["spec_sha256"] == sha256(adapter.spec_json.encode()).hexdigest()
    assert obj["unrestricted_python_executed"] is False
    assert obj["broker_platform_parity_verified"] is False
    assert len(adapter.ast_sha256) == 64


def test_two_independent_signal_implementations_agree_on_58_closed_bars():
    adapter = accepted()
    trace = samples()
    output = compare_python_with_spec(adapter, trace)
    assert output["status"] == "SIGNAL_PREDICATE_PARITY_ONLY"
    assert output["signal_count"] == 2
    assert output["python_signals_utc"] == output["spec_signals_utc"]
    assert output["python_signals_utc"] == [
        trace[50].closed_at_utc.isoformat().replace("+00:00", "Z"),
        trace[54].closed_at_utc.isoformat().replace("+00:00", "Z"),
    ]
    assert not output["unrestricted_python_executed"]
    assert not output["external_python_strategy_qualified"]
    assert not output["original_broker_platform_parity"]


def test_closed_prefix_independence_prevents_future_bar_lookahead():
    adapter = accepted()
    full = samples()
    early = evaluate_restricted_python(adapter, full[:53])
    entire = evaluate_restricted_python(adapter, full)
    assert early == entire[:1]
    amended = list(full)
    amended[-1] = replace(amended[-1], fast_ema=Decimal(100))
    assert evaluate_restricted_python(adapter, tuple(amended))[:1] == early


def test_equal_now_is_not_cross_and_equal_previous_is_allowed():
    adapter = accepted()
    rows = list(samples())
    rows[50] = replace(rows[50], fast_ema=Decimal(101))
    assert rows[50].closed_at_utc not in evaluate_restricted_python(adapter, tuple(rows))
    rows = list(samples())
    rows[49] = replace(rows[49], fast_ema=Decimal(101))
    assert rows[50].closed_at_utc in evaluate_restricted_python(adapter, tuple(rows))


def test_flat_trace_never_signals():
    adapter = accepted()
    rows = tuple(replace(row, fast_ema=Decimal(100), slow_ema=Decimal(100))
                 for row in samples())
    assert evaluate_restricted_python(adapter, rows) == ()


def test_deterministic_source_hash_receipt_and_cross():
    a, b = accepted(), accepted()
    assert a == b
    assert a.to_json() == b.to_json()
    assert compare_python_with_spec(a, samples()) == compare_python_with_spec(b, samples())


@pytest.mark.parametrize("payload", [
    "import os\n" + source().decode(),
    "from os import system\n" + source().decode(),
    "open('untrusted.txt', 'w')\n" + source().decode(),
    "x = 1\n" + source().decode(),
    source().decode() + "\nprint('side effect')\n",
    "def signal(fast_prev,slow_prev,fast_now,slow_now):\n"
    "    __import__('os').system('touch escaped.txt')\n"
    "    return fast_prev <= slow_prev and fast_now > slow_now\n",
    "def signal(fast_prev,slow_prev,fast_now,slow_now):\n"
    "    while True:\n        pass\n    return True\n",
    "def signal(fast_prev,slow_prev,fast_now,slow_now):\n"
    "    return eval('True')\n",
    "def signal(fast_prev,slow_prev,fast_now,slow_now):\n"
    "    return fast_now.__class__ is Decimal\n",
    "def signal(fast_prev,slow_prev,fast_now,slow_now):\n"
    "    return [x for x in range(10)]\n",
    "def signal(fast_prev,slow_prev,fast_now,slow_now):\n"
    "    return fast_prev <= slow_prev and fast_now > slow_now and True\n",
    "@property\n" + source().decode(),
    "def signal(fast_prev,slow_prev,fast_now,slow_now, **kwargs):\n"
    "    return fast_prev <= slow_prev and fast_now > slow_now\n",
    "def signal(*args):\n    return True\n",
    "def signal(fast_prev,slow_prev,fast_now,slow_now):\n"
    "    x = True\n    return fast_prev <= slow_prev and fast_now > slow_now\n",
    "async " + source().decode(),
])
def test_hostile_and_general_python_forms_are_rejected_not_executed(payload):
    with pytest.raises(ValueError):
        accepted(payload.encode())


@pytest.mark.parametrize("payload", [
    "def signal(fast_prev,slow_prev,fast_now,slow_now):\n"
    "    return fast_prev < slow_prev and fast_now > slow_now\n",
    "def signal(fast_prev,slow_prev,fast_now,slow_now):\n"
    "    return fast_prev <= slow_prev and fast_now >= slow_now\n",
    "def signal(fast_prev,slow_prev,fast_now,slow_now):\n"
    "    return fast_prev <= slow_prev or fast_now > slow_now\n",
    "def signal(fast_prev,slow_prev,fast_now,slow_now):\n"
    "    return fast_now > slow_now\n",
    "def signal(fast_prev,slow_prev,fast_now,slow_now):\n"
    "    return fast_prev <= slow_prev and fast_prev <= slow_prev\n",
])
def test_other_rule_semantics_rejected_instead_of_inferred(payload):
    with pytest.raises(ValueError):
        accepted(payload.encode())


def test_evidence_digest_mismatch_denied_even_if_code_is_valid():
    original = source()
    spec = candidate(original)
    with pytest.raises(ValueError, match="SHA256"):
        admit_python_predicate(
            original, json.dumps(spec),
            expected_source_sha256="0" * 64, source_snapshot_ref=SOURCE_REF,
        )


def test_python_spec_source_identity_and_language_must_match():
    spec = candidate()
    spec["origin"]["source_language"] = "written_rules"
    with pytest.raises(ValueError, match="inconsistent"):
        accepted(spec=spec)
    spec = candidate()
    spec["origin"]["source_snapshot_ref"] = "wrong_reference.py"
    with pytest.raises(ValueError, match="inconsistent"):
        accepted(spec=spec)


def test_python_source_can_not_override_declared_direction_or_operator():
    spec = candidate()
    spec["long"]["entry"]["predicates"][0]["operator"] = "cross_below"
    with pytest.raises(ValueError, match="inconsistent"):
        accepted(spec=spec)
    spec = candidate()
    spec["short"]["entry"] = json.loads(json.dumps(spec["long"]["entry"]))
    with pytest.raises(ValueError, match="inconsistent"):
        accepted(spec=spec)


def test_relabelled_source_rejected_when_original_sha_or_spec_mismatches():
    original = source()
    changed = original.replace(b"fast_prev", b"fast_last")
    spec = candidate(original)
    with pytest.raises(ValueError, match="SHA256"):
        admit_python_predicate(
            changed, json.dumps(spec),
            expected_source_sha256=sha256(original).hexdigest(),
            source_snapshot_ref=SOURCE_REF,
        )


@pytest.mark.parametrize("tamper", ["source_bytes", "source_sha256",
                                    "spec_json", "ast_sha256",
                                    "broker_platform_parity_verified"])
def test_forged_adapter_does_not_bypass_original_checks(tamper):
    obj = accepted()
    new = {
        "source_bytes": obj.source_bytes + b" ",
        "source_sha256": "f" * 64,
        "spec_json": obj.spec_json + " ",
        "ast_sha256": "0" * 64,
        "broker_platform_parity_verified": True,
    }[tamper]
    with pytest.raises(ValueError):
        evaluate_restricted_python(replace(obj, **{tamper:new}), samples())


def test_malformed_sample_order_nan_and_naive_timestamps_rejected():
    obj = accepted()
    rows = list(samples())
    rows[52] = replace(rows[52], closed_at_utc=rows[51].closed_at_utc)
    with pytest.raises(ValueError, match="consecutive"):
        evaluate_restricted_python(obj, tuple(rows))
    rows = list(samples())
    rows[52] = replace(rows[52], fast_ema=Decimal("NaN"))
    with pytest.raises(ValueError, match="finite"):
        evaluate_restricted_python(obj, tuple(rows))
    rows = list(samples())
    rows[52] = replace(rows[52], closed_at_utc=rows[52].closed_at_utc.replace(tzinfo=None))
    with pytest.raises(ValueError):
        evaluate_restricted_python(obj, tuple(rows))


def test_closed_bar_warmup_and_type_required():
    obj = accepted()
    with pytest.raises(ValueError, match="insufficient"):
        evaluate_restricted_python(obj, samples()[:50])
    with pytest.raises(ValueError):
        evaluate_restricted_python(obj, list(samples()))
    rows = list(samples())
    rows[51] = None
    with pytest.raises(ValueError):
        evaluate_restricted_python(obj, tuple(rows))


def test_only_original_approved_python_source_not_user_executed(tmp_path):
    sentinel = tmp_path / "python_source_was_executed"
    malicious = (
        "def signal(fast_prev, slow_prev, fast_now, slow_now):\n"
        f"    open({str(sentinel)!r}, 'w').write('unsafe')\n"
        "    return fast_prev <= slow_prev and fast_now > slow_now\n"
    )
    with pytest.raises(ValueError):
        accepted(malicious.encode())
    assert not sentinel.exists()


def test_source_size_and_invalid_utf8_fail_closed():
    with pytest.raises(ValueError):
        accepted(b"a" * 9000)
    with pytest.raises(ValueError):
        accepted(b"\xff")


def test_only_signal_hook_is_proven_not_trade_risk_or_broker():
    obj = accepted()
    result = compare_python_with_spec(obj, samples())
    assert result["signal_count"] == 2
    assert result["status"] == "SIGNAL_PREDICATE_PARITY_ONLY"
    assert result["external_python_strategy_qualified"] is False
