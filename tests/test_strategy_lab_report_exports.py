"""Day30 genuine PDF/CSV/charts and tamper-proof numeric parity regressions."""
from __future__ import annotations

import csv
import io
import json
from copy import deepcopy
from shutil import copytree

import pytest
from test_strategy_lab_oos_protocol import sample_history

from aidy.strategy_lab_report_contract import _hash
from aidy.strategy_lab_report_exports import (
    SCHEMA,
    STRESS_HEADER,
    TRADE_HEADER,
    _csv_cell,
    build_export_bundle,
    validate_research_receipt,
    verify_export_bundle,
)
from scripts.strategy_lab.day29_canonical_report_acceptance import audit_source


@pytest.fixture(scope="module")
def source():
    report = audit_source(sample_history())
    return {
        "status": "PASS",
        "scope": "CANONICAL_AIDY_REPORT_REPLAY_NOT_GOLDTHINKER_PRODUCTION",
        "report": report,
        "paper_and_live_performance_qualified": False,
    }


@pytest.fixture(scope="module")
def exported(source, tmp_path_factory):
    path = tmp_path_factory.mktemp("day30_pdf_csv_production")
    result = build_export_bundle(source, path)
    return path, result


def test_actual_downloadable_bundle_contains_complete_data_and_pdf(exported):
    path, output = exported
    assert output["status"] == "PASS"
    assert output["source_canonical_sha256"]
    assert output["verified_complete_trades"] == 4
    assert output["verified_cost_stress_scenarios"] == 3
    assert 3 <= output["verified_pdf_pages"] <= 8
    assert output["pdf_csv_json_net_profit_usd"] == "13.00"
    assert len(output["file_shas"]) == 7
    assert set(output["file_shas"]) == {
        "canonical_result.json", "trades.csv", "cost_scenarios.csv",
        "equity_curve.png", "cost_stress.png", "research_report.pdf",
        "report_preview_page1.png",
    }
    assert (path/"research_report.pdf").read_bytes().startswith(b"%PDF")
    assert (path/"equity_curve.png").read_bytes().startswith(b"\x89PNG\r\n")
    assert (path/"report_preview_page1.png").read_bytes().startswith(b"\x89PNG\r\n")
    assert not output["actual_forward_paper_pnl_available"]
    assert not output["real_strategy_alpha_qualified"]


def test_complete_trade_csv_exact_cash_and_journal_tip(exported, source):
    path, _ = exported
    csvrows = list(csv.DictReader(io.StringIO(
        (path/"trades.csv").read_text(encoding="utf-8")
    )))
    assert tuple(csvrows[0]) == TRADE_HEADER
    assert len(csvrows) == 4
    assert [x["net_usd"] for x in csvrows] == [
        "9.50", "-5.50", "14.50", "-5.50"
    ]
    report = source["report"]
    for i, row in enumerate(csvrows, 1):
        assert row["trade_number"] == str(i)
        assert row["canonical_result_sha256"] == report["canonical_result_sha256"]
        assert row["verified_journal_tip_sha256"] == (
            report["provenance"]["source_sha256"]["day24_sqlite_journal"]
        )
        assert row["research_origin"] == "INTERNAL_SYNTHETIC_JOURNAL_NOT_GOLD_TRADING"


def test_all_original_cost_scenarios_reconcile(exported, source):
    path, _ = exported
    rows = list(csv.DictReader(io.StringIO(
        (path/"cost_scenarios.csv").read_text(encoding="utf-8")
    )))
    assert tuple(rows[0]) == STRESS_HEADER
    assert [x["scenario"] for x in rows] == ["base", "adverse", "severe"]
    assert [x["candidate_net_usd"] for x in rows] == ["8.30", "7.54", "6.60"]
    assert [x["independently_scheduled_same_session_long_net_usd"]
            for x in rows] == ["18.30", "17.54", "16.60"]
    assert [x["candidate_minus_scheduled_naive_usd"] for x in rows] == [
        "-10.00", "-10.00", "-10.00"
    ]
    assert all(x["canonical_result_sha256"] ==
               source["report"]["canonical_result_sha256"] for x in rows)
    assert all(x["research_origin"].endswith("NOT_REAL_MARKET") for x in rows)


