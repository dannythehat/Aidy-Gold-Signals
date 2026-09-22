from __future__ import annotations

import sys
from pathlib import Path

from aidy.gold_evidence_dependency import (
    build_evidence_dependency_engine,
    extract_dependency_signals,
)
from aidy.gold_family_meta_direction import build_family_meta_direction_view

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from blocker1_v9_full_fixture_validator import (  # noqa: E402
    AS_OF,
    add_unknowns,
    attach_fixture_trust,
    build_connected_state,
    build_fixture,
    validate_correct_derivation,
)


def test_canonical_v9_full_fixture_reaches_two_independent_families() -> None:
    environment, connected, market_state = build_connected_state()
    experts = add_unknowns(environment, connected)
    assert len(experts) == 15

    fixture = build_fixture(
        environment=environment,
        connected=connected,
        all_experts=experts,
        market_state=market_state,
    )
    validate_correct_derivation(fixture)

    subject_ids = {
        str(item["subject_key"])
        for item in fixture["connected_subcalculator_manifest"]
    }
    assert len(subject_ids) == 70

    experts_with_trust, _ = attach_fixture_trust(experts, fixture)
    dependency = build_evidence_dependency_engine(
        signals=extract_dependency_signals(experts_with_trust),
        historical_rows=fixture["dependency_history"],
        as_of_utc=AS_OF,
    )
    historical_rows = [
        dict(row)
        for item in fixture["subject_histories"]
        for row in item["history_rows"]
    ]

    view = build_family_meta_direction_view(
        global_environment=environment,
        expert_results=experts_with_trust,
        dependency_engine=dependency,
        historical_subcalculator_rows=historical_rows,
        resolved_outcome_rows=fixture["resolved_outcome_history"],
    )

    assert view["direction"] == "bullish"
    assert view["decision_reason"] == "bullish_family_evidence"
    assert view["meta_balance"] == "1.000000"
    assert view["qualifying_family_count"] == 2
    qualifying = {
        row["family_id"]: row["family_strength"]
        for row in view["families"]
        if row["qualifies"]
    }
    assert qualifying == {
        "liquidity_mechanism": "0.373330",
        "price_action": "0.331592",
    }
    assert view["live_money_execution_allowed"] is False
    assert view["formal_forward_evidence_created"] is False
