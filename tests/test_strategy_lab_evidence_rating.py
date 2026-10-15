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
