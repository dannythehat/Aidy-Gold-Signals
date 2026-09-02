from __future__ import annotations

import copy

import pytest

import aidy.semantic_context_composer as target
from aidy.context_composer_v2 import digest
from aidy.market_data_semantics import twelve_data_semantic_identity
from aidy.semantic_analogue_retrieval import (
    SEMANTIC_ANALOGUE_QUERY_VERSION,
    SEMANTIC_ANALOGUE_RETRIEVAL_VERSION,
)
from aidy.semantic_context_composer import (
    SEMANTIC_CONTEXT_COMPOSER_VERSION,
    compose_semantic_context_v2,
    validate_semantic_decision_inputs,
    verify_semantic_retrieval_wrapper,
)
from aidy.semantic_context_packet import SEMANTIC_CONTEXT_PACKET_VERSION


def _context() -> dict:
    identity = twelve_data_semantic_identity()
    return {
        "semantic_context_packet_version": SEMANTIC_CONTEXT_PACKET_VERSION,
        "market_data_semantic_identity_digest": identity["semantic_identity_digest"],
        "provenance": {"gold_market_data_semantic_identity": identity},
    }


def _retrieval(identity_digest: str) -> dict:
    value = {
        "semantic_retrieval_version": SEMANTIC_ANALOGUE_RETRIEVAL_VERSION,
        "semantic_query_version": SEMANTIC_ANALOGUE_QUERY_VERSION,
        "query_id": "query",
        "query_market_data_semantic_identity_digest": identity_digest,
        "candidate_count_before_semantic_gate": 4,
        "semantic_compatible_candidate_count": 2,
        "semantic_exclusion_counts": {"market_data_semantic_identity_incompatible": 2},
        "compatibility_evidence": [],
        "accepted_equivalence_ledger_record_digests": [],
        "base_retrieval": {"retrieval_version": "placeholder"},
        "cross_source_comparison_without_ledger_proven_pass_allowed": False,
    }
    value["semantic_retrieval_digest"] = digest(value)
    return value


def test_legacy_retrieval_cannot_qualify_twelve_dossier() -> None:
    with pytest.raises(ValueError, match="verified semantic analogue retrieval"):
        validate_semantic_decision_inputs(
            context=_context(),
            semantic_retrieval={"retrieval_version": "aidy_historical_analogue_retrieval_v2"},
        )


def test_semantic_retrieval_must_bind_same_market_data_identity() -> None:
    context = _context()
    retrieval = _retrieval("0" * 64)
    with pytest.raises(ValueError, match="does not match current Gold context"):
        validate_semantic_decision_inputs(context=context, semantic_retrieval=retrieval)


def test_semantic_wrapper_digest_is_tamper_evident() -> None:
    context = _context()
    retrieval = _retrieval(context["market_data_semantic_identity_digest"])
    assert verify_semantic_retrieval_wrapper(retrieval)
    tampered = copy.deepcopy(retrieval)
    tampered["semantic_compatible_candidate_count"] = 3
    assert not verify_semantic_retrieval_wrapper(tampered)


def test_composed_dossier_binds_semantic_gate_before_model_surface(monkeypatch) -> None:
    context = _context()
    retrieval = _retrieval(context["market_data_semantic_identity_digest"])
    observed: dict = {}

    def fake_legacy_composer(**kwargs):
        observed.update(kwargs)
        return {"composer_version": "legacy", "dossier_digest": "legacy-digest"}

    monkeypatch.setattr(target, "compose_context_v2", fake_legacy_composer)
    result = compose_semantic_context_v2(
        context=context,
        aidy_state={},
        semantic_retrieval=retrieval,
        evidence_report={},
        hypothesis_direction="none",
        setup_family=None,
        invalidation_inputs={},
    )

    assert observed["retrieval"] == retrieval["base_retrieval"]
    assert "semantic_retrieval" not in observed
    assert result["semantic_context_composer_version"] == SEMANTIC_CONTEXT_COMPOSER_VERSION
    binding = result["semantic_dossier_binding"]
    assert binding["market_data_semantic_identity_digest"] == context[
        "market_data_semantic_identity_digest"
    ]
    assert binding["semantic_retrieval_digest"] == retrieval["semantic_retrieval_digest"]
    assert binding["cross_source_comparison_without_ledger_proven_pass_allowed"] is False
    assert result["dossier_digest"] == digest(
        {key: value for key, value in result.items() if key != "dossier_digest"}
    )
