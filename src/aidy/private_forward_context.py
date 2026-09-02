from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from aidy.bigquery_exporter import load_identity
from aidy.cme_contract_intelligence import (
    CME_CONTRACT_INTELLIGENCE_VERSION,
    build_contract_roll_state,
    verify_contract_roll_state,
)
from aidy.context_composer_v2 import digest
from aidy.context_packet import compute_context_hash
from aidy.evidence_grading_v2 import build_evidence_report_v2
from aidy.historical_case_semantics import build_semantic_pit_case_input
from aidy.macro_event_intelligence import EVENT_INTELLIGENCE_VERSION
from aidy.macro_vintages import (
    RATES_DECOMPOSITION_VERSION,
    REVISION_INTELLIGENCE_VERSION,
    build_rates_macro_state,
    verify_rates_macro_state,
)
from aidy.market_structure_context import (
    MARKET_STRUCTURE_CONTEXT_VERSION,
    build_market_structure_context,
    verify_market_structure_context,
)
from aidy.price_structure_v2 import (
    PRICE_STRUCTURE_VERSION,
    build_price_structure_packet,
    verify_price_structure_packet,
)
from aidy.semantic_analogue_retrieval import (
    build_semantic_analogue_query,
    retrieve_semantic_analogues_v2,
)
from aidy.semantic_context_packet import build_semantic_context_packet
from aidy.semantic_feature_packet import build_semantic_feature_packet
from aidy.setup_detector import detect_candidate_setups
from aidy.twelve_data_market import AGGREGATE_SOURCE, AIDY_SYMBOL
from aidy.twelve_launch_policy import classify_twelve_private_forward_regime
from aidy.volatility_intelligence import (
    VOLATILITY_INTELLIGENCE_VERSION,
    build_volatility_state,
    verify_volatility_state,
)

PRIVATE_FORWARD_CONTEXT_ADAPTER_VERSION = "aidy_private_forward_context_adapter_v1"
ARCHITECTURE_V2_EXTENSION_VERSION = "aidy_private_forward_architecture_v2_extensions_v1"
PRIVATE_FORWARD_SIGNAL_STATE_VERSION = "aidy_private_forward_signal_state_v1"

_STORAGE_TO_CANONICAL_TIMEFRAME = {
    "1m": "M1",
    "5m": "M5",
    "15m": "M15",
    "1h": "H1",
    "4h": "H4",
    "1d": "D1",
}


