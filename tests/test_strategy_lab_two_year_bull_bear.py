"""Never run AI tweaks after one year or only two bullish environments."""
from dataclasses import replace
from decimal import Decimal

import pytest

from aidy.strategy_lab_two_year_bull_bear import (
    SmallChange,
    VariantReport,
    YearReport,
    compare,
    eligibility,
    targeted_diagnosis,
)


def source(year=2025, **override):
    report = YearReport(
        year=year,
        regime="bull_year" if year != 2021 else "down_year",
        system="S010",
        rule_hash="a" * 64,
        execution_cost_hash="b" * 64,
        original_report_hash=("c" if year == 2025 else "d") * 64,
        real_source_hash=("e" if year == 2025 else "f") * 64,
        completed_real_months=12,
        starting_usd=Decimal(10000),
        net_usd=Decimal(5000),
        return_pct=Decimal(50),
        max_drawdown_pct=Decimal(-33),
        trades=83,
        profit_factor=Decimal("1.66"),
        worst_trade_usd=Decimal(-5000),
        has_protective_stop=False,
        leverage=Decimal("3.28"),
    )
    return replace(report, **override)


def variant(original, *, key="atr3_stop", net="5500", dd="-29", h="g"):
    return VariantReport(
        year=original.year,
        hypothesis_key=key,
        modified_rule_hash=h * 64,
        original_report_hash=original.original_report_hash,
        same_cost_model=True,
        independently_replayed=True,
        full_real_year=True,
        net_usd=Decimal(net),
        return_pct=Decimal(55),
        max_drawdown_pct=Decimal(dd),
    )


def test_2025_bull_first_alone_cannot_trigger_tweaking():
    first = source()
    status = eligibility(first)
    assert status["status"] == "AWAIT_UNCHANGED_2021_DOWN_YEAR"
    assert status["improvements_allowed"] is False
    assert status["second"] is None


def test_2021_down_year_then_passes_only_if_unchanged_and_profitable():
    first, second = source(), source(2021)
    status = eligibility(first, second)
    assert status["status"] == "TWO_YEAR_PROMISING_ELIGIBLE_FOR_DIAGNOSTICS"
    assert status["first_regime"] == "bull_year"
    assert status["second_regime"] == "down_year"
    assert [h.key for h in targeted_diagnosis(first, second)] == [
        "atr3_stop", "leverage2",
    ]


@pytest.mark.parametrize("changes", [
    {"net_usd": Decimal(-10)},
    {"completed_real_months": 11},
    {"execution_cost_hash": "f" * 64},
    {"rule_hash": "f" * 64},
    {"real_source_hash": "e" * 64},
    {"starting_usd": Decimal(20000)},
    {"trades": 3},
    {"profit_factor": Decimal("0.8")},
    {"regime": "bull_year"},
])
def test_frozen_two_year_original_rule_gate_fails_on_modified_source(changes):
    a, b = source(), source(2021, **changes)
    assert eligibility(a, b)["improvements_allowed"] is False
    assert targeted_diagnosis(a, b) == []


def test_two_bull_years_do_not_count_as_two_different_regimes():
    a = source()
    b = source(2024)
    assert eligibility(a, b)["improvements_allowed"] is False


def test_structurally_healthy_original_needs_no_ai_tweaks():
    a = source(has_protective_stop=True, leverage=Decimal(1),
               max_drawdown_pct=Decimal(-9), worst_trade_usd=Decimal(-50))
    b = source(2021, has_protective_stop=True, leverage=Decimal(1),
               max_drawdown_pct=Decimal(-10), worst_trade_usd=Decimal(-40))
    assert eligibility(a, b)["improvements_allowed"]
    assert targeted_diagnosis(a, b) == []


def test_rerun_same_edit_on_second_year_then_crosscheck_original_first_year():
    a, b = source(), source(2021)
    hypothesis = targeted_diagnosis(a, b)[0]
    result = compare(a, b, hypothesis, variant(b), variant(a))
    assert result["verdict"] == "PROMISING_TWO_REGIME_COMPARISON_UNCONFIRMED"
    assert [item["year"] for item in
            result["last_year_trial_then_first_year_crosscheck"]] == [2021, 2025]
    assert result["original_results_never_edited"]
    assert result["no_auto_promotion_to_live"]
    assert result["2025_was_already_examined_not_blind_oos"]


def test_unprofitable_tweak_is_explicit_rejection_not_silently_hidden():
    a, b = source(), source(2021)
    hypothesis = targeted_diagnosis(a, b)[0]
    result = compare(a, b, hypothesis, variant(b, net="-500"),
                     variant(a, net="5500"))
    assert result["verdict"] == "REJECTED_KEEP_ORIGINAL"
    assert result["report_both_positive_and_failed_variants"]


def test_change_cannot_be_tuned_differently_across_years():
    a, b = source(), source(2021)
    hypothesis = targeted_diagnosis(a, b)[0]
    with pytest.raises(ValueError, match="refitted"):
        compare(a, b, hypothesis, variant(b, h="x"), variant(a, h="y"))


def test_changed_cost_model_or_fake_evidence_refused():
    a, b = source(), source(2021)
    hypothesis = targeted_diagnosis(a, b)[0]
    with pytest.raises(ValueError, match="matching real-year"):
        compare(a, b, hypothesis, replace(variant(b), same_cost_model=False),
                variant(a))


def test_analyst_cannot_introduce_unexplained_parameter_grid():
    a, b = source(), source(2021)
    unsolicited = SmallChange(
        "RSI_grid_10_to_90", "nothing observed", "change RSI every time",
        "search for largest in-sample profit",
    )
    with pytest.raises(ValueError, match="not justified"):
        compare(a, b, unsolicited, variant(b, key="RSI_grid_10_to_90"),
                variant(a, key="RSI_grid_10_to_90"))
