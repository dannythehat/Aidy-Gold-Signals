from __future__ import annotations

import importlib.util
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

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


def _acceptance_module() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / "day32_research_integrity_acceptance.py"
    spec = importlib.util.spec_from_file_location("day32_acceptance", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
        "event_intelligence": {
            "state": "known",
            "next_scheduled_event_at": (NOW + timedelta(days=1)).isoformat(),
        },
        "volatility_state": {
            "gvz": {"state": "known", "value_annualized_percent": "27.29"},
            "realized_volatility": {"state": "unknown_insufficient_daily_history"},
        },
        "context_hash": "a" * 64,
    }


def _policy(
    contract: str = "context_v7",
    *,
    observation: datetime = NOW,
    first_observed: datetime = NOW,
    publication: datetime | None = None,
    timing_semantics: str = "derived_at_asof",
    surface_state: str = "accepted_staged_context",
    pit_state: str = "true",
    decision_input_eligible: bool = True,
    retrospective_eligible: bool = True,
    historical_backfill_allowed: bool = False,
) -> dict[str, object]:
    return {
        "field_contract": contract,
        "contract_version": "v1",
        "source": "accepted_context_packet",
        "evidence_family": "market_context",
        "provenance_class": "point_in_time",
        "pit_reconstructable": pit_state,
        "reconstruction_method": "immutable_asof_selection",
        "reconstruction_version": "v1",
        "retrospective_eligible": retrospective_eligible,
        "historical_backfill_allowed": historical_backfill_allowed,
        "evaluation_eligible": True,
        "decision_input_eligible": decision_input_eligible,
        "staleness_rule": "inherit_source_contract",
        "observation_timestamp": observation.isoformat(),
        "publication_timestamp": None if publication is None else publication.isoformat(),
        "first_observed_timestamp": first_observed.isoformat(),
        "timing_semantics": timing_semantics,
        "surface_state": surface_state,
        "quality_state": "verified_or_explicit_unknown",
    }


def _policies() -> dict[str, dict[str, object]]:
    packet = _packet()
    policies = {
        f"$.{key}": _policy(str(key))
        for key in packet
        if key not in {"context_hash", "event_intelligence"}
    }
    policies["$.event_intelligence"] = _policy("event_intelligence")
    policies["$.event_intelligence.next_scheduled_event_at"] = _policy(
        "event_intelligence.schedule",
        observation=NOW + timedelta(days=1),
        first_observed=NOW - timedelta(hours=2),
        publication=NOW - timedelta(hours=3),
        timing_semantics="knowledge_can_precede_effective",
    )
    return policies


def _manifest() -> dict[str, object]:
    return build_field_attestation_manifest(_packet(), policies=_policies())


def test_every_active_leaf_has_an_immutable_attestation() -> None:
    manifest = _manifest()
    assert verify_field_attestation_manifest(manifest)
    assert manifest["active_field_count"] == len(manifest["attestations"])
    paths = {row["json_path"] for row in manifest["attestations"]}
    assert "$.features.atr" in paths
    assert "$.volatility_state.realized_volatility.state" in paths
    assert "$.event_intelligence.next_scheduled_event_at" in paths
    assert "$.context_hash" not in paths
    assert all(row["context_hash_covered"] for row in manifest["attestations"])


def test_manifest_separates_active_decision_and_staged_context_surfaces() -> None:
    policies = _policies()
    policies["$.symbol"]["surface_state"] = "active_decision_surface"
    manifest = build_field_attestation_manifest(_packet(), policies=policies)
    assert verify_field_attestation_manifest(manifest)
    assert manifest["active_decision_field_count"] == 1
    assert manifest["accepted_staged_field_count"] == manifest["active_field_count"] - 1


def test_missing_field_policy_and_digest_tampering_fail_closed() -> None:
    packet = _packet()
    with pytest.raises(IntegrityError, match="lacks a policy"):
        build_field_attestation_manifest(packet, policies={"$.symbol": _policy()})
    manifest = _manifest()
    manifest["attestations"][0]["quality_state"] = "fabricated"
    assert not verify_field_attestation_manifest(manifest)


@pytest.mark.parametrize("pit_state", ["false", "partial"])
def test_false_or_partial_pit_field_cannot_be_decision_input(pit_state: str) -> None:
    packet = _packet()
    policies = _policies()
    policies["$.features"]["pit_reconstructable"] = pit_state
    with pytest.raises(IntegrityError, match="cannot be decision eligible"):
        build_field_attestation_manifest(packet, policies=policies)


def test_ordinary_evidence_cannot_be_known_before_it_exists() -> None:
    policies = _policies()
    policies["$.features"] = _policy(
        "features",
        observation=NOW,
        first_observed=NOW - timedelta(seconds=1),
        timing_semantics="observation_then_knowledge",
    )
    with pytest.raises(IntegrityError, match="cannot precede observation"):
        build_field_attestation_manifest(_packet(), policies=policies)


def test_forward_known_schedule_may_be_known_before_effective_time() -> None:
    manifest = _manifest()
    schedule = next(
        row
        for row in manifest["attestations"]
        if row["json_path"] == "$.event_intelligence.next_scheduled_event_at"
    )
    assert schedule["timing_semantics"] == "knowledge_can_precede_effective"
    assert schedule["first_observed_timestamp"] < schedule["observation_timestamp"]
    assert verify_field_attestation_manifest(manifest)