def _utc(value: datetime | str, *, name: str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware.")
    return parsed.astimezone(UTC)


def _row(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    try:
        return dict(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise TypeError("Unexpected D1 row shape.") from exc


def _results(value: object) -> list[dict[str, Any]]:
    rows = getattr(value, "results", None)
    if rows is None and isinstance(value, dict):
        rows = value.get("results")
    if rows is None:
        return []
    return [row for item in rows if (row := _row(item)) is not None]


def _json_object(value: object, *, name: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} is not valid JSON.") from exc
    if not isinstance(decoded, dict):
        raise TypeError(f"{name} must decode to an object.")
    return decoded


def _json_list(value: object, *, name: str) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} is not valid JSON.") from exc
    if not isinstance(decoded, list):
        raise TypeError(f"{name} must decode to a list.")
    return [str(item) for item in decoded]


def _conservative_quote_age(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return int(math.ceil(parsed))


def normalize_snapshot_row(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    archive_key = str(snapshot.get("archive_key") or "").strip()
    snapshot_digest = str(snapshot.get("snapshot_digest") or "").strip()
    if not archive_key or not snapshot_digest:
        raise ValueError("Private-forward snapshot lacks immutable archive identity.")
    result = dict(snapshot)
    result["data_availability"] = _json_object(
        snapshot.get("data_availability_json"), name="snapshot.data_availability_json"
    )
    result["quote_age_seconds"] = _conservative_quote_age(snapshot.get("quote_age_seconds"))
    result["load_identity"] = load_identity(archive_key, snapshot_digest)
    result["evidence_id"] = str(snapshot.get("id") or "")
    result["provenance_class"] = "pit_observed"
    result["pit_eligible"] = True
    return result


def _normalize_candle(row: Mapping[str, Any]) -> dict[str, Any]:
    archive_key = str(row.get("archive_key") or "").strip()
    payload_digest = str(row.get("payload_digest") or "").strip()
    timeframe = _STORAGE_TO_CANONICAL_TIMEFRAME.get(
        str(row.get("timeframe") or "").strip().lower(),
        str(row.get("timeframe") or ""),
    )
    if not archive_key or not payload_digest or timeframe not in set(_STORAGE_TO_CANONICAL_TIMEFRAME.values()):
        raise ValueError("Decision candle lacks canonical immutable identity.")
    result = dict(row)
    result["timeframe"] = timeframe
    result["load_identity"] = load_identity(archive_key, payload_digest)
    result["evidence_id"] = str(row.get("id") or "")
    result["provenance_class"] = "pit_observed"
    result["pit_eligible"] = True
    return result


def _dedupe_candles(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        normalized = _normalize_candle(row)
        key = (str(normalized["timeframe"]), str(normalized.get("open_time_utc") or ""))
        current = selected.get(key)
        rank = (
            int(normalized.get("revision_index") or 0),
            str(normalized.get("first_observed_at") or ""),
            str(normalized.get("id") or ""),
        )
        if current is None:
            selected[key] = normalized
            continue
        current_rank = (
            int(current.get("revision_index") or 0),
            str(current.get("first_observed_at") or ""),
            str(current.get("id") or ""),
        )
        if rank > current_rank:
            selected[key] = normalized
    return sorted(selected.values(), key=lambda item: (str(item["timeframe"]), str(item["open_time_utc"])))


def _normalize_event(row: Mapping[str, Any]) -> dict[str, Any]:
    archive_key = str(row.get("archive_key") or "").strip()
    payload_digest = str(row.get("payload_digest") or "").strip()
    if not archive_key or not payload_digest:
        raise ValueError("Event observation lacks immutable identity.")
    result = dict(row)
    result["load_identity"] = load_identity(archive_key, payload_digest)
    result["evidence_id"] = str(row.get("id") or "")
    result["provenance_class"] = "pit_observed"
    result["pit_eligible"] = True
    return result


def _normalize_cross_market(row: Mapping[str, Any]) -> dict[str, Any]:
    archive_key = str(row.get("archive_key") or "").strip()
    payload_digest = str(row.get("payload_digest") or "").strip()
    if not archive_key or not payload_digest:
        raise ValueError("Cross-market observation lacks immutable identity.")
    result = dict(row)
    result["load_identity"] = load_identity(archive_key, payload_digest)
    result["evidence_id"] = str(row.get("id") or "")
    result["provenance_class"] = "pit_observed"
    result["pit_eligible"] = True
    return result


async def _snapshot(d1: Any, snapshot_id: str) -> dict[str, Any] | None:
    value = await d1.prepare(
        """
        SELECT id,captured_at,symbol,capture_status,bid,ask,mid,spread,quote_time,
               quote_age_seconds,session_code,data_availability_json,event_observation_ids_json,
               latest_m1_id,latest_m5_id,latest_m15_id,latest_h1_id,latest_h4_id,latest_d1_id,
               snapshot_digest,archive_key
        FROM market_snapshots WHERE id=? LIMIT 1
        """
    ).bind(snapshot_id).first()
    return _row(value)


async def _decision_candles(d1: Any, *, as_of: datetime) -> list[dict[str, Any]]:
    m1_start = (as_of - timedelta(days=7)).isoformat()
    aggregate_start = (as_of - timedelta(days=45)).isoformat()
    cutoff = as_of.isoformat()
    m1_result = await d1.prepare(
        """
        SELECT * FROM twelve_data_decision_admitted_m1_v1
        WHERE open_time_utc>=? AND first_observed_at<=?
        ORDER BY open_time_utc,revision_index
        """
    ).bind(m1_start, cutoff).all()
    aggregate_result = await d1.prepare(
        """
        SELECT c.*
        FROM market_candles c
        WHERE c.source=? AND c.symbol=? AND c.timeframe<>'1m'
          AND c.open_time_utc>=? AND c.first_observed_at<=?
          AND EXISTS (
            SELECT 1 FROM market_snapshots s
            WHERE s.captured_at<=?
              AND c.id IN (
                s.latest_m5_id,s.latest_m15_id,s.latest_h1_id,s.latest_h4_id,s.latest_d1_id
              )
              AND json_extract(s.data_availability_json,'$.request_kind')='scheduled_capture'
              AND json_extract(s.data_availability_json,'$.request_ledger_status')='succeeded'
          )
        ORDER BY c.timeframe,c.open_time_utc,c.revision_index
        """
    ).bind(AGGREGATE_SOURCE, AIDY_SYMBOL, aggregate_start, cutoff, cutoff).all()
    return _dedupe_candles(_results(m1_result) + _results(aggregate_result))


async def _event_rows(d1: Any, *, snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    ids = _json_list(
        snapshot.get("event_observation_ids_json"), name="snapshot.event_observation_ids_json"
    )
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    result = await d1.prepare(
        f"""
        SELECT id,source,external_id,event_type,published_at,first_observed_at,
               revision_index,headline,structured_data_json,payload_digest,archive_key
        FROM market_event_observations
        WHERE id IN ({placeholders})
        ORDER BY first_observed_at,source,external_id
        """
    ).bind(*ids).all()
    return [_normalize_event(row) for row in _results(result)]


async def _cross_market_rows(d1: Any, *, as_of: datetime) -> list[dict[str, Any]]:
    result = await d1.prepare(
        """
        SELECT id,source,series_id,observation_date,value,unit,source_url,
               source_document_digest,first_observed_at,revision_index,payload_digest,archive_key
        FROM cross_market_observations
        WHERE first_observed_at<=? AND observation_date<=?
        ORDER BY series_id,observation_date,first_observed_at,revision_index
        """
    ).bind(as_of.isoformat(), as_of.date().isoformat()).all()
    return [_normalize_cross_market(row) for row in _results(result)]


async def _research_ledger_rows(d1: Any) -> list[dict[str, Any]]:
    result = await d1.prepare(
        """
        SELECT sequence,record_digest,previous_digest,ledger_version,record_type,
               recorded_at_utc,code_head_sha,initiated_by,payload_json
        FROM research_evidence_ledger
        ORDER BY sequence
        """
    ).all()
    return _results(result)


def _known_none_signal_state(as_of: datetime) -> dict[str, Any]:
    return {
        "state": "none",
        "lifecycle_version": PRIVATE_FORWARD_SIGNAL_STATE_VERSION,
        "as_of_utc": as_of.isoformat(),
        "last_decision_id": None,
        "active_signals": [],
    }


def _architecture_extensions(
    *,
    as_of: datetime,
    candle_rows: list[dict[str, Any]],
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    structural = build_market_structure_context(as_of=as_of, official_schedule_records=())
    if not verify_market_structure_context(structural):
        raise RuntimeError("Private-forward market-structure context failed verification.")
    price_structure = build_price_structure_packet(
        as_of=as_of,
        symbol=AIDY_SYMBOL,
        candle_rows=candle_rows,
        mode="pit",
        snapshot=snapshot,
    )
    if not verify_price_structure_packet(price_structure):
        raise RuntimeError("Private-forward price/liquidity structure failed verification.")
    rates = build_rates_macro_state([], as_of=as_of)
    if not verify_rates_macro_state(rates):
        raise RuntimeError("Private-forward rates/macro unknown state failed verification.")
    cme = build_contract_roll_state(as_of=as_of, daily_records=(), calendar_records=())
    if not verify_contract_roll_state(cme):
        raise RuntimeError("Private-forward CME unknown state failed verification.")
    volatility = build_volatility_state(
        as_of=as_of,
        gvz_record=None,
        daily_candles=candle_rows,
        intraday_candles=candle_rows,
        mode="pit",
    )
    if not verify_volatility_state(volatility):
        raise RuntimeError("Private-forward volatility state failed verification.")

    event_intelligence = {
        "event_intelligence_version": EVENT_INTELLIGENCE_VERSION,
        "state": "unknown_live_day29_schedule_source_not_operationally_ingested",
        "decision_input_allowed": False,
        "predictive_edge_claimed": False,
        "trading_gate_created": False,
        "unknown_stays_unknown": True,
    }
    result: dict[str, Any] = {
        "extension_version": ARCHITECTURE_V2_EXTENSION_VERSION,
        "as_of_utc": as_of.isoformat(),
        "private_forward_only": True,
        "staged_research_promoted_as_directional_edge": False,
        "market_structure_context": structural,
        "price_structure_context": price_structure,
        "rates_macro_context": rates,
        "event_intelligence": event_intelligence,
        "cme_contract_context": cme,
        "volatility_state": volatility,
        "live_source_availability": {
            "market_structure": "derived_live",
            "price_liquidity_structure": "derived_live_from_admitted_twelve_candles",
            "rates_macro_vintages": "unknown_no_operational_day28_vintage_feed",
            "tiered_macro_events": "unknown_no_operational_day29_schedule_feed",
            "cme_contract_state": "unknown_no_operational_day30_bulletin_feed",
            "gvz_implied_volatility": "unknown_no_operational_day31_gvz_feed",
            "realized_volatility": "derived_when_candle_history_is_sufficient",
        },
        "unknown_stays_unknown": True,
        "predictive_edge_claimed_by_adapter": False,
    }
    result["extension_digest"] = digest(result)
    return result


def _hypothesis(setup: Mapping[str, Any]) -> tuple[str, str | None]:
    candidates = setup.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        return "none", None
    candidate = candidates[0]
    if not isinstance(candidate, Mapping):
        return "none", None
    direction = str(candidate.get("direction") or "")
    family = str(candidate.get("family") or "").strip()
    if direction not in {"long", "short"} or not family:
        return "none", None
    return direction, family


def _episode_id(
    *, as_of: datetime, context: Mapping[str, Any], regime: Mapping[str, Any], setup: Mapping[str, Any]
) -> str:
    session = context.get("session")
    session = session if isinstance(session, Mapping) else {}
    identity = {
        "kind": "private_forward_market_episode_v1",
        "date": as_of.date().isoformat(),
        "session": session.get("computed_session_code"),
        "regime": regime.get("compound_regime_key"),
        "setup_detector_state": setup.get("detector_state"),
        "candidate_setup_ids": sorted(str(value) for value in setup.get("candidate_setup_ids") or []),
        "candidate_directions": sorted(str(value) for value in setup.get("candidate_directions") or []),
    }
    return f"pf_episode_{digest(identity)[:32]}"


async def build_private_forward_decision_inputs(
    *, d1: Any, snapshot_id: str
) -> dict[str, Any]:
    """Reconstruct the exact admitted Twelve snapshot into Architecture V2 inputs.

    HistData cases are deliberately not supplied. Until a ledger-proven semantic
    equivalence exists, the retrieval layer must return an explicit
    NO_COMPARABLE_CASE rather than inherit a cross-source scale.
    """

    raw_snapshot = await _snapshot(d1, snapshot_id)
    if raw_snapshot is None:
        raise KeyError(f"Unknown market snapshot: {snapshot_id}")
    snapshot = normalize_snapshot_row(raw_snapshot)
    as_of = _utc(str(snapshot["captured_at"]), name="snapshot.captured_at")
    candles = await _decision_candles(d1, as_of=as_of)
    events = await _event_rows(d1, snapshot=raw_snapshot)
    cross_market = await _cross_market_rows(d1, as_of=as_of)
    ledger = await _research_ledger_rows(d1)

    feature = build_semantic_feature_packet(
        as_of=as_of,
        symbol=AIDY_SYMBOL,
        candle_rows=candles,
        mode="pit",
        snapshot=snapshot,
    )
    availability = snapshot.get("data_availability")
    availability = availability if isinstance(availability, Mapping) else {}
    macro_evidence_state = (
        "known"
        if availability.get("external_events") == "point_in_time_linked"
        else "unknown"
    )
    context = build_semantic_context_packet(
        as_of=as_of,
        symbol=AIDY_SYMBOL,
        feature_packet=feature,
        event_rows=events,
        macro_evidence_state=macro_evidence_state,
        cross_market_rows=cross_market,
        aidy_signal_state=_known_none_signal_state(as_of),
    )
    extensions = _architecture_extensions(
        as_of=as_of,
        candle_rows=candles,
        snapshot=snapshot,
    )
    context = dict(context)
    context.pop("context_hash", None)
    versions = dict(context.get("source_contract_versions") or {})
    versions.update(
        {
            "market_structure_context": MARKET_STRUCTURE_CONTEXT_VERSION,
            "price_structure": PRICE_STRUCTURE_VERSION,
            "rates_decomposition": RATES_DECOMPOSITION_VERSION,
            "macro_revision_intelligence": REVISION_INTELLIGENCE_VERSION,
            "macro_event_intelligence": EVENT_INTELLIGENCE_VERSION,
            "cme_contract_intelligence": CME_CONTRACT_INTELLIGENCE_VERSION,
            "volatility_intelligence": VOLATILITY_INTELLIGENCE_VERSION,
            "private_forward_context_adapter": PRIVATE_FORWARD_CONTEXT_ADAPTER_VERSION,
        }
    )
    context["source_contract_versions"] = versions
    context["architecture_v2_extensions"] = extensions
    context["context_hash"] = compute_context_hash(context)

    regime = classify_twelve_private_forward_regime(context)
    setup = detect_candidate_setups(context=context, regime=regime)
    case_input = build_semantic_pit_case_input(
        context=context,
        regime=regime,
        setup_detection=setup,
    )
    query = build_semantic_analogue_query(input_boundary=case_input)
    semantic_retrieval = retrieve_semantic_analogues_v2(
        query=query,
        candidate_cases=(),
        research_ledger_records=ledger,
    )
    retrieval = semantic_retrieval["base_retrieval"]
    evidence_report = build_evidence_report_v2(retrieval=retrieval)
    direction, family = _hypothesis(setup)
    quote = context.get("gold")
    quote = quote.get("quote_context") if isinstance(quote, Mapping) else {}

    aidy_state = {
        "state_version": PRIVATE_FORWARD_CONTEXT_ADAPTER_VERSION,
        "regime": regime,
        "setup": setup,
        "data_quality": context.get("data_quality"),
        "architecture_v2_extension_digest": extensions["extension_digest"],
        "liquidity_structure_digest": extensions["price_structure_context"][
            "structure_semantic_digest"
        ],
        "cross_source_analogue_permission": False,
    }
    invalidation_inputs = {
        "input_version": "aidy_private_forward_invalidation_inputs_v1",
        "context_hash": context["context_hash"],
        "current_mid": quote.get("mid") if isinstance(quote, Mapping) else None,
        "price_liquidity_structure_available": True,
        "price_structure_semantic_digest": extensions["price_structure_context"][
            "structure_semantic_digest"
        ],
        "machine_condition_paths_are_relative_to_current_context": True,
        "example_current_context_paths": [
            "$.gold.quote_context.mid",
            "$.architecture_v2_extensions.price_structure_context.structure.prior_day_breakout.state",
            "$.architecture_v2_extensions.price_structure_context.structure.swing_extreme_penetration_with_reversion.high_side.reverted",
        ],
        "unknown_stays_unknown": True,
    }

    return {
        "adapter_version": PRIVATE_FORWARD_CONTEXT_ADAPTER_VERSION,
        "snapshot_id": snapshot_id,
        "as_of_utc": as_of.isoformat(),
        "context": context,
        "regime": regime,
        "setup_detection": setup,
        "semantic_case_input": case_input,
        "semantic_retrieval": semantic_retrieval,
        "retrieval": retrieval,
        "evidence_report": evidence_report,
        "aidy_state": aidy_state,
        "hypothesis_direction": direction,
        "setup_family": family,
        "invalidation_inputs": invalidation_inputs,
        "episode_id": _episode_id(as_of=as_of, context=context, regime=regime, setup=setup),
        "retrieval_effective_n": int(evidence_report.get("effective_independent_n") or 0),
        "cross_source_analogue_permission": False,
        "public_publication_enabled": False,
        "live_money_execution_allowed": False,
    }
