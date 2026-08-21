from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy import analogue_retrieval as v1

ANALOGUE_RETRIEVAL_VERSION_V2 = "aidy_historical_analogue_retrieval_v2_independent_episodes"
SIMILARITY_FEATURE_VERSION_V2 = "aidy_gold_similarity_features_v2_decorrelated"
INDEPENDENCE_POLICY_VERSION = "aidy_analogue_independence_policy_v1"
STRUCTURAL_GATE_VERSION = "aidy_analogue_structural_gate_v1"
EPISODE_HORIZON_MINUTES = 240
EMBARGO_MINUTES = 240

# The Day-17 numerical thresholds are deliberately carried forward unchanged.
# Day 24 changes the evidence geometry, not the threshold values.
DEFAULT_MIN_SIMILARITY = v1.DEFAULT_MIN_SIMILARITY
DEFAULT_MIN_COMPONENT_COVERAGE = v1.DEFAULT_MIN_COMPONENT_COVERAGE

_UNKNOWN = {"", "unknown", "unavailable", "unavailable_by_retrospective_provenance", None}

# Low-dimensional, deliberately decorrelated similarity after hard structural gating.
# Trend and volatility are gates, not repeated as soft similarity votes.
_COMPONENTS: tuple[tuple[str, tuple[str, ...], str, Decimal, Decimal | None], ...] = (
    ("session", ("regime", "session"), "categorical", Decimal("1.00"), None),
    ("event_timing", ("regime", "event_timing"), "categorical", Decimal("1.00"), None),
    ("h1_atr", ("h1_atr_14_bps",), "numeric", Decimal("1.00"), Decimal(40)),
    (
        "range_position",
        ("m15_range_position_20",),
        "numeric",
        Decimal("1.00"),
        Decimal("0.50"),
    ),
    ("setup_ids", ("candidate_setup_ids",), "set", Decimal("1.00"), None),
)
_TOTAL_WEIGHT = sum((item[3] for item in _COMPONENTS), Decimal(0))


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Day 24 timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _score(value: Decimal) -> str:
    bounded = min(Decimal(1), max(Decimal(0), value))
    return str(bounded.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def _number(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def _path(payload: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _known_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    return None if text in {"", "unknown", "unavailable", "unavailable_by_retrospective_provenance"} else text


def _market_structure_epoch(features: Mapping[str, Any]) -> str | None:
    direct = _known_text(features.get("market_structure_epoch"))
    if direct is not None:
        return direct
    regime = features.get("regime")
    if isinstance(regime, Mapping):
        return _known_text(regime.get("market_structure_epoch"))
    return None


def similarity_manifest_v2() -> dict[str, Any]:
    body = {
        "similarity_feature_version": SIMILARITY_FEATURE_VERSION_V2,
        "source_query_similarity_version": v1.SIMILARITY_FEATURE_VERSION,
        "source_query_version": v1.ANALOGUE_QUERY_VERSION,
        "retrieval_version": ANALOGUE_RETRIEVAL_VERSION_V2,
        "independence_policy_version": INDEPENDENCE_POLICY_VERSION,
        "structural_gate_version": STRUCTURAL_GATE_VERSION,
        "episode_horizon_minutes": EPISODE_HORIZON_MINUTES,
        "embargo_minutes": EMBARGO_MINUTES,
        "threshold_basis": "day17_values_carried_forward_without_outcome_optimization",
        "default_min_similarity_score": str(DEFAULT_MIN_SIMILARITY),
        "default_min_component_coverage": str(DEFAULT_MIN_COMPONENT_COVERAGE),
        "hard_gate_dimensions": ["regime.trend_structure", "regime.volatility_band"],
        "market_structure_epoch_gate": (
            "hard_when_query_epoch_is_known;_explicit_pre_day25_relaxation_when_query_epoch_unavailable"
        ),
        "components": [
            {
                "name": name,
                "path": ".".join(path),
                "kind": kind,
                "weight": str(weight),
                "numeric_scale": None if scale is None else str(scale),
            }
            for name, path, kind, weight, scale in _COMPONENTS
        ],
        "total_weight": str(_TOTAL_WEIGHT),
        "deliberately_excluded_redundant_soft_votes": [
            "regime.trend_structure",
            "regime.volatility_band",
            "m15_direction",
            "h1_direction",
            "h4_direction",
            "m15_realized_vol_20_bps",
            "m15_close_location",
            "session_range_position",
            "regime.quote_spread_condition",
        ],
        "learned_embeddings": False,
        "metric_learning": False,
        "dynamic_time_warping": False,
        "outcome_values_used_for_similarity": False,
    }
    body["manifest_digest"] = _digest(body)
    return body


def _categorical(left: Any, right: Any) -> Decimal | None:
    lhs = _known_text(left)
    rhs = _known_text(right)
    if lhs is None or rhs is None:
        return None
    return Decimal(1) if lhs == rhs else Decimal(0)


def _numeric(left: Any, right: Any, *, scale: Decimal) -> Decimal | None:
    lhs = _decimal(left)
    rhs = _decimal(right)
    if lhs is None or rhs is None:
        return None
    return max(Decimal(0), Decimal(1) - abs(lhs - rhs) / scale)


def _set_similarity(left: Any, right: Any) -> Decimal | None:
    if not isinstance(left, (list, tuple, set)) or not isinstance(right, (list, tuple, set)):
        return None
    lhs = {str(value) for value in left}
    rhs = {str(value) for value in right}
    if not lhs and not rhs:
        return Decimal(1)
    union = lhs | rhs
    return Decimal(len(lhs & rhs)) / Decimal(len(union)) if union else Decimal(1)


def score_similarity_v2(
    *, query_features: Mapping[str, Any], candidate_features: Mapping[str, Any]
) -> dict[str, Any]:
    components: list[dict[str, Any]] = []
    covered = Decimal(0)
    earned = Decimal(0)
    for name, path, kind, weight, scale in _COMPONENTS:
        left = _path(query_features, path)
        right = _path(candidate_features, path)
        if kind == "categorical":
            value = _categorical(left, right)
        elif kind == "numeric":
            assert scale is not None
            value = _numeric(left, right, scale=scale)
        elif kind == "set":
            value = _set_similarity(left, right)
        else:  # pragma: no cover - frozen manifest makes this unreachable.
            raise RuntimeError(f"Unsupported Day 24 similarity kind: {kind}")
        if value is None:
            state = "unavailable"
            rendered = None
        else:
            state = "compared"
            rendered = _score(value)
            covered += weight
            earned += weight * value
        components.append(
            {
                "name": name,
                "kind": kind,
                "weight": str(weight),
                "state": state,
                "query_value": left,
                "candidate_value": right,
                "component_similarity": rendered,
            }
        )
    coverage = covered / _TOTAL_WEIGHT if _TOTAL_WEIGHT else Decimal(0)
    similarity = earned / covered if covered else Decimal(0)
    result = {
        "similarity_feature_version": SIMILARITY_FEATURE_VERSION_V2,
        "similarity_score": _score(similarity),
        "distance_score": _score(Decimal(1) - similarity),
        "component_coverage": _score(coverage),
        "covered_weight": str(covered),
        "total_weight": str(_TOTAL_WEIGHT),
        "components": components,
        "future_outcomes_used": False,
    }
    result["score_digest"] = _digest(result)
    return result


def _hard_gate(
    query_features: Mapping[str, Any], candidate_features: Mapping[str, Any]
) -> tuple[bool, str, list[str]]:
    relaxations: list[str] = []
    for key in ("trend_structure", "volatility_band"):
        query_value = _known_text(_path(query_features, ("regime", key)))
        candidate_value = _known_text(_path(candidate_features, ("regime", key)))
        if query_value is None:
            return False, f"query_hard_gate_{key}_unknown", relaxations
        if candidate_value is None:
            return False, f"candidate_hard_gate_{key}_unknown", relaxations
        if query_value != candidate_value:
            return False, f"hard_gate_{key}_mismatch", relaxations

    query_epoch = _market_structure_epoch(query_features)
    candidate_epoch = _market_structure_epoch(candidate_features)
    if query_epoch is None:
        # Day 25 creates the canonical epoch field. Day 24 must surface, not hide,
        # this temporary migration relaxation so the gate becomes hard automatically
        # once the query carries an epoch.
        relaxations.append("market_structure_epoch_unavailable_pre_day25")
    elif candidate_epoch is None:
        return False, "candidate_market_structure_epoch_unknown", relaxations
    elif query_epoch != candidate_epoch:
        return False, "hard_gate_market_structure_epoch_mismatch", relaxations
    return True, "hard_gate_pass", relaxations


def _move_240(case: Mapping[str, Any]) -> Mapping[str, Any] | None:
    future = case.get("future_evaluation")
    if not isinstance(future, Mapping):
        return None
    bundle = future.get("move_bundle")
    if not isinstance(bundle, Mapping):
        return None
    labels = bundle.get("labels")
    if not isinstance(labels, list):
        return None
    for label in labels:
        if (
            isinstance(label, Mapping)
            and int(label.get("horizon_minutes", -1)) == EPISODE_HORIZON_MINUTES
            and label.get("coverage_state") == "complete"
        ):
            return label
    return None


def _episode_window(case: Mapping[str, Any]) -> tuple[datetime, datetime] | None:
    label = _move_240(case)
    if label is None:
        return None
    anchor = label.get("anchor_time_utc")
    horizon_end = label.get("horizon_end_utc")
    if anchor is None or horizon_end is None:
        return None
    start = _utc(str(anchor))
    end = _utc(str(horizon_end))
    if end <= start:
        return None
    return start, end


def _episode_components(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        matches,
        key=lambda item: (
            _utc(str(item["episode_window_start_utc"])),
            str(item["case_id"]),
        ),
    )
    episodes: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for item in ordered:
        start = _utc(str(item["episode_window_start_utc"]))
        end = _utc(str(item["episode_window_end_utc"]))
        if current is None or start >= current["window_end"]:
            current = {"window_start": start, "window_end": end, "members": []}
            episodes.append(current)
        else:
            current["window_end"] = max(current["window_end"], end)
        current["members"].append(item)
    return episodes


def _independence_payload(pre_dedup: list[dict[str, Any]], returned: list[dict[str, Any]]) -> dict[str, Any]:
    raw_n = len(pre_dedup)
    episodes = _episode_components(pre_dedup) if pre_dedup else []
    counts = [len(item["members"]) for item in episodes]
    if raw_n:
        sum_squares = sum(value * value for value in counts)
        kish = Decimal(raw_n * raw_n) / Decimal(sum_squares)
        ratio = kish / Decimal(raw_n)
    else:
        kish = Decimal(0)
        ratio = None
    stamps = [_utc(str(item["as_of_utc"])) for item in returned]
    months = sorted({stamp.strftime("%Y-%m") for stamp in stamps})
    span_hours = (
        Decimal(str((max(stamps) - min(stamps)).total_seconds())) / Decimal(3600)
        if len(stamps) >= 2
        else Decimal(0) if stamps else None
    )
    episode_rows = []
    for episode in episodes:
        members = sorted(
            episode["members"],
            key=lambda item: (
                -Decimal(str(item["similarity"]["similarity_score"])),
                -Decimal(str(item["similarity"]["component_coverage"])),
                str(item["case_id"]),
            ),
        )
        episode_identity = {
            "window_start_utc": episode["window_start"].isoformat(),
            "window_end_utc": episode["window_end"].isoformat(),
            "member_case_ids": [str(item["case_id"]) for item in members],
        }
        episode_rows.append(
            {
                **episode_identity,
                "representative_case_id": str(members[0]["case_id"]),
                "episode_id": _digest(episode_identity),
            }
        )
    return {
        "independence_policy_version": INDEPENDENCE_POLICY_VERSION,
        "pre_dedup_raw_n": raw_n,
        "pre_dedup_kish_effective_n": _number(kish),
        "pre_dedup_effective_n_over_raw_n": None if ratio is None else _number(ratio),
        "distinct_independent_episodes": len(episodes),
        "grading_effective_n": len(returned),
        "returned_episode_representatives": len(returned),
        "temporal_span_hours": None if span_hours is None else _number(span_hours),
        "distinct_months": len(months),
        "months": months,
        "episodes": episode_rows,
    }


def _selection_digest(query_id: str, matches: list[dict[str, Any]]) -> str:
    return _digest(
        {
            "query_id": query_id,
            "selection": [
                {
                    "rank": item["rank"],
                    "case_id": item["case_id"],
                    "episode_id": item["episode_id"],
                    "similarity_score": item["similarity"]["similarity_score"],
                    "component_coverage": item["similarity"]["component_coverage"],
                }
                for item in matches
            ],
        }
    )


def retrieve_analogues_v2(
    *, query: Mapping[str, Any], candidate_cases: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    # The exact frozen Day-17 query payload remains the comparison input.
    v1._validate_query(query)
    candidates = list(candidate_cases)
    query_id = str(query["query_id"])
    query_time = _utc(str(query["as_of_utc"]))
    max_results = int(query["max_results"])
    min_similarity = Decimal(str(query["min_similarity_score"]))
    min_coverage = Decimal(str(query["min_component_coverage"]))
    query_features = query.get("analogue_features")
    if not isinstance(query_features, Mapping):
        raise TypeError("Day 24 query requires analogue_features.")

    if query.get("query_retrieval_eligible") is False:
        empty_independence = _independence_payload([], [])
        result = {
            "retrieval_version": ANALOGUE_RETRIEVAL_VERSION_V2,
            "source_query_version": v1.ANALOGUE_QUERY_VERSION,
            "source_query_retrieval_version": v1.ANALOGUE_RETRIEVAL_VERSION,
            "similarity_feature_version": SIMILARITY_FEATURE_VERSION_V2,
            "query_id": query_id,
            "query_as_of_utc": query["as_of_utc"],
            "evidence_state": "query_insufficient_quality",
            "no_comparable_reason": "query_retrieval_eligible_false",
            "candidate_count": len(candidates),
            "eligible_candidate_count": 0,
            "hard_gate_pass_count": 0,
            "sufficient_match_count": 0,
            "returned_match_count": 0,
            "matches": [],
            "exclusion_counts": {},
            "gate_relaxations": [],
            "independence": empty_independence,
            "selection_digest": _selection_digest(query_id, []),
            "outcome_values_used_for_selection": False,
            "outcome_window_metadata_used_for_independence": True,
            "probability_claims_included": False,
        }
        result["retrieval_digest"] = _digest(result)
        return result

    # Fail closed if the query cannot support the structural gate itself.
    for key in ("trend_structure", "volatility_band"):
        if _known_text(_path(query_features, ("regime", key))) is None:
            empty_independence = _independence_payload([], [])
            result = {
                "retrieval_version": ANALOGUE_RETRIEVAL_VERSION_V2,
                "source_query_version": v1.ANALOGUE_QUERY_VERSION,
                "source_query_retrieval_version": v1.ANALOGUE_RETRIEVAL_VERSION,
                "similarity_feature_version": SIMILARITY_FEATURE_VERSION_V2,
                "query_id": query_id,
                "query_as_of_utc": query["as_of_utc"],
                "evidence_state": "no_comparable_case",
                "no_comparable_reason": f"query_hard_gate_{key}_unknown",
                "candidate_count": len(candidates),
                "eligible_candidate_count": 0,
                "hard_gate_pass_count": 0,
                "sufficient_match_count": 0,
                "returned_match_count": 0,
                "matches": [],
                "exclusion_counts": {},
                "gate_relaxations": [],
                "independence": empty_independence,
                "selection_digest": _selection_digest(query_id, []),
                "outcome_values_used_for_selection": False,
                "outcome_window_metadata_used_for_independence": True,
                "probability_claims_included": False,
            }
            result["retrieval_digest"] = _digest(result)
            return result

    exclusion_counts: Counter[str] = Counter()
    relaxations: Counter[str] = Counter()
    sufficient: list[dict[str, Any]] = []
    eligible_count = 0
    hard_gate_pass_count = 0
    embargo_cutoff = query_time - timedelta(minutes=EMBARGO_MINUTES)

    for raw_case in candidates:
        if not isinstance(raw_case, Mapping):
            raise TypeError("Day 24 candidates must be historical-case objects.")
        v1._validate_candidate_case(raw_case)
        eligible, reason = v1._candidate_eligibility(query=query, case=raw_case)
        if not eligible:
            exclusion_counts[reason] += 1
            continue
        eligible_count += 1

        window = _episode_window(raw_case)
        if window is None:
            exclusion_counts["episode_window_unavailable"] += 1
            continue
        window_start, window_end = window
        if window_end > embargo_cutoff:
            exclusion_counts["query_embargo_overlap"] += 1
            continue

        boundary = raw_case.get("input_boundary")
        if not isinstance(boundary, Mapping):
            raise TypeError("Day 24 candidate requires input_boundary.")
        candidate_features = boundary.get("analogue_features")
        if not isinstance(candidate_features, Mapping):
            raise TypeError("Day 24 candidate requires analogue_features.")
        gate_pass, gate_reason, gate_relaxations = _hard_gate(query_features, candidate_features)
        for item in gate_relaxations:
            relaxations[item] += 1
        if not gate_pass:
            exclusion_counts[gate_reason] += 1
            continue
        hard_gate_pass_count += 1

        similarity = score_similarity_v2(
            query_features=query_features,
            candidate_features=candidate_features,
        )
        coverage = Decimal(str(similarity["component_coverage"]))
        score = Decimal(str(similarity["similarity_score"]))
        if coverage < min_coverage:
            exclusion_counts["coverage_below_threshold"] += 1
            continue
        if score < min_similarity:
            exclusion_counts["similarity_below_threshold"] += 1
            continue

        future = raw_case.get("future_evaluation")
        if not isinstance(future, Mapping):
            raise TypeError("Day 24 candidate requires future_evaluation.")
        sufficient.append(
            {
                "case_id": raw_case["case_id"],
                "as_of_utc": raw_case["as_of_utc"],
                "provenance_class": raw_case["provenance_class"],
                "input_digest": boundary["input_digest"],
                "data_quality_grade": boundary["data_quality"]["grade"],
                "regime": boundary["regime"]["labels"],
                "setup_detector_state": boundary["setup"]["detector_state"],
                "candidate_setup_ids": list(boundary["setup"]["candidate_setup_ids"]),
                "episode_window_start_utc": window_start.isoformat(),
                "episode_window_end_utc": window_end.isoformat(),
                "similarity": similarity,
                "future_evaluation": dict(future),
                "outcome_available_by_query_time": True,
                "outcome_used_for_similarity": False,
            }
        )

    sufficient.sort(
        key=lambda item: (
            -Decimal(str(item["similarity"]["similarity_score"])),
            -Decimal(str(item["similarity"]["component_coverage"])),
            str(item["case_id"]),
        )
    )
    pre_dedup = sufficient[:max_results]
    episodes = _episode_components(pre_dedup)
    representatives: list[dict[str, Any]] = []
    for episode in episodes:
        members = sorted(
            episode["members"],
            key=lambda item: (
                -Decimal(str(item["similarity"]["similarity_score"])),
                -Decimal(str(item["similarity"]["component_coverage"])),
                str(item["case_id"]),
            ),
        )
        representative = dict(members[0])
        episode_body = {
            "window_start_utc": episode["window_start"].isoformat(),
            "window_end_utc": episode["window_end"].isoformat(),
            "member_case_ids": [str(item["case_id"]) for item in members],
        }
        representative["episode_id"] = _digest(episode_body)
        representative["episode_member_count"] = len(members)
        representatives.append(representative)
    representatives.sort(
        key=lambda item: (
            -Decimal(str(item["similarity"]["similarity_score"])),
            -Decimal(str(item["similarity"]["component_coverage"])),
            str(item["case_id"]),
        )
    )
    returned = representatives[:max_results]
    for rank, item in enumerate(returned, start=1):
        item["rank"] = rank

    independence = _independence_payload(pre_dedup, returned)
    state = "matches_found" if returned else "no_comparable_case"
    no_reason = None
    if not returned:
        if exclusion_counts:
            no_reason = min(exclusion_counts.items(), key=lambda item: (-item[1], item[0]))[0]
        else:
            no_reason = "no_eligible_candidate"
    result = {
        "retrieval_version": ANALOGUE_RETRIEVAL_VERSION_V2,
        "source_query_version": v1.ANALOGUE_QUERY_VERSION,
        "source_query_retrieval_version": v1.ANALOGUE_RETRIEVAL_VERSION,
        "similarity_feature_version": SIMILARITY_FEATURE_VERSION_V2,
        "query_id": query_id,
        "query_as_of_utc": query["as_of_utc"],
        "evidence_state": state,
        "no_comparable_reason": no_reason,
        "candidate_count": len(candidates),
        "eligible_candidate_count": eligible_count,
        "hard_gate_pass_count": hard_gate_pass_count,
        "sufficient_match_count": len(sufficient),
        "returned_match_count": len(returned),
        "matches": returned,
        "exclusion_counts": dict(sorted(exclusion_counts.items())),
        "gate_relaxations": [
            {"name": name, "candidate_count": count}
            for name, count in sorted(relaxations.items())
        ],
        "embargo_minutes": EMBARGO_MINUTES,
        "episode_horizon_minutes": EPISODE_HORIZON_MINUTES,
        "independence": independence,
        "selection_digest": _selection_digest(query_id, returned),
        "outcome_values_used_for_selection": False,
        "outcome_window_metadata_used_for_independence": True,
        "probability_claims_included": False,
    }
    result["retrieval_digest"] = _digest(result)
    return result


def verify_retrieval_digest_v2(retrieval: Mapping[str, Any]) -> bool:
    supplied = str(retrieval.get("retrieval_digest") or "")
    body = dict(retrieval)
    body.pop("retrieval_digest", None)
    return bool(supplied) and supplied == _digest(body)
