"""Committed evidence retains 83 identities and every executed negative result."""
import csv
import hashlib
import json
from pathlib import Path

from scripts.oracle_gold.history import digest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/gold_oracle"


def test_original83_retained_without_unproven_aliases_or_independence():
    data = json.loads((OUT/"83_source_and_duplicate_audit.json").read_text())
    expected = data.pop("sha256")
    assert digest(data) == expected
    assert {r["id"] for r in data["rows"]} == {f"S{i:03}" for i in range(1, 84)}
    assert len(data["rows"]) == 83
    assert all(r["canonical_id"] == r["id"] and r["independence"] == "NOT_PROVEN" for r in data["rows"])
    assert data["coverage"]["all83_fully_audited"] is False
    assert sum(r["mechanics"] is not None for r in data["rows"]) == 6
    assert all(r["source_audit_status"] != "SOURCE_AUDITED" for r in data["rows"] if r["source_access"] == "SOURCE_ACCESS_BLOCKED")


def test_all36_results_and18_negative_scenarios_retained_and_no_apex_grade():
    result = json.loads((OUT/"strategy_results_register.json").read_text())
    expected = result.pop("sha256")
    assert digest(result) == expected
    rows = result["experiments"]
    assert len(rows) == 36 and len({(r["strategy_id"], r["year"], r["scenario"]) for r in rows}) == 36
    assert sum(r["net_sign"] == "NEGATIVE" for r in rows) == 18
    assert {r["year"] for r in rows} == {2023, 2024, 2025}
    assert all(r["status"] == "BLOCKED_PUBLISHER_LOOKAHEAD_DIAGNOSTIC_ONLY" for r in rows if r["strategy_id"] != "S010")
    assert result["execution_qualified_ids"] == [] and result["all83_tested"] is False
    for path, sha in result["ledger_file_sha256"].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == sha


def test_native_closed_trade_ledgers_reconcile_and_s010_is_separate_marked_model():
    result = json.loads((OUT/"strategy_results_register.json").read_text())
    for case in result["experiments"]:
        with (ROOT/case["ledger"]).open() as f:
            trades = list(csv.DictReader(f))
        assert len(trades) == case["closed_trades"]
        assert abs(sum(float(t["net_usd"]) for t in trades)-case["net_closed_usd"]) < .03
        if case["strategy_id"] != "S010":
            assert abs(case["net_closed_usd"]-case["net_marked_usd"]) < .05


def test_all61_original_source_urls_have_access_receipts():
    catalog = json.loads((ROOT/"research/strategy_lab/day33_gold_edge_83_snapshot.json").read_text())
    receipts = json.loads((OUT/"source_access_receipts.json").read_text())
    assert len(receipts) == 61
    assert {r["source_url"] for r in receipts} == {r["source_url"] for r in catalog["candidates"]}
    assert all(r["full_mechanics_audit"] is False for r in receipts)


def test_common_cost_comparison_retains_first_experiment_and_exact_data_identity():
    first = json.loads((OUT/"strategy_results_register.json").read_text())
    common = json.loads((OUT/"common_cost_results_register.json").read_text())
    sha = common.pop("sha256")
    assert digest(common) == sha
    assert len(common["experiments"]) == 36
    assert common["negative_scenario_results_retained"] == 18
    lookup = {(r["strategy_id"], r["year"], r["scenario"]): r for r in first["experiments"]}
    for row in common["experiments"]:
        old = lookup[(row["strategy_id"], row["year"], row["scenario"])]
        assert old["source_snapshot_sha256"] == row["source_snapshot_sha256"]
        assert old["ledger"] != row["ledger"]
        if row["strategy_id"] != "S010":
            assert row["causal_sizing_parity_status"] == "EXACT_LEDGER_AND_EQUITY_PARITY"
    for path, expected in common["ledger_file_sha256"].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == expected


def test_common_cost_reports_have_equal_total_round_trip_costs():
    import pytest
    for year in (2023, 2024, 2025):
        report = json.loads((OUT/"batch01_common"/str(year)/"report.json").read_text())
        assert report["common_total_round_trip_costs_across_systems"] is True
        for scenario in ("base", "stress"):
            costs = report["models"]["S010/"+scenario]["costs"]
            total = costs["spread_usd_per_oz"] + 2*costs["slippage_usd_per_oz_each_side"] + costs["commission_usd_per_oz_round_trip"]
            for ident in ("S005", "S006", "S007", "S008", "S009"):
                assert report["models"][ident+"/"+scenario]["rt_cost_per_oz_model"] == pytest.approx(total)


def test_dependence_and_tool_manifest_does_not_manufacture_portfolio_or_runtime_use():
    p = json.loads((OUT/"common_cost_dependence_and_capability_coverage.json").read_text())
    assert len(p["monthly_dependence"]) == 30
    assert all(r["common_months"] == 36 and r["independence_proven"] is False for r in p["monthly_dependence"])
    assert len(p["toolbox_use_or_exclusion"]) == 34
    assert sum(r["owner"] == "super_signals" for r in p["toolbox_use_or_exclusion"]) == 9
    assert p["portfolio"]["sum_of_independent_accounts_used_as_master"] is False
    assert p["original_entries_or_exits_changed"] is False
