from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

from aidy import analogue_retrieval as v1
from aidy import analogue_retrieval_v2 as v2
from aidy.market_data_semantics import (
    assert_semantic_compatible,
    digest,
    verify_semantic_identity,
)

SEMANTIC_ANALOGUE_QUERY_VERSION = "aidy_semantic_analogue_query_v1"
SEMANTIC_ANALOGUE_RETRIEVAL_VERSION = "aidy_semantic_analogue_retrieval_v1"


def build_semantic_analogue_query(
    *,
    input_boundary: Mapping[str, Any],
    allowed_provenance: Iterable[str] = ("retrospective_history",),
    source_case_id: str | None = None,
    max_results: int = v1.DEFAULT_MAX_RESULTS,
    min_similarity_score: Any = v1.DEFAULT_MIN_SIMILARITY,
    min_component_coverage: Any = v1.DEFAULT_MIN_COMPONENT_COVERAGE,
) -> dict[str, Any]:
    identity = input_boundary.get("market_data_semantic_identity")
    if not isinstance(identity, Mapping) or not verify_semantic_identity(identity):
        raise ValueError("semantic analogue query requires a valid market-data semantic identity")
    if input_boundary.get("market_data_semantic_identity_digest") != identity.get(
        "semantic_identity_digest"
    ):
        raise ValueError("case input semantic identity digest does not match identity contents")

    query = v1.build_analogue_query(
        input_boundary=input_boundary,
        allowed_provenance=allowed_provenance,
        source_case_id=source_case_id,
        max_results=max_results,
        min_similarity_score=min_similarity_score,
        min_component_coverage=min_component_coverage,
    )
    query.pop("query_id", None)
    query["semantic_query_version"] = SEMANTIC_ANALOGUE_QUERY_VERSION
    query["market_data_semantic_identity"] = dict(identity)
    query["market_data_semantic_identity_digest"] = identity["semantic_identity_digest"]
    query["query_id"] = v1._digest(query)
    v1._validate_query(query)
    return query


def _candidate_identity(case: Mapping[str, Any]) -> Mapping[str, Any] | None:
    boundary = case.get("input_boundary")
    if not isinstance(boundary, Mapping):
        return None
    identity = boundary.get("market_data_semantic_identity")
    return identity if isinstance(identity, Mapping) else None


def retrieve_semantic_analogues_v2(
    *,
    query: Mapping[str, Any],
    candidate_cases: Iterable[Mapping[str, Any]],
    accepted_equivalence_contracts: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    v1._validate_query(query)
    if query.get("semantic_query_version") != SEMANTIC_ANALOGUE_QUERY_VERSION:
        raise ValueError("Twelve Data epoch analogue retrieval requires semantic query v1")
    query_identity = query.get("market_data_semantic_identity")
    if not isinstance(query_identity, Mapping) or not verify_semantic_identity(query_identity):
        raise ValueError("query market-data semantic identity is missing or invalid")
    if query.get("market_data_semantic_identity_digest") != query_identity.get(
        "semantic_identity_digest"
    ):
        raise ValueError("query semantic identity digest does not match identity contents")

    contracts = dict(accepted_equivalence_contracts or {})
    raw_candidates = list(candidate_cases)
    compatible: list[Mapping[str, Any]] = []
    exclusions: Counter[str] = Counter()
    compatibility_evidence: list[dict[str, Any]] = []
    query_digest = str(query_identity["semantic_identity_digest"])

    for case in raw_candidates:
        if not isinstance(case, Mapping):
            raise TypeError("semantic analogue candidates must be historical-case objects")
        candidate_identity = _candidate_identity(case)
        if candidate_identity is None or not verify_semantic_identity(candidate_identity):
            exclusions["candidate_semantic_identity_missing_or_invalid"] += 1
            continue
        candidate_digest = str(candidate_identity["semantic_identity_digest"])
        contract_key = f"{query_digest}:{candidate_digest}"
        contract_digest = contracts.get(contract_key)
        try:
            evidence = assert_semantic_compatible(
                query_identity,
                candidate_identity,
                accepted_equivalence_contract_digest=contract_digest,
            )
        except ValueError:
            exclusions["market_data_semantic_identity_incompatible"] += 1
            continue
        compatible.append(case)
        compatibility_evidence.append(
            {
                "case_id": case.get("case_id"),
                **evidence,
            }
        )

    base = v2.retrieve_analogues_v2(query=query, candidate_cases=compatible)
    result: dict[str, Any] = {
        "semantic_retrieval_version": SEMANTIC_ANALOGUE_RETRIEVAL_VERSION,
        "semantic_query_version": SEMANTIC_ANALOGUE_QUERY_VERSION,
        "query_id": query["query_id"],
        "query_market_data_semantic_identity_digest": query_digest,
        "candidate_count_before_semantic_gate": len(raw_candidates),
        "semantic_compatible_candidate_count": len(compatible),
        "semantic_exclusion_counts": dict(sorted(exclusions.items())),
        "compatibility_evidence": compatibility_evidence,
        "accepted_equivalence_contracts": dict(sorted(contracts.items())),
        "base_retrieval": base,
        "cross_source_comparison_without_qualified_contract_allowed": False,
    }
    result["semantic_retrieval_digest"] = digest(result)
    return result
