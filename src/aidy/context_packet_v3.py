from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from aidy.context_packet import compute_context_hash
from aidy.context_packet_v2 import build_context_packet_v2
from aidy.price_structure_v2 import (
    FEED_HEALTH_VERSION,
    PRICE_STRUCTURE_VERSION,
    verify_price_structure_packet,
)

CONTEXT_PACKET_VERSION_V3 = "aidy_market_context_v3_price_structure_feed_health"


def build_context_packet_v3(
    *,
    as_of: datetime | str,
    symbol: str,
    feature_packet: Mapping[str, Any],
    price_structure_packet: Mapping[str, Any],
    event_rows: Iterable[Mapping[str, Any]],
    macro_evidence_state: str,
    cross_market_rows: Iterable[Mapping[str, Any]],
    aidy_signal_state: Mapping[str, Any] | None = None,
    quote_stale_after_seconds: int = 300,
    event_minutes_before: int = 60,
    event_minutes_after: int = 180,
    official_schedule_records: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Add verified Day-26 price structure to the accepted Day-25 context."""

    if not verify_price_structure_packet(price_structure_packet):
        raise ValueError("Day 26 price-structure packet digest does not match contents.")

    packet = build_context_packet_v2(
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
        official_schedule_records=official_schedule_records,
    )
    if str(price_structure_packet.get("as_of_utc") or "") != str(packet["as_of_utc"]):
        raise ValueError("Day 26 price structure and context packet must share the same T.")
    if price_structure_packet.get("symbol") != packet.get("symbol"):
        raise ValueError("Day 26 price structure and context packet symbols differ.")
    if price_structure_packet.get("mode") != "pit" or price_structure_packet.get("pit_eligible") is not True:
        raise ValueError("Live Day 26 context requires a PIT-eligible price-structure packet.")

    result = dict(packet)
    result.pop("context_hash", None)
    result["context_packet_version"] = CONTEXT_PACKET_VERSION_V3
    versions = dict(result.get("source_contract_versions") or {})
    versions["price_structure"] = PRICE_STRUCTURE_VERSION
    versions["feed_health"] = FEED_HEALTH_VERSION
    result["source_contract_versions"] = versions
    result["price_structure_context"] = dict(price_structure_packet)
    result["context_hash"] = compute_context_hash(result)
    return result


def verify_context_hash_v3(packet: Mapping[str, Any]) -> bool:
    if packet.get("context_packet_version") != CONTEXT_PACKET_VERSION_V3:
        return False
    structure = packet.get("price_structure_context")
    if not isinstance(structure, Mapping) or not verify_price_structure_packet(structure):
        return False
    supplied = str(packet.get("context_hash") or "")
    return bool(supplied) and supplied == compute_context_hash(packet)
