"""Day31 independent second-path report reconciliation and adversarial review.

Distinct from Day30's first verifier: no trust in manifest-rehashed CSV inputs.
Every trade and EVERY cost scenario CSV cell must agree with the source result.
Human stage signoff is a separate explicit owner action, never self-attested.
"""
from __future__ import annotations

import csv
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from pypdf import PdfReader

from aidy.strategy_lab_report_contract import PERIODS
from aidy.strategy_lab_report_exports import (
    STRESS_HEADER,
    TRADE_HEADER,
    _decimal,
    validate_research_receipt,
    verify_export_bundle,
)

SCHEMA = "aidy.strategy_lab.day31.independent_adversarial_review.v1"
TRADE_FIELD_MAP = {
    "position_id": "position_id",
    "direction": "direction",
    "opened_at_utc": "opened_at_utc",
    "closed_at_utc": "closed_at_utc",
    "gross_usd": "gross_usd",
    "allocated_cash_costs_usd": "costs_usd",
    "net_usd": "net_usd",
}
SCENARIO_FIELD_MAP = {
    "scenario": "name",
    "extra_spread_ticks_per_side": "extra_spread_ticks_per_side",
    "cash_charge_multiplier": "cash_charge_multiplier",
    "candidate_gross_quote_side_usd": "candidate_gross_quote_side_usd",
    "candidate_commission_usd": "candidate_commission_usd",
    "candidate_slippage_usd": "candidate_slippage_usd",
    "candidate_funding_usd": "candidate_funding_usd",
    "candidate_net_usd": "candidate_net_usd",
    "independent_blind_clock_long_net_usd": "independent_blind_clock_long_net_usd",
    "blind_clock_short_net_usd": "blind_clock_short_net_usd",
    "independently_scheduled_same_session_long_net_usd":
        "independently_scheduled_same_session_long_net_usd",
    "candidate_minus_scheduled_naive_usd": "candidate_minus_scheduled_naive_usd",
}
NUMERIC = frozenset((
    "gross_usd", "allocated_cash_costs_usd", "net_usd",
    "extra_spread_ticks_per_side", "cash_charge_multiplier",
    "candidate_gross_quote_side_usd", "candidate_commission_usd",
    "candidate_slippage_usd", "candidate_funding_usd", "candidate_net_usd",
    "independent_blind_clock_long_net_usd", "blind_clock_short_net_usd",
    "independently_scheduled_same_session_long_net_usd",
    "candidate_minus_scheduled_naive_usd",
))
FORBIDDEN_CLAIMS = (
    "GUARANTEED RETURNS",
    "VERIFIED LIVE PROFIT",
    "LIVE GOLD TRADING PROFITS",
    "CUSTOMER ACCOUNT SUCCESS",
    "100% WIN RATE",
    "CERTIFIED REAL XAUUSD ALPHA",
)


