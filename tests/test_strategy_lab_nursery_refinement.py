"""Tests for private frozen Nursery refinement review; synthetic structure ONLY."""
import json
from pathlib import Path
import pytest
from aidy.strategy_lab_nursery_refinement import (
    METHOD, VERSIONS, VALUES, build_refinement, verify_draft, write_bundle,
)

def synthetic_source():
    years = {}
    for year in ("2025", "2026"):
        examples = {}
        for name, (profit, dd) in zip(VERSIONS, VALUES[year]):
            examples[name] = {
                "variant": name, "quote_case": "assumed",
                "profit_usd": profit, "max_dd_pct": dd,
            }
        years[year] = {
            "h1_rows": 5866 if year == "2025" else 4382,
            "source_csv_sha256": ("a" if year == "2025" else "b") * 64,
            "scenarios": {"assumed_bid_ask": examples},
        }
    return {
        "method": METHOD, "status": "HISTORICAL_RESEARCH_NO_PAPER_ORDERS",
        "source_years": [2025, 2026], "excluded_years": [2020, 2021],
        "modelled_vantage_costs_verified": False,
        "broker_swaps_and_margin_stopout_modelled": False,
        "no_optimization_claimed": True, "years": years,
    }

def test_comparison_is_exact_source_grounded_and_owner_locked():
    result = build_refinement(synthetic_source())
    verify_draft(result)
    assert result["proposed_compromise"] == "hourly_state_half_new"
    assert result["comparison"]["2025"]["hourly_state_half_new"]["dd_improvement_pp"] == 11.599
    assert result["comparison"]["2026"]["hourly_state_half_new"]["dd_improvement_pp"] == 15.240
    assert result["comparison"]["2025"]["hourly_state_half_new"]["profit_usd"] == 10048.65
    assert result["comparison"]["2026"]["hourly_state_half_new"]["profit_usd"] == 10542.25
    assert result["selected_version"] is None
    assert result["school_admission_approved"] is False
    assert result["paper_trading_authorised"] is False
    assert result["publication_authorised"] is False

def test_readable_private_appendix_and_pdf(tmp_path: Path):
    p = write_bundle(synthetic_source(), tmp_path)
    assert p["draft_sha256"]
    body = (tmp_path / "nursery_refinement_package.md").read_text()
    assert "Original versus actual tested variants" in body
    assert "15.240 pp" in body
    assert "owner" in body.lower()
    pdf = tmp_path / "nursery_refinement_internal_appendix.pdf"
    assert pdf.stat().st_size > 1000
    from pypdf import PdfReader
    reader = PdfReader(str(pdf))
    assert len(reader.pages) >= 2
    txt = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "System Builder" in txt and "PENDING" in txt
    assert json.loads((tmp_path / "nursery_refinement_package.json").read_text()) == p

@pytest.mark.parametrize("path,value", [
    (("status",), "BROKER_LIVE"),
    (("modelled_vantage_costs_verified",), True),
    (("years", "2025", "h1_rows"), 12),
    (("years", "2026", "scenarios", "assumed_bid_ask", "original", "profit_usd"), 151111.00),
    (("years", "2026", "scenarios", "assumed_bid_ask", "hourly_state_half_new", "max_dd_pct"), -2.0),
])
def test_wrong_or_fabricated_evidence_fails_closed(path, value):
    src = synthetic_source()
    node = src
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    with pytest.raises((ValueError, KeyError)):
        build_refinement(src)

def test_removing_a_variant_or_year_fails():
    src = synthetic_source()
    del src["years"]["2025"]["scenarios"]["assumed_bid_ask"]["half_new_plus_open_trim"]
    with pytest.raises(ValueError, match="missing"):
        build_refinement(src)
    src = synthetic_source()
    del src["years"]["2026"]
    with pytest.raises(ValueError, match="missing"):
        build_refinement(src)

@pytest.mark.parametrize("field,value", [
    ("paper_trading_authorised", True),
    ("real_trading_authorised", True),
    ("publication_authorised", True),
    ("customer_copy_authorised", True),
    ("selected_version", "hourly_state_half_new"),
    ("paper_profit_usd", 99999),
    ("school_admission_approved", True),
])
def test_no_premature_stage_or_money_authority_even_if_rehashed(field, value):
    from aidy.strategy_lab_nursery_refinement import checksum
    review = build_refinement(synthetic_source())
    review[field] = value
    review["draft_sha256"] = checksum({
        k: v for k, v in review.items() if k != "draft_sha256"})
    with pytest.raises(ValueError, match="Nursery draft"):
        verify_draft(review)

def test_source_drift_changes_private_digest():
    src = synthetic_source()
    first = build_refinement(src)
    src["years"]["2025"]["source_csv_sha256"] = "c" * 64
    newer = build_refinement(src)
    assert first["draft_sha256"] != newer["draft_sha256"]