def test_pdf_extract_has_genuine_source_hashes_and_no_public_perf(exported, source):
    from pypdf import PdfReader

    path, output = exported
    reader = PdfReader(str(path/"research_report.pdf"))
    text = "\n".join(p.extract_text() or "" for p in reader.pages)
    assert len(reader.pages) == output["verified_pdf_pages"]
    for expected in (
        "AIDY", "GoldThinker", "INTERNAL SYNTHETIC",
        "NOT REAL GOLD PROFITS", "Elite 20", "UNAVAILABLE",
        source["report"]["run_id"],
        source["report"]["canonical_result_sha256"],
        "10013.00", "13.00", "9.00",
        "Transaction-level audit", "Provenance appendix",
    ):
        assert expected in text
    assert "Source type: actual forward-paper investment returns" not in text


@pytest.mark.parametrize("filename", [
    "trades.csv", "cost_scenarios.csv", "research_report.pdf",
    "equity_curve.png", "report_preview_page1.png", "canonical_result.json",
])
def test_any_export_byte_tampering_fails_hash_verification(exported, source, tmp_path,
                                                            filename):
    original, _ = exported
    copied = tmp_path/"bundle"
    copytree(original, copied)
    with (copied/filename).open("ab") as fp:
        fp.write(b"bad-tainted-export")
    with pytest.raises(ValueError, match="SHA"):
        verify_export_bundle(copied, source)


def test_attacker_updates_manifest_after_csv_change_still_fails_values(exported, source,
                                                                        tmp_path):
    original, _ = exported
    copied = tmp_path/"bundle"
    copytree(original, copied)
    import hashlib
    raw = (copied/"trades.csv").read_text()
    bad = raw.replace("9.50", "99.50", 1)
    assert raw != bad
    (copied/"trades.csv").write_text(bad)
    manifest = json.loads((copied/"manifest.json").read_text())
    manifest["files"]["trades.csv"]["sha256"] = hashlib.sha256(
        bad.encode()
    ).hexdigest()
    manifest["files"]["trades.csv"]["bytes"] = len(bad.encode())
    (copied/"manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="CSV original transaction"):
        verify_export_bundle(copied, source)


def test_future_nonexistent_goldthinker_paper_pnl_cannot_be_exported(source):
    malicious = deepcopy(source)
    malicious["report"]["production"]["paper"]["forward_paper_pnl"] = "+99999.00"
    malicious["report"]["canonical_result_sha256"] = _hash({
        k: v for k, v in malicious["report"].items()
        if k != "canonical_result_sha256"
    })
    with pytest.raises(ValueError, match="no unqualified"):
        validate_research_receipt(malicious)


def test_public_name_or_customer_connection_never_populates_from_fixture(source):
    for key, value in (("customer_can_connect", True),
                       ("goldthinker_system_name", "The Down Hunter"),
                       ("publication_allowed", True)):
        malicious = deepcopy(source)
        malicious["report"]["identity"][key] = value
        malicious["report"]["canonical_result_sha256"] = _hash({
            k: v for k, v in malicious["report"].items()
            if k != "canonical_result_sha256"
        })
        with pytest.raises(ValueError, match="no unqualified|cannot be published"):
            validate_research_receipt(malicious)


def test_missing_provenance_refuses_any_export(source):
    malicious = deepcopy(source)
    malicious["report"]["provenance"]["numeric_field_lineage"][
        "/research/trades/0/net_usd"
    ]["source_sha256"] = "f"*64
    malicious["report"]["canonical_result_sha256"] = _hash({
        k: v for k, v in malicious["report"].items()
        if k != "canonical_result_sha256"
    })
    with pytest.raises(ValueError, match="original journal path"):
        validate_research_receipt(malicious)


@pytest.mark.parametrize("payload", [
    "=SUM(1,1)", "+HYPERLINK(1)", "-HACK()", "@NOW()", "\tFORMULA",
])
def test_spreadsheet_formula_injection_in_customer_text_is_denied(payload):
    with pytest.raises(ValueError, match="unsafe spreadsheet"):
        _csv_cell(payload)


def test_metadata_does_not_permit_paper_or_elite_20_gains(exported):
    path, output = exported
    manifest = json.loads((path/"manifest.json").read_text())
    assert manifest["schema"] == SCHEMA
    assert manifest["reference_research_only"] is True
    assert output["goldthinker_master_portfolio_pnl_available"] is False
    assert json.loads((path/"canonical_result.json").read_text())[
        "production"
    ]["elite20"]["combined_account_id"] is None


def test_verification_is_repeatable_without_rebuilding_any_chart(exported, source):
    path, first = exported
    assert first == verify_export_bundle(path, source)
    assert first == verify_export_bundle(path, source)
