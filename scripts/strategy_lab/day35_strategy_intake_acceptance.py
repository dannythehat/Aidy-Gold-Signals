"""Day35 actual source-safe strategy interface acceptance.

Exercise all four submission modes and adversarial rejection against local
synthetic strategy drafts only. Day34 real Gold Edge source acceptance is a
separate CI step and none of the 83 collected systems is profit-tested.
"""
from __future__ import annotations

import json
from pathlib import Path

from aidy.strategy_lab_customer_intake import (
    RULE_FIELDS, IntakeRejected, prepare_intake, verify_draft,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/strategy_lab/day35"
HTML = ROOT / "web/strategy_lab/day35_private_intake_preview.html"
RULES = {
    "market": "XAUUSD",
    "timeframe": "H1",
    "trade_direction": "Long only in this imaginary rule fixture",
    "entry_rules": "After one fully closed H1 bar crosses previous high, enter next open",
    "exit_rules": "Exit after a maximum two fully closed bars",
    "stop_loss_rule": "Sample: fixed 2*ATR14 initial stop",
    "take_profit_rule": "Sample: target 3*ATR14, or two bar timeout",
    "position_sizing_rule": "Sample: risk budget 1% of simulated balance",
    "trading_session_and_timezone": "09:00–17:00 Europe/London including DST",
    "execution_and_cost_assumptions":
        "Sample bid ask, fees, variable spread and realistic slippage assumptions",
}


def _safe(mode: str, source: str | bytes, **opts) -> dict:
    item = prepare_intake(
        mode=mode, value=source, title="EXAMPLE INERT STRATEGY NOT TESTED",
        rules=RULES, **opts,
    )
    verify_draft(item)
    if (item["status"] != "AWAITING_INDEPENDENT_RULE_REVIEW"
            or item["eligible_for_production"]
            or item["aidy_research_executed"]
            or item["paper_or_live_trading_enabled"]):
        raise ValueError("unsafe intake promoted synthetic test")
    return item


def _reject(mode: str, source: str | bytes, **opts) -> str:
    try:
        _safe(mode, source, **opts)
    except IntakeRejected as exc:
        return exc.code
    raise ValueError("unsafe source passed customer intake preflight")


def audit_local_interface() -> dict:
    page = HTML.read_text(encoding="utf-8")
    for token in (
        "<form", 'id="paste"', 'id="upload"', 'id="link"',
        'id="template"', 'id="entry_rules"', 'id="download"',
        "connect-src 'none'", "new Blob(", "INCOMPLETE_RULES",
    ):
        if token not in page:
            raise ValueError("actual HTML input interface missing supported mode")
    examples = [
        _safe("paste", "Example: on H1 close above previous high, long next bar"),
        _safe("upload", b"// Inert Pine strategy example\nstrategy('Fixture')",
              filename="example.pine", media_type="text/plain"),
        _safe("link", "https://github.com/example/imaginary-gold-system"),
        _safe("template", "session_range"),
    ]
    partial = prepare_intake(
        mode="paste", value="Only one source fragment; incomplete setup",
        title="INCOMPLETE EXAMPLE STRATEGY",
        rules={key:"XAUUSD" if key == "market" else "" for key in RULE_FIELDS},
    )
    if (partial["status"] != "INCOMPLETE_RULES"
            or len(partial["missing_rules"]) != 9):
        raise ValueError("missing-rule guidance changed")
    denied = {
        "exe": _reject("upload", b"MZbadbinary", filename="attack.exe"),
        "zip_as_text": _reject("upload", b"PK\x03\x04trick",
                               filename="strat.txt", media_type="text/plain"),
        "html_xss": _reject("paste", "<script>alert(1)</script>"),
        "stolen_key": _reject("paste", "api_key=super_secret_access_value"),
        "internal_ssrf": _reject("link", "https://127.0.0.1/private"),
        "unsafe_scheme": _reject("link", "javascript:alert(1)"),
        "unsupported_upload": _reject("upload", b"fake pdf",
                                      filename="strategy.pdf"),
    }
    if len(denied) != 7 or len(set(denied.values())) < 3:
        raise ValueError("adversarial intake cases not independently rejected")
    return {
        "status": "PASS",
        "scope": "DAY35_PRIVATE_LOCAL_STRATEGY_INTAKE_NO_SERVER",
        "html_form_created": True,
        "four_modes_exercised": sorted(x["source"]["kind"] for x in examples),
        "example_drafts": examples,
        "missing_rule_guidance_fields": len(partial["missing_rules"]),
        "attacks_rejected": denied,
        "original_gold_edge_systems_backtested": 0,
        "trusted_customer_server_running": False,
        "real_accounts_or_goldthinker_publication_enabled": False,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        proof = audit_local_interface()
        examples = proof.pop("example_drafts")
        (OUT / "four_safe_test_drafts.json").write_text(
            json.dumps(examples, indent=2, sort_keys=True)+"\n", encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001 - fail closed and archive block
        proof = {
            "status": "BLOCKED", "error_type": type(exc).__name__,
            "message": str(exc)[:300],
            "original_gold_edge_systems_backtested": 0,
        }
    (OUT / "intake_acceptance.json").write_text(
        json.dumps(proof, indent=2, sort_keys=True)+"\n", encoding="utf-8",
    )
    print(json.dumps(proof, sort_keys=True))
    return 0 if proof["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
