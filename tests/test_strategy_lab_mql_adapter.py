"""Day23 source integrity, hostile MQL blocking and closed entry/exit predicates."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from test_strategy_lab_written_rule_intake import inputs, samples

from aidy.strategy_lab_customer_mql_intake import inspect_customer_mql
from aidy.strategy_lab_mql_adapter import (
    admit_mql_closed_cross,
    evaluate_mql_closed_cross,
)

ROOT = Path(__file__).resolve().parents[1] / "research/strategy_lab/fixtures"


def source(lang="mql4"):
    ext = "mq4" if lang == "mql4" else "mq5"
    ref = f"research/strategy_lab/fixtures/day23_internal_closed_cross.{ext}"
    return (ROOT / f"day23_internal_closed_cross.{ext}").read_bytes(), ref


def adapter(lang="mql4", changed=None, spec_changed=None):
    raw, ref = source(lang)
    if changed is not None:
        raw = changed
    _, spec, _ = inputs()
    spec["origin"]["source_language"] = lang
    spec["origin"]["source_sha256"] = sha256(raw).hexdigest()
    spec["origin"]["source_snapshot_ref"] = ref
    spec["origin"]["interpretation_notes"] = [
        "MQL closed entry and opposite-cross exit predicate only; no terminal EA, stops, fills."
    ]
    spec["long"]["exit"]["close_on_opposite_signal"] = True
    if spec_changed is not None:
        spec_changed(spec)
    return admit_mql_closed_cross(
        raw, json.dumps(spec, sort_keys=True),
        expected_source_sha256=sha256(raw).hexdigest(),
        source_ref=ref, source_language=lang,
    )


@pytest.mark.parametrize("lang", ["mql4", "mql5"])
def test_both_original_languages_admitted_and_signal_exit_timestamps_identical(lang):
    selected = adapter(lang)
    results = evaluate_mql_closed_cross(selected, samples())
    trace = samples()
    assert selected.source_language == lang
    assert results["entry_signals_utc"] == [
        trace[50].closed_at_utc.isoformat().replace("+00:00", "Z"),
        trace[54].closed_at_utc.isoformat().replace("+00:00", "Z"),
    ]
    assert results["opposite_cross_exit_signals_utc"] == [
        trace[52].closed_at_utc.isoformat().replace("+00:00", "Z")
    ]
    assert results["entry_count"] == 2
    assert results["opposite_cross_exit_count"] == 1
    assert not results["native_mt4_mt5_execution_parity_verified"]
    assert not results["full_exit_order_management_verified"]
    assert not results["untrusted_mql_executed"]


@pytest.mark.parametrize("lang", ["mql4", "mql5"])
def test_customer_mql_receipt_file_identity_and_plain_english_next_questions(lang):
    raw, ref = source(lang)
    result = inspect_customer_mql(raw, filename=ref.split("/")[-1])
    assert result.source_sha256 == sha256(raw).hexdigest()
    assert result.declared_language == lang
    assert result.predicate_subset_supported
    assert result.status == "PREDICATE_SUBSET_SUPPORTED_REVIEW_REQUIRED"
    assert result.questions and not result.full_strategy_qualified
    assert not result.native_mt_parity_qualified
    assert result.to_json() == inspect_customer_mql(raw, filename=ref.split("/")[-1]).to_json()


@pytest.mark.parametrize("addition", [
    "#include <Trade/Trade.mqh>\n",
    "void OnTick(){ OrderSend(_Symbol, OP_BUY, 1, Ask, 3, 0, 0); }\n",
    "void OnTester() { }\n",
    "#import \"kernel32.dll\"\n",
    "int x = iMA(NULL, 0, 10, 0, MODE_EMA, PRICE_CLOSE, 0);\n",
    "bool Bad(){return true;}\n",
    "#define LongEntry malicious\n",
    "void OnInit(){}\n",
    "__import__('os').system('touch bad')\n",
    "return fast_prev < slow_prev && fast_now > slow_now;\n",
])
def test_added_or_changed_source_is_rejected_not_executed(addition):
    raw, _ = source()
    if addition.startswith("return"):
        changed = raw.replace(b"return fast_prev <= slow_prev", addition.encode())
    else:
        changed = raw + addition.encode()
    with pytest.raises(ValueError, match="UNSUPPORTED_MQL"):
        adapter(changed=changed)


@pytest.mark.parametrize("mutation", [
    lambda spec: spec["origin"].update(source_language="pine"),
    lambda spec: spec["origin"].update(unresolved_questions=["stop priority"]),
    lambda spec: spec["market"].update(signal_timeframe="H1"),
    lambda spec: spec["market"].update(symbol="XAGUSD"),
    lambda spec: spec["indicators"][0].update(period=11),
    lambda spec: spec["long"]["exit"].update(close_on_opposite_signal=False),
    lambda spec: spec["execution"].update(entry_execution="signal_close"),
])
def test_forged_or_incompatible_strategy_spec_is_blocked(mutation):
    with pytest.raises(ValueError):
        adapter(spec_changed=mutation)


def test_original_sha_checked_before_parsing_and_filename_bound():
    raw, ref = source("mql5")
    with pytest.raises(ValueError, match="SHA256"):
        admit_mql_closed_cross(
            raw + b" ", adapter("mql5").spec_json,
            expected_source_sha256=sha256(raw).hexdigest(),
            source_ref=ref, source_language="mql5",
        )
    with pytest.raises(ValueError, match="extension"):
        admit_mql_closed_cross(
            raw, adapter("mql5").spec_json, expected_source_sha256=sha256(raw).hexdigest(),
            source_ref="missing.mq4", source_language="mql5",
        )


@pytest.mark.parametrize("field,altered", [
    ("source_bytes", b"UNTRUSTED"),
    ("source_sha256", "f"*64),
    ("spec_sha256", "f"*64),
    ("source_language", "mql5"),
    ("native_metatrader_parity_verified", True),
    ("complete_ea_ported", True),
])
def test_frozen_adapter_tampering_rejected(field, altered):
    a = adapter()
    with pytest.raises(ValueError):
        evaluate_mql_closed_cross(replace(a, **{field: altered}), samples())


def test_no_future_bar_and_invalid_chronology_and_ema_rejected():
    a = adapter()
    s = samples()
    assert evaluate_mql_closed_cross(a, s[:53])["entry_count"] == 1
    with pytest.raises(ValueError, match="insufficient"):
        evaluate_mql_closed_cross(a, s[:50])
    bad = list(s)
    bad[52] = replace(bad[52], closed_at_utc=bad[51].closed_at_utc)
    with pytest.raises(ValueError, match="UTC"):
        evaluate_mql_closed_cross(a, tuple(bad))
    bad = list(s)
    bad[52] = replace(bad[52], fast_ema=__import__("decimal").Decimal("NaN"))
    with pytest.raises(ValueError, match="EMA"):
        evaluate_mql_closed_cross(a, tuple(bad))
    bad = list(s)
    bad[52] = replace(bad[52], closed_at_utc=bad[52].closed_at_utc + timedelta(minutes=1))
    with pytest.raises(ValueError, match="UTC"):
        evaluate_mql_closed_cross(a, tuple(bad))


@pytest.mark.parametrize("bad_name", [
    "../hack.mq4", "nested/file.mq5", "dir\\foo.mq4", "x"*129 + ".mq5",
    "a.mq4\x00", "source.exe", "",
])
def test_customer_source_filename_boundary(bad_name):
    with pytest.raises(ValueError):
        inspect_customer_mql(source()[0], filename=bad_name)


@pytest.mark.parametrize("bad", [b"", b"\xff", b"abc\x00def", b"x"*100001])
def test_customer_invalid_source_rejected(bad):
    with pytest.raises(ValueError):
        inspect_customer_mql(bad, filename="customer.mq4")


def test_unhandled_realistic_ea_returns_questions_not_fake_pass():
    src = b"#property strict\nvoid OnTick(){ OrderSend(Symbol(), 0, 1, Ask, 3, 0, 0); }"
    receipt = inspect_customer_mql(src, filename="complex.mq4")
    assert not receipt.predicate_subset_supported
    assert receipt.status == "RULE_RECONSTRUCTION_REQUIRED"
    assert any("order" in x.lower() for x in receipt.findings)
    assert not receipt.full_strategy_qualified


def test_mql_code_not_executed(tmp_path):
    path = tmp_path / "compromised"
    payload = source()[0] + f"\n__import__('os').system('touch {path}');".encode()
    receipt = inspect_customer_mql(payload, filename="safe.mq4")
    assert receipt.status == "RULE_RECONSTRUCTION_REQUIRED"
    with pytest.raises(ValueError):
        adapter(changed=payload)
    assert not path.exists()
