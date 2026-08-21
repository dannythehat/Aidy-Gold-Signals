from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from aidy.context_packet import build_context_packet, compute_context_hash
from aidy.market_structure_context import (
    MARKET_STRUCTURE_CONTEXT_VERSION,
    build_market_structure_context,
    verify_market_structure_context,
)

CONTEXT_PACKET_VERSION_V2 = "aidy_market_context_v2_structural_calendar"


def build_context_packet_v2(
    *,
    as_of: datetime | str,
    symbol: str,
    feature_packet: Mapping[str, Any],
    event_rows: Iterable[Mapping[str, Any]],
    macro_evidence_state: str,
    cross_market_rows: Iterable[Mapping[str, Any]],
    aidy_signal_state: Mapping[str, Any] | None = None,
    quote_stale_after_seconds: int = 300,
    event_minutes_before: int = 60,
    event_minutes_after: int = 180,
    official_schedule_records: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build the accepted PIT packet, then add deterministic Day 25 structure.

    The Day 0-24 builder is deliberately left untouched. This wrapper preserves
    all accepted validation and adds an objective structural/calendar layer.
    """

    packet = build_context_packet(
        as_of=as_of,
        symbol=symbol,
        feature_packet=feature_packet,
        event_rows=event_rows,
        macro_evidence_state=macro_evidence_state,
        cross_market_rows=cross_market_rows,
        aidy_signal_state=aidy_signal_state,
        quote_stale_after_seconds=quote_stale_after_seconds,
        event_minutes_before=event_minutes_before,
        event_minutes_after=event_minutes_after,
    )
    structural = build_market_structure_context(
        as_of=packet["as_of_utc"],
        official_schedule_records=official_schedule_records,
    )
    if not verify_market_structure_context(structural):
        raise ValueError("Day 25 market-structure context digest does not match contents.")

    result = dict(packet)
    result.pop("context_hash", None)
    result["context_packet_version"] = CONTEXT_PACKET_VERSION_V2
    versions = dict(result.get("source_contract_versions") or {})
    versions["market_structure_context"] = MARKET_STRUCTURE_CONTEXT_VERSION
    result["source_contract_versions"] = versions
    result["structural_context"] = structural
    result["context_hash"] = compute_context_hash(result)
    return result


def verify_context_hash_v2(packet: Mapping[str, Any]) -> bool:
    if packet.get("context_packet_version") != CONTEXT_PACKET_VERSION_V2:
        return False
    structural = packet.get("structural_context")
    if not isinstance(structural, Mapping) or not verify_market_structure_context(structural):
        return False
    supplied = str(packet.get("context_hash") or "")
    return bool(supplied) and supplied == compute_context_hash(packet)
