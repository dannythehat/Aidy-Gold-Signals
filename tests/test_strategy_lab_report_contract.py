"""Day29 audit-quality results contract, period arithmetic and provenance tests."""
from __future__ import annotations

import json
from copy import deepcopy

import pytest
from test_strategy_lab_oos_protocol import sample_history

from aidy.strategy_lab_report_contract import (
    PERIODS,
    build_canonical_report,
    verify_canonical_report,
)
from scripts.strategy_lab.day24_ledger_metrics_acceptance import OUT as DAY24_OUT
from scripts.strategy_lab.day25_baselines_cost_stress_acceptance import audit as cost_audit
from scripts.strategy_lab.day28_evidence_rating_acceptance import audit_source as rating_audit
from scripts.strategy_lab.day29_canonical_report_acceptance import AS_OF, audit_source

imported = None


@pytest.fixture(scope="module")
def trusted():
    evidence = rating_audit(sample_history())
    journal = json.loads(DAY24_OUT.read_text(encoding="utf-8"))
    costs = cost_audit()
    return journal, costs, evidence


def report(*args, when=AS_OF):
    return build_canonical_report(*args, as_of_utc=when)


def test_real_sqlite_research_journal_canonical_metrics_and_periods(trusted):
    obj = report(*trusted)
    verify_canonical_report(obj)
    assert obj["identity"]["research_engine"] == "AIDY"
    assert obj["identity"]["customer_brand"] == "GoldThinker"
    assert obj["identity"]["goldthinker_system_name"] is None
    assert obj["identity"]["strategy_id"] is None
    assert not obj["identity"]["publication_allowed"]
    assert not obj["identity"]["customer_can_connect"]
    assert obj["research"]["accounting"]["initial_capital_usd"] == "10000.00"
    assert obj["research"]["accounting"]["final_cash_usd"] == "10013.00"
    assert obj["research"]["accounting"]["net_profit_usd"] == "13.00"
    assert obj["research"]["accounting"]["transaction_costs_usd"] == "-2.00"
    assert [x["net_usd"] for x in obj["research"]["trades"]] == [
        "9.50", "-5.50", "14.50", "-5.50"
    ]
    assert tuple(obj["research"]["periods"]) == PERIODS
    assert [obj["research"]["periods"][key]["realised_net_pnl_usd"]
            for key in PERIODS] == ["9.00", "13.00", "9.00", "13.00", "13.00"]
    assert obj["research"]["evidence_rating"]["score_out_of_100"] is None
    assert obj["research"]["evidence_rating"]["governance"] == "ORANGE_INVESTIGATE"


def test_forward_paper_and_elite20_have_no_fabricated_funds(trusted):
    x = report(*trusted)
    assert x["production"]["paper"]["periods"] is None
    assert x["production"]["paper"]["forward_paper_pnl"] is None
    assert x["production"]["paper"]["account_id"] is None
    assert x["production"]["elite20"]["combined_account_id"] is None
    assert x["production"]["elite20"]["portfolio_pnl"] is None
    assert x["production"]["elite20"]["periods"] is None
    assert not x["account_separation"]["portfolio_return_is_sum_of_system_balances"]
    assert not x["lifecycle"]["aidy_research_qualified"]
    assert not x["lifecycle"]["forward_paper_production_qualified"]


def test_every_exposed_accounting_and_trade_dollar_has_source_trace(trusted):
    x = report(*trusted)
    origins = x["provenance"]["numeric_field_lineage"]
    src = x["provenance"]["source_sha256"]
    for k in x["research"]["accounting"]:
        if k.endswith(("_usd", "_percent", "_trades")) or k in (
            "wins", "losses", "breakeven", "profit_factor", "sharpe_annualized"
        ):
            pointer = f"/research/accounting/{k}"
            assert origins[pointer]["source_sha256"] == src["day24_sqlite_journal"]
    for i, t in enumerate(x["research"]["trades"]):
        for k in ("gross_usd", "costs_usd", "net_usd"):
            path = f"/research/trades/{i}/{k}"
            assert origins[path]["source_sha256"] == src["day24_sqlite_journal"]
    for period in PERIODS:
        for k in ("closed_trades", "wins", "realised_net_pnl_usd",
                  "allocated_cash_costs_usd"):
            path = f"/research/periods/{period}/{k}"
            assert origins[path]["source_sha256"] == src["day24_sqlite_journal"]
    for i, _ in enumerate(x["research"]["evidence_rating"]["factor_weights"]):
        assert origins[f"/research/evidence_rating/factor_weights/{i}/1"][
            "source_sha256"
        ] == src["day28_rating_policy"]
    for i, scenario in enumerate(x["research"]["cost_stress"]):
        for field in scenario:
            if field.endswith("_usd"):
                assert f"/research/cost_stress/{i}/{field}" in origins


