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
CURRENT_OBJECTIVE_CONTEXT_VERSION = "aidy_current_objective_context_projection_v1"

# The model needs objective market facts, not large provenance arrays. The full
# authenticated context remains bound by context_hash; this projection removes
# only lineage-heavy fields that do not change the market fact itself.
_PROJECTION_LINEAGE_KEYS = frozenset(
    {
        "source_identities",
        "source_identity",
        "source_links",
        "load_identity",
        "evidence_id",
        "archive_key",
        "raw_payload_json",
    }
)
_OBJECTIVE_CONTEXT_ROOTS = (
    "gold",
    "session",
    "event_risk",
    "cross_market",
    "aidy_signal_lifecycle",
    "data_quality",
    "structural_context",
    "price_structure_context",
    "rates_macro_context",
    "event_intelligence",
    "cme_contract_context",
    "volatility_state",
    "architecture_v2_extensions",
)


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


def _project_objective_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _project_objective_value(item)
            for key, item in value.items()
            if str(key) not in _PROJECTION_LINEAGE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_project_objective_value(item) for item in value]
    return copy.deepcopy(value)


def current_objective_context_projection(context: Mapping[str, Any]) -> dict[str, Any]:
    """Expose authenticated live facts to Master Trader without raw lineage bulk."""

    projection: dict[str, Any] = {
        "projection_version": CURRENT_OBJECTIVE_CONTEXT_VERSION,
        "context_packet_version": context.get("context_packet_version"),
        "context_hash": context.get("context_hash"),
        "as_of_utc": context.get("as_of_utc"),
        "symbol": context.get("symbol"),
        "market_data_semantic_identity_digest": context.get(
            "market_data_semantic_identity_digest"
        ),
        "source_contract_versions": _project_objective_value(
            context.get("source_contract_versions") or {}
        ),
    }
    for root in _OBJECTIVE_CONTEXT_ROOTS:
        if root in context:
            projection[root] = _project_objective_value(context[root])
    projection["projection_digest"] = digest(projection)
    return projection


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

    The accepted Day-35 composer remains the deterministic historical-evidence
    implementation. This wrapper makes semantic compatibility a prerequisite,
    then adds the authenticated current objective context so Master Trader sees
    the same live candle/liquidity facts that deterministic safety and setup
    recognition see. Raw historical outcomes and provenance-heavy identity lists
    remain outside the prompt surface.
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
    current_context = current_objective_context_projection(context)
    result = copy.deepcopy(dict(dossier))
    result.pop("dossier_digest", None)
    result["semantic_context_composer_version"] = SEMANTIC_CONTEXT_COMPOSER_VERSION
    result["current_objective_context"] = current_context
    result["current_objective_context_digest"] = current_context["projection_digest"]
    result["semantic_dossier_binding"] = {
        "binding_version": SEMANTIC_DOSSIER_BINDING_VERSION,
        "market_data_semantic_identity_digest": identity_digest,
        "current_context_hash": context.get("context_hash"),
        "current_objective_context_digest": current_context["projection_digest"],
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