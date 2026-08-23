from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from aidy.context_packet import compute_context_hash
from aidy.context_packet_v6 import build_context_packet_v6
from aidy.volatility_intelligence import (
    VOLATILITY_INTELLIGENCE_VERSION,
    verify_volatility_state,
)

CONTEXT_PACKET_VERSION_V7 = "aidy_market_context_v7_volatility_state"


def build_context_packet_v7(
    *,
    as_of: datetime | str,
    symbol: str,
    feature_packet: Mapping[str, Any],
    price_structure_packet: Mapping[str, Any],
    rates_macro_state: Mapping[str, Any],
    event_intelligence_state: Mapping[str, Any],
    cme_contract_state: Mapping[str, Any],
    volatility_state: Mapping[str, Any],
    event_rows: Iterable[Mapping[str, Any]],
    macro_evidence_state: str,
    cross_market_rows: Iterable[Mapping[str, Any]],
    aidy_signal_state: Mapping[str, Any] | None = None,
    quote_stale_after_seconds: int = 300,
    official_schedule_records: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    if not verify_volatility_state(volatility_state):
        raise ValueError("Day 31 volatility state digest or contract is invalid.")
    if volatility_state.get("decision_input_allowed") is not True:
        raise ValueError("Retrospective Day 31 volatility research cannot enter a context packet.")
    packet = build_context_packet_v6(
        as_of=as_of,
        symbol=symbol,
        feature_packet=feature_packet,
        price_structure_packet=price_structure_packet,
        rates_macro_state=rates_macro_state,
        event_intelligence_state=event_intelligence_state,
        cme_contract_state=cme_contract_state,
        event_rows=event_rows,
        macro_evidence_state=macro_evidence_state,
        cross_market_rows=cross_market_rows,
        aidy_signal_state=aidy_signal_state,
        quote_stale_after_seconds=quote_stale_after_seconds,
        official_schedule_records=official_schedule_records,
    )
    if str(volatility_state.get("as_of_utc") or "") != str(packet["as_of_utc"]):
        raise ValueError("Day 31 volatility state and context packet must share the same T.")
    result = dict(packet)
    result.pop("context_hash", None)
    result["context_packet_version"] = CONTEXT_PACKET_VERSION_V7
    versions = dict(result.get("source_contract_versions") or {})
    versions["volatility_intelligence"] = VOLATILITY_INTELLIGENCE_VERSION
    result["source_contract_versions"] = versions
    result["volatility_state"] = dict(volatility_state)
    result["context_hash"] = compute_context_hash(result)
    return result


def verify_context_hash_v7(packet: Mapping[str, Any]) -> bool:
    if packet.get("context_packet_version") != CONTEXT_PACKET_VERSION_V7:
        return False
    state = packet.get("volatility_state")
    if not isinstance(state, Mapping) or not verify_volatility_state(state):
        return False
    if state.get("decision_input_allowed") is not True:
        return False
    supplied = str(packet.get("context_hash") or "")
    return bool(supplied) and supplied == compute_context_hash(packet)