def test_first_observation_cannot_precede_publication() -> None:
    policies = _policies()
    policies["$.features"] = _policy(
        "features",
        observation=NOW - timedelta(minutes=5),
        publication=NOW,
        first_observed=NOW - timedelta(minutes=1),
        timing_semantics="observation_then_knowledge",
    )
    with pytest.raises(IntegrityError, match="cannot precede publication"):
        build_field_attestation_manifest(_packet(), policies=policies)


def test_historical_backfill_requires_retrospective_eligibility() -> None:
    policies = _policies()
    policies["$.features"] = _policy(
        "features",
        retrospective_eligible=False,
        historical_backfill_allowed=True,
    )
    with pytest.raises(IntegrityError, match="requires retrospective eligibility"):
        build_field_attestation_manifest(_packet(), policies=policies)


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
    manifest = _manifest()
    identity = manifest["attestations"][0]["field_identity"]
    finding = build_leak_finding(
        field_identity=identity,
        category=category,
        detected_at=NOW,
        evidence={"fixture": category},
    )
    audit = audit_decision_eligibility(manifest, [finding])
    assert audit["unresolved_blocking_count"] == 1
    assert audit["decision_input_allowed"] is False


def test_leak_findings_must_reference_real_attested_fields() -> None:
    finding = build_leak_finding(
        field_identity="synthetic:not-real",
        category="publication_lag",
        detected_at=NOW,
        evidence={"fixture": True},
        resolved=True,
    )
    with pytest.raises(IntegrityError, match="does not reference an attested field"):
        audit_decision_eligibility(_manifest(), [finding])


def test_resolved_findings_remain_visible_without_blocking() -> None:
    manifest = _manifest()
    identity = manifest["attestations"][0]["field_identity"]
    finding = build_leak_finding(
        field_identity=identity,
        category="publication_lag",
        detected_at=NOW,
        evidence={"publication_delay_seconds": 120},
        resolved=True,
    )
    audit = audit_decision_eligibility(manifest, [finding])
    assert audit["finding_count"] == 1
    assert audit["decision_input_allowed"] is True


def test_bigquery_reconciliation_is_insert_only_and_idempotent() -> None:
    acceptance = _acceptance_module()
    values = [("a", {"value": 1}), ("b", {"value": 2})]
    expected = acceptance._expected_records(values)
    assert acceptance._reconcile_existing_records(existing=[], expected=expected) is False
    existing = [
        {"identity": identity, **payload}
        for identity, payload in sorted(expected.items())
    ]
    assert acceptance._reconcile_existing_records(existing=existing, expected=expected) is True


def test_bigquery_reconciliation_rejects_mutation_duplicate_and_identity_drift() -> None:
    acceptance = _acceptance_module()
    expected = acceptance._expected_records([("a", {"value": 1})])
    mutated = [{"identity": "a", **expected["a"]}]
    mutated[0]["record_digest"] = "0" * 64
    with pytest.raises(RuntimeError, match="digest mismatch"):
        acceptance._reconcile_existing_records(existing=mutated, expected=expected)
    duplicate = [
        {"identity": "a", **expected["a"]},
        {"identity": "a", **expected["a"]},
    ]
    with pytest.raises(RuntimeError, match="duplicate immutable identities"):
        acceptance._reconcile_existing_records(existing=duplicate, expected=expected)
    with pytest.raises(RuntimeError, match="identity set drift"):
        acceptance._reconcile_existing_records(
            existing=[{"identity": "other", **expected["a"]}],
            expected=expected,
        )


def _trial(
    records: list[dict[str, object]],
    *,
    number: int,
    holdout: str,
    purpose: str = "evaluation",
) -> dict[str, object]:
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
    final = finalize_trial(
        first,
        executed_at=NOW + timedelta(seconds=1),
        result_state="null",
        result={"effect": 0},
    )
    second = _trial([final], number=2, holdout="holdout-b")
    assert verify_trial_record(final)
    assert verify_trial_registry([final, second])
    assert second["previous_trial_digest"] == final["trial_digest"]
    with pytest.raises(IntegrityError, match="expected 3"):
        _trial([final, second], number=4, holdout="holdout-c")


@pytest.mark.parametrize("state", ["null", "insufficient", "failed", "passed"])
def test_all_terminal_trial_results_are_retained(state: str) -> None:
    record = _trial([], number=1, holdout=f"holdout-{state}")
    final = finalize_trial(
        record,
        executed_at=NOW + timedelta(minutes=1),
        result_state=state,
        result={"state": state},
    )
    assert verify_trial_record(final)
    assert final["result_state"] == state
    assert final["result"] == {"state": state}


def test_execution_before_preregistration_is_rejected() -> None:
    record = _trial([], number=1, holdout="holdout-a")
    with pytest.raises(IntegrityError, match="cannot precede"):
        finalize_trial(
            record,
            executed_at=NOW - timedelta(seconds=1),
            result_state="failed",
            result={"error": "fixture"},
        )


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
