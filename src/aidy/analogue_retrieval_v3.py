from __future__ import annotations

import copy
import json
from collections.abc import Iterable, Mapping
from hashlib import sha256
from typing import Any

from aidy import analogue_retrieval as v1
from aidy.analogue_retrieval_v2 import (
    ANALOGUE_RETRIEVAL_VERSION_V2,
    DEFAULT_MIN_COMPONENT_COVERAGE,
    DEFAULT_MIN_SIMILARITY,
    EMBARGO_MINUTES,
    EPISODE_HORIZON_MINUTES,
    retrieve_analogues_v2,
    verify_retrieval_digest_v2,
)
from aidy.historical_case_context_v2 import enrich_historical_case_with_market_structure
from aidy.market_structure_context import (
    MARKET_STRUCTURE_CONTEXT_VERSION,
    build_market_structure_context,
)

ANALOGUE_RETRIEVAL_VERSION_V3 = "aidy_historical_analogue_retrieval_v3_structural_epoch"


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def enrich_query_with_market_structure(query: Mapping[str, Any]) -> dict[str, Any]:
    v1._validate_query(query)
    enriched = copy.deepcopy(dict(query))
    structural = build_market_structure_context(as_of=str(enriched["as_of_utc"]))
    features = enriched.get("analogue_features")
    if not isinstance(features, Mapping):
        raise TypeError("Day 25 query requires analogue_features.")
    analogue_features = copy.deepcopy(dict(features))
    analogue_features["market_structure_epoch"] = structural["market_structure_epoch"]
    enriched["analogue_features"] = analogue_features
    enriched["day25_structural_context"] = structural
    enriched.pop("query_id", None)
    enriched["query_id"] = _digest(enriched)
    v1._validate_query(enriched)
    return enriched


def retrieve_analogues_v3(
    *,
    query: Mapping[str, Any],
    candidate_cases: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Activate the Day 24 hard epoch gate without changing Day 24 selection logic."""

    enriched_query = enrich_query_with_market_structure(query)
    source_cases = list(candidate_cases)
    enriched_cases: list[dict[str, Any]] = []
    source_case_ids: dict[str, str] = {}
    for source_case in source_cases:
        enriched = enrich_historical_case_with_market_structure(case=source_case)
        enriched_cases.append(enriched)
        source_case_ids[str(enriched["case_id"])] = str(source_case["case_id"])

    retrieval = retrieve_analogues_v2(
        query=enriched_query,
        candidate_cases=enriched_cases,
    )
    if not verify_retrieval_digest_v2(retrieval):
        raise ValueError("Day 25 delegated Day 24 retrieval digest does not reproduce.")
    forbidden_relaxation = "market_structure_epoch_unavailable_pre_day25"
    if any(item.get("name") == forbidden_relaxation for item in retrieval["gate_relaxations"]):
        raise RuntimeError("Day 25 known-epoch query emitted the pre-Day25 epoch relaxation.")

    body: dict[str, Any] = {
        "day25_retrieval_version": ANALOGUE_RETRIEVAL_VERSION_V3,
        "market_structure_context_version": MARKET_STRUCTURE_CONTEXT_VERSION,
        "source_retrieval_version": ANALOGUE_RETRIEVAL_VERSION_V2,
        "source_retrieval_digest": retrieval["retrieval_digest"],
        "source_query_id": query["query_id"],
        "enriched_query_id": enriched_query["query_id"],
        "query_market_structure_epoch": enriched_query["analogue_features"][
            "market_structure_epoch"
        ],
        "source_candidate_count": len(source_cases),
        "derived_candidate_count": len(enriched_cases),
        "derived_to_source_case_ids": dict(sorted(source_case_ids.items())),
        "day24_thresholds_unchanged": {
            "min_similarity_score": str(DEFAULT_MIN_SIMILARITY),
            "min_component_coverage": str(DEFAULT_MIN_COMPONENT_COVERAGE),
            "embargo_minutes": EMBARGO_MINUTES,
            "episode_horizon_minutes": EPISODE_HORIZON_MINUTES,
        },
        "known_epoch_relaxation_permitted": False,
        "outcome_values_used_for_epoch_assignment": False,
        "outcome_values_used_for_selection": False,
        "retrieval": retrieval,
    }
    body["day25_retrieval_digest"] = _digest(body)
    return body


def verify_retrieval_digest_v3(value: Mapping[str, Any]) -> bool:
    if value.get("day25_retrieval_version") != ANALOGUE_RETRIEVAL_VERSION_V3:
        return False
    retrieval = value.get("retrieval")
    if not isinstance(retrieval, Mapping) or not verify_retrieval_digest_v2(retrieval):
        return False
    body = dict(value)
    supplied = str(body.pop("day25_retrieval_digest", ""))
    return bool(supplied) and supplied == _digest(body)
