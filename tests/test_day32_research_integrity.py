from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from aidy.research_integrity import (
    IntegrityError,
    audit_decision_eligibility,
    build_field_attestation_manifest,
    build_leak_finding,
    finalize_trial,
    preregister_trial,
    verify_field_attestation_manifest,
    verify_trial_record,
    verify_trial_registry,
)

NOW = datetime(2026, 8, 23, 15, tzinfo=UTC)


def _packet() -> dict[str, object]:
    return {
        "as_of_utc": NOW.isoformat(),
        "symbol": "XAUUSD",
        "context_packet_version": "aidy_market_context_v7_volatility_state",
        "source_contract_versions": {
            "feature_engine": "v1",
            "volatility_intelligence": "aidy_gold_volatility_intelligence_v1",
        },
        "features": {"atr": None, "trend": "up"},
        "volatility_state": {
            "gvz": {"state": "known", "value_annualized_percent": "27.29"},
            "realized_volatility": {"state": "unknown_insufficient_daily_history"},
        },
        "context_hash": "a" * 64,
    }


def _policy(contract: str = "context_v7") -> dict[str, object]:
    return {
        "field_contract": contract,
        "contract_version": "v1",
        "source": "accepted_context_packet",
        "evidence_family": "market_context",
        "provenance_class": "point_in_time",
        "pit_reconstructable": "true",
        "reconstruction_method": "immutable_asof_selection",
        "reconstruction_version": "v1",
        "retrospective_eligible": True,
        "evaluation_eligible": True,
        "decision_input_eligible": True,
        "staleness_rule": "inherit_source_contract",
    }


def _manifest() -> dict[str, object]:
    packet = _packet()
    policies = {f"$.{key}": _policy(str(key)) for key in packet if key != "context_hash"}
    return build_field_attestation_manifest(
        packet,
        policies=policies,
        observed_at=NOW - timedelta(minutes=1),
        published_at=None,
        first_observed_at=NOW,
        staleness_state="fresh",
        quality_state="verified",
    )


def test_every_active_leaf_has_an_immutable_attestation() -> None:
    manifest = _manifest()
    assert verify_field_attestation_manifest(manifest)
    assert manifest["active_field_count"] == len(manifest["attestations"])
    paths = {row["json_path"] for row in manifest["attestations"]}
    assert "$.features.atr" in paths
    assert "$.volatility_state.realized_volatility.state" in paths
    assert "$.context_hash" not in paths
    assert all(row["context_hash_covered"] for row in manifest["attestations"])


def test_missing_field_policy_and_digest_tampering_fail_closed() -> None:
    packet = _packet()
    with pytest.raises(IntegrityError, match="lacks a policy"):
        build_field_attestation_manifest(
            packet,
            policies={"$.symbol": _policy()},
            observed_at=NOW,
            published_at=NOW,
            first_observed_at=NOW,
            staleness_state="fresh",
            quality_state="verified",
        )
    manifest = _manifest()
    manifest["attestations"][0]["quality_state"] = "fabricated"
    assert not verify_field_attestation_manifest(manifest)


@pytest.mark.parametrize("pit_state", ["false", "partial"])
def test_false_or_partial_pit_field_cannot_be_decision_input(pit_state: str) -> None:
    packet = _packet()
    policies = {f"$.{key}": _policy() for key in packet if key != "context_hash"}
    policies["$.features"]["pit_reconstructable"] = pit_state
    with pytest.raises(IntegrityError, match="cannot be decision eligible"):
        build_field_attestation_manifest(
            packet,
            policies=policies,
            observed_at=NOW,
            published_at=NOW,
            first_observed_at=NOW,
            staleness_state="fresh",
            quality_state="verified",
        )


def test_publication_and_first_observation_boundaries_are_conservative() -> None:
    packet = _packet()
    policies = {f"$.{key}": _policy() for key in packet if key != "context_hash"}
    with pytest.raises(IntegrityError, match="cannot precede"):
        build_field_attestation_manifest(
            packet,
            policies=policies,
            observed_at=NOW,
            published_at=None,
            first_observed_at=NOW - timedelta(seconds=1),
            staleness_state="unknown",
            quality_state="partial",
        )


