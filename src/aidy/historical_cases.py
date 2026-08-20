from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256
from typing import Any

from aidy.bigquery_exporter import FieldSpec, TableSpec
from aidy.context_packet import CONTEXT_PACKET_VERSION, verify_context_hash
from aidy.feature_engine import FEATURE_DEFINITION_VERSION, build_feature_packet
from aidy.historical_backfill import RETROSPECTIVE_PROVENANCE
from aidy.market_sessions import session_code_at
from aidy.move_detective import (
    DEFAULT_HORIZONS_MINUTES,
    MOVE_BUNDLE_VERSION,
    build_move_bundle,
    verify_move_bundle_digest,
)
from aidy.no_trade_counterfactual import (
    COUNTERFACTUAL_VERSION,
    verify_no_trade_counterfactual_digest,
)
from aidy.regime_classifier import (
    REGIME_DEFINITION_VERSION,
    classify_trend_structure,
    classify_volatility_band,
    verify_regime_digest,
)
from aidy.setup_detector import (
    RISK_TEMPLATE_VERSION,
    SETUP_DEFINITIONS,
    SETUP_DETECTION_VERSION,
    SETUP_DETECTOR_VERSION,
    SETUP_TAXONOMY_VERSION,
    taxonomy_manifest,
    verify_setup_detection_digest,
)
from aidy.trade_outcomes import (
    TRADE_OUTCOME_BUNDLE_VERSION,
    build_trade_outcome_bundle,
    verify_trade_outcome_bundle_digest,
)

CASE_INPUT_VERSION = "aidy_historical_case_input_v1"
CASE_VERSION = "aidy_historical_gold_case_v1"
CASE_DIGEST_ALGORITHM = "sha256"
CASE_REPLAY_VERSION = "aidy_research_asof_replay_v1"
CASE_REGIME_REPLAY_VERSION = "aidy_gold_regime_replay_v1"
CASE_SETUP_REPLAY_VERSION = "aidy_gold_setup_replay_v1"
CASE_QUALITY_VERSION = "aidy_historical_case_quality_v1"
ANALOGUE_INPUT_VIEW_VERSION = "aidy_historical_analogue_input_v1"
CASE_DISTRIBUTION_VERSION = "aidy_historical_case_distribution_v1"
PIT_OBSERVED_PROVENANCE = "pit_observed"
SUPPORTED_SYMBOL = "XAUUSD"

