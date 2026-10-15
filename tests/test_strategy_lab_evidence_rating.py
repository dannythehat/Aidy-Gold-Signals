"""Nine-factor policy gate and qualified-evidence regression tests."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from aidy.strategy_lab_evidence_rating import FACTOR_WEIGHTS, EvidenceBasis, FactorFinding, rate_strategy_evidence

WEIGHTS = (30, 15, 10, 10, 10, 10, 5, 5, 5)
HASHES = tuple(f"{i:064x}" for i in range(1, 16))


def example(independent=True):
    return EvidenceBasis(
        "independent_costed_xauusd" if independent else "retrospective_bid_only",
        HASHES[0], HASHES[1], HASHES[2], HASHES[3] if independent else None,
        HASHES[4], HASHES[5] if independent else None,
        True, independent, independent, independent, independent,
        300 if independent else None,
        Decimal("3.75") if independent else None,
        Decimal("1.30") if independent else None,
    )


def full(points=WEIGHTS):
    return tuple(FactorFinding(name, "VERIFIED", value, HASHES[i+6],
                               "Policy-only fictional independent evidence receipt")
                 for i, ((name, _), value) in enumerate(zip(FACTOR_WEIGHTS, points, strict=True)))


def test_original_nine_factor_weights_are_exact():
    assert tuple(w for _, w in FACTOR_WEIGHTS) == WEIGHTS
    assert len(WEIGHTS) == 9 and sum(WEIGHTS) == 100


def test_full_synthetic_policy_input_does_not_authorise_broker_activity():
    a = rate_strategy_evidence(example(), full())
    assert a.score_out_of_100 == 100
    assert a.governance == "GREEN_HIGH_PRIORITY"
    assert not a.automatically_authorised_for_live_trading
    assert a.to_json() == rate_strategy_evidence(example(), full()).to_json()


def test_actual_origin_unqualified_cannot_get_numeric_score():
    for origin in ("retrospective_bid_only", "internal_synthetic_fixture", "unqualified_customer_claim"):
        score = rate_strategy_evidence(replace(example(False), origin=origin), full())
        assert score.score_out_of_100 is None
        assert score.governance == "ORANGE_INVESTIGATE"
        assert not score.optimisation_suggestions_eligible


def test_missing_factor_is_not_a_zero_or_partial_total():
    factors = list(full())
    factors[1] = replace(factors[1], status="INSUFFICIENT", awarded_points=None,
                         source_sha256=None)
    score = rate_strategy_evidence(example(), tuple(factors))
    assert score.score_out_of_100 is None
    assert score.governance == "ORANGE_INVESTIGATE"


def test_verified_negative_expectancy_or_benchmark_vetoes_green():
    for field in ("observed_net_expectancy_usd", "observed_benchmark_edge_usd"):
        score = rate_strategy_evidence(replace(example(), **{field: Decimal(0)}), full())
        assert score.governance == "RED_REJECT"
        assert not score.optimisation_suggestions_eligible
        assert not score.historical_profitability_qualified


def test_bad_evidence_cannot_silently_claim_full_qualifications():
    with pytest.raises(ValueError, match="synthetic or bid-only"):
        rate_strategy_evidence(replace(example(), origin="retrospective_bid_only"), full())


@pytest.mark.parametrize(("field", "replacement"), [
    ("actual_bid_ask_costed_trades_independently_replayed", False),
    ("chronological_oos_trading_independently_verified", False),
    ("fair_benchmark_independently_verified", False),
    ("full_trial_family_independently_registered", False),
    ("historical_source_independently_verified", False),
    ("verified_costed_trade_ledger_sha256", None),
    ("oos_holdout_trial_tip_sha256", None),
    ("fair_matched_benchmark_sha256", None),
    ("original_run_sha256", None),
    ("historical_trades", 29),
    ("observed_net_expectancy_usd", None),
    ("observed_benchmark_edge_usd", None),
])
def test_any_missing_genuine_qualification_denies_scoring(field, replacement):
    result = rate_strategy_evidence(replace(example(), **{field: replacement}), full())
    assert result.score_out_of_100 is None
    assert not result.optimisation_suggestions_eligible


@pytest.mark.parametrize(("field", "value"), [
    ("observed_net_expectancy_usd", Decimal("-0.01")),
    ("observed_benchmark_edge_usd", Decimal("-2.00")),
    ("independently_verified_unacceptable_risk", True),
])
def test_measured_economic_or_risk_failure_is_red_not_green(field, value):
    r = rate_strategy_evidence(replace(example(), **{field: value}), full())
    assert r.governance == "RED_REJECT"
    assert r.veto_reasons and not r.optimisation_suggestions_eligible


@pytest.mark.parametrize(("index", "awarded"), [
    (0, 20), (1, 10), (3, 6), (4, 6), (8, 3),
])
def test_mandatory_key_green_factor_not_overridden_by_total(index, awarded):
    points = list(WEIGHTS)
    points[index] = awarded
    r = rate_strategy_evidence(example(), full(tuple(points)))
    assert r.score_out_of_100 is not None
    assert r.governance != "GREEN_HIGH_PRIORITY"
    assert not r.optimisation_suggestions_eligible


def test_orange_and_red_hypothetical_complete_policy_examples():
    orange = rate_strategy_evidence(example(), full((21, 11, 7, 7, 7, 6, 3, 3, 4)))
    assert orange.score_out_of_100 == 69
    assert orange.governance == "ORANGE_INVESTIGATE"
    red = rate_strategy_evidence(example(), full((10, 5, 2, 2, 2, 2, 1, 1, 1)))
    assert red.score_out_of_100 == 26
    assert red.governance == "RED_REJECT"


@pytest.mark.parametrize("invalid", [-1, 31, 7.5, True, None, Decimal(3)])
def test_invalid_earned_points_cannot_be_counted(invalid):
    factors = list(full())
    factors[0] = replace(factors[0], awarded_points=invalid)
    with pytest.raises(ValueError, match="bounded"):
        rate_strategy_evidence(example(), tuple(factors))


def test_unqualified_factor_with_non_null_data_fails_closed():
    factors = list(full())
    factors[3] = replace(factors[3], status="UNKNOWN", awarded_points=0)
    with pytest.raises(ValueError, match="null"):
        rate_strategy_evidence(example(), tuple(factors))


def test_duplicate_or_missing_factor_and_duplicate_receipt_are_denied():
    with pytest.raises(ValueError, match="exactly"):
        rate_strategy_evidence(example(), full()[:-1])
    rows = list(full())
    rows[1] = replace(rows[1], factor=rows[0].factor)
    with pytest.raises(ValueError, match="ordering"):
        rate_strategy_evidence(example(), tuple(rows))
    rows = list(full())
    rows[1] = replace(rows[1], source_sha256=rows[0].source_sha256)
    with pytest.raises(ValueError, match="independent"):
        rate_strategy_evidence(example(), tuple(rows))


@pytest.mark.parametrize(("field", "value"), [
    ("historical_trades", True),
    ("historical_trades", -2),
    ("historical_source_independently_verified", 1),
    ("historical_input_sha256", "bad"),
    ("observed_net_expectancy_usd", Decimal("NaN")),
    ("observed_benchmark_edge_usd", 3.1),
])
def test_invalid_input_origin_count_or_non_finite_economics_fails(field, value):
    with pytest.raises(ValueError):
        rate_strategy_evidence(replace(example(), **{field: value}), full())


def test_zero_trades_cannot_report_real_net_returns():
    with pytest.raises(ValueError, match="zero trades"):
        rate_strategy_evidence(replace(example(), historical_trades=0), full())
