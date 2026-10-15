"""Day31 independent adversarial report parity and misleading-claim rejection."""
from __future__ import annotations

import csv
import io
import json
from copy import deepcopy
from hashlib import sha256
from shutil import copytree

import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from test_strategy_lab_oos_protocol import sample_history

from aidy.strategy_lab_report_adversarial import (
    _check_all_cost_stress,
    _check_all_trades,
    audit_outcome_json,
    independent_report_audit,
    no_trade_analysis,
    write_review_packet,
)
from aidy.strategy_lab_report_contract import _hash
from aidy.strategy_lab_report_exports import (
    build_export_bundle,
    validate_research_receipt,
    verify_export_bundle,
)
from scripts.strategy_lab.day29_canonical_report_acceptance import audit_source


@pytest.fixture(scope="module")
def canonical():
    return {
        "status": "PASS",
        "scope": "CANONICAL_AIDY_REPORT_REPLAY_NOT_GOLDTHINKER_PRODUCTION",
        "paper_and_live_performance_qualified": False,
        "report": audit_source(sample_history()),
    }


@pytest.fixture(scope="module")
def actual_pdf_csv(canonical, tmp_path_factory):
    out = tmp_path_factory.mktemp("day31_original_exports")
    result = build_export_bundle(canonical, out)
    assert result["status"] == "PASS"
    return out


def altered_bundle(original, tmp_path, relative):
    out = tmp_path/"mutated"
    copytree(original, out)
    return out, out/relative


def resign_file_in_manifest(out, name):
    f = out/name
    manifest_path = out/"manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][name]["sha256"] = sha256(f.read_bytes()).hexdigest()
    manifest["files"][name]["bytes"] = f.stat().st_size
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def altered_csv(out, name, field, value):
    path = out/name
    with path.open(encoding="utf-8", newline="") as input_file:
        reader = csv.DictReader(input_file)
        headers, rows = reader.fieldnames, list(reader)
    assert headers is not None
    rows[0][field] = value
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    resign_file_in_manifest(out, name)


def forged_profit_pdf(out):
    path = out/"research_report.pdf"
    original = PdfReader(str(path))
    writer = PdfWriter()
    for page in original.pages:
        writer.add_page(page)
    extra = io.BytesIO()
    forged = canvas.Canvas(extra)
    forged.drawString(75, 710, "VERIFIED LIVE PROFIT: 100 percent guaranteed returns")
    forged.save()
    extra.seek(0)
    writer.add_page(PdfReader(extra).pages[0])
    with path.open("wb") as target:
        writer.write(target)
    resign_file_in_manifest(out, "research_report.pdf")


def test_independent_pdf_and_full_csv_parity_matches_original(actual_pdf_csv, canonical):
    result = independent_report_audit(actual_pdf_csv, canonical)
    assert result["status"] == "PASS"
    assert result["reviewed_all_trade_fields"] == 4
    assert result["reviewed_all_stress_fields"] == 3
    assert result["reviewed_pdf_pages"] == 4
    assert len(result["export_manifest_sha256"]) == 64
    assert result["source_type"] == "internal_synthetic_trade_cash_not_live"
    assert not result["independent_human_review_complete"]
    assert not result["customer_publication_permitted"]


@pytest.mark.parametrize(("name","field","value"), [
    ("trades.csv", "opened_at_utc", "2026-01-01T00:00:00Z"),
    ("trades.csv", "direction", "short"),
    ("trades.csv", "position_id", "forged_trade_900"),
    ("cost_scenarios.csv", "candidate_commission_usd", "-99.00"),
    ("cost_scenarios.csv", "candidate_slippage_usd", "99.00"),
    ("cost_scenarios.csv", "extra_spread_ticks_per_side", "999"),
    ("cost_scenarios.csv", "cash_charge_multiplier", "999"),
    ("cost_scenarios.csv", "independent_blind_clock_long_net_usd", "9999.00"),
])
def test_changed_single_source_cell_even_with_resigned_manifest_is_rejected(
    actual_pdf_csv, canonical, tmp_path, name, field, value,
):
    out, _ = altered_bundle(actual_pdf_csv, tmp_path, name)
    altered_csv(out, name, field, value)
    # Assert these are actual Day30 verifier blind-spots: a matching
    # manifest and unchanged headline values previously passed.
    assert verify_export_bundle(out, canonical)["status"] == "PASS"
    with pytest.raises(ValueError, match="field-level"):
        independent_report_audit(out, canonical)


