"""Day28 executable integration with ACTUAL Day24/25 and Day26/27 sources.

No mocked winning strategy, no fake green/100 rating. A successful acceptance
means unsafe promotion of synthetic/bid-only evidence was demonstrably blocked.
"""
from __future__ import annotations

from dataclasses import replace

import pytest
from test_strategy_lab_oos_protocol import sample_history

from scripts.strategy_lab.day28_evidence_rating_acceptance import audit_source


def test_source_bound_nine_factor_audit_abstains_instead_of_fake_score():
    result = audit_source(sample_history())
    assert result["status"] == "PASS"
    assert result["independent_real_bidask_net_alpha_qualified"] is False
    assert result["customer_optimisation_requires_separate_permission"] is True
    rating = result["rating"]
    assert rating["score_out_of_100"] is None
    assert rating["score_status"] == "WITHHELD_UNQUALIFIED_OR_INCOMPLETE"
    assert rating["governance"] == "ORANGE_INVESTIGATE"
    assert rating["optimisation_suggestions_eligible"] is False
    assert rating["automatically_authorised_for_live_trading"] is False
    assert len(rating["factor_scores"]) == 9
    assert sum(n for _, n in rating["factor_weights"]) == 100
    assert all(x["awarded_points"] is None for x in rating["factor_scores"])
    assert any(x["status"] == "INSUFFICIENT" for x in rating["factor_scores"])
    assert result["upstream_evidence"]["day24_synthetic"]
    assert result["upstream_evidence"]["day25_synthetic"]
    assert result["upstream_evidence"]["day26_day27_retrospective_bid_only"]
    assert result["upstream_evidence"]["held_out_final_oos_reused"] == 0
    assert result["upstream_evidence"]["walkforward_development_decisions"] == 48


def test_complete_source_proof_reproduces_verbatim_from_separate_sqlite_runs():
    first = audit_source(sample_history())
    second = audit_source(sample_history())
    assert first == second
    upstream = first["upstream_evidence"]
    assert len(upstream["day24_two_replays_tip_sha256"]) == 64
    assert len(upstream["day25_scenario_policy_sha256"]) == 64
    assert len(upstream["day26_real_bid_source_sha256"]) == 64
    assert len(upstream["day27_48_decisions_sha256"]) == 64
    assert len(first["rating"]["scoring_policy_sha256"]) == 64


def test_unclosed_or_gapped_market_source_fails_against_day26_qualification():
    old = sample_history()
    bars = list(old.bars)
    bars[17] = replace(bars[17], available_at_utc=bars[17].open_time_utc)
    with pytest.raises(ValueError):
        audit_source(replace(old, bars=tuple(bars)))