@pytest.mark.parametrize(
    "category",
    [
        "revision_after_decision",
        "overwritten_vendor_file",
        "publication_lag",
        "missing_historical_release_timestamp",
        "retrospective_before_first_observation",
        "timezone_date_dst_ambiguity",
        "future_outcome_in_decision",
        "unknown_converted_to_absent",
        "context_hash_coverage_gap",
        "attestation_contract_mismatch",
    ],
)
def test_deliberate_leak_categories_are_machine_blocking(category: str) -> None:
    finding = build_leak_finding(
        field_identity="contract:$.field",
        category=category,
        detected_at=NOW,
        evidence={"fixture": category},
    )
    audit = audit_decision_eligibility(_manifest(), [finding])
    assert audit["unresolved_blocking_count"] == 1
    assert audit["decision_input_allowed"] is False


def test_resolved_findings_remain_visible_without_blocking() -> None:
    finding = build_leak_finding(
        field_identity="contract:$.field",
        category="publication_lag",
        detected_at=NOW,
        evidence={"publication_delay_seconds": 120},
        resolved=True,
    )
    audit = audit_decision_eligibility(_manifest(), [finding])
    assert audit["finding_count"] == 1
    assert audit["decision_input_allowed"] is True


def _trial(records: list[dict[str, object]], *, number: int, holdout: str, purpose: str = "evaluation") -> dict[str, object]:
    return preregister_trial(
        records,
        trial_number=number,
        hypothesis="Feature X reduces outcome dispersion.",
        null_hypothesis="Feature X does not reduce outcome dispersion.",
        dataset_version="dataset-v1",
        feature_context_version="context-v7",
        frozen_parameters={"threshold": "0.50"},
        chronological_split={"train_end": "2025-12-31", "holdout_start": "2026-01-01"},
        purge="24h",
        embargo="24h",
        evaluation_identity="evaluation-2026q1",
        holdout_identity=holdout,
        preregistered_at=NOW,
        code_head="f39a6f957f458cbb0dbbe569775de15fc511c556",
        evidence_digest="b" * 64,
        purpose=purpose,
    )


def test_trial_numbers_are_monotonic_and_digest_chained() -> None:
    first = _trial([], number=1, holdout="holdout-a")
    final = finalize_trial(first, executed_at=NOW + timedelta(seconds=1), result_state="null", result={"effect": 0})
    second = _trial([final], number=2, holdout="holdout-b")
    assert verify_trial_record(final)
    assert verify_trial_registry([final, second])
    assert second["previous_trial_digest"] == final["trial_digest"]
    with pytest.raises(IntegrityError, match="expected 3"):
        _trial([final, second], number=4, holdout="holdout-c")


@pytest.mark.parametrize("state", ["null", "insufficient", "failed", "passed"])
def test_all_terminal_trial_results_are_retained(state: str) -> None:
    record = _trial([], number=1, holdout=f"holdout-{state}")
    final = finalize_trial(record, executed_at=NOW + timedelta(minutes=1), result_state=state, result={"state": state})
    assert verify_trial_record(final)
    assert final["result_state"] == state
    assert final["result"] == {"state": state}


def test_execution_before_preregistration_is_rejected() -> None:
    record = _trial([], number=1, holdout="holdout-a")
    with pytest.raises(IntegrityError, match="cannot precede"):
        finalize_trial(record, executed_at=NOW - timedelta(seconds=1), result_state="failed", result={"error": "fixture"})


def test_holdout_reuse_for_tuning_is_detected_and_forbidden() -> None:
    first = finalize_trial(
        _trial([], number=1, holdout="holdout-a"),
        executed_at=NOW + timedelta(seconds=1),
        result_state="passed",
        result={"metric": "0.1"},
    )
    with pytest.raises(IntegrityError, match="holdout reuse"):
        _trial([first], number=2, holdout="holdout-a", purpose="tuning")


def test_trial_and_manifest_exact_reruns_are_digest_stable() -> None:
    assert _manifest() == _manifest()
    first = _trial([], number=1, holdout="holdout-a")
    assert first == _trial([], number=1, holdout="holdout-a")
    tampered = deepcopy(first)
    tampered["frozen_parameters"]["threshold"] = "0.99"
    assert not verify_trial_record(tampered)
