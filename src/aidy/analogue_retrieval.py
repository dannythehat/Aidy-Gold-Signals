from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy.feature_engine import FEATURE_DEFINITION_VERSION
from aidy.historical_backfill import RETROSPECTIVE_PROVENANCE
from aidy.historical_cases import (
    ANALOGUE_INPUT_VIEW_VERSION,
    CASE_DIGEST_ALGORITHM,
    CASE_INPUT_VERSION,
    CASE_VERSION,
    PIT_OBSERVED_PROVENANCE,
    compute_historical_case_digest,
    verify_case_input_digest,
    verify_historical_case_digest,
)
from aidy.regime_classifier import REGIME_DEFINITION_VERSION
from aidy.setup_detector import SETUP_DETECTOR_VERSION, SETUP_TAXONOMY_VERSION

SIMILARITY_FEATURE_VERSION = "aidy_gold_similarity_features_v1"
ANALOGUE_QUERY_VERSION = "aidy_historical_analogue_query_v1"
ANALOGUE_RETRIEVAL_VERSION = "aidy_historical_analogue_retrieval_v1"
ANALOGUE_DIGEST_ALGORITHM = "sha256"
SUPPORTED_SYMBOL = "XAUUSD"

DEFAULT_MAX_RESULTS = 8
DEFAULT_MIN_SIMILARITY = Decimal("0.72")
DEFAULT_MIN_COMPONENT_COVERAGE = Decimal("0.65")
DEFAULT_CANDIDATE_LIMIT = 2000

_ALLOWED_PROVENANCE = {RETROSPECTIVE_PROVENANCE, PIT_OBSERVED_PROVENANCE}
_UNKNOWN_TEXT = {
    "",
    "unknown",
    "unavailable",
    "unavailable_by_retrospective_provenance",
}
_FORBIDDEN_QUERY_KEYS = {
    "available_after_utc",
    "counterfactual_digest",
    "counterfactual_version",
    "evaluation_only",
    "future_evaluation",
    "future_return",
    "future_returns",
    "horizon_assessments",
    "mae",
    "mfe",
    "move_bundle",
    "move_bundle_version",
    "outcome",
    "outcome_label",
    "outcome_state",
    "outcomes",
    "path_class",
    "pnl",
    "primary_classification",
    "realized_pnl",
    "stop_hit",
    "target_hit",
    "trade_outcome_bundle",
    "trade_outcome_bundle_version",
}

