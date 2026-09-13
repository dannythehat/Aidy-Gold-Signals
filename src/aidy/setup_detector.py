from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256
from typing import Any

from aidy.bigquery_exporter import FieldSpec, TableSpec
from aidy.context_packet import CONTEXT_PACKET_VERSION, verify_context_hash
from aidy.feature_engine import FEATURE_DEFINITION_VERSION, PIT_PROVENANCE
from aidy.no_trade_counterfactual import build_setup_eligibility_evidence
from aidy.regime_classifier import REGIME_DEFINITION_VERSION, verify_regime_digest

SETUP_TAXONOMY_VERSION = "aidy_gold_setup_taxonomy_v1"
SETUP_DETECTOR_VERSION = "aidy_gold_setup_detector_v1"
SETUP_DETECTION_VERSION = "aidy_gold_setup_detection_v1"
SETUP_DISTRIBUTION_VERSION = "aidy_gold_setup_distribution_v1"
SETUP_DIGEST_ALGORITHM = "sha256"
SUPPORTED_SYMBOL = "XAUUSD"
RISK_TEMPLATE_VERSION = "aidy_atr_1r2r_normalized_geometry_v1"

_DETECTOR_STATES = {"single", "multiple", "none", "indeterminate"}
_DIRECTIONS = {"long", "short"}
_NUMERIC_OPS = {"gt", "gte", "lt", "lte"}
_HEX = frozenset("0123456789abcdef")
_FORBIDDEN_HINDSIGHT_KEYS = {
    "available_after_utc",
    "counterfactual_digest",
    "future_return",
    "future_returns",
    "horizon_assessments",
    "mae",
    "mfe",
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
    "trade_outcome_bundle_version",
}


def _definition(
    setup_id: str,
    family: str,
    direction: str,
    description: str,
    *clauses: tuple[str, str, str],
) -> dict[str, Any]:
    return {
        "setup_id": setup_id,
        "family": family,
        "direction": direction,
        "description": description,
        "clauses": [
            {"observation": field, "op": op, "value": value}
            for field, op, value in clauses
        ],
    }


