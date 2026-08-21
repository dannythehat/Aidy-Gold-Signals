from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from aidy.historical_cases import (
    build_historical_case,
    compute_case_input_digest,
    verify_historical_case_digest,
)
from aidy.market_structure_context import (
    MARKET_STRUCTURE_CONTEXT_VERSION,
    build_market_structure_context,
    verify_market_structure_context,
)

HISTORICAL_CASE_CONTEXT_VERSION_V2 = "aidy_historical_case_structural_context_v2"


def enrich_input_boundary_with_market_structure(
    *,
    input_boundary: Mapping[str, Any],
    official_schedule_records: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    enriched = copy.deepcopy(dict(input_boundary))
    structural = build_market_structure_context(
        as_of=str(enriched.get("as_of_utc") or ""),
        official_schedule_records=official_schedule_records,
    )
    if not verify_market_structure_context(structural):
        raise ValueError("Day 25 structural context digest does not match contents.")

    features = enriched.get("analogue_features")
    if not isinstance(features, Mapping):
        raise TypeError("Day 25 historical input requires analogue_features.")
    analogue_features = copy.deepcopy(dict(features))
    analogue_features["market_structure_epoch"] = structural["market_structure_epoch"]

    enriched["structural_context_version"] = HISTORICAL_CASE_CONTEXT_VERSION_V2
    enriched["market_structure_context_version"] = MARKET_STRUCTURE_CONTEXT_VERSION
    enriched["structural_context"] = structural
    enriched["analogue_features"] = analogue_features
    enriched["input_digest"] = compute_case_input_digest(enriched)
    return enriched


def enrich_historical_case_with_market_structure(
    *,
    case: Mapping[str, Any],
    official_schedule_records: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Create a valid derived canonical case without mutating the accepted v1 case."""

    if not verify_historical_case_digest(case):
        raise ValueError("Day 25 enrichment requires a valid accepted historical case.")
    boundary = case.get("input_boundary")
    future = case.get("future_evaluation")
    if not isinstance(boundary, Mapping) or not isinstance(future, Mapping):
        raise TypeError("Day 25 case requires input_boundary and future_evaluation objects.")

    enriched_boundary = enrich_input_boundary_with_market_structure(
        input_boundary=boundary,
        official_schedule_records=official_schedule_records,
    )
    return build_historical_case(
        input_boundary=enriched_boundary,
        move_bundle=(
            dict(future["move_bundle"])
            if isinstance(future.get("move_bundle"), Mapping)
            else None
        ),
        trade_outcome_bundle=(
            dict(future["trade_outcome_bundle"])
            if isinstance(future.get("trade_outcome_bundle"), Mapping)
            else None
        ),
        no_trade_counterfactual=(
            dict(future["no_trade_counterfactual"])
            if isinstance(future.get("no_trade_counterfactual"), Mapping)
            else None
        ),
    )


def enrich_historical_cases_with_market_structure(
    cases: Iterable[Mapping[str, Any]],
    *,
    official_schedule_records: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    records = list(official_schedule_records)
    return [
        enrich_historical_case_with_market_structure(
            case=case,
            official_schedule_records=records,
        )
        for case in cases
    ]


def market_structure_epoch_from_case(case: Mapping[str, Any]) -> str:
    boundary = case.get("input_boundary")
    if not isinstance(boundary, Mapping):
        raise TypeError("Historical case input_boundary must be an object.")
    structural = boundary.get("structural_context")
    if not isinstance(structural, Mapping) or not verify_market_structure_context(structural):
        raise ValueError("Historical case lacks valid Day 25 structural context.")
    return str(structural["market_structure_epoch"])


def structural_context_for_timestamp(
    value: datetime | str,
    *,
    official_schedule_records: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    return build_market_structure_context(
        as_of=value,
        official_schedule_records=official_schedule_records,
    )