def test_version_hash_stable_through_identical_sqlite_replays(trusted):
    first = report(*trusted)
    second = audit_source(sample_history())
    assert first == second
    assert first["run_id"] == second["run_id"]
    assert len(first["canonical_result_sha256"]) == 64


@pytest.mark.parametrize(("field", "new"), [
    ("net_profit_usd", "15.00"),
    ("final_cash_usd", "999999.00"),
    ("transaction_costs_usd", "-1.99"),
    ("closed_trades", 3),
])
def test_modified_total_without_original_cash_journal_refused(trusted, field, new):
    journal, cost, rating = deepcopy(trusted)
    journal["metrics"][field] = new
    with pytest.raises(ValueError, match="ledger accounting|source trace"):
        report(journal, cost, rating)


def test_trade_cost_and_duplicate_trades_denied(trusted):
    for mutator in ("costs", "duplicate"):
        journal, cost, rating = deepcopy(trusted)
        if mutator == "costs":
            journal["metrics"]["trades"][0]["costs_usd"] = "-7.00"
        else:
            journal["metrics"]["trades"][1]["position_id"] = (
                journal["metrics"]["trades"][0]["position_id"]
            )
        with pytest.raises(ValueError, match="trade cash|duplicate"):
            report(journal, cost, rating)


def test_original_provenance_digest_mismatch_never_is_accepted(trusted):
    journal, cost, rating = deepcopy(trusted)
    rating["upstream_evidence"]["day24_two_replays_tip_sha256"] = "f"*64
    with pytest.raises(ValueError, match="canonical source trace"):
        report(journal, cost, rating)
    journal, cost, rating = deepcopy(trusted)
    cost["benchmark_and_stress"]["reference_journal_tip_sha256"] = "e"*64
    with pytest.raises(ValueError, match="canonical source trace"):
        report(journal, cost, rating)


def test_hypothetical_relabel_of_unqualified_rating_to_green_refused(trusted):
    journal, cost, rating = deepcopy(trusted)
    rating["rating"]["governance"] = "GREEN_HIGH_PRIORITY"
    rating["rating"]["score_out_of_100"] = 100
    with pytest.raises(ValueError, match="unqualified historical"):
        report(journal, cost, rating)


def test_future_closed_trade_cannot_appear_as_current_statement(trusted):
    with pytest.raises(ValueError, match="future trade"):
        report(*trusted, when="2026-09-30T09:00:00Z")


@pytest.mark.parametrize("as_of", ["2026-10-01", "2026-10-01T11:04:00+03:00", "oops"])
def test_non_utc_or_invalid_as_of_rejected(trusted, as_of):
    with pytest.raises(ValueError):
        report(*trusted, when=as_of)


def test_report_hash_detects_changed_paper_balance_or_public_availability(trusted):
    obj = report(*trusted)
    for modify in ("paper_balance", "publish"):
        changed = deepcopy(obj)
        if modify == "paper_balance":
            changed["production"]["paper"]["forward_paper_pnl"] = "1000.00"
        else:
            changed["identity"]["customer_can_connect"] = True
        with pytest.raises(ValueError, match="tampered"):
            verify_canonical_report(changed)


def test_zero_data_on_separate_paper_account_is_absent_not_zero(trusted):
    report_obj = report(*trusted)
    assert report_obj["production"]["paper"]["forward_paper_pnl"] is None
    assert report_obj["production"]["elite20"]["portfolio_pnl"] is None
    assert report_obj["research"]["synthetic_historical_net_pnl_only"] is True
    assert report_obj["output_contract"]["pdf"] == "DAY30_NOT_BUILT"
    assert report_obj["output_contract"]["csv"] == "DAY30_NOT_BUILT"