SETUP_DEFINITIONS: tuple[dict[str, Any], ...] = (
    _definition(
        "trend_pullback_long",
        "trend_pullback",
        "long",
        "Bullish higher-timeframe structure with a controlled M15 pullback.",
        ("trend_structure", "eq", "bullish_trend"),
        ("h1_direction", "eq", "bullish"),
        ("m15_direction", "eq", "bearish"),
        ("m15_range_position", "lte", "0.55"),
    ),
    _definition(
        "trend_pullback_short",
        "trend_pullback",
        "short",
        "Bearish higher-timeframe structure with a controlled M15 pullback.",
        ("trend_structure", "eq", "bearish_trend"),
        ("h1_direction", "eq", "bearish"),
        ("m15_direction", "eq", "bullish"),
        ("m15_range_position", "gte", "0.45"),
    ),
    _definition(
        "trend_momentum_long",
        "trend_momentum",
        "long",
        "Bullish trend with M15/H1 continuation and a strong M15 close.",
        ("trend_structure", "eq", "bullish_trend"),
        ("h1_direction", "eq", "bullish"),
        ("m15_direction", "eq", "bullish"),
        ("m15_body_bps", "gt", "0"),
        ("m15_close_location", "gte", "0.67"),
    ),
    _definition(
        "trend_momentum_short",
        "trend_momentum",
        "short",
        "Bearish trend with M15/H1 continuation and a weak M15 close.",
        ("trend_structure", "eq", "bearish_trend"),
        ("h1_direction", "eq", "bearish"),
        ("m15_direction", "eq", "bearish"),
        ("m15_body_bps", "lt", "0"),
        ("m15_close_location", "lte", "0.33"),
    ),
    _definition(
        "recent_high_pressure_long",
        "recent_extreme_pressure",
        "long",
        "Bullish pressure in the upper fifth of the recent M15 range.",
        ("m15_range_position", "gte", "0.80"),
        ("m15_direction", "eq", "bullish"),
        ("m15_return_1_bps", "gt", "0"),
        ("m15_close_location", "gte", "0.67"),
    ),
    _definition(
        "recent_low_pressure_short",
        "recent_extreme_pressure",
        "short",
        "Bearish pressure in the lower fifth of the recent M15 range.",
        ("m15_range_position", "lte", "0.20"),
        ("m15_direction", "eq", "bearish"),
        ("m15_return_1_bps", "lt", "0"),
        ("m15_close_location", "lte", "0.33"),
    ),
    _definition(
        "session_high_pressure_long",
        "session_extreme_pressure",
        "long",
        "Positive momentum while price is in the top 15% of the active session range.",
        ("session_range_position", "gte", "0.85"),
        ("m1_return_1_bps", "gt", "0"),
        ("m15_direction", "eq", "bullish"),
    ),
    _definition(
        "session_low_pressure_short",
        "session_extreme_pressure",
        "short",
        "Negative momentum while price is in the bottom 15% of the active session range.",
        ("session_range_position", "lte", "0.15"),
        ("m1_return_1_bps", "lt", "0"),
        ("m15_direction", "eq", "bearish"),
    ),
    _definition(
        "lower_extreme_rejection_long",
        "extreme_rejection",
        "long",
        "Bullish M15 rejection from the lower fifth of the recent range.",
        ("m15_range_position", "lte", "0.20"),
        ("m15_body_bps", "gt", "0"),
        ("m15_close_location", "gte", "0.60"),
    ),
    _definition(
        "upper_extreme_rejection_short",
        "extreme_rejection",
        "short",
        "Bearish M15 rejection from the upper fifth of the recent range.",
        ("m15_range_position", "gte", "0.80"),
        ("m15_body_bps", "lt", "0"),
        ("m15_close_location", "lte", "0.40"),
    ),
    _definition(
        "countertrend_reversal_long",
        "countertrend_reversal",
        "long",
        "Bullish M15 reversal evidence against a bearish higher-timeframe trend.",
        ("trend_structure", "eq", "bearish_trend"),
        ("m15_direction", "eq", "bullish"),
        ("m15_return_1_bps", "gt", "0"),
        ("m15_close_location", "gte", "0.67"),
        ("m15_range_position", "lte", "0.45"),
    ),
    _definition(
        "countertrend_reversal_short",
        "countertrend_reversal",
        "short",
        "Bearish M15 reversal evidence against a bullish higher-timeframe trend.",
        ("trend_structure", "eq", "bullish_trend"),
        ("m15_direction", "eq", "bearish"),
        ("m15_return_1_bps", "lt", "0"),
        ("m15_close_location", "lte", "0.33"),
        ("m15_range_position", "gte", "0.55"),
    ),
    _definition(
        "range_low_reversion_long",
        "range_reversion",
        "long",
        "Bullish rejection from the lower quarter of a classified range.",
        ("trend_structure", "eq", "range"),
        ("m15_range_position", "lte", "0.25"),
        ("m15_body_bps", "gt", "0"),
        ("m15_close_location", "gte", "0.55"),
    ),
    _definition(
        "range_high_reversion_short",
        "range_reversion",
        "short",
        "Bearish rejection from the upper quarter of a classified range.",
        ("trend_structure", "eq", "range"),
        ("m15_range_position", "gte", "0.75"),
        ("m15_body_bps", "lt", "0"),
        ("m15_close_location", "lte", "0.45"),
    ),
    _definition(
        "session_low_reversion_long",
        "session_reversion",
        "long",
        "Positive M1/M15 response from the lower fifth of the active session range.",
        ("session_range_position", "lte", "0.20"),
        ("m1_return_1_bps", "gt", "0"),
        ("m15_body_bps", "gt", "0"),
    ),
    _definition(
        "session_high_reversion_short",
        "session_reversion",
        "short",
        "Negative M1/M15 response from the upper fifth of the active session range.",
        ("session_range_position", "gte", "0.80"),
        ("m1_return_1_bps", "lt", "0"),
        ("m15_body_bps", "lt", "0"),
    ),
    _definition(
        "low_vol_break_pressure_long",
        "volatility_transition",
        "long",
        "Low H1 volatility with bullish M15 expansion pressure near the recent high.",
        ("volatility_band", "eq", "low"),
        ("m15_range_position", "gte", "0.75"),
        ("m15_direction", "eq", "bullish"),
        ("m15_close_location", "gte", "0.67"),
        ("m15_range_atr_ratio", "gte", "1.00"),
    ),
    _definition(
        "low_vol_break_pressure_short",
        "volatility_transition",
        "short",
        "Low H1 volatility with bearish M15 expansion pressure near the recent low.",
        ("volatility_band", "eq", "low"),
        ("m15_range_position", "lte", "0.25"),
        ("m15_direction", "eq", "bearish"),
        ("m15_close_location", "lte", "0.33"),
        ("m15_range_atr_ratio", "gte", "1.00"),
    ),
    _definition(
        "high_vol_recovery_long",
        "volatility_recovery",
        "long",
        "Bullish recovery from the lower third during a high-volatility H1 regime.",
        ("volatility_band", "eq", "high"),
        ("m15_range_position", "lte", "0.35"),
        ("m15_return_1_bps", "gt", "0"),
        ("m15_close_location", "gte", "0.67"),
    ),
    _definition(
        "high_vol_recovery_short",
        "volatility_recovery",
        "short",
        "Bearish recovery from the upper third during a high-volatility H1 regime.",
        ("volatility_band", "eq", "high"),
        ("m15_range_position", "gte", "0.65"),
        ("m15_return_1_bps", "lt", "0"),
        ("m15_close_location", "lte", "0.33"),
    ),
)

