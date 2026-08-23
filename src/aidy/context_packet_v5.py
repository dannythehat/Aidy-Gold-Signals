from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from aidy.context_packet import compute_context_hash
from aidy.context_packet_v4 import build_context_packet_v4

from aidy.macro_event_intelligence import (
    EVENT_INTELLIGENCE_VERSION,
    verify_event_intelligence_state,
)

CONTEXT_PACKET_VERSION_V5 = "aidy_market_context_v5_tiered_macro_events"


def build_context_packet_v5(
    *,
    as_of: datetime | str,
    symbol: str,
    feature_packet: Mapping[str, Any],
    price_structure_packet: Mapping[str, Any],
    rates_macro_state: Mapping[str, Any],
    event_intelligence_state: Mapping[str, Any],
    event_rows: Iterable[Mapping[str, Any]],
    macro_evidence_state: str,
    cross_market_rows: Iterable[Mapping[str, Any]],
    aidy_signal_state: Mapping[str, Any] | None = None,
    quote_stale_after_seconds: int = 300,
    official_schedule_records: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    if not verify_event_intelligence_state(event_intelligence_state):
        raise ValueError("Day 29 event-intelligence state digest or contract is invalid.")
    packet = build_context_packet_v4(
        as_of=as_of,
        symbol=symbol,
        feature_packet=feature_packet,
        price_structure_packet=price_structure_packet,
        rates_macro_state=rates_macro_state,
        event_rows=event_rows,
        macro_evidence_state=macro_evidence_state,
        cross_market_rows=cross_market_rows,
        aidy_signal_state=aidy_signal_state,
        quote_stale_after_seconds=quote_stale_after_seconds,
        official_schedule_records=official_schedule_records,
    )
    if str(event_intelligence_state.get("as_of_utc") or "") != str(packet["as_of_utc"]):
        raise ValueError("Day 29 event intelligence and context packet must share the same T.")
    result = dict(packet)
    result.pop("context_hash", None)
    result["context_packet_version"] = CONTEXT_PACKET_VERSION_V5
    versions = dict(result.get("source_contract_versions") or {})
    versions["macro_event_intelligence"] = EVENT_INTELLIGENCE_VERSION
    result["source_contract_versions"] = versions
    result["event_intelligence"] = dict(event_intelligence_state)
    result["legacy_event_risk_superseded_by"] = "event_intelligence"
    result["context_hash"] = compute_context_hash(result)
    return result


def verify_context_hash_v5(packet: Mapping[str, Any]) -> bool:
    if packet.get("context_packet_version") != CONTEXT_PACKET_VERSION_V5:
        return False
    state = packet.get("event_intelligence")
    if not isinstance(state, Mapping) or not verify_event_intelligence_state(state):
        return False
    supplied = str(packet.get("context_hash") or "")
    return bool(supplied) and supplied == compute_context_hash(packet)