def _csv(path: Path, header: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = csv.reader(stream, strict=True)
        observed = next(rows, None)
        if observed != list(header):
            raise ValueError("changed, repeated or missing CSV headers")
        data = list(rows)
    if not data or any(len(record) != len(header) for record in data):
        raise ValueError("truncated, malformed or zero-trade source CSV")
    return [dict(zip(header, record, strict=True)) for record in data]


def _match_column(actual: str, expected: object, name: str) -> None:
    if name in NUMERIC:
        if _decimal(actual) != Decimal(str(expected)):
            raise ValueError(f"field-level numeric source mismatch: {name}")
    elif actual != str(expected):
        raise ValueError(f"field-level source mismatch: {name}")


def _check_all_trades(out: Path, report: dict) -> int:
    trades = _csv(out / "trades.csv", TRADE_HEADER)
    original = report["research"]["trades"]
    if len(trades) != len(original):
        raise ValueError("original trade count does not reconcile")
    src = report["provenance"]["source_sha256"]["day24_sqlite_journal"]
    for number, (row, trade) in enumerate(zip(trades, original, strict=True), 1):
        constants = {
            "run_id": report["run_id"],
            "canonical_result_sha256": report["canonical_result_sha256"],
            "research_origin": "INTERNAL_SYNTHETIC_JOURNAL_NOT_GOLD_TRADING",
            "verified_journal_tip_sha256": src,
            "trade_number": number,
        }
        for field, original_value in constants.items():
            _match_column(row[field], original_value, field)
        for field, source_key in TRADE_FIELD_MAP.items():
            _match_column(row[field], trade[source_key], field)
    return len(trades)


def _check_all_cost_stress(out: Path, report: dict) -> int:
    rows = _csv(out / "cost_scenarios.csv", STRESS_HEADER)
    original = report["research"]["cost_stress"]
    if len(rows) != len(original):
        raise ValueError("original transaction cost scenario count mismatch")
    src = report["provenance"]["source_sha256"]
    for row, source in zip(rows, original, strict=True):
        constants = {
            "run_id": report["run_id"],
            "canonical_result_sha256": report["canonical_result_sha256"],
            "research_origin": "INTERNAL_SYNTHETIC_COST_STRESS_NOT_REAL_MARKET",
            "quote_snapshot_sha256": src["day25_synthetic_quotes"],
            "cost_policy_sha256": src["day25_cost_policy"],
        }
        for field, expected in constants.items():
            _match_column(row[field], expected, field)
        for field, source_key in SCENARIO_FIELD_MAP.items():
            _match_column(row[field], source[source_key], field)
    return len(rows)


def _check_pdf_parity(out: Path, report: dict) -> int:
    reader = PdfReader(str(out/"research_report.pdf"))
    if not 3 <= len(reader.pages) <= 8:
        raise ValueError("unqualified PDF page count")
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    upper = text.upper()
    if any(s in upper for s in FORBIDDEN_CLAIMS):
        raise ValueError("forbidden fabricated performance assertion in PDF")
    mandatory = [
        report["run_id"], report["canonical_result_sha256"],
        "NOT REAL GOLD PROFITS", "INTERNAL SYNTHETIC",
        "GoldThinker Elite 20", "UNAVAILABLE",
    ]
    m = report["research"]["accounting"]
    mandatory.extend((
        m["initial_capital_usd"], m["net_profit_usd"],
        m["final_cash_usd"], str(m["closed_trades"]),
    ))
    for name in PERIODS:
        period = report["research"]["periods"][name]
        mandatory.extend((name.replace("_", " ").title(),
                          period["realised_net_pnl_usd"]))
    for row in report["research"]["trades"]:
        mandatory.extend((row["gross_usd"], row["costs_usd"], row["net_usd"]))
    for row in report["research"]["cost_stress"]:
        mandatory.extend((
            row["name"].title(), row["candidate_net_usd"],
            row["independently_scheduled_same_session_long_net_usd"],
            row["candidate_minus_scheduled_naive_usd"],
        ))
    for name, weight in report["research"]["evidence_rating"]["factor_weights"]:
        mandatory.extend((name.replace("_", " ").title(), str(weight)))
    mandatory.extend(report["provenance"]["source_sha256"].values())
    if any(value not in text for value in mandatory):
        raise ValueError("PDF missing original journal amount, factor, or provenance")
    return len(reader.pages)


def independent_report_audit(out: Path, receipt: dict) -> dict:
    report = validate_research_receipt(receipt)
    day30 = verify_export_bundle(out, receipt)
    if not report["research"]["trades"]:
        raise ValueError("NO_TRADES: cannot advertise positive financial results")
    n_trades = _check_all_trades(out, report)
    n_scenarios = _check_all_cost_stress(out, report)
    pages = _check_pdf_parity(out, report)
    if (n_trades != day30["verified_complete_trades"]
            or n_scenarios != day30["verified_cost_stress_scenarios"]
            or pages != day30["verified_pdf_pages"]
            or day30["actual_forward_paper_pnl_available"] is not False
            or day30["goldthinker_master_portfolio_pnl_available"] is not False):
        raise ValueError("independent reviewer disagrees with Day30 source parity")
    return {
        "schema": SCHEMA, "status": "PASS",
        "source_run_id": report["run_id"],
        "canonical_result_sha256": report["canonical_result_sha256"],
        "export_manifest_sha256": sha256(
            (out/"manifest.json").read_bytes()
        ).hexdigest(),
        "reviewed_all_trade_fields": n_trades,
        "reviewed_all_stress_fields": n_scenarios,
        "reviewed_pdf_pages": pages,
        "source_type": "internal_synthetic_trade_cash_not_live",
        "independent_human_review_complete": False,
        "human_reviewer_status": "AWAITING_OWNER_OR_INDEPENDENT_HUMAN_REVIEW",
        "customer_publication_permitted": False,
        "actual_gold_strategy_profit_qualified": False,
    }


def no_trade_analysis(trades: list[dict]) -> dict:
    """Abstain on empty history; no 0%-win-rate or profitable claims."""
    if not isinstance(trades, list):
        raise TypeError("untrusted trade source")
    if trades:
        raise ValueError("only empty trade evidence uses NO_TRADES state")
    return {
        "status": "NO_TRADES_INSUFFICIENT_EVIDENCE",
        "net_trading_expectancy_usd": None,
        "win_rate_percent": None,
        "sharpe_annualized": None,
        "score_out_of_100": None,
        "goldthinker_publication_permitted": False,
        "live_or_paper_track_record_verified": False,
    }


def write_review_packet(path: Path, result: dict, attacks: list[dict]) -> None:
    """Create a reviewable checklist and explicit UNSIGNED reviewer slots."""
    lines = [
        "# Day31 independent human review packet",
        "",
        f"Run: `{result['source_run_id']}`",
        f"Source result SHA256: `{result['canonical_result_sha256']}`",
        f"Manifest SHA256: `{result['export_manifest_sha256']}`",
        "",
        "## Verified automated engineering inspection",
        "",
        f"- Full rows checked: {result['reviewed_all_trade_fields']}",
        f"- Full stress scenarios checked: {result['reviewed_all_stress_fields']}",
        f"- PDF pages checked: {result['reviewed_pdf_pages']}",
        "- No customer paper/live/Elite20 investment performance or joining implied",
        "- All trade profits in the exported report are INTERNAL SYNTHETIC",
        "",
        "## Attacks executed (all must have been rejected)",
        "",
    ]
    for attack in attacks:
        lines.append(
            f"- {attack['name']}: {attack['outcome']}"
            f" ({attack['rejection_type']})"
        )
    lines.extend([
        "",
        "## HUMAN REVIEW — REQUIRED, NOT SELF-SIGNED",
        "",
        "- [ ] Independently open all four PDF pages and examine labels, charts,",
        "      page layout, warnings, content and factual consistency",
        "- [ ] Compare PDF cash/fees/five reporting periods with trades.csv and",
        "      independent source canonical_result.json",
        "- [ ] Examine the cost-scenario chart against cost_scenarios.csv",
        "- [ ] Confirm genuine real-market XAUUSD profits are NOT claimed",
        "- [ ] Confirm GoldThinker individual paper/Elite20 accounts show NO",
        "      balances, customer join access or backtested profits",
        "- [ ] Review documented attack outcomes and limitations",
        "",
        "Reviewer name: NOT PROVIDED",
        "",
        "Date/time of review: NOT PROVIDED",
        "",
        "Decision: PENDING HUMAN REVIEW",
        "",
        "Day31 HUMAN PASS MUST NOT BE CLAIMED until an independent individual",
        "actually examines the PDF and originals and records their decision.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def audit_outcome_json(out: Path, receipt: dict, attacks: list[dict]) -> dict:
    result = independent_report_audit(out, receipt)
    if not attacks or any(row["outcome"] != "REJECTED" for row in attacks):
        raise ValueError("adversarial acceptance requires all attacks rejected")
    return {
        **result,
        "attacks_attempted": len(attacks),
        "attacks_rejected": len(attacks),
        "adversarial_engineering_accepted": True,
        "overall_owner_day31_stage_pass": False,
    }
