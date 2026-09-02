from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from aidy.historical_cases import (
    build_pit_case_input,
    build_retrospective_case_input,
    compute_case_input_digest,
)
from aidy.market_data_semantics import (
    histdata_semantic_identity,
    identity_from_feature_packet,
    verify_semantic_identity,
)

SEMANTIC_CASE_INPUT_VERSION = "aidy_semantic_case_input_wrapper_v1"


def _attach(input_boundary: Mapping[str, Any], identity: Mapping[str, Any]) -> dict[str, Any]:
    if not verify_semantic_identity(identity):
        raise ValueError("cannot attach invalid market-data semantic identity")
    result = dict(input_boundary)
    result.pop("input_digest", None)
    result["semantic_case_input_version"] = SEMANTIC_CASE_INPUT_VERSION
    result["market_data_semantic_identity"] = dict(identity)
    result["market_data_semantic_identity_digest"] = identity["semantic_identity_digest"]
    result["input_digest"] = compute_case_input_digest(result)
    return result


def build_semantic_retrospective_case_input(
    *,
    as_of: Any,
    research_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    rows = list(research_rows)
    base = build_retrospective_case_input(as_of=as_of, research_rows=rows)
    return _attach(base, histdata_semantic_identity())


def build_semantic_pit_case_input(
    *,
    context: Mapping[str, Any],
    regime: Mapping[str, Any],
    setup_detection: Mapping[str, Any],
) -> dict[str, Any]:
    base = build_pit_case_input(
        context=context,
        regime=regime,
        setup_detection=setup_detection,
    )
    gold = context.get("gold")
    if not isinstance(gold, Mapping):
        raise TypeError("PIT context.gold must be an object")
    identity = identity_from_feature_packet(gold)
    return _attach(base, identity)
