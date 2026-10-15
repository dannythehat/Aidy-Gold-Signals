"""Day33 owner-only dashboard and frozen source validation."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from test_strategy_lab_oos_protocol import sample_history

from aidy.strategy_lab_owner_dashboard import (
    _source_url,
    build_snapshot,
    export_dashboard,
    render_owner_html,
    verify_snapshot,
)
from scripts.strategy_lab.day29_canonical_report_acceptance import audit_source
from scripts.strategy_lab.day32_100_job_acceptance import exercise

CATALOGUE = Path(__file__).resolve().parents[1]/"research/strategy_lab/day33_gold_edge_83_snapshot.json"


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    catalogue = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    proof, trials = exercise(tmp_path_factory.mktemp("day33_queue")/"queue.sqlite")
    original = {
        "status": "PASS",
        "scope": "CANONICAL_AIDY_REPORT_REPLAY_NOT_GOLDTHINKER_PRODUCTION",
        "paper_and_live_performance_qualified": False,
        "independent_real_historical_query_job_ids": ["replay_one", "replay_two"],
        "report": audit_source(sample_history()),
    }
    return catalogue, trials, proof, original


@pytest.fixture(scope="module")
def dashboard(source):
    return build_snapshot(*source)


def test_eighty_three_real_original_drive_rows_still_unqualified(dashboard):
    assert len(dashboard["candidates"]) == 83
    assert dashboard["candidates"][0]["id"] == "S001"
    assert dashboard["candidates"][-1]["id"] == "S083"
    assert dashboard["counts"]["independently_qualified_strategies"] == 0
    assert all(x["research_stage"] == "NOT TESTED"
               and x["aidy_score_100"] is None
               and x["paper_net_pnl_usd"] is None
               and not x["join_available"] for x in dashboard["candidates"])


def test_source_provenance_keeps_hundred_synthetic_jobs_separate(dashboard):
    assert dashboard["counts"]["synthetic_queue_experiments_completed"] == 100
    assert len(dashboard["batch"]["experiments"]) == 100
    assert dashboard["batch"]["not_mapped_to_gold_edge_candidate_ids"]
    assert all(not x["profitability_verified"]
               for x in dashboard["batch"]["experiments"])
    assert dashboard["research_reference"]["nine_factor_score"] is None
    assert dashboard["counts"]["actual_paper_accounts"] == 0
    assert dashboard["billing"] is None


def test_all_candidates_have_real_original_source_links_and_blockers(dashboard):
    for candidate in dashboard["candidates"]:
        assert candidate["source_url"].startswith("https://")
        assert len(candidate["blockers"]) >= 3
        assert candidate["goldthinker_system_name"] is None
    assert dashboard["candidates"][5]["blockers"][0] == "Source not reviewed"


def test_actual_offline_owner_html_and_machine_json_export(dashboard, tmp_path):
    receipt = export_dashboard(dashboard, tmp_path)
    html = (tmp_path/"owner_research_dashboard.html").read_text(encoding="utf-8")
    assert len(receipt["files"]) == 2
    assert html.count('data-stage="not-tested"') == 83
    assert html.count("Synthetic complete") == 100
    for label in ("S001", "S083", "AIDY", "GoldThinker",
                  "Gold Edge workbook", "ORANGE", "NOT TESTED",
                  dashboard["snapshot_sha256"]):
        assert label.lower() in html.lower()
    assert json.loads((tmp_path/"owner_dashboard_data.json").read_text()) == dashboard
    assert "checkout" not in html.lower()
    assert "stripe" not in html.lower()


def test_same_source_bytes_yield_same_complete_export(dashboard, tmp_path):
    first = export_dashboard(dashboard, tmp_path/"first")
    second = export_dashboard(dashboard, tmp_path/"second")
    assert first == second
    assert (tmp_path/"first/owner_research_dashboard.html").read_bytes() == (
        tmp_path/"second/owner_research_dashboard.html"
    ).read_bytes()


@pytest.mark.parametrize("invalid", [
    "javascript:unsupported",
    "http://github.com/example",
    "https://github.com.fake.test/resource",
    "https://unapproved.example.org/bad",
])
def test_untrusted_source_link_cannot_enter_owner_dashboard(source, invalid):
    catalogue, rows, proof, research = deepcopy(source)
    catalogue["candidates"][0]["source_url"] = invalid
    with pytest.raises(ValueError, match="unapproved"):
        build_snapshot(catalogue, rows, proof, research)


@pytest.mark.parametrize(("field", "bad"), [
    ("research_stage", "PERFORMANCE PASS"),
    ("independent_aidy_score", 98),
    ("grade", "GREEN"),
    ("goldthinker_status", "LIVE"),
])
def test_unverified_gold_edge_candidate_cannot_be_promoted(source, field, bad):
    catalogue, rows, proof, research = deepcopy(source)
    catalogue["candidates"][0][field] = bad
    with pytest.raises(ValueError, match="incorrectly promoted"):
        build_snapshot(catalogue, rows, proof, research)


def test_original_catalogue_must_contain_exactly_83_rows(source):
    catalogue, rows, proof, research = deepcopy(source)
    catalogue["candidates"].pop()
    with pytest.raises(ValueError, match="83 source rows"):
        build_snapshot(catalogue, rows, proof, research)


def test_faked_day32_profit_record_is_rejected(source):
    catalogue, rows, proof, research = deepcopy(source)
    rows[0]["profitability_verified"] = True
    with pytest.raises(ValueError, match="100-result source"):
        build_snapshot(catalogue, rows, proof, research)


def test_faked_day32_output_sha_is_rejected(source):
    catalogue, rows, proof, research = deepcopy(source)
    proof["results_sha256"] = "a"*64
    with pytest.raises(ValueError, match="100-result source"):
        build_snapshot(catalogue, rows, proof, research)


def test_faked_real_trading_rating_is_rejected(source):
    catalogue, rows, proof, research = deepcopy(source)
    research["report"]["research"]["evidence_rating"]["score_out_of_100"] = 100
    with pytest.raises(ValueError, match="tampered canonical"):
        build_snapshot(catalogue, rows, proof, research)


def test_faked_forward_paper_account_profit_is_rejected(source):
    catalogue, rows, proof, research = deepcopy(source)
    research["report"]["production"]["paper"]["forward_paper_pnl"] = "1000.00"
    with pytest.raises(ValueError, match="tampered canonical"):
        build_snapshot(catalogue, rows, proof, research)


def test_snapshot_hash_prevents_false_owner_success_counter(dashboard):
    bad = deepcopy(dashboard)
    bad["counts"]["independently_qualified_strategies"] = 11
    with pytest.raises(ValueError, match="hash"):
        verify_snapshot(bad)


def test_frozen_source_never_misrepresented_as_live_drive_sync(source):
    catalogue, rows, proof, research = deepcopy(source)
    catalogue["live_drive_sync"] = True
    with pytest.raises(ValueError, match="live or unqualified"):
        build_snapshot(catalogue, rows, proof, research)


def test_source_link_allowlist_exact_not_suffix():
    assert _source_url("https://github.com/example") == "https://github.com/example"
    assert _source_url("https://papers.ssrn.com/sol3/papers") is not None
    with pytest.raises(ValueError, match="unapproved"):
        _source_url("https://github.com.other.example/x")


def test_markup_escaped_when_original_title_contains_angle_characters(source):
    catalogue, rows, proof, research = deepcopy(source)
    catalogue["candidates"][0]["title"] = "<em>Example</em>"
    snapshot = build_snapshot(catalogue, rows, proof, research)
    rendered = render_owner_html(snapshot)
    assert "&lt;em&gt;Example&lt;/em&gt;" in rendered
    assert "<em>Example</em>" not in rendered
