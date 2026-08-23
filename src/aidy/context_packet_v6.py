from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from aidy.cme_contract_intelligence import (
    CME_CONTRACT_INTELLIGENCE_VERSION,
    verify_contract_roll_state,
)
from aidy.context_packet import compute_context_hash
from aidy.context_packet_v5 import build_context_packet_v5

CONTEXT_PACKET_VERSION_V6 = "aidy_market_context_v6_cme_contract_state"


def build_context_packet_v6(
    *,
    as_of: datetime | str,
    symbol: str,
    feature_packet: Mapping[str, Any],
    price_structure_packet: Mapping[str, Any],
    rates_macro_state: Mapping[str, Any],
    event_intelligence_state: Mapping[str, Any],
    cme_contract_state: Mapping[str, Any],
    event_rows: Iterable[Mapping[str, Any]],
    macro_evidence_state: str,
    cross_market_rows: Iterable[Mapping[str, Any]],
    aidy_signal_state: Mapping[str, Any] | None = None,
    quote_stale_after_seconds: int = 300,
    official_schedule_records: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    if not verify_contract_roll_state(cme_contract_state):
        raise ValueError("Day 30 CME contract state digest or contract is invalid.")
    packet = build_context_packet_v5(
        as_of=as_of,
        symbol=symbol,
        feature_packet=feature_packet,
        price_structure_packet=price_structure_packet,
        rates_macro_state=rates_macro_state,
        event_intelligence_state=event_intelligence_state,
        event_rows=event_rows,
        macro_evidence_state=macro_evidence_state,
        cross_market_rows=cross_market_rows,
        aidy_signal_state=aidy_signal_state,
        quote_stale_after_seconds=quote_stale_after_seconds,
        official_schedule_records=official_schedule_records,
    )
    if str(cme_contract_state.get("as_of_utc") or "") != str(packet["as_of_utc"]):
        raise ValueError("Day 30 CME contract state and context packet must share the same T.")
    result = dict(packet)
    result.pop("context_hash", None)
    result["context_packet_version"] = CONTEXT_PACKET_VERSION_V6
    versions = dict(result.get("source_contract_versions") or {})
    versions["cme_contract_intelligence"] = CME_CONTRACT_INTELLIGENCE_VERSION
    result["source_contract_versions"] = versions
    result["cme_contract_context"] = dict(cme_contract_state)
    result["context_hash"] = compute_context_hash(result)
    return result


def verify_context_hash_v6(packet: Mapping[str, Any]) -> bool:
    if packet.get("context_packet_version") != CONTEXT_PACKET_VERSION_V6:
        return False
    state = packet.get("cme_contract_context")
    if not isinstance(state, Mapping) or not verify_contract_roll_state(state):
        return False
    supplied = str(packet.get("context_hash") or "")
    return bool(supplied) and supplied == compute_context_hash(packet)