_TIMEFRAME_MINUTES = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}
_CORE_TIMEFRAMES = ("M1", "M15", "H1", "H4")
_NUMERIC_OPS = {"gt", "gte", "lt", "lte"}
_FORBIDDEN_INPUT_KEYS = {
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

RESEARCH_GOLD_CASES = TableSpec(
    name="research_gold_cases",
    partition_field="as_of_utc",
    clustering_fields=("symbol", "provenance_class", "data_quality_grade", "detector_state"),
    fields=(
        FieldSpec("case_digest", "STRING", "REQUIRED"),
        FieldSpec("case_version", "STRING", "REQUIRED"),
        FieldSpec("case_id", "STRING", "REQUIRED"),
        FieldSpec("symbol", "STRING", "REQUIRED"),
        FieldSpec("as_of_utc", "TIMESTAMP", "REQUIRED"),
        FieldSpec("provenance_class", "STRING", "REQUIRED"),
        FieldSpec("input_digest", "STRING", "REQUIRED"),
        FieldSpec("feature_definition_version", "STRING", "REQUIRED"),
        FieldSpec("regime_definition_version", "STRING", "REQUIRED"),
        FieldSpec("setup_taxonomy_version", "STRING", "REQUIRED"),
        FieldSpec("setup_detector_version", "STRING", "REQUIRED"),
        FieldSpec("data_quality_grade", "STRING", "REQUIRED"),
        FieldSpec("regime_key", "STRING", "REQUIRED"),
        FieldSpec("detector_state", "STRING", "REQUIRED"),
        FieldSpec("candidate_setup_ids", "STRING", "REPEATED"),
        FieldSpec("future_available_after_utc", "TIMESTAMP", "NULLABLE"),
        FieldSpec("input_boundary", "JSON", "REQUIRED"),
        FieldSpec("future_evaluation", "JSON", "REQUIRED"),
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
            raise ValueError(f"Invalid historical-case timestamp: {value}") from exc
    else:
        raise TypeError("Historical-case timestamps must be timezone-aware.")
    if parsed.tzinfo is None:
        raise ValueError("Historical-case timestamps must be timezone-aware.")
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


def _feature_digest(packet: Mapping[str, Any]) -> str:
    body = dict(packet)
    body.pop("feature_packet_digest", None)
    return _digest(body)


def _verify_feature_packet(packet: Mapping[str, Any]) -> bool:
    supplied = str(packet.get("feature_packet_digest") or "")
    return bool(supplied) and supplied == _feature_digest(packet)


def _assert_input_clean(value: Any, *, path: str = "input_boundary") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_INPUT_KEYS:
                raise ValueError(f"Future/outcome field is forbidden at {path}.{key}.")
            if normalized == "future_derived" and item is not False:
                raise ValueError(f"Input future_derived must remain false at {path}.{key}.")
            _assert_input_clean(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_input_clean(item, path=f"{path}[{index}]")


def _closed_research_rows_as_of(
    rows: Iterable[Mapping[str, Any]], *, as_of: datetime
) -> list[Mapping[str, Any]]:
    selected: list[Mapping[str, Any]] = []
    for row in rows:
        if row.get("provenance_class") != RETROSPECTIVE_PROVENANCE:
            raise ValueError("Historical replay accepts retrospective_history rows only.")
        if row.get("pit_eligible") is not False:
            raise ValueError("Historical replay research rows must be pit_eligible=false.")
        if str(row.get("symbol") or "") != SUPPORTED_SYMBOL:
            continue
        timeframe = str(row.get("timeframe") or "")
        try:
            duration = _TIMEFRAME_MINUTES[timeframe]
        except KeyError as exc:
            raise ValueError(f"Unsupported historical replay timeframe: {timeframe}") from exc
        open_time = _utc(str(row.get("open_time_utc") or ""))
        available_at = open_time + timedelta(minutes=duration)
        if available_at <= as_of:
            selected.append(row)
    return selected


def _tf(feature_packet: Mapping[str, Any], timeframe: str) -> Mapping[str, Any]:
    timeframes = feature_packet.get("timeframes")
    timeframes = timeframes if isinstance(timeframes, Mapping) else {}
    payload = timeframes.get(timeframe)
    if not isinstance(payload, Mapping) or payload.get("state") != "known":
        return {}
    return payload


def _known_text(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value in (None, "", "unknown"):
        return None
    return str(value)


def _regime_replay(feature_packet: Mapping[str, Any], *, as_of: datetime) -> dict[str, Any]:
    directions = {
        timeframe: _known_text(_tf(feature_packet, timeframe), "return_5_direction") or "unknown"
        for timeframe in ("M15", "H1", "H4")
    }
    h1 = _tf(feature_packet, "H1")
    labels = {
        "trend_structure": classify_trend_structure(directions),
        "volatility_band": classify_volatility_band(h1.get("atr_14_bps")),
        "session": session_code_at(as_of),
        "quote_spread_condition": "unknown",
        "event_timing": "unknown",
    }
    compound_key = "|".join(f"{key}={value}" for key, value in labels.items())
    packet: dict[str, Any] = {
        "replay_version": CASE_REGIME_REPLAY_VERSION,
        "source_regime_definition_version": REGIME_DEFINITION_VERSION,
        "as_of_utc": as_of.isoformat(),
        "symbol": SUPPORTED_SYMBOL,
        "retrospective_replay": True,
        "pit_eligible": False,
        "future_derived": False,
        "causal_claims_included": False,
        "labels": labels,
        "compound_regime_key": compound_key,
        "rule_evidence": {
            "trend_directions": directions,
            "h1_atr_14_bps": h1.get("atr_14_bps"),
            "quote_spread_condition": "unavailable_by_retrospective_provenance",
            "event_timing": "unavailable_by_retrospective_provenance",
        },
    }
    packet["replay_digest"] = _digest(packet)
    return packet


def _setup_observations(
    feature_packet: Mapping[str, Any], regime_replay: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    m1 = _tf(feature_packet, "M1")
    m15 = _tf(feature_packet, "M15")
    h1 = _tf(feature_packet, "H1")
    h4 = _tf(feature_packet, "H4")
    labels = regime_replay["labels"]
    range_context = feature_packet.get("range_context")
    range_context = range_context if isinstance(range_context, Mapping) else {}
    session = range_context.get("session")
    session = session if isinstance(session, Mapping) and session.get("state") == "known" else {}

    m15_range = _decimal(m15.get("range_bps"))
    m15_atr = _decimal(m15.get("atr_14_bps"))
    range_atr_ratio = None
    if m15_range is not None and m15_atr is not None and m15_atr > 0:
        with localcontext() as ctx:
            ctx.prec = 34
            range_atr_ratio = m15_range / m15_atr

    runtime = {
        "trend_structure": labels.get("trend_structure"),
        "volatility_band": labels.get("volatility_band"),
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
    serializable = {
        key: _decimal_text(value) if isinstance(value, Decimal) else value
        for key, value in sorted(runtime.items())
    }
    risk_basis = {
        "risk_template_version": RISK_TEMPLATE_VERSION,
        "h1_atr_14_bps": h1.get("atr_14_bps"),
        "reference_price": m1.get("latest_close"),
        "reference_price_source": "last_closed_retrospective_m1_close",
        "geometry_rule": "1.0x_H1_ATR_stop_with_1R_and_2R_targets",
        "research_normalization_only": True,
        "trade_recommendation": False,
    }
    return runtime, {"observations": serializable, "risk_basis": risk_basis}


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
        raise ValueError(f"Unsupported setup replay operator: {op}")
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


def _setup_replay(
    feature_packet: Mapping[str, Any],
    regime_replay: Mapping[str, Any],
    *,
    as_of: datetime,
) -> dict[str, Any]:
    observations, serializable = _setup_observations(feature_packet, regime_replay)
    candidates: list[dict[str, Any]] = []
    unresolved: list[str] = []
    evaluations: dict[str, dict[str, Any]] = {}
    for definition in SETUP_DEFINITIONS:
        clause_results = [
            _evaluate_clause(clause, observations) for clause in definition["clauses"]
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
                    "definition_digest": _digest(definition),
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
        "replay_version": CASE_SETUP_REPLAY_VERSION,
        "source_detection_version": SETUP_DETECTION_VERSION,
        "source_taxonomy_version": SETUP_TAXONOMY_VERSION,
        "source_taxonomy_digest": taxonomy["taxonomy_digest"],
        "source_detector_version": SETUP_DETECTOR_VERSION,
        "as_of_utc": as_of.isoformat(),
        "symbol": SUPPORTED_SYMBOL,
        "retrospective_replay": True,
        "pit_eligible": False,
        "future_derived": False,
        "trading_decision_made": False,
        "trade_recommendation_made": False,
        "detector_state": detector_state,
        "candidate_setup_ids": [item["setup_id"] for item in candidates],
        "candidate_directions": sorted({str(item["direction"]) for item in candidates}),
        "unresolved_setup_ids": unresolved,
        "candidates": candidates,
        "observations": serializable["observations"],
        "observation_digest": _digest(serializable["observations"]),
        "risk_basis": serializable["risk_basis"],
        "rule_evaluations": evaluations,
    }
    packet["replay_digest"] = _digest(packet)
    return packet


def _normalized_trade_spec(setup_replay: Mapping[str, Any]) -> dict[str, Any] | None:
    if setup_replay.get("detector_state") != "single":
        return None
    candidates = setup_replay.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        return None
    risk_basis = setup_replay.get("risk_basis")
    risk_basis = risk_basis if isinstance(risk_basis, Mapping) else {}
    entry = _decimal(risk_basis.get("reference_price"))
    atr_bps = _decimal(risk_basis.get("h1_atr_14_bps"))
    if entry is None or entry <= 0 or atr_bps is None or atr_bps <= 0:
        return None
    direction = str(candidates[0].get("direction") or "")
    with localcontext() as ctx:
        ctx.prec = 34
        risk = entry * atr_bps / Decimal(10000)
        if direction == "long":
            stop = entry - risk
            targets = (entry + risk, entry + risk * Decimal(2))
        elif direction == "short":
            stop = entry + risk
            targets = (entry - risk, entry - risk * Decimal(2))
        else:
            return None
    if stop <= 0 or any(target <= 0 for target in targets):
        return None
    return {
        "template_version": RISK_TEMPLATE_VERSION,
        "research_normalization_only": True,
        "direction": direction,
        "entry": _decimal_text(entry),
        "stop_loss": _decimal_text(stop),
        "targets": [_decimal_text(target) for target in targets],
    }


def _retrospective_quality(feature_packet: Mapping[str, Any]) -> dict[str, Any]:
    known = [timeframe for timeframe in _CORE_TIMEFRAMES if _tf(feature_packet, timeframe)]
    m15 = _tf(feature_packet, "M15")
    h1 = _tf(feature_packet, "H1")
    required_metrics = {
        "h1_atr_14_bps": h1.get("atr_14_bps"),
        "m15_close_location": m15.get("close_location"),
        "m15_range_position_20": m15.get("range_position_20"),
    }
    known_metrics = sum(value not in (None, "", "unknown") for value in required_metrics.values())
    if len(known) == len(_CORE_TIMEFRAMES) and known_metrics == len(required_metrics):
        grade = "strong"
    elif len(known) >= 3 and known_metrics >= 1:
        grade = "moderate"
    elif len(known) >= 2:
        grade = "limited"
    else:
        grade = "insufficient"
    return {
        "quality_version": CASE_QUALITY_VERSION,
        "grade": grade,
        "retrieval_eligible": grade != "insufficient",
        "known_core_timeframes": known,
        "missing_core_timeframes": sorted(set(_CORE_TIMEFRAMES) - set(known)),
        "known_required_metric_count": known_metrics,
        "required_metric_count": len(required_metrics),
        "quote_state": "unavailable_by_retrospective_provenance",
        "event_state": "unavailable_by_retrospective_provenance",
        "cross_market_state": "unavailable_by_retrospective_provenance",
    }


def _pit_quality(context: Mapping[str, Any]) -> dict[str, Any]:
    data_quality = context.get("data_quality")
    data_quality = data_quality if isinstance(data_quality, Mapping) else {}
    missing = {str(value) for value in data_quality.get("missing_gold_timeframes") or []}
    missing_core = sorted(set(_CORE_TIMEFRAMES) & missing)
    quote_freshness = str(data_quality.get("quote_freshness") or "unknown")
    macro_state = str(data_quality.get("macro_evidence_state") or "unknown")
    cross_missing = list(data_quality.get("cross_market_missing_series") or [])
    if not missing_core and quote_freshness == "fresh" and macro_state == "known" and not cross_missing:
        grade = "strong"
    elif not missing_core:
        grade = "moderate"
    elif len(missing_core) <= 2:
        grade = "limited"
    else:
        grade = "insufficient"
    return {
        "quality_version": CASE_QUALITY_VERSION,
        "grade": grade,
        "retrieval_eligible": grade != "insufficient",
        "missing_core_timeframes": missing_core,
        "quote_freshness": quote_freshness,
        "macro_evidence_state": macro_state,
        "cross_market_missing_series": sorted(str(value) for value in cross_missing),
        "flags": list(data_quality.get("flags") or []),
    }


def _feature_summary(feature_packet: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "state",
        "bars_available",
        "latest_open_time_utc",
        "latest_close",
        "return_1_bps",
        "return_5_bps",
        "return_5_direction",
        "body_bps",
        "range_bps",
        "close_location",
        "atr_14_bps",
        "realized_vol_20_bps",
        "distance_to_high_20_bps",
        "distance_from_low_20_bps",
        "range_position_20",
        "confirmed_swing_high",
        "confirmed_swing_low",
    )
    return {
        timeframe: {key: payload.get(key) for key in keys}
        for timeframe in _TIMEFRAME_MINUTES
        if (payload := _tf(feature_packet, timeframe))
    }


def _analogue_features(
    *,
    feature_packet: Mapping[str, Any],
    regime_labels: Mapping[str, Any],
    setup_state: str,
    candidate_setup_ids: Iterable[Any],
) -> dict[str, Any]:
    m15 = _tf(feature_packet, "M15")
    h1 = _tf(feature_packet, "H1")
    h4 = _tf(feature_packet, "H4")
    range_context = feature_packet.get("range_context")
    range_context = range_context if isinstance(range_context, Mapping) else {}
    session = range_context.get("session")
    session = session if isinstance(session, Mapping) else {}
    return {
        "regime": dict(regime_labels),
        "m15_direction": m15.get("return_5_direction"),
        "h1_direction": h1.get("return_5_direction"),
        "h4_direction": h4.get("return_5_direction"),
        "h1_atr_14_bps": h1.get("atr_14_bps"),
        "m15_realized_vol_20_bps": m15.get("realized_vol_20_bps"),
        "m15_range_position_20": m15.get("range_position_20"),
        "m15_close_location": m15.get("close_location"),
        "session_range_position": session.get("position"),
        "setup_detector_state": setup_state,
        "candidate_setup_ids": sorted(str(value) for value in candidate_setup_ids),
    }


def compute_case_input_digest(input_boundary: Mapping[str, Any]) -> str:
    body = dict(input_boundary)
    body.pop("input_digest", None)
    return _digest(body)


def verify_case_input_digest(input_boundary: Mapping[str, Any]) -> bool:
    supplied = str(input_boundary.get("input_digest") or "")
    return bool(supplied) and supplied == compute_case_input_digest(input_boundary)


def build_retrospective_case_input(
    *,
    as_of: datetime | str,
    research_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    cutoff = _utc(as_of)
    raw_rows = list(research_rows)
    closed_rows = _closed_research_rows_as_of(raw_rows, as_of=cutoff)
    feature_packet = build_feature_packet(
        as_of=cutoff,
        symbol=SUPPORTED_SYMBOL,
        candle_rows=closed_rows,
        mode="retrospective",
    )
    if not _verify_feature_packet(feature_packet):
        raise ValueError("Retrospective feature packet digest does not match contents.")
    regime = _regime_replay(feature_packet, as_of=cutoff)
    setup = _setup_replay(feature_packet, regime, as_of=cutoff)
    quality = _retrospective_quality(feature_packet)
    trade_spec = _normalized_trade_spec(setup)

    m1 = _tf(feature_packet, "M1")
    latest_open = m1.get("latest_open_time_utc")
    evaluation_anchor = None
    if latest_open and m1.get("latest_close") is not None:
        anchor_time = _utc(str(latest_open))
        if anchor_time + timedelta(minutes=1) > cutoff:
            raise ValueError("Retrospective M1 anchor was not closed by the case as-of time.")
        evaluation_anchor = {
            "anchor_time_utc": anchor_time.isoformat(),
            "anchor_price": str(m1["latest_close"]),
            "forward_start_utc": (anchor_time + timedelta(minutes=1)).isoformat(),
            "alignment_rule": "last_closed_m1_bar_then_next_minute_future_path",
        }

    source_links = feature_packet.get("source_links")
    source_links = source_links if isinstance(source_links, Mapping) else {}
    source_identities = sorted(
        {
            str(item.get("identity"))
            for links in source_links.values()
            if isinstance(links, list)
            for item in links
            if isinstance(item, Mapping) and item.get("identity")
        }
    )
    input_boundary: dict[str, Any] = {
        "input_version": CASE_INPUT_VERSION,
        "replay_version": CASE_REPLAY_VERSION,
        "symbol": SUPPORTED_SYMBOL,
        "as_of_utc": cutoff.isoformat(),
        "provenance_class": RETROSPECTIVE_PROVENANCE,
        "pit_observed": False,
        "retrospective_replay": True,
        "future_derived": False,
        "analogue_match_allowed": True,
        "live_decision_input_allowed": False,
        "feature": {
            "feature_definition_version": FEATURE_DEFINITION_VERSION,
            "feature_packet_digest": feature_packet["feature_packet_digest"],
            "mode": "retrospective",
            "summary": _feature_summary(feature_packet),
            "range_context": feature_packet.get("range_context"),
            "multi_timeframe_alignment": feature_packet.get("multi_timeframe_alignment"),
        },
        "regime": regime,
        "setup": setup,
        "normalized_trade_spec": trade_spec,
        "data_quality": quality,
        "analogue_features": _analogue_features(
            feature_packet=feature_packet,
            regime_labels=regime["labels"],
            setup_state=str(setup["detector_state"]),
            candidate_setup_ids=setup["candidate_setup_ids"],
        ),
        "evaluation_anchor": evaluation_anchor,
        "provenance": {
            "source_provenance_class": RETROSPECTIVE_PROVENANCE,
            "source_identity_count": len(source_identities),
            "source_identities_digest": _digest(source_identities),
            "source_links_digest": _digest(source_links),
        },
    }
    _assert_input_clean(input_boundary)
    input_boundary["input_digest"] = compute_case_input_digest(input_boundary)
    return input_boundary


def build_pit_case_input(
    *,
    context: Mapping[str, Any],
    regime: Mapping[str, Any],
    setup_detection: Mapping[str, Any],
) -> dict[str, Any]:
    if context.get("context_packet_version") != CONTEXT_PACKET_VERSION:
        raise ValueError("PIT case input requires aidy_market_context_v1.")
    if not verify_context_hash(context):
        raise ValueError("PIT case context hash does not match contents.")
    if context.get("symbol") != SUPPORTED_SYMBOL:
        raise ValueError(f"Historical cases support only {SUPPORTED_SYMBOL}.")
    if context.get("objective_only") is not True:
        raise ValueError("PIT case context must be objective-only.")
    if context.get("retrospective_history_included") is not False:
        raise ValueError("PIT case context cannot include retrospective history.")
    gold = context.get("gold")
    if not isinstance(gold, Mapping):
        raise TypeError("PIT context.gold must be an object.")
    if not _verify_feature_packet(gold):
        raise ValueError("PIT case Gold feature packet digest does not match contents.")

    if regime.get("regime_definition_version") != REGIME_DEFINITION_VERSION:
        raise ValueError("PIT case input requires aidy_gold_regime_v1.")
    if not verify_regime_digest(regime):
        raise ValueError("PIT case regime digest does not match contents.")
    if regime.get("source_context_hash") != context.get("context_hash"):
        raise ValueError("PIT case regime must originate from the supplied context.")

    if setup_detection.get("detection_version") != SETUP_DETECTION_VERSION:
        raise ValueError("PIT case input requires aidy_gold_setup_detection_v1.")
    if setup_detection.get("taxonomy_version") != SETUP_TAXONOMY_VERSION:
        raise ValueError("PIT case setup taxonomy version is unsupported.")
    if setup_detection.get("detector_version") != SETUP_DETECTOR_VERSION:
        raise ValueError("PIT case setup detector version is unsupported.")
    if not verify_setup_detection_digest(setup_detection):
        raise ValueError("PIT case setup detection digest does not match contents.")
    if setup_detection.get("source_context_hash") != context.get("context_hash"):
        raise ValueError("PIT setup detection must originate from the supplied context.")
    if setup_detection.get("source_regime_digest") != regime.get("regime_digest"):
        raise ValueError("PIT setup detection must originate from the supplied regime.")

    as_of = _utc(str(context.get("as_of_utc") or ""))
    if _utc(str(regime.get("as_of_utc") or "")) != as_of:
        raise ValueError("PIT context/regime as-of timestamps must match.")
    if _utc(str(setup_detection.get("as_of_utc") or "")) != as_of:
        raise ValueError("PIT context/setup as-of timestamps must match.")

    quote = gold.get("quote_context")
    quote = quote if isinstance(quote, Mapping) else {}
    m1 = _tf(gold, "M1")
    quality = _pit_quality(context)
    reference_price = None
    reference_source = "unknown"
    quote_mid = _decimal(quote.get("mid"))
    if quality.get("quote_freshness") == "fresh" and quote_mid is not None and quote_mid > 0:
        reference_price = str(quote.get("mid"))
        reference_source = "fresh_quote_mid"
    elif m1.get("latest_close") is not None:
        reference_price = str(m1.get("latest_close"))
        reference_source = "latest_m1_close"

    input_boundary: dict[str, Any] = {
        "input_version": CASE_INPUT_VERSION,
        "replay_version": None,
        "symbol": SUPPORTED_SYMBOL,
        "as_of_utc": as_of.isoformat(),
        "provenance_class": PIT_OBSERVED_PROVENANCE,
        "pit_observed": True,
        "retrospective_replay": False,
        "future_derived": False,
        "analogue_match_allowed": True,
        "live_decision_input_allowed": True,
        "feature": {
            "feature_definition_version": gold.get("feature_definition_version"),
            "feature_packet_digest": gold.get("feature_packet_digest"),
            "mode": gold.get("mode"),
            "summary": _feature_summary(gold),
            "range_context": gold.get("range_context"),
            "multi_timeframe_alignment": gold.get("multi_timeframe_alignment"),
        },
        "regime": {
            "regime_definition_version": regime["regime_definition_version"],
            "regime_digest": regime["regime_digest"],
            "labels": regime["labels"],
            "compound_regime_key": regime["compound_regime_key"],
        },
        "setup": {
            "detection_version": setup_detection["detection_version"],
            "detection_digest": setup_detection["detection_digest"],
            "taxonomy_version": setup_detection["taxonomy_version"],
            "taxonomy_digest": setup_detection["taxonomy_digest"],
            "detector_version": setup_detection["detector_version"],
            "detector_state": setup_detection["detector_state"],
            "candidate_setup_ids": list(setup_detection["candidate_setup_ids"]),
            "candidate_directions": list(setup_detection["candidate_directions"]),
            "unresolved_setup_ids": list(setup_detection["unresolved_setup_ids"]),
            "risk_basis": setup_detection["risk_basis"],
        },
        "normalized_trade_spec": None,
        "data_quality": quality,
        "analogue_features": _analogue_features(
            feature_packet=gold,
            regime_labels=regime["labels"],
            setup_state=str(setup_detection["detector_state"]),
            candidate_setup_ids=setup_detection["candidate_setup_ids"],
        ),
        "evaluation_anchor": (
            None
            if reference_price is None
            else {
                "anchor_time_utc": as_of.isoformat(),
                "anchor_price": reference_price,
                "forward_start_utc": as_of.isoformat(),
                "alignment_rule": reference_source,
            }
        ),
        "provenance": {
            "source_provenance_class": PIT_OBSERVED_PROVENANCE,
            "context_hash": context["context_hash"],
            "regime_digest": regime["regime_digest"],
            "setup_detection_digest": setup_detection["detection_digest"],
        },
    }
    _assert_input_clean(input_boundary)
    input_boundary["input_digest"] = compute_case_input_digest(input_boundary)
    return input_boundary


def _validate_case_input(input_boundary: Mapping[str, Any]) -> None:
    if input_boundary.get("input_version") != CASE_INPUT_VERSION:
        raise ValueError("Unsupported historical case input version.")
    if input_boundary.get("symbol") != SUPPORTED_SYMBOL:
        raise ValueError(f"Historical cases support only {SUPPORTED_SYMBOL}.")
    if input_boundary.get("provenance_class") not in {
        RETROSPECTIVE_PROVENANCE,
        PIT_OBSERVED_PROVENANCE,
    }:
        raise ValueError("Unsupported historical case provenance class.")
    if input_boundary.get("future_derived") is not False:
        raise ValueError("Historical case input must be future_derived=false.")
    if input_boundary.get("analogue_match_allowed") is not True:
        raise ValueError("Historical case input must explicitly allow analogue matching.")
    _assert_input_clean(input_boundary)
    if not verify_case_input_digest(input_boundary):
        raise ValueError("Historical case input digest does not match contents.")
    _utc(str(input_boundary.get("as_of_utc") or ""))


def _evaluation_anchor(input_boundary: Mapping[str, Any]) -> tuple[datetime, str]:
    anchor = input_boundary.get("evaluation_anchor")
    if not isinstance(anchor, Mapping):
        raise TypeError("Historical case outcomes require an evaluation anchor.")
    anchor_time = _utc(str(anchor.get("anchor_time_utc") or ""))
    anchor_price = str(anchor.get("anchor_price") or "")
    if _decimal(anchor_price) is None:
        raise ValueError("Historical case evaluation anchor requires a finite price.")
    return anchor_time, anchor_price


def _validate_move_bundle(
    bundle: Mapping[str, Any], *, anchor_time: datetime, anchor_price: str
) -> str:
    if bundle.get("move_bundle_version") != MOVE_BUNDLE_VERSION:
        raise ValueError("Historical case requires aidy_move_bundle_v1.")
    if not verify_move_bundle_digest(bundle):
        raise ValueError("Historical case move bundle digest does not match contents.")
    if bundle.get("evaluation_only") is not True or bundle.get("future_derived") is not True:
        raise ValueError("Move bundle must remain evaluation-only future evidence.")
    if bundle.get("pit_eligible") is not False or bundle.get("decision_input_allowed") is not False:
        raise ValueError("Move bundle cannot become decision-time evidence.")
    if _utc(str(bundle.get("anchor_time_utc") or "")) != anchor_time:
        raise ValueError("Move bundle anchor time does not match the case evaluation anchor.")
    if _decimal(bundle.get("anchor_price")) != _decimal(anchor_price):
        raise ValueError("Move bundle anchor price does not match the case evaluation anchor.")
    return str(bundle["available_after_utc"])


def _validate_trade_bundle(
    bundle: Mapping[str, Any],
    *,
    anchor_time: datetime,
    normalized_trade_spec: Mapping[str, Any] | None,
) -> str:
    if bundle.get("trade_outcome_bundle_version") != TRADE_OUTCOME_BUNDLE_VERSION:
        raise ValueError("Historical case requires aidy_trade_outcome_bundle_v1.")
    if not verify_trade_outcome_bundle_digest(bundle):
        raise ValueError("Historical case trade bundle digest does not match contents.")
    if bundle.get("evaluation_only") is not True or bundle.get("future_derived") is not True:
        raise ValueError("Trade bundle must remain evaluation-only future evidence.")
    if bundle.get("pit_eligible") is not False or bundle.get("decision_input_allowed") is not False:
        raise ValueError("Trade bundle cannot become decision-time evidence.")
    if _utc(str(bundle.get("anchor_time_utc") or "")) != anchor_time:
        raise ValueError("Trade bundle anchor time does not match the case evaluation anchor.")
    if normalized_trade_spec is not None:
        expected = {
            "direction": normalized_trade_spec["direction"],
            "entry": normalized_trade_spec["entry"],
            "stop_loss": normalized_trade_spec["stop_loss"],
            "targets": normalized_trade_spec["targets"],
        }
        observed = bundle.get("trade_spec")
        if not isinstance(observed, Mapping):
            raise ValueError("Trade outcome geometry must contain the Day 13 canonical trade_spec.")
        observed_geometry = {
            "direction": observed.get("direction"),
            "entry": observed.get("entry"),
            "stop_loss": observed.get("stop_loss"),
            "targets": observed.get("targets"),
        }
        if observed_geometry != expected:
            raise ValueError("Trade outcome geometry does not match the case normalized geometry.")
    return str(bundle["available_after_utc"])


def _validate_counterfactual(
    record: Mapping[str, Any],
    *,
    input_boundary: Mapping[str, Any],
) -> str:
    if input_boundary.get("provenance_class") != PIT_OBSERVED_PROVENANCE:
        raise ValueError(
            "Day 14 no-trade counterfactuals require genuinely observed PIT setup evidence."
        )
    if record.get("counterfactual_version") != COUNTERFACTUAL_VERSION:
        raise ValueError("Historical case counterfactual version is unsupported.")
    if not verify_no_trade_counterfactual_digest(record):
        raise ValueError("Historical case counterfactual digest does not match contents.")
    if record.get("evaluation_only") is not True or record.get("future_derived") is not True:
        raise ValueError("Counterfactual must remain evaluation-only future evidence.")
    if record.get("pit_eligible") is not False or record.get("decision_input_allowed") is not False:
        raise ValueError("Counterfactual cannot become decision-time evidence.")
    if _utc(str(record.get("decision_time_utc") or "")) != _utc(
        str(input_boundary["as_of_utc"])
    ):
        raise ValueError("Counterfactual decision time does not match the case as-of time.")
    return str(record["available_after_utc"])


def compute_historical_case_digest(case: Mapping[str, Any]) -> str:
    body = dict(case)
    body.pop("case_digest", None)
    return _digest(body)


def verify_historical_case_digest(case: Mapping[str, Any]) -> bool:
    supplied = str(case.get("case_digest") or "")
    return bool(supplied) and supplied == compute_historical_case_digest(case)


def build_historical_case(
    *,
    input_boundary: Mapping[str, Any],
    move_bundle: Mapping[str, Any] | None,
    trade_outcome_bundle: Mapping[str, Any] | None = None,
    no_trade_counterfactual: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    _validate_case_input(input_boundary)
    anchor_time, anchor_price = _evaluation_anchor(input_boundary)
    availability: list[str] = []
    if move_bundle is not None:
        availability.append(
            _validate_move_bundle(move_bundle, anchor_time=anchor_time, anchor_price=anchor_price)
        )
    if trade_outcome_bundle is not None:
        trade_spec = input_boundary.get("normalized_trade_spec")
        trade_spec = trade_spec if isinstance(trade_spec, Mapping) else None
        availability.append(
            _validate_trade_bundle(
                trade_outcome_bundle,
                anchor_time=anchor_time,
                normalized_trade_spec=trade_spec,
            )
        )
    if no_trade_counterfactual is not None:
        availability.append(
            _validate_counterfactual(no_trade_counterfactual, input_boundary=input_boundary)
        )
    if not availability:
        raise ValueError("A completed historical case requires at least one future evaluation label.")

    input_digest = str(input_boundary["input_digest"])
    case_id = _digest(
        {
            "case_version": CASE_VERSION,
            "symbol": input_boundary["symbol"],
            "as_of_utc": input_boundary["as_of_utc"],
            "provenance_class": input_boundary["provenance_class"],
            "input_digest": input_digest,
        }
    )
    future_evaluation = {
        "evaluation_only": True,
        "future_derived": True,
        "pit_eligible": False,
        "decision_input_allowed": False,
        "analogue_match_allowed": False,
        "available_after_utc": max(availability),
        "move_bundle": None if move_bundle is None else dict(move_bundle),
        "trade_outcome_bundle": (
            None if trade_outcome_bundle is None else dict(trade_outcome_bundle)
        ),
        "no_trade_counterfactual": (
            None if no_trade_counterfactual is None else dict(no_trade_counterfactual)
        ),
        "causal_claims_included": False,
    }
    case: dict[str, Any] = {
        "case_version": CASE_VERSION,
        "case_digest_algorithm": CASE_DIGEST_ALGORITHM,
        "case_id": case_id,
        "symbol": input_boundary["symbol"],
        "as_of_utc": input_boundary["as_of_utc"],
        "provenance_class": input_boundary["provenance_class"],
        "decision_input_allowed": False,
        "analogue_query_must_use_input_boundary_only": True,
        "input_boundary": dict(input_boundary),
        "future_evaluation": future_evaluation,
    }
    case["case_digest"] = compute_historical_case_digest(case)
    return case


def build_retrospective_case(
    *,
    as_of: datetime | str,
    research_rows: Iterable[Mapping[str, Any]],
    horizons_minutes: Iterable[int] = DEFAULT_HORIZONS_MINUTES,
) -> dict[str, Any]:
    rows = list(research_rows)
    input_boundary = build_retrospective_case_input(as_of=as_of, research_rows=rows)
    anchor_time, anchor_price = _evaluation_anchor(input_boundary)
    m1_rows = [
        row
        for row in rows
        if str(row.get("symbol") or "") == SUPPORTED_SYMBOL
        and str(row.get("timeframe") or "") == "M1"
    ]
    move_bundle = build_move_bundle(
        anchor_time=anchor_time,
        anchor_price=anchor_price,
        research_rows=m1_rows,
        horizons_minutes=horizons_minutes,
    )
    trade_bundle = None
    trade_spec = input_boundary.get("normalized_trade_spec")
    if isinstance(trade_spec, Mapping):
        trade_bundle = build_trade_outcome_bundle(
            anchor_time=anchor_time,
            direction=str(trade_spec["direction"]),
            entry=trade_spec["entry"],
            stop_loss=trade_spec["stop_loss"],
            targets=trade_spec["targets"],
            research_rows=m1_rows,
            horizons_minutes=horizons_minutes,
        )
    return build_historical_case(
        input_boundary=input_boundary,
        move_bundle=move_bundle,
        trade_outcome_bundle=trade_bundle,
    )


def analogue_input_view(case: Mapping[str, Any]) -> dict[str, Any]:
    if case.get("case_version") != CASE_VERSION or not verify_historical_case_digest(case):
        raise ValueError("Analogue projection requires a valid historical case.")
    input_boundary = case.get("input_boundary")
    if not isinstance(input_boundary, Mapping):
        raise TypeError("Historical case input_boundary must be an object.")
    _validate_case_input(input_boundary)
    view = {
        "view_version": ANALOGUE_INPUT_VIEW_VERSION,
        "case_id": case["case_id"],
        "symbol": case["symbol"],
        "as_of_utc": case["as_of_utc"],
        "provenance_class": case["provenance_class"],
        "input_digest": input_boundary["input_digest"],
        "feature_definition_version": input_boundary["feature"]["feature_definition_version"],
        "regime_definition_version": (
            input_boundary["regime"].get("source_regime_definition_version")
            or input_boundary["regime"].get("regime_definition_version")
        ),
        "setup_taxonomy_version": (
            input_boundary["setup"].get("source_taxonomy_version")
            or input_boundary["setup"].get("taxonomy_version")
        ),
        "setup_detector_version": (
            input_boundary["setup"].get("source_detector_version")
            or input_boundary["setup"].get("detector_version")
        ),
        "data_quality": input_boundary["data_quality"],
        "regime": input_boundary["regime"]["labels"],
        "setup_detector_state": input_boundary["setup"]["detector_state"],
        "candidate_setup_ids": list(input_boundary["setup"]["candidate_setup_ids"]),
        "analogue_features": input_boundary["analogue_features"],
        "future_evaluation_included": False,
    }
    _assert_input_clean(view, path="analogue_input_view")
    view["view_digest"] = _digest(view)
    return view


def historical_case_storage_row(case: Mapping[str, Any]) -> dict[str, Any]:
    if case.get("case_version") != CASE_VERSION or not verify_historical_case_digest(case):
        raise ValueError("Storage accepts only valid historical Gold cases.")
    view = analogue_input_view(case)
    input_boundary = case["input_boundary"]
    future = case["future_evaluation"]
    return {
        "case_digest": case["case_digest"],
        "case_version": case["case_version"],
        "case_id": case["case_id"],
        "symbol": case["symbol"],
        "as_of_utc": case["as_of_utc"],
        "provenance_class": case["provenance_class"],
        "input_digest": input_boundary["input_digest"],
        "feature_definition_version": view["feature_definition_version"],
        "regime_definition_version": view["regime_definition_version"],
        "setup_taxonomy_version": view["setup_taxonomy_version"],
        "setup_detector_version": view["setup_detector_version"],
        "data_quality_grade": input_boundary["data_quality"]["grade"],
        "regime_key": input_boundary["regime"]["compound_regime_key"],
        "detector_state": input_boundary["setup"]["detector_state"],
        "candidate_setup_ids": list(input_boundary["setup"]["candidate_setup_ids"]),
        "future_available_after_utc": future["available_after_utc"],
        "input_boundary": dict(input_boundary),
        "future_evaluation": dict(future),
    }


def historical_case_distribution(cases: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    items = list(cases)
    provenance = Counter()
    quality = Counter()
    detector = Counter()
    setups = Counter()
    with_trade = 0
    for case in items:
        if case.get("case_version") != CASE_VERSION or not verify_historical_case_digest(case):
            raise ValueError("Distribution input contains an invalid historical case.")
        input_boundary = case["input_boundary"]
        provenance[str(case["provenance_class"])] += 1
        quality[str(input_boundary["data_quality"]["grade"])] += 1
        detector[str(input_boundary["setup"]["detector_state"])] += 1
        setups.update(str(value) for value in input_boundary["setup"]["candidate_setup_ids"])
        if case["future_evaluation"].get("trade_outcome_bundle") is not None:
            with_trade += 1
    result = {
        "distribution_version": CASE_DISTRIBUTION_VERSION,
        "case_version": CASE_VERSION,
        "case_count": len(items),
        "provenance_counts": dict(sorted(provenance.items())),
        "quality_counts": dict(sorted(quality.items())),
        "detector_state_counts": dict(sorted(detector.items())),
        "candidate_setup_counts": dict(sorted(setups.items())),
        "cases_with_trade_outcomes": with_trade,
        "future_outcomes_used_for_case_selection": False,
        "analogue_matching_uses_input_boundary_only": True,
    }
    result["distribution_digest"] = _digest(result)
    return result
