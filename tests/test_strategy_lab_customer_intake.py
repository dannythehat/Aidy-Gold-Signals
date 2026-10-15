"""Day35 safe inert customer intake contract, no trading or source execution."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from aidy.strategy_lab_customer_intake import (
    RULE_FIELDS, IntakeRejected, prepare_intake, validate_link, verify_draft,
)

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT/"web/strategy_lab/day35_private_intake_preview.html"
BASE = {
    "market": "XAUUSD", "timeframe": "H1", "trade_direction": "Long and short",
    "entry_rules": "After closed H1 breakout candle, enter next H1 open.",
    "exit_rules": "Exit after two fully closed H1 bars.",
    "stop_loss_rule": "Initial stop 2 ATR(14), no trailing stop.",
    "take_profit_rule": "Exit at 3 ATR(14), or two-bar time exit.",
    "position_sizing_rule": "1% risk of initial simulated capital.",
    "trading_session_and_timezone": "London 08:00–17:00 Europe/London incl DST.",
    "execution_and_cost_assumptions": "Bid/ask, 0.25 spread, 1 tick slip, fees.",
}


def draft(*, mode="paste", value="IF H1 gold candle close > previous high, buy.",
          title="Original gold strategy", rules=None, **kwargs):
    return prepare_intake(
        mode=mode, value=value, title=title,
        rules=BASE if rules is None else rules, **kwargs,
    )


@pytest.mark.parametrize(("mode","value","extras"), [
    ("paste", "H1 fully closed breakout; next candle open; exit after two bars.", {}),
    ("upload", b"// TradingView pine source sample\nstrategy('Sample')", {
        "filename": "my_rules.pine", "media_type": "text/plain",
    }),
    ("upload", b'{"rules":"inert text data"}', {
        "filename": "source.json", "media_type": "application/json",
    }),
    ("upload", b"# Gold system example\nNo automatic execution.", {
        "filename": "rules.md", "media_type": "text/markdown",
    }),
    ("link", "https://github.com/user/strategy/tree/main", {}),
    ("link", "https://www.tradingview.com/script/Example123/", {}),
    ("template", "breakout", {}),
    ("template", "trend_pullback", {}),
    ("template", "mean_reversion", {}),
    ("template", "session_range", {}),
])
def test_all_four_source_modes_create_only_inert_review_draft(mode, value, extras):
    p = draft(mode=mode, value=value, **extras)
    verify_draft(p)
    assert p["schema"] == "aidy.strategy_lab.strategy_intake.v1"
    assert p["research_engine"] == "AIDY"
    assert p["future_customer_brand"] == "GoldThinker"
    assert p["status"] == "AWAITING_INDEPENDENT_RULE_REVIEW"
    assert p["source"]["kind"] == mode
    assert len(p["source"]["original_sha256"]) == 64
    assert len(p["draft_sha256"]) == 64
    assert p["missing_rules"] == []
    assert not p["tenant_authenticated"]
    assert not p["trusted_server_accepted"]
    assert not p["strategy_rules_verified"]
    assert not p["aidy_research_executed"]
    assert not p["eligible_for_production"]
    assert not p["goldthinker_named_or_joinable"]
    assert not p["paper_or_live_trading_enabled"]


def test_partially_filled_strategy_receives_guidance_not_fake_completed_rules():
    incomplete = {key: "" for key in RULE_FIELDS}
    incomplete["market"] = "XAUUSD"
    p = draft(rules=incomplete)
    assert p["status"] == "INCOMPLETE_RULES"
    assert len(p["missing_rules"]) == len(RULE_FIELDS)-1
    assert all(x["guidance"] and x["field"] in RULE_FIELDS for x in p["missing_rules"])
    assert p["rules"]["entry_rules"] == ""
    verify_draft(p)


def test_empty_link_still_requires_source_not_just_fields():
    with pytest.raises(IntakeRejected) as e:
        draft(mode="link", value="")
    assert e.value.code == "UNSAFE_OR_MISSING_TEXT"


@pytest.mark.parametrize(("name","blob"), [
    ("malware.exe", b"MZ..."), ("dangerous.zip", b"PK\x03\x04"),
    ("binary.txt", b"MZ\x90\x00payload"),
    ("binary.md", b"\x7fELF...."), ("bundle.pine", b"PK\x03\x04test"),
    ("pdf.txt", b"%PDF-1.5"), ("image.txt", b"\x89PNG\r\n"),
    ("file.txt", b"abc\x00def"), ("file.txt", b"\x1b[31m"),
    ("compressed.md", b"\x1f\x8bsecret"), ("jpeg.txt", b"\xff\xd8\xff.."),
    ("file.pdf", b"%PDF-1.4"),
    ("file.png", b"\x89PNG\r\n"),
    ("file.py", b"import os"),
    ("file.sh", b"rm -rf /"),
])
def test_unsafe_binary_or_unapproved_upload_suffix_fails_closed(name, blob):
    with pytest.raises(IntakeRejected):
        draft(mode="upload", value=blob, filename=name,
              media_type="application/octet-stream")


@pytest.mark.parametrize("file_name", ["../strategy.txt", "/tmp/strategy.md",
    "C:\\strategy.txt", ".env.txt", "script.TAR.GZ", "binary.dll"])
def test_directory_traversal_hidden_and_unapproved_file_names(file_name):
    with pytest.raises(IntakeRejected, match="UNSUPPORTED_UPLOAD_TYPE"):
        draft(mode="upload", value=b"rule text", filename=file_name)


@pytest.mark.parametrize(("blob", "error"), [
    (b"", "UNSUPPORTED_OR_OVERSIZED_FILE"),
    (b"x"*65537, "UNSUPPORTED_OR_OVERSIZED_FILE"),
    (b"\xff\xfe\x00x", "BINARY_UPLOAD_REJECTED"),
    (b"\xff\xfea", "UTF8_TEXT_REQUIRED"),
])
def test_empty_oversized_or_invalid_utf8_uploads_refused(blob, error):
    with pytest.raises(IntakeRejected) as e:
        draft(mode="upload", value=blob, filename="x.txt",
              media_type="text/plain")
    assert e.value.code == error


@pytest.mark.parametrize("url", [
    "http://github.com/a/b", "file:///etc/passwd",
    "javascript:alert(1)", "https://127.0.0.1/path",
    "https://10.0.0.5/x", "https://[::1]/secret",
    "https://localhost/api", "https://company.internal/private",
    "https://site.local/x", "https://github.com:8080/private",
    "https://user:pass@github.com/a", "https://github.com/a#fragment",
    "https://github.com?access_token=MY_SECRET",
    "https://github.com?api_key=MY_SECRET",
    "https://github.com.evil.example\\@github.com/",
    "https://bad..host.example/test",
    "https://api",
])
def test_url_never_fetches_private_or_non_https_sources(url):
    with pytest.raises(IntakeRejected):
        validate_link(url)


def test_valid_remote_reference_is_not_fetched_or_accepted_as_real_code():
    p = draft(mode="link", value="https://github.com/example/gold-strategy")
    assert p["source"]["remote_content_fetched"] is False
    assert p["source"]["inert_text"] is None
    assert p["strategy_rules_verified"] is False


@pytest.mark.parametrize("value", [
    "-----BEGIN PRIVATE KEY-----\nsecret", "api_key=abc123456789",
    "PASSWORD : aVerySecretPassword",
    "<script>alert('x')</script>", "<iframe src='x'>",
    "<svg onload=alert(1)>", "\x00", "\x01",
])
def test_credentials_html_and_control_chars_refused_without_leak(value):
    with pytest.raises(IntakeRejected) as e:
        draft(value=value)
    assert "secret" not in str(e.value).lower()


@pytest.mark.parametrize("market,timeframe", [
    ("EURUSD","H1"),("BTCUSD","M5"),("XAUUSD","H2"),
    ("XAUUSD","tick"),("XAUUSD","D2"),
])
def test_unsupported_market_or_timeframe_not_silently_accepted(market, timeframe):
    changed = dict(BASE, market=market, timeframe=timeframe)
    with pytest.raises(IntakeRejected, match="UNSUPPORTED"):
        draft(rules=changed)


def test_unknown_rule_key_or_non_string_field_rejected():
    with pytest.raises(IntakeRejected, match="RULE_SCHEMA_UNSUPPORTED"):
        draft(rules={**BASE, "broker_password": "dont-store"})
    with pytest.raises(IntakeRejected, match="INVALID_RULE_FIELD"):
        draft(rules={**BASE, "entry_rules": 42})


def test_source_and_rule_hash_deterministic_for_same_submission():
    a = draft()
    b = draft()
    assert a == b and a["draft_sha256"] == b["draft_sha256"]
    assert draft(value="Different but inert signal")["draft_sha256"] != a["draft_sha256"]


def test_rehashing_draft_to_claim_privilege_fails():
    valid = draft()
    for flag in ("tenant_authenticated", "trusted_server_accepted",
                 "eligible_for_production", "aidy_research_executed",
                 "goldthinker_named_or_joinable", "paper_or_live_trading_enabled"):
        changed = deepcopy(valid)
        changed[flag] = True
        from aidy.strategy_lab_customer_intake import _hash
        changed["draft_sha256"] = _hash({
            key:value for key,value in changed.items() if key != "draft_sha256"
        })
        with pytest.raises(IntakeRejected, match="UNTRUSTED_DRAFT_PRIVILEGES"):
            verify_draft(changed)


def test_consent_declaration_does_not_grant_publish_or_licence():
    p = draft(submitter_rights_declaration=True)
    assert p["submitter_rights_declaration"]
    assert not p["actual_licence_verified"]
    assert not p["goldthinker_named_or_joinable"]


def test_static_html_is_real_interactive_and_never_posts_or_fetches():
    html = HTML.read_text(encoding="utf-8")
    for token in (
        'id="form"', 'id="mode"', 'id="paste"', 'id="upload"',
        'id="link"', 'id="template"', 'id="download"',
        'id="rights"', 'id="status"', 'id="result"',
        'type="file"', 'Download draft JSON',
        "INCOMPLETE_RULES", "AWAITING_INDEPENDENT_RULE_REVIEW",
        "addEventListener(\"submit\"", "new Blob(",
        "textContent=", "connect-src 'none'",
        "AIDY", "GoldThinker",
    ):
        assert token in html
    assert "fetch(" not in html
    assert "XMLHttpRequest" not in html
    assert "innerHTML" not in html
    assert "multipart/form-data" not in html
    assert "action=\"http" not in html
    assert "paper_trading_enabled:true" not in html


def test_offline_form_has_exact_ten_rule_fields_and_source_modes():
    body = HTML.read_text(encoding="utf-8")
    for field in RULE_FIELDS:
        assert f'id="{field}"' in body
    for mode in ("paste", "upload", "link", "template"):
        assert f'value="{mode}"' in body


def test_untrusted_upload_mime_spoofing_detected_by_signature():
    with pytest.raises(IntakeRejected, match="BINARY_UPLOAD_REJECTED"):
        draft(mode="upload", value=b"PK\x03\x04fake_zip",
              filename="safe.txt", media_type="text/plain")


def test_missing_rules_and_original_source_not_equivalent_to_profit_pass():
    p = draft(mode="template", value="session_range",
              rules={field:"" for field in RULE_FIELDS})
    assert p["status"] == "INCOMPLETE_RULES"
    assert len(p["missing_rules"]) == 10
    assert not p["real_xauusd_profit_evaluated"]


def test_downloadable_html_is_valid_html_with_one_form():
    from html.parser import HTMLParser

    class Counter(HTMLParser):
        def __init__(self):
            super().__init__()
            self.form_count = 0
            self.script_count = 0

        def handle_starttag(self, tag, attrs):
            if tag == "form":
                self.form_count += 1
            if tag == "script":
                self.script_count += 1

    parser = Counter()
    parser.feed(HTML.read_text())
    assert parser.form_count == 1
    assert parser.script_count == 1
