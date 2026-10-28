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
