from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from aidy.context_composer_v2 import compose_context_v2, digest
from aidy.market_data_semantics import verify_semantic_identity
from aidy.semantic_analogue_retrieval import (
    SEMANTIC_ANALOGUE_QUERY_VERSION,
    SEMANTIC_ANALOGUE_RETRIEVAL_VERSION,
)
from aidy.semantic_context_packet import SEMANTIC_CONTEXT_PACKET_VERSION

SEMANTIC_CONTEXT_COMPOSER_VERSION = "aidy_semantic_context_composer_v1"
SEMANTIC_DOSSIER_BINDING_VERSION = "aidy_semantic_dossier_binding_v1"


def _semantic_retrieval_body(value: Mapping[str, Any]) -> dict[str, Any]:
    body = copy.deepcopy(dict(value))
    body.pop("semantic_retrieval_digest", None)
    return body


def verify_semantic_retrieval_wrapper(value: Mapping[str, Any]) -> bool:
    if not isinstance(value, Mapping):
        return False
    supplied = str(value.get("semantic_retrieval_digest") or "")
    if not supplied or supplied != digest(_semantic_retrieval_body(value)):
        return False
    if value.get("semantic_retrieval_version") != SEMANTIC_ANALOGUE_RETRIEVAL_VERSION:
        return False
    if value.get("semantic_query_version") != SEMANTIC_ANALOGUE_QUERY_VERSION:
        return False
    if value.get("cross_source_comparison_without_ledger_proven_pass_allowed") is not False:
        return False
    base = value.get("base_retrieval")
    return isinstance(base, Mapping)


def validate_semantic_decision_inputs(
    *,
    context: Mapping[str, Any],
    semantic_retrieval: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    """Require the semantic boundary before a Twelve Data dossier can be composed."""

    if not isinstance(context, Mapping):
        raise TypeError("semantic decision context must be a mapping")
    if context.get("semantic_context_packet_version") != SEMANTIC_CONTEXT_PACKET_VERSION:
        raise ValueError("Twelve Data dossier requires semantic market context v1")

    provenance = context.get("provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    identity = provenance.get("gold_market_data_semantic_identity")
    if not isinstance(identity, Mapping) or not verify_semantic_identity(identity):
        raise ValueError("Twelve Data dossier requires a valid embedded market-data identity")
    identity_digest = str(identity["semantic_identity_digest"])
    if context.get("market_data_semantic_identity_digest") != identity_digest:
        raise ValueError("semantic context identity digest does not match embedded identity")

    if not verify_semantic_retrieval_wrapper(semantic_retrieval):
        raise ValueError("Twelve Data dossier requires a verified semantic analogue retrieval")
    if semantic_retrieval.get("query_market_data_semantic_identity_digest") != identity_digest:
        raise ValueError("semantic retrieval query identity does not match current Gold context")

    base = semantic_retrieval.get("base_retrieval")
    if not isinstance(base, Mapping):  # defensive; verifier already checks this.
        raise TypeError("semantic retrieval base_retrieval must be a mapping")
    return copy.deepcopy(dict(base)), identity_digest


def compose_semantic_context_v2(
    *,
    context: Mapping[str, Any],
    aidy_state: Mapping[str, Any],
    semantic_retrieval: Mapping[str, Any],
    evidence_report: Mapping[str, Any],
    hypothesis_direction: str,
    setup_family: str | None,
    invalidation_inputs: Mapping[str, Any],
    max_bundle_bytes: int | None = None,
) -> dict[str, Any]:
    """Compose the authoritative Twelve Data dossier through the semantic gate.

    The legacy Day-35 composer remains the deterministic dossier implementation.
    This wrapper makes semantic compatibility a prerequisite and binds the
    verified semantic-retrieval identity into the final dossier digest without
    exposing raw historical outcomes to the model.
    """

    base_retrieval, identity_digest = validate_semantic_decision_inputs(
        context=context,
        semantic_retrieval=semantic_retrieval,
    )
    dossier = compose_context_v2(
        context=context,
        aidy_state=aidy_state,
        retrieval=base_retrieval,
        evidence_report=evidence_report,
        hypothesis_direction=hypothesis_direction,
        setup_family=setup_family,
        invalidation_inputs=invalidation_inputs,
        max_bundle_bytes=max_bundle_bytes,
    )
    result = copy.deepcopy(dict(dossier))
    result.pop("dossier_digest", None)
    result["semantic_context_composer_version"] = SEMANTIC_CONTEXT_COMPOSER_VERSION
    result["semantic_dossier_binding"] = {
        "binding_version": SEMANTIC_DOSSIER_BINDING_VERSION,
        "market_data_semantic_identity_digest": identity_digest,
        "semantic_retrieval_digest": semantic_retrieval["semantic_retrieval_digest"],
        "semantic_query_version": semantic_retrieval["semantic_query_version"],
        "semantic_retrieval_version": semantic_retrieval["semantic_retrieval_version"],
        "semantic_candidate_count_before_gate": semantic_retrieval.get(
            "candidate_count_before_semantic_gate"
        ),
        "semantic_compatible_candidate_count": semantic_retrieval.get(
            "semantic_compatible_candidate_count"
        ),
        "semantic_exclusion_counts": copy.deepcopy(
            semantic_retrieval.get("semantic_exclusion_counts") or {}
        ),
        "accepted_equivalence_ledger_record_digests": copy.deepcopy(
            semantic_retrieval.get("accepted_equivalence_ledger_record_digests") or []
        ),
        "cross_source_comparison_without_ledger_proven_pass_allowed": False,
    }
    result["dossier_digest"] = digest(result)
    return result