def test_pdf_with_forged_profit_appendix_even_when_resigned_rejected(
    actual_pdf_csv, canonical, tmp_path,
):
    out, _ = altered_bundle(actual_pdf_csv, tmp_path, "research_report.pdf")
    forged_profit_pdf(out)
    assert verify_export_bundle(out, canonical)["status"] == "PASS"
    with pytest.raises(ValueError, match="forbidden fabricated"):
        independent_report_audit(out, canonical)


@pytest.mark.parametrize(("mutator","message"), [
    (lambda p: p["report"]["identity"].update(
        {"customer_can_connect": True}), "cannot be published|no unqualified"),
    (lambda p: p["report"]["production"]["paper"].update(
        {"forward_paper_pnl": "5000.00"}), "no unqualified"),
    (lambda p: p["report"]["production"]["elite20"].update(
        {"portfolio_pnl": "1000000.00"}), "no unqualified"),
    (lambda p: p["report"]["research"]["evidence_rating"].update(
        {"score_out_of_100": 100}), "no unqualified"),
    (lambda p: p["report"]["provenance"].update(
        {"numeric_field_lineage": {}}), "provenance"),
])
def test_rehashed_customer_profit_and_fake_score_claims_rejected(
    canonical, mutator, message,
):
    changed = deepcopy(canonical)
    mutator(changed)
    changed["report"]["canonical_result_sha256"] = _hash({
        k: v for k, v in changed["report"].items()
        if k != "canonical_result_sha256"
    })
    with pytest.raises(ValueError, match=message):
        validate_research_receipt(changed)


def test_zero_trades_produce_unknown_not_misleading_zero_percent():
    no_trades = no_trade_analysis([])
    assert no_trades["status"] == "NO_TRADES_INSUFFICIENT_EVIDENCE"
    assert no_trades["net_trading_expectancy_usd"] is None
    assert no_trades["score_out_of_100"] is None
    assert no_trades["win_rate_percent"] is None
    assert not no_trades["goldthinker_publication_permitted"]
    with pytest.raises(ValueError, match="only empty"):
        no_trade_analysis([{"net_usd": "10.00"}])
    with pytest.raises(ValueError, match="untrusted"):
        no_trade_analysis(None)


def test_empty_trading_journal_with_fake_positive_cash_rejected(canonical):
    changed = deepcopy(canonical)
    changed["report"]["research"]["trades"] = []
    changed["report"]["canonical_result_sha256"] = _hash({
        k: v for k, v in changed["report"].items()
        if k != "canonical_result_sha256"
    })
    with pytest.raises(ValueError, match="incomplete original journal"):
        validate_research_receipt(changed)


def test_independent_reviewer_rejects_no_trades_and_missing_scenario_files(
    actual_pdf_csv, canonical, tmp_path,
):
    out, _ = altered_bundle(actual_pdf_csv, tmp_path, "cost_scenarios.csv")
    (out/"cost_scenarios.csv").unlink()
    with pytest.raises(FileNotFoundError):
        independent_report_audit(out, canonical)


def test_human_review_packet_is_not_falsely_self_approved(
    actual_pdf_csv, canonical, tmp_path,
):
    audit = independent_report_audit(actual_pdf_csv, canonical)
    attacks = [{"name": "modified_cost_charge", "outcome": "REJECTED",
                "rejection_type": "ValueError"}]
    path = tmp_path/"DAY31_OWNER_REVIEW.md"
    write_review_packet(path, audit, attacks)
    text = path.read_text(encoding="utf-8")
    assert "PENDING HUMAN REVIEW" in text
    assert "Reviewer name: NOT PROVIDED" in text
    assert "independently" in text.lower()
    assert "REJECTED" in text
    evidence = audit_outcome_json(actual_pdf_csv, canonical, attacks)
    assert evidence["adversarial_engineering_accepted"]
    assert not evidence["overall_owner_day31_stage_pass"]


def test_accepted_engineering_result_refuses_missing_or_successful_attack(
    actual_pdf_csv, canonical,
):
    with pytest.raises(ValueError, match="all attacks rejected"):
        audit_outcome_json(actual_pdf_csv, canonical, [])
    with pytest.raises(ValueError, match="all attacks rejected"):
        audit_outcome_json(
            actual_pdf_csv, canonical,
            [{"name": "bad", "outcome": "ACCEPTED", "rejection_type": "none"}],
        )


def test_field_audit_uses_all_expected_trades_and_cost_scenarios(actual_pdf_csv, canonical):
    assert _check_all_trades(actual_pdf_csv, canonical["report"]) == 4
    assert _check_all_cost_stress(actual_pdf_csv, canonical["report"]) == 3
