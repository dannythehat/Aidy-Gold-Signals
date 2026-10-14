"""Day22 customer-owned Pine source intake: no accounts, exports or source execution."""
from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from aidy.strategy_lab_customer_pine_intake import inspect_customer_pine

SOURCE = (Path(__file__).resolve().parents[1] / "research" / "strategy_lab"
          / "fixtures" / "day22_internal_pine_v6.pine.txt")


def read_source() -> bytes:
    return SOURCE.read_bytes()


def original(**kwargs):
    return inspect_customer_pine(read_source(), filename="client-strategy.pine", **kwargs)


def test_customer_supported_signal_fragment_never_claims_full_strategy():
    r=original()
    assert r.status=="SIGNAL_SUBSET_SUPPORTED_REQUIRES_REVIEW"
    assert r.signal_adapter_supported
    assert not r.full_strategy_reproduction_qualified
    assert not r.independent_tradingview_parity_verified
    assert r.source_sha256==sha256(read_source()).hexdigest()
    assert r.pine_version=="6" and r.script_type=="strategy"
    assert len(r.customer_questions)==4
    assert "risk and exit" in r.next_action


def test_customer_receipt_is_deterministic_and_explicit_about_scope():
    a,b=original(),original()
    assert a==b and a.to_json()==b.to_json()
    wire=json.loads(a.to_json())
    assert wire["supplied_filename"]=="client-strategy.pine"
    assert wire["full_strategy_reproduction_qualified"] is False
    assert wire["independent_tradingview_parity_verified"] is False
    assert "source_sha256" in wire
    assert len(wire["inspection_findings"])==2


def test_customer_never_needs_tradingview_account_or_chart_export():
    wire=original().to_wire()
    assert "tradingview_account" not in wire
    assert "chart_csv" not in wire
    assert wire["status"]=="SIGNAL_SUBSET_SUPPORTED_REQUIRES_REVIEW"


@pytest.mark.parametrize("script", [
    "//@version=6\nstrategy('Customer test')\nstrategy.entry('L',strategy.long)\n",
    "//@version=5\nstrategy('Gold')\nif close > open\n    strategy.entry('L', strategy.long)\n",
    "//@version=6\nindicator('Signals')\nplot(ta.ema(close,10))\n",
    "//@version=6\nlibrary('Helpers')\nexport myfunc() => close\n",
])
def test_realistic_unhandled_customer_script_returns_reconstruction_questions(script):
    result=inspect_customer_pine(script.encode())
    assert result.status=="RULE_RECONSTRUCTION_REQUIRED"
    assert not result.signal_adapter_supported
    assert not result.full_strategy_reproduction_qualified
    assert result.customer_questions


@pytest.mark.parametrize(("snippet", "expected"), [
    ("request.security(syminfo.tickerid, 'D', high)", "another timeframe"),
    ("barmerge.lookahead_on", "lookahead"),
    ("calc_on_every_tick=true", "unfinished candle"),
    ("strategy.exit('SL', 'Long', stop=100)", "exit or order-management"),
    ("alert('possible signal')", "alerts"),
    ("for i=0 to 9\n    a = i", "advanced programme"),
])
def test_advanced_submission_returns_honest_blocked_feature_details(snippet,expected):
    raw=("//@version=6\nstrategy('Gold')\n"+snippet+"\n").encode()
    result=inspect_customer_pine(raw)
    assert result.status=="RULE_RECONSTRUCTION_REQUIRED"
    assert any(expected in item for item in result.inspection_findings)


def test_unsupported_pine_v4_is_not_marked_supported():
    raw=b"//@version=4\nstrategy('Example')\nstrategy.entry('L', strategy.long)\n"
    r=inspect_customer_pine(raw)
    assert r.pine_version=="4"
    assert not r.signal_adapter_supported
    assert any("not been calibrated" in s for s in r.inspection_findings)


@pytest.mark.parametrize("raw", [
    b"strategy('X')\n",
    b"//@version=6\n//@version=6\nstrategy('X')\n",
    b"//@version=6\n",
    b"//@version=6\nindicator('X')\nstrategy('Y')\n",
    b"not a Pine source at all",
])
def test_incomplete_version_or_declaration_gives_question_not_fake_results(raw):
    report=inspect_customer_pine(raw)
    assert report.status=="NEEDS_SCRIPT_IDENTIFICATION"
    assert not report.signal_adapter_supported
    assert report.customer_questions


def test_source_hash_changes_when_customer_edits_one_char():
    original=read_source()
    changed=original.replace(b"ta.crossover",b"ta.crossunder")
    assert inspect_customer_pine(original).source_sha256!=inspect_customer_pine(changed).source_sha256
    assert inspect_customer_pine(changed).status=="RULE_RECONSTRUCTION_REQUIRED"


@pytest.mark.parametrize("bad", [b"",b"\xff",b"//@version=6\x00strategy('X')",b"x"*100001])
def test_invalid_size_binary_and_non_utf8_fail_before_any_processing(bad):
    with pytest.raises(ValueError):
        inspect_customer_pine(bad)


@pytest.mark.parametrize("name", [
    "../../ssh/id_rsa", "folder\\secret.pine", "x"*129,
    "", "x\x00.pine", "dir/submission.pine",
])
def test_uploaded_filename_cannot_reference_local_files(name):
    with pytest.raises(ValueError):
        inspect_customer_pine(read_source(),filename=name)


def test_source_type_and_submission_method_explicit():
    result=inspect_customer_pine(read_source(),submission_type="source_text_paste")
    assert result.submission_type=="source_text_paste"
    with pytest.raises(ValueError):
        inspect_customer_pine(read_source(),submission_type="provider_export")


def test_file_storage_or_strategy_execution_not_involved(tmp_path):
    sentinel=tmp_path/"should_not_be_created"
    source=(
        b"//@version=6\nstrategy('Danger')\n"
        +f"__import__('os').system('touch {sentinel}')\n".encode()
    )
    response=inspect_customer_pine(source)
    assert response.status=="RULE_RECONSTRUCTION_REQUIRED"
    assert not sentinel.exists()
    assert not response.full_strategy_reproduction_qualified


def test_exact_source_includes_no_invented_broker_or_performance():
    r=original()
    s=r.to_json().lower()
    for false_claim in ("win rate", "profit factor", "verified broker", "live trading", "executed"):
        assert false_claim not in s


def test_partial_custom_pine_source_requires_customer_clarification():
    s=b"//@version=6\nindicator('EMAs')\nplot(ta.ema(close, 10))\n"
    r=inspect_customer_pine(s,filename="ema_indicator.pine")
    assert r.script_type=="indicator"
    assert any("indicator" in row for row in r.inspection_findings)
    assert r.customer_questions
    assert not r.signal_adapter_supported