_COMPONENTS: tuple[tuple[str, tuple[str, ...], str, Decimal, Decimal | None], ...] = (
    ("regime_trend", ("regime", "trend_structure"), "categorical", Decimal("1.50"), None),
    ("regime_volatility", ("regime", "volatility_band"), "categorical", Decimal("1.00"), None),
    ("regime_session", ("regime", "session"), "categorical", Decimal("0.75"), None),
    ("regime_event", ("regime", "event_timing"), "categorical", Decimal("0.50"), None),
    (
        "regime_quote_spread",
        ("regime", "quote_spread_condition"),
        "categorical",
        Decimal("0.25"),
        None,
    ),
    ("m15_direction", ("m15_direction",), "categorical", Decimal("0.75"), None),
    ("h1_direction", ("h1_direction",), "categorical", Decimal("1.00"), None),
    ("h4_direction", ("h4_direction",), "categorical", Decimal("1.00"), None),
    ("h1_atr", ("h1_atr_14_bps",), "numeric", Decimal("0.75"), Decimal(40)),
    (
        "m15_realized_vol",
        ("m15_realized_vol_20_bps",),
        "numeric",
        Decimal("0.50"),
        Decimal(30),
    ),
    (
        "m15_range_position",
        ("m15_range_position_20",),
        "numeric",
        Decimal("0.75"),
        Decimal("0.50"),
    ),
    (
        "m15_close_location",
        ("m15_close_location",),
        "numeric",
        Decimal("0.50"),
        Decimal("0.50"),
    ),
    (
        "session_range_position",
        ("session_range_position",),
        "numeric",
        Decimal("0.25"),
        Decimal("0.50"),
    ),
    (
        "setup_detector_state",
        ("setup_detector_state",),
        "categorical",
        Decimal("0.50"),
        None,
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
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"Invalid analogue timestamp: {value}") from exc
    else:
        raise TypeError("Analogue timestamps must be timezone-aware datetime or ISO-8601 text.")
    if parsed.tzinfo is None:
        raise ValueError("Analogue timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _score_text(value: Decimal) -> str:
    bounded = min(Decimal(1), max(Decimal(0), value))
    return str(bounded.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def _assert_no_future(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_QUERY_KEYS:
                raise ValueError(f"Future/outcome field is forbidden at {path}.{key}.")
            if normalized == "future_derived" and item is not False:
                raise ValueError(f"Query-side future_derived must remain false at {path}.{key}.")
            _assert_no_future(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_no_future(item, path=f"{path}[{index}]")


def _mapping(value: Any, *, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object.")
    return value


def _json_mapping(value: Any, *, name: str) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{name} contains invalid JSON.") from exc
        if isinstance(decoded, Mapping):
            return decoded
    raise TypeError(f"{name} must be a JSON object or JSON-object string.")


def _versions(input_boundary: Mapping[str, Any]) -> dict[str, str]:
    feature = _mapping(input_boundary.get("feature"), name="input.feature")
    regime = _mapping(input_boundary.get("regime"), name="input.regime")
    setup = _mapping(input_boundary.get("setup"), name="input.setup")
    result = {
        "feature_definition_version": str(feature.get("feature_definition_version") or ""),
        "regime_definition_version": str(
            regime.get("source_regime_definition_version")
            or regime.get("regime_definition_version")
            or ""
        ),
        "setup_taxonomy_version": str(
            setup.get("source_taxonomy_version") or setup.get("taxonomy_version") or ""
        ),
        "setup_detector_version": str(
            setup.get("source_detector_version") or setup.get("detector_version") or ""
        ),
    }
    expected = {
        "feature_definition_version": FEATURE_DEFINITION_VERSION,
        "regime_definition_version": REGIME_DEFINITION_VERSION,
        "setup_taxonomy_version": SETUP_TAXONOMY_VERSION,
        "setup_detector_version": SETUP_DETECTOR_VERSION,
    }
    if result != expected:
        raise ValueError(
            "Analogue retrieval requires the frozen Day 7/11/15 feature, regime and setup versions."
        )
    return result


def _validate_input_boundary(input_boundary: Mapping[str, Any]) -> tuple[datetime, dict[str, str]]:
    if input_boundary.get("input_version") != CASE_INPUT_VERSION:
        raise ValueError("Analogue retrieval requires aidy_historical_case_input_v1.")
    if input_boundary.get("symbol") != SUPPORTED_SYMBOL:
        raise ValueError(f"Analogue retrieval supports only {SUPPORTED_SYMBOL}.")
    if input_boundary.get("provenance_class") not in _ALLOWED_PROVENANCE:
        raise ValueError("Analogue query has unsupported provenance.")
    if input_boundary.get("future_derived") is not False:
        raise ValueError("Analogue query input must be future_derived=false.")
    if input_boundary.get("analogue_match_allowed") is not True:
        raise ValueError("Analogue query input must explicitly allow analogue matching.")
    _assert_no_future(input_boundary, path="input_boundary")
    if not verify_case_input_digest(input_boundary):
        raise ValueError("Analogue query input digest does not match contents.")
    analogue_features = input_boundary.get("analogue_features")
    if not isinstance(analogue_features, Mapping):
        raise TypeError("Analogue query requires input_boundary.analogue_features.")
    return _utc(str(input_boundary.get("as_of_utc") or "")), _versions(input_boundary)


def similarity_manifest() -> dict[str, Any]:
    components = [
        {
            "name": name,
            "path": ".".join(path),
            "kind": kind,
            "weight": str(weight),
            "numeric_scale": None if scale is None else str(scale),
        }
        for name, path, kind, weight, scale in _COMPONENTS
    ]
    manifest = {
        "similarity_feature_version": SIMILARITY_FEATURE_VERSION,
        "source_analogue_input_view_version": ANALOGUE_INPUT_VIEW_VERSION,
        "threshold_basis": "fixed_v1_descriptive_not_future_outcome_calibrated",
        "default_min_similarity_score": str(DEFAULT_MIN_SIMILARITY),
        "default_min_component_coverage": str(DEFAULT_MIN_COMPONENT_COVERAGE),
        "components": components,
        "total_weight": str(_TOTAL_WEIGHT),
        "future_outcomes_used_for_similarity": False,
    }
    manifest["manifest_digest"] = _digest(manifest)
    return manifest


def _normalized_provenance(values: Iterable[str]) -> list[str]:
    normalized = sorted({str(value) for value in values})
    if not normalized or any(value not in _ALLOWED_PROVENANCE for value in normalized):
        raise ValueError("Analogue query requires one or more supported provenance classes.")
    return normalized


def build_analogue_query(
    *,
    input_boundary: Mapping[str, Any],
    allowed_provenance: Iterable[str] = (RETROSPECTIVE_PROVENANCE,),
    source_case_id: str | None = None,
    max_results: int = DEFAULT_MAX_RESULTS,
    min_similarity_score: Any = DEFAULT_MIN_SIMILARITY,
    min_component_coverage: Any = DEFAULT_MIN_COMPONENT_COVERAGE,
) -> dict[str, Any]:
    as_of, versions = _validate_input_boundary(input_boundary)
    provenance = _normalized_provenance(allowed_provenance)
    if max_results <= 0:
        raise ValueError("Analogue max_results must be positive.")
    min_similarity = _decimal(min_similarity_score)
    min_coverage = _decimal(min_component_coverage)
    if min_similarity is None or not Decimal(0) <= min_similarity <= Decimal(1):
        raise ValueError("min_similarity_score must be between 0 and 1.")
    if min_coverage is None or not Decimal(0) <= min_coverage <= Decimal(1):
        raise ValueError("min_component_coverage must be between 0 and 1.")

    quality = _mapping(input_boundary.get("data_quality"), name="input.data_quality")
    body: dict[str, Any] = {
        "query_version": ANALOGUE_QUERY_VERSION,
        "similarity_feature_version": SIMILARITY_FEATURE_VERSION,
        "retrieval_version": ANALOGUE_RETRIEVAL_VERSION,
        "symbol": SUPPORTED_SYMBOL,
        "as_of_utc": as_of.isoformat(),
        "source_input_digest": input_boundary["input_digest"],
        "source_case_id": source_case_id,
        "source_provenance_class": input_boundary["provenance_class"],
        "allowed_candidate_provenance": provenance,
        "max_results": int(max_results),
        "min_similarity_score": _score_text(min_similarity),
        "min_component_coverage": _score_text(min_coverage),
        "feature_versions": versions,
        "query_data_quality_grade": str(quality.get("grade") or "unknown"),
        "query_retrieval_eligible": quality.get("retrieval_eligible") is not False,
        "analogue_features": dict(input_boundary["analogue_features"]),
        "outcomes_in_query": False,
    }
    _assert_no_future(body, path="analogue_query")
    body["query_id"] = _digest(body)
    return body


def _validate_query(query: Mapping[str, Any]) -> None:
    if query.get("query_version") != ANALOGUE_QUERY_VERSION:
        raise ValueError("Unsupported analogue query version.")
    if query.get("similarity_feature_version") != SIMILARITY_FEATURE_VERSION:
        raise ValueError("Unsupported analogue similarity version.")
    if query.get("retrieval_version") != ANALOGUE_RETRIEVAL_VERSION:
        raise ValueError("Unsupported analogue retrieval version.")
    if query.get("symbol") != SUPPORTED_SYMBOL:
        raise ValueError(f"Analogue retrieval supports only {SUPPORTED_SYMBOL}.")
    _utc(str(query.get("as_of_utc") or ""))
    _assert_no_future(query, path="analogue_query")
    supplied = str(query.get("query_id") or "")
    body = dict(query)
    body.pop("query_id", None)
    if not supplied or supplied != _digest(body):
        raise ValueError("Analogue query ID does not match query contents.")
    expected = {
        "feature_definition_version": FEATURE_DEFINITION_VERSION,
        "regime_definition_version": REGIME_DEFINITION_VERSION,
        "setup_taxonomy_version": SETUP_TAXONOMY_VERSION,
        "setup_detector_version": SETUP_DETECTOR_VERSION,
    }
    if query.get("feature_versions") != expected:
        raise ValueError("Analogue query feature versions are incompatible.")
    _normalized_provenance(query.get("allowed_candidate_provenance") or [])


def reconstruct_case_from_storage_row(row: Mapping[str, Any]) -> dict[str, Any]:
    input_boundary = dict(_json_mapping(row.get("input_boundary"), name="input_boundary"))
    future_evaluation = dict(
        _json_mapping(row.get("future_evaluation"), name="future_evaluation")
    )
    case = {
        "case_version": row.get("case_version"),
        "case_digest_algorithm": CASE_DIGEST_ALGORITHM,
        "case_id": row.get("case_id"),
        "symbol": row.get("symbol"),
        "as_of_utc": (
            row["as_of_utc"].isoformat()
            if isinstance(row.get("as_of_utc"), datetime)
            else row.get("as_of_utc")
        ),
        "provenance_class": row.get("provenance_class"),
        "decision_input_allowed": False,
        "analogue_query_must_use_input_boundary_only": True,
        "input_boundary": input_boundary,
        "future_evaluation": future_evaluation,
        "case_digest": row.get("case_digest"),
    }
    if str(case.get("case_digest") or "") != compute_historical_case_digest(case):
        raise ValueError("Stored candidate case digest does not match reconstructed contents.")
    _validate_candidate_case(case)
    return case


def _expected_case_id(input_boundary: Mapping[str, Any]) -> str:
    return _digest(
        {
            "case_version": CASE_VERSION,
            "symbol": input_boundary["symbol"],
            "as_of_utc": input_boundary["as_of_utc"],
            "provenance_class": input_boundary["provenance_class"],
            "input_digest": input_boundary["input_digest"],
        }
    )


def _validate_candidate_case(case: Mapping[str, Any]) -> None:
    if case.get("case_version") != CASE_VERSION:
        raise ValueError("Candidate has an unsupported historical-case version.")
    if case.get("case_digest_algorithm") != CASE_DIGEST_ALGORITHM:
        raise ValueError("Candidate has an unsupported historical-case digest algorithm.")
    if not verify_historical_case_digest(case):
        raise ValueError("Candidate historical-case digest does not match contents.")
    input_boundary = _mapping(case.get("input_boundary"), name="candidate.input_boundary")
    _validate_input_boundary(input_boundary)
    if case.get("case_id") != _expected_case_id(input_boundary):
        raise ValueError("Candidate case_id does not match its input identity.")
    if case.get("symbol") != input_boundary.get("symbol"):
        raise ValueError("Candidate symbol does not match its input boundary.")
    if case.get("provenance_class") != input_boundary.get("provenance_class"):
        raise ValueError("Candidate provenance does not match its input boundary.")
    if _utc(str(case.get("as_of_utc") or "")) != _utc(str(input_boundary["as_of_utc"])):
        raise ValueError("Candidate as-of timestamp does not match its input boundary.")

    future = _mapping(case.get("future_evaluation"), name="candidate.future_evaluation")
    if (
        future.get("evaluation_only") is not True
        or future.get("future_derived") is not True
        or future.get("pit_eligible") is not False
        or future.get("decision_input_allowed") is not False
        or future.get("analogue_match_allowed") is not False
    ):
        raise ValueError("Candidate future evaluation violates the Day 16 permission boundary.")
    _utc(str(future.get("available_after_utc") or ""))


def _path_value(payload: Mapping[str, Any], path: tuple[str, ...]) -> Any:
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
    return None if text in _UNKNOWN_TEXT else text


def _categorical_similarity(query_value: Any, candidate_value: Any) -> Decimal | None:
    left = _known_text(query_value)
    right = _known_text(candidate_value)
    if left is None or right is None:
        return None
    return Decimal(1) if left == right else Decimal(0)


def _numeric_similarity(
    query_value: Any, candidate_value: Any, *, scale: Decimal
) -> Decimal | None:
    left = _decimal(query_value)
    right = _decimal(candidate_value)
    if left is None or right is None or scale <= 0:
        return None
    return max(Decimal(0), Decimal(1) - abs(left - right) / scale)


def _set_similarity(
    query_features: Mapping[str, Any],
    candidate_features: Mapping[str, Any],
    query_value: Any,
    candidate_value: Any,
) -> Decimal | None:
    query_state = _known_text(query_features.get("setup_detector_state"))
    candidate_state = _known_text(candidate_features.get("setup_detector_state"))
    if query_state is None or candidate_state is None:
        return None
    if query_state == "indeterminate" or candidate_state == "indeterminate":
        return None
    if not isinstance(query_value, (list, tuple, set)) or not isinstance(
        candidate_value, (list, tuple, set)
    ):
        return None
    left = {str(value) for value in query_value}
    right = {str(value) for value in candidate_value}
    if not left and not right:
        return Decimal(1)
    union = left | right
    return Decimal(len(left & right)) / Decimal(len(union)) if union else Decimal(1)


def score_similarity(
    *,
    query_features: Mapping[str, Any],
    candidate_features: Mapping[str, Any],
) -> dict[str, Any]:
    components: list[dict[str, Any]] = []
    covered_weight = Decimal(0)
    earned_weight = Decimal(0)

    for name, path, kind, weight, scale in _COMPONENTS:
        query_value = _path_value(query_features, path)
        candidate_value = _path_value(candidate_features, path)
        if kind == "categorical":
            similarity = _categorical_similarity(query_value, candidate_value)
        elif kind == "numeric":
            assert scale is not None
            similarity = _numeric_similarity(query_value, candidate_value, scale=scale)
        elif kind == "set":
            similarity = _set_similarity(
                query_features, candidate_features, query_value, candidate_value
            )
        else:
            raise RuntimeError(f"Unsupported similarity component kind: {kind}")

        if similarity is None:
            state = "unavailable"
            similarity_text = None
        else:
            state = "compared"
            covered_weight += weight
            earned_weight += weight * similarity
            similarity_text = _score_text(similarity)

        components.append(
            {
                "name": name,
                "kind": kind,
                "weight": str(weight),
                "state": state,
                "query_value": query_value,
                "candidate_value": candidate_value,
                "component_similarity": similarity_text,
            }
        )

    coverage = covered_weight / _TOTAL_WEIGHT if _TOTAL_WEIGHT else Decimal(0)
    similarity_score = earned_weight / covered_weight if covered_weight else Decimal(0)
    result = {
        "similarity_feature_version": SIMILARITY_FEATURE_VERSION,
        "similarity_score": _score_text(similarity_score),
        "distance_score": _score_text(Decimal(1) - similarity_score),
        "component_coverage": _score_text(coverage),
        "covered_weight": str(covered_weight),
        "total_weight": str(_TOTAL_WEIGHT),
        "components": components,
        "future_outcomes_used": False,
    }
    result["score_digest"] = _digest(result)
    return result


def _candidate_versions(case: Mapping[str, Any]) -> dict[str, str]:
    return _versions(_mapping(case["input_boundary"], name="candidate.input_boundary"))


def _candidate_eligibility(
    *,
    query: Mapping[str, Any],
    case: Mapping[str, Any],
) -> tuple[bool, str]:
    query_as_of = _utc(str(query["as_of_utc"]))
    candidate_as_of = _utc(str(case["as_of_utc"]))
    if candidate_as_of >= query_as_of:
        return False, "candidate_not_before_query"
    if query.get("source_case_id") and case.get("case_id") == query.get("source_case_id"):
        return False, "source_case_excluded"
    if case.get("provenance_class") not in set(query["allowed_candidate_provenance"]):
        return False, "provenance_not_allowed"
    if _candidate_versions(case) != query["feature_versions"]:
        return False, "version_incompatible"

    input_boundary = _mapping(case["input_boundary"], name="candidate.input_boundary")
    quality = _mapping(input_boundary.get("data_quality"), name="candidate.data_quality")
    if quality.get("retrieval_eligible") is False or quality.get("grade") == "insufficient":
        return False, "candidate_quality_insufficient"

    future = _mapping(case["future_evaluation"], name="candidate.future_evaluation")
    available_after = _utc(str(future.get("available_after_utc") or ""))
    if available_after > query_as_of:
        return False, "outcome_not_yet_available"
    return True, "eligible"


def _selection_digest(query_id: str, matches: list[dict[str, Any]]) -> str:
    selection = [
        {
            "rank": item["rank"],
            "case_id": item["case_id"],
            "similarity_score": item["similarity"]["similarity_score"],
            "component_coverage": item["similarity"]["component_coverage"],
        }
        for item in matches
    ]
    return _digest({"query_id": query_id, "selection": selection})


def retrieve_analogues(
    *,
    query: Mapping[str, Any],
    candidate_cases: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    _validate_query(query)
    min_similarity = Decimal(str(query["min_similarity_score"]))
    min_coverage = Decimal(str(query["min_component_coverage"]))
    max_results = int(query["max_results"])
    candidate_items = list(candidate_cases)

    if query.get("query_retrieval_eligible") is False:
        result = {
            "retrieval_version": ANALOGUE_RETRIEVAL_VERSION,
            "query_id": query["query_id"],
            "evidence_state": "query_insufficient_quality",
            "candidate_count": len(candidate_items),
            "eligible_candidate_count": 0,
            "sufficient_match_count": 0,
            "returned_match_count": 0,
            "matches": [],
            "selection_digest": _selection_digest(str(query["query_id"]), []),
            "outcomes_used_for_selection": False,
            "probability_claims_included": False,
        }
        result["retrieval_digest"] = _digest(result)
        return result

    eligible_count = 0
    exclusion_counts: dict[str, int] = {}
    sufficient: list[dict[str, Any]] = []

    for raw_case in candidate_items:
        if not isinstance(raw_case, Mapping):
            raise TypeError("Analogue candidates must be historical-case objects.")
        _validate_candidate_case(raw_case)
        eligible, reason = _candidate_eligibility(query=query, case=raw_case)
        if not eligible:
            exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1
            continue
        eligible_count += 1
        input_boundary = _mapping(raw_case["input_boundary"], name="candidate.input_boundary")
        features = _mapping(
            input_boundary.get("analogue_features"), name="candidate.analogue_features"
        )
        similarity = score_similarity(
            query_features=_mapping(query["analogue_features"], name="query.analogue_features"),
            candidate_features=features,
        )
        score = Decimal(similarity["similarity_score"])
        coverage = Decimal(similarity["component_coverage"])
        if coverage < min_coverage or score < min_similarity:
            reason = (
                "coverage_below_threshold"
                if coverage < min_coverage
                else "similarity_below_threshold"
            )
            exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1
            continue
        future = _mapping(raw_case["future_evaluation"], name="candidate.future_evaluation")
        sufficient.append(
            {
                "case_id": raw_case["case_id"],
                "as_of_utc": raw_case["as_of_utc"],
                "provenance_class": raw_case["provenance_class"],
                "input_digest": input_boundary["input_digest"],
                "data_quality_grade": input_boundary["data_quality"]["grade"],
                "regime": input_boundary["regime"]["labels"],
                "setup_detector_state": input_boundary["setup"]["detector_state"],
                "candidate_setup_ids": list(input_boundary["setup"]["candidate_setup_ids"]),
                "similarity": similarity,
                "future_evaluation": dict(future),
                "outcome_available_by_query_time": True,
                "outcome_used_for_similarity": False,
            }
        )

    sufficient.sort(
        key=lambda item: (
            -Decimal(item["similarity"]["similarity_score"]),
            -Decimal(item["similarity"]["component_coverage"]),
            str(item["case_id"]),
        )
    )
    returned = sufficient[:max_results]
    for rank, item in enumerate(returned, start=1):
        item["rank"] = rank

    state = "matches_found" if returned else "no_sufficient_similarity"
    result = {
        "retrieval_version": ANALOGUE_RETRIEVAL_VERSION,
        "similarity_feature_version": SIMILARITY_FEATURE_VERSION,
        "query_id": query["query_id"],
        "query_as_of_utc": query["as_of_utc"],
        "evidence_state": state,
        "candidate_count": len(candidate_items),
        "eligible_candidate_count": eligible_count,
        "sufficient_match_count": len(sufficient),
        "returned_match_count": len(returned),
        "exclusion_counts": dict(sorted(exclusion_counts.items())),
        "matches": returned,
        "selection_digest": _selection_digest(str(query["query_id"]), returned),
        "outcomes_used_for_selection": False,
        "probability_claims_included": False,
    }
    result["retrieval_digest"] = _digest(result)
    return result


def candidate_query_sql(*, project: str, dataset: str) -> str:
    table = f"{project}.{dataset}.research_gold_cases"
    return f"""
        SELECT case_digest, case_version, case_id, symbol, as_of_utc,
               provenance_class, input_digest, feature_definition_version,
               regime_definition_version, setup_taxonomy_version,
               setup_detector_version, data_quality_grade,
               future_available_after_utc, input_boundary, future_evaluation
        FROM `{table}`
        WHERE symbol = @symbol
          AND as_of_utc < @query_as_of
          AND future_available_after_utc IS NOT NULL
          AND future_available_after_utc <= @query_as_of
          AND provenance_class IN UNNEST(@allowed_provenance)
          AND data_quality_grade != 'insufficient'
          AND feature_definition_version = @feature_definition_version
          AND regime_definition_version = @regime_definition_version
          AND setup_taxonomy_version = @setup_taxonomy_version
          AND setup_detector_version = @setup_detector_version
        ORDER BY as_of_utc DESC, case_id
        LIMIT @candidate_limit
    """.strip()


def candidate_query_parameters(
    query: Mapping[str, Any], *, candidate_limit: int = DEFAULT_CANDIDATE_LIMIT
) -> dict[str, Any]:
    _validate_query(query)
    if candidate_limit <= 0:
        raise ValueError("candidate_limit must be positive.")
    versions = query["feature_versions"]
    return {
        "symbol": SUPPORTED_SYMBOL,
        "query_as_of": query["as_of_utc"],
        "allowed_provenance": list(query["allowed_candidate_provenance"]),
        "feature_definition_version": versions["feature_definition_version"],
        "regime_definition_version": versions["regime_definition_version"],
        "setup_taxonomy_version": versions["setup_taxonomy_version"],
        "setup_detector_version": versions["setup_detector_version"],
        "candidate_limit": int(candidate_limit),
    }