RESEARCH_SETUP_DETECTIONS = TableSpec(
    name="research_setup_detections",
    partition_field="as_of_utc",
    clustering_fields=("symbol", "detector_state", "taxonomy_version"),
    fields=(
        FieldSpec("detection_digest", "STRING", "REQUIRED"),
        FieldSpec("detection_version", "STRING", "REQUIRED"),
        FieldSpec("taxonomy_version", "STRING", "REQUIRED"),
        FieldSpec("taxonomy_digest", "STRING", "REQUIRED"),
        FieldSpec("detector_version", "STRING", "REQUIRED"),
        FieldSpec("pit_eligible", "BOOLEAN", "REQUIRED"),
        FieldSpec("future_derived", "BOOLEAN", "REQUIRED"),
        FieldSpec("decision_input_allowed", "BOOLEAN", "REQUIRED"),
        FieldSpec("trading_decision_made", "BOOLEAN", "REQUIRED"),
        FieldSpec("symbol", "STRING", "REQUIRED"),
        FieldSpec("as_of_utc", "TIMESTAMP", "REQUIRED"),
        FieldSpec("source_context_hash", "STRING", "REQUIRED"),
        FieldSpec("source_regime_digest", "STRING", "REQUIRED"),
        FieldSpec("detector_state", "STRING", "REQUIRED"),
        FieldSpec("candidate_setup_ids", "STRING", "REPEATED"),
        FieldSpec("candidate_directions", "STRING", "REPEATED"),
        FieldSpec("unresolved_setup_ids", "STRING", "REPEATED"),
        FieldSpec("observation_digest", "STRING", "REQUIRED"),
        FieldSpec("candidates", "JSON", "REQUIRED"),
        FieldSpec("risk_basis", "JSON", "REQUIRED"),
    ),
)


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
            raise ValueError(f"Invalid setup timestamp: {value}") from exc
    else:
        raise TypeError("Setup timestamps must be timezone-aware datetime or ISO-8601 text.")
    if parsed.tzinfo is None:
        raise ValueError("Setup timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _assert_no_hindsight(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized == "future_derived":
                if item is not False:
                    raise ValueError(f"Future-derived evidence is forbidden at {path}.{key}.")
            elif normalized == "evaluation_only":
                if item is not False:
                    raise ValueError(f"Evaluation-only evidence is forbidden at {path}.{key}.")
            elif normalized in _FORBIDDEN_HINDSIGHT_KEYS:
                raise ValueError(f"Future/outcome field is forbidden at {path}.{key}.")
            _assert_no_hindsight(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_no_hindsight(item, path=f"{path}[{index}]")


def taxonomy_manifest() -> dict[str, Any]:
    setup_ids = [item["setup_id"] for item in SETUP_DEFINITIONS]
    families = sorted({item["family"] for item in SETUP_DEFINITIONS})
    manifest = {
        "taxonomy_version": SETUP_TAXONOMY_VERSION,
        "setup_count": len(SETUP_DEFINITIONS),
        "setup_ids": setup_ids,
        "families": families,
        "definitions": list(SETUP_DEFINITIONS),
        "threshold_basis": "fixed_v1_descriptive_not_future_outcome_calibrated",
        "trading_decision_made": False,
    }
    manifest["taxonomy_digest"] = _digest(manifest)
    return manifest


def _validate_inputs(
    context: Mapping[str, Any], regime: Mapping[str, Any]
) -> tuple[datetime, Mapping[str, Any], Mapping[str, Any]]:
    if not isinstance(context, Mapping) or not isinstance(regime, Mapping):
        raise TypeError("Day 15 requires context and regime objects.")
    _assert_no_hindsight(context, path="context")
    _assert_no_hindsight(regime, path="regime")
    if context.get("context_packet_version") != CONTEXT_PACKET_VERSION:
        raise ValueError("Day 15 requires aidy_market_context_v1.")
    if context.get("objective_only") is not True:
        raise ValueError("Day 15 accepts objective-only context packets.")
    if context.get("retrospective_history_included") is not False:
        raise ValueError("Retrospective history cannot enter Day 15 setup detection.")
    if context.get("broker_follower_state_included") is not False:
        raise ValueError("Broker/follower state cannot enter Day 15 setup detection.")
    if not verify_context_hash(context):
        raise ValueError("Day 15 context hash does not match packet contents.")
    if context.get("symbol") != SUPPORTED_SYMBOL:
        raise ValueError(f"Day 15 supports only {SUPPORTED_SYMBOL}.")

    gold = context.get("gold")
    if not isinstance(gold, Mapping):
        raise TypeError("Day 15 context.gold must be an object.")
    if gold.get("feature_definition_version") != FEATURE_DEFINITION_VERSION:
        raise ValueError("Day 15 requires aidy_gold_features_v1.")
    if (
        gold.get("mode") != "pit"
        or gold.get("provenance_class") != PIT_PROVENANCE
        or gold.get("pit_eligible") is not True
    ):
        raise ValueError("Day 15 accepts PIT Gold features only.")

    if regime.get("regime_definition_version") != REGIME_DEFINITION_VERSION:
        raise ValueError("Day 15 requires aidy_gold_regime_v1.")
    if not verify_regime_digest(regime):
        raise ValueError("Day 15 regime digest does not match packet contents.")
    if regime.get("symbol") != SUPPORTED_SYMBOL:
        raise ValueError(f"Day 15 regime supports only {SUPPORTED_SYMBOL}.")
    if regime.get("source_context_hash") != context.get("context_hash"):
        raise ValueError("Day 15 regime must originate from the supplied context hash.")

    as_of = _utc(str(context.get("as_of_utc") or ""))
    if _utc(str(regime.get("as_of_utc") or "")) != as_of:
        raise ValueError("Day 15 context and regime as-of timestamps must match.")
    return as_of, gold, regime


def _tf(gold: Mapping[str, Any], timeframe: str) -> Mapping[str, Any]:
    timeframes = gold.get("timeframes")
    if not isinstance(timeframes, Mapping):
        return {}
    payload = timeframes.get(timeframe)
    return payload if isinstance(payload, Mapping) and payload.get("state") == "known" else {}


def _known_text(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value in (None, "", "unknown"):
        return None
    return str(value)


def _observations(
    context: Mapping[str, Any], gold: Mapping[str, Any], regime: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    m1 = _tf(gold, "M1")
    m15 = _tf(gold, "M15")
    h1 = _tf(gold, "H1")
    h4 = _tf(gold, "H4")
    labels = regime.get("labels")
    labels = labels if isinstance(labels, Mapping) else {}

    range_context = gold.get("range_context")
    range_context = range_context if isinstance(range_context, Mapping) else {}
    session = range_context.get("session")
    session = session if isinstance(session, Mapping) and session.get("state") == "known" else {}

    m15_range = _decimal(m15.get("range_bps"))
    m15_atr = _decimal(m15.get("atr_14_bps"))
    if m15_range is None or m15_atr is None or m15_atr <= 0:
        range_atr_ratio = None
    else:
        with localcontext() as ctx:
            ctx.prec = 34
            range_atr_ratio = m15_range / m15_atr

    quote = gold.get("quote_context")
    quote = quote if isinstance(quote, Mapping) else {}
    data_quality = context.get("data_quality")
    data_quality = data_quality if isinstance(data_quality, Mapping) else {}
    quote_mid = _decimal(quote.get("mid"))
    m1_close = _decimal(m1.get("latest_close"))
    if quote_mid is not None and quote_mid > 0 and data_quality.get("quote_freshness") == "fresh":
        reference_price = quote_mid
        reference_source = "fresh_quote_mid"
    elif m1_close is not None and m1_close > 0:
        reference_price = m1_close
        reference_source = "latest_m1_close"
    else:
        reference_price = None
        reference_source = "unknown"

    runtime = {
        "trend_structure": _known_text(labels, "trend_structure"),
        "volatility_band": _known_text(labels, "volatility_band"),
        "m1_return_1_bps": _decimal(m1.get("return_1_bps")),
        "m15_return_1_bps": _decimal(m15.get("return_1_bps")),
        "m15_direction": _known_text(m15, "return_5_direction"),
        "h1_direction": _known_text(h1, "return_5_direction"),
        "h4_direction": _known_text(h4, "return_5_direction"),
        "m15_body_bps": _decimal(m15.get("body_bps")),
        "m15_close_location": _decimal(m15.get("close_location")),
        "m15_range_position": _decimal(m15.get("range_position_20")),
        "m15_range_atr_ratio": range_atr_ratio,
        "session_range_position": _decimal(session.get("position")),
    }
    serialized = {
        key: (_decimal_text(value) if isinstance(value, Decimal) else value)
        for key, value in sorted(runtime.items())
    }
    risk_basis = {
        "risk_template_version": RISK_TEMPLATE_VERSION,
        "h1_atr_14_bps": (
            None if _decimal(h1.get("atr_14_bps")) is None else _decimal_text(_decimal(h1.get("atr_14_bps")))
        ),
        "reference_price": None if reference_price is None else _decimal_text(reference_price),
        "reference_price_source": reference_source,
        "geometry_rule": "1.0x_H1_ATR_stop_with_1R_and_2R_targets",
        "research_normalization_only": True,
        "trade_recommendation": False,
    }
    return runtime, {"observations": serialized, "risk_basis": risk_basis}


def _evaluate_clause(clause: Mapping[str, Any], observations: Mapping[str, Any]) -> str:
    field = str(clause["observation"])
    op = str(clause["op"])
    expected = str(clause["value"])
    observed = observations.get(field)
    if observed is None:
        return "unknown"
    if op == "eq":
        return "true" if str(observed) == expected else "false"
    if op not in _NUMERIC_OPS:
        raise ValueError(f"Unsupported setup rule operator: {op}")
    observed_number = _decimal(observed)
    expected_number = _decimal(expected)
    if observed_number is None or expected_number is None:
        return "unknown"
    if op == "gt":
        matched = observed_number > expected_number
    elif op == "gte":
        matched = observed_number >= expected_number
    elif op == "lt":
        matched = observed_number < expected_number
    else:
        matched = observed_number <= expected_number
    return "true" if matched else "false"


def _definition_digest(definition: Mapping[str, Any]) -> str:
    return _digest(definition)


def compute_setup_detection_digest(packet: Mapping[str, Any]) -> str:
    body = dict(packet)
    body.pop("detection_digest", None)
    return _digest(body)


def verify_setup_detection_digest(packet: Mapping[str, Any]) -> bool:
    supplied = str(packet.get("detection_digest") or "")
    return bool(supplied) and supplied == compute_setup_detection_digest(packet)


def detect_candidate_setups(
    *, context: Mapping[str, Any], regime: Mapping[str, Any]
) -> dict[str, Any]:
    """Recognize candidate Gold structures without making a trading decision."""

    as_of, gold, validated_regime = _validate_inputs(context, regime)
    runtime_observations, serializable = _observations(context, gold, validated_regime)
    observation_packet = serializable["observations"]
    observation_digest = _digest(observation_packet)

    candidates: list[dict[str, Any]] = []
    unresolved: list[str] = []
    evaluations: dict[str, dict[str, Any]] = {}
    for definition in SETUP_DEFINITIONS:
        clause_results = [
            _evaluate_clause(clause, runtime_observations)
            for clause in definition["clauses"]
        ]
        if "false" in clause_results:
            state = "not_matched"
        elif "unknown" in clause_results:
            state = "unresolved"
            unresolved.append(str(definition["setup_id"]))
        else:
            state = "matched"
            candidates.append(
                {
                    "setup_id": definition["setup_id"],
                    "family": definition["family"],
                    "direction": definition["direction"],
                    "definition_digest": _definition_digest(definition),
                }
            )
        evaluations[str(definition["setup_id"])] = {
            "state": state,
            "clause_results": clause_results,
        }

    candidates.sort(key=lambda item: str(item["setup_id"]))
    unresolved.sort()
    if len(candidates) == 1:
        detector_state = "single"
    elif len(candidates) > 1:
        detector_state = "multiple"
    elif unresolved:
        detector_state = "indeterminate"
    else:
        detector_state = "none"

    taxonomy = taxonomy_manifest()
    packet: dict[str, Any] = {
        "detection_version": SETUP_DETECTION_VERSION,
        "digest_algorithm": SETUP_DIGEST_ALGORITHM,
        "taxonomy_version": SETUP_TAXONOMY_VERSION,
        "taxonomy_digest": taxonomy["taxonomy_digest"],
        "detector_version": SETUP_DETECTOR_VERSION,
        "pit_eligible": True,
        "future_derived": False,
        "decision_input_allowed": True,
        "trading_decision_made": False,
        "trade_recommendation_made": False,
        "symbol": SUPPORTED_SYMBOL,
        "as_of_utc": as_of.isoformat(),
        "source_context_hash": context["context_hash"],
        "source_regime_digest": validated_regime["regime_digest"],
        "detector_state": detector_state,
        "candidate_setup_ids": [item["setup_id"] for item in candidates],
        "candidate_directions": sorted({str(item["direction"]) for item in candidates}),
        "unresolved_setup_ids": unresolved,
        "candidates": candidates,
        "observation_digest": observation_digest,
        "observations": observation_packet,
        "risk_basis": serializable["risk_basis"],
        "rule_evaluations": evaluations,
    }
    packet["detection_digest"] = compute_setup_detection_digest(packet)
    return packet


def _validate_detection(packet: Mapping[str, Any]) -> None:
    if packet.get("detection_version") != SETUP_DETECTION_VERSION:
        raise ValueError("Unsupported Day 15 setup detection version.")
    if packet.get("taxonomy_version") != SETUP_TAXONOMY_VERSION:
        raise ValueError("Unsupported Day 15 setup taxonomy version.")
    if packet.get("detector_version") != SETUP_DETECTOR_VERSION:
        raise ValueError("Unsupported Day 15 setup detector version.")
    if packet.get("detector_state") not in _DETECTOR_STATES:
        raise ValueError("Invalid Day 15 detector state.")
    if (
        packet.get("pit_eligible") is not True
        or packet.get("future_derived") is not False
        or packet.get("decision_input_allowed") is not True
        or packet.get("trading_decision_made") is not False
    ):
        raise ValueError("Day 15 detection must remain PIT-safe non-decision evidence.")
    if packet.get("symbol") != SUPPORTED_SYMBOL:
        raise ValueError(f"Day 15 supports only {SUPPORTED_SYMBOL}.")
    if not verify_setup_detection_digest(packet):
        raise ValueError("Day 15 detection digest does not match packet contents.")
    manifest = taxonomy_manifest()
    if packet.get("taxonomy_digest") != manifest["taxonomy_digest"]:
        raise ValueError("Day 15 taxonomy digest does not match the frozen v1 taxonomy.")


def _risk_geometry(packet: Mapping[str, Any], *, anchor_price: Decimal) -> tuple[str, dict[str, Any] | None, str]:
    risk_basis = packet.get("risk_basis")
    risk_basis = risk_basis if isinstance(risk_basis, Mapping) else {}
    observed_price = _decimal(risk_basis.get("reference_price"))
    atr_bps = _decimal(risk_basis.get("h1_atr_14_bps"))
    if observed_price is None or atr_bps is None:
        return "unknown", None, "day15_structural_risk_unknown"
    if anchor_price != observed_price:
        raise ValueError("Day 15 Day 14 adapter requires anchor_price to match observed reference price.")
    if atr_bps <= 0:
        return "invalid", None, "day15_structural_risk_invalid"

    candidate = packet["candidates"][0]
    direction = str(candidate["direction"])
    with localcontext() as ctx:
        ctx.prec = 34
        risk_distance = anchor_price * atr_bps / Decimal(10000)
        if direction == "long":
            stop = anchor_price - risk_distance
            targets = (anchor_price + risk_distance, anchor_price + risk_distance * Decimal(2))
        elif direction == "short":
            stop = anchor_price + risk_distance
            targets = (anchor_price - risk_distance, anchor_price - risk_distance * Decimal(2))
        else:
            raise ValueError("Day 15 candidate direction must be long or short.")
    if stop <= 0 or any(target <= 0 for target in targets):
        return "invalid", None, "day15_structural_risk_invalid"
    trade_spec = {
        "entry_type": "market",
        "entry": _decimal_text(anchor_price),
        "stop_loss": _decimal_text(stop),
        "targets": [_decimal_text(target) for target in targets],
    }
    return "valid", trade_spec, "day15_atr_normalized_geometry_valid"


def build_day14_setup_evidence_from_detection(
    detection: Mapping[str, Any], *, anchor_price: Any
) -> dict[str, Any]:
    """Adapt Day 15 recognition into Day 14's contemporaneous setup/risk interface."""

    _validate_detection(detection)
    detector_state = str(detection["detector_state"])
    common = {
        "as_of": detection["as_of_utc"],
        "taxonomy_version": detection["taxonomy_version"],
        "detector_version": detection["detector_version"],
        "source_context_hash": detection["source_context_hash"],
        "source_regime_digest": detection["source_regime_digest"],
    }
    if detector_state == "none":
        return build_setup_eligibility_evidence(
            **common,
            setup_state="absent",
            risk_state="not_applicable",
            reason_codes=("day15_no_candidate_setup",),
        )
    if detector_state == "indeterminate":
        return build_setup_eligibility_evidence(
            **common,
            setup_state="unknown",
            risk_state="unknown",
            reason_codes=("day15_setup_evidence_indeterminate",),
        )
    if detector_state == "multiple":
        return build_setup_eligibility_evidence(
            **common,
            setup_state="ambiguous",
            risk_state="unknown",
            candidate_setup_ids=detection["candidate_setup_ids"],
            reason_codes=("day15_multiple_candidate_setups",),
        )

    candidate = detection["candidates"][0]
    direction = str(candidate["direction"])
    if direction not in _DIRECTIONS:
        raise ValueError("Day 15 single candidate has invalid direction.")
    anchor = _decimal(anchor_price)
    if anchor is None or anchor <= 0:
        raise ValueError("Day 15 Day 14 adapter requires a finite positive anchor_price.")
    risk_state, trade_spec, reason = _risk_geometry(detection, anchor_price=anchor)
    return build_setup_eligibility_evidence(
        **common,
        setup_state="present",
        risk_state=risk_state,
        candidate_setup_ids=(str(candidate["setup_id"]),),
        direction=direction,
        trade_spec=trade_spec,
        reason_codes=(reason, "day15_single_candidate_setup"),
    )


def setup_detection_storage_row(packet: Mapping[str, Any]) -> dict[str, Any]:
    _validate_detection(packet)
    return {
        field.name: packet[field.name]
        for field in RESEARCH_SETUP_DETECTIONS.fields
    }


def setup_detection_distribution(packets: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    items = list(packets)
    state_counts: Counter[str] = Counter()
    setup_counts: Counter[str] = Counter()
    family_counts: Counter[str] = Counter()
    direction_counts: Counter[str] = Counter()
    for packet in items:
        _validate_detection(packet)
        state_counts[str(packet["detector_state"])] += 1
        for candidate in packet["candidates"]:
            setup_counts[str(candidate["setup_id"])] += 1
            family_counts[str(candidate["family"])] += 1
            direction_counts[str(candidate["direction"])] += 1
    result = {
        "distribution_version": SETUP_DISTRIBUTION_VERSION,
        "taxonomy_version": SETUP_TAXONOMY_VERSION,
        "detector_version": SETUP_DETECTOR_VERSION,
        "pit_eligible": True,
        "future_derived": False,
        "outcome_statistics_included": False,
        "packet_count": len(items),
        "detector_state_counts": dict(sorted(state_counts.items())),
        "candidate_setup_counts": dict(sorted(setup_counts.items())),
        "candidate_family_counts": dict(sorted(family_counts.items())),
        "candidate_direction_counts": dict(sorted(direction_counts.items())),
    }
    result["distribution_digest"] = _digest(result)
    return result
