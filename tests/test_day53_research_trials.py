from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from aidy.research_trials import (
    NO_EDGE_RULE,
    build_record,
    equivalence_contract_payload,
    governance_genesis_payload,
    qualification_result_payload,
    research_family_payload,
    trial_started_payload,
    validate_trial_against_family,
    verify_chain,
)

SHA40 = "a" * 40
D64 = "b" * 64


def test_governance_genesis_contains_no_edge_and_default_insufficient() -> None:
    payload = governance_genesis_payload()
    assert payload["no_edge_rule"] == NO_EDGE_RULE
    assert payload["qualification_policy"]["default_state"] == "insufficient_evidence"
    assert payload["qualification_policy"]["fail_allows_inheritance"] is False
    assert payload["qualification_policy"]["insufficient_evidence_allows_inheritance"] is False
    assert payload["mutation_policy"]["update_allowed"] is False
    assert payload["mutation_policy"]["delete_allowed"] is False


def test_hash_chain_is_code_head_bound() -> None:
    first = build_record(
        sequence=0,
        previous_digest=None,
        record_type="governance_genesis",
        recorded_at=datetime(2026, 9, 2, 8, 0, tzinfo=UTC),
        code_head_sha=SHA40,
        initiated_by="human",
        payload=governance_genesis_payload(),
    )
    second = build_record(
        sequence=1,
        previous_digest=first["record_digest"],
        record_type="research_family_registered",
        recorded_at=datetime(2026, 9, 2, 8, 1, tzinfo=UTC),
        code_head_sha=SHA40,
        initiated_by="agent",
        payload=research_family_payload(
            research_family_id="twelve-regime-equivalence-v1",
            research_question="Do HistData and Twelve Data preserve the 20/50 bps regime decision surface?",
            hypothesis="The existing classifier is decision-semantically equivalent across the two sources.",
            parameter_space_digest=D64,
        ),
    )
    assert verify_chain([first, second])
    second["code_head_sha"] = "c" * 40
    assert not verify_chain([first, second])


def test_mechanical_selection_requires_ex_ante_registered_space() -> None:
    family = research_family_payload(
        research_family_id="cot-transform-v1",
        research_question="Does COT positioning add PIT-safe decision value?",
        hypothesis="At least one preregistered transform adds value after costs.",
        parameter_space_digest=D64,
    )
    trial = trial_started_payload(
        trial_id="trial-001",
        research_family_id="cot-transform-v1",
        parent_trial_id=None,
        selection_origin="preregistered_enumerated",
        parameter_space_digest=D64,
        configuration_digest=D64,
        dataset_boundary_digest=D64,
        feature_definition_digest=D64,
        label_definition_digest=D64,
        validation_contract_digest=D64,
        cost_model_digest=D64,
        market_data_semantic_identity_digest=D64,
    )
    validate_trial_against_family(trial, family)

    bad_family = dict(family)
    bad_family["parameter_space_digest"] = "c" * 64
    with pytest.raises(ValueError, match="ex-ante registered parameter space"):
        validate_trial_against_family(trial, bad_family)


def test_mechanical_self_report_without_parameter_space_proof_is_rejected() -> None:
    with pytest.raises(ValueError, match="Mechanical selection"):
        trial_started_payload(
            trial_id="trial-002",
            research_family_id="cot-transform-v1",
            parent_trial_id=None,
            selection_origin="adaptive_algorithm_registered_ex_ante",
            parameter_space_digest=None,
            configuration_digest=D64,
            dataset_boundary_digest=D64,
            feature_definition_digest=D64,
            label_definition_digest=D64,
            validation_contract_digest=D64,
            cost_model_digest=D64,
            market_data_semantic_identity_digest=D64,
        )


def test_equivalence_contract_requires_distribution_and_decision_surface_tests() -> None:
    with pytest.raises(ValueError, match="both feature distribution and resulting decision surface"):
        equivalence_contract_payload(
            qualification_id="regime-20-50-v1",
            affected_surface="regime_classifier.volatility_band",
            source_identity_a_digest=D64,
            source_identity_b_digest=D64,
            comparison_population_digest=D64,
            minimum_paired_sample=100,
            coverage_requirements={"sessions": ["asia", "london", "new_york"]},
            distribution_metrics=[{"metric": "paired_abs_difference_bps"}],
            decision_surface_metrics=[],
            pass_criteria={"max_disagreement_rate": "frozen_before_run"},
            fail_criteria={"disagreement_rate_gte": "frozen_before_run"},
            insufficient_evidence_criteria={"paired_sample_lt": 100},
        )


def test_only_affirmative_pass_allows_inheritance() -> None:
    contract_digest = "c" * 64
    evidence_digest = "d" * 64
    assert qualification_result_payload(
        qualification_id="q1",
        contract_digest=contract_digest,
        outcome="pass",
        evidence_digest=evidence_digest,
    )["inheritance_allowed"] is True
    assert qualification_result_payload(
        qualification_id="q1",
        contract_digest=contract_digest,
        outcome="fail",
        evidence_digest=evidence_digest,
    )["inheritance_allowed"] is False
    assert qualification_result_payload(
        qualification_id="q1",
        contract_digest=contract_digest,
        outcome="insufficient_evidence",
        evidence_digest=evidence_digest,
    )["inheritance_allowed"] is False


def test_d1_migration_vetoes_update_and_delete() -> None:
    from pathlib import Path

    migration = Path("migrations/d1/0008_research_evidence_ledger.sql").read_text()
    db = sqlite3.connect(":memory:")
    db.executescript(migration)
    db.execute(
        """
        INSERT INTO research_evidence_ledger (
          sequence,record_digest,previous_digest,ledger_version,record_type,
          recorded_at_utc,code_head_sha,initiated_by,payload_json
        ) VALUES (0,?,?,?,?,?,?,?,?)
        """,
        (
            "e" * 64,
            None,
            "aidy_research_ledger_v1",
            "governance_genesis",
            "2026-09-02T08:00:00+00:00",
            SHA40,
            "human",
            "{}",
        ),
    )
    with pytest.raises(sqlite3.DatabaseError, match="UPDATE forbidden"):
        db.execute("UPDATE research_evidence_ledger SET record_type='changed' WHERE sequence=0")
    with pytest.raises(sqlite3.DatabaseError, match="DELETE forbidden"):
        db.execute("DELETE FROM research_evidence_ledger WHERE sequence=0")
