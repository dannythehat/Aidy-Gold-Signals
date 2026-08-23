from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from aidy.context_packet import compute_context_hash
from aidy.context_packet_v3 import build_context_packet_v3
from aidy.macro_vintages import (
    RATES_DECOMPOSITION_VERSION,
    REVISION_INTELLIGENCE_VERSION,
    verify_rates_macro_state,
)

CONTEXT_PACKET_VERSION_V4 = "aidy_market_context_v4_pit_vintaged_rates"


def build_context_packet_v4(
    *,
    as_of: datetime | str,
    symbol: str,
    feature_packet: Mapping[str, Any],
    price_structure_packet: Mapping[str, Any],
    rates_macro_state: Mapping[str, Any],
    event_rows: Iterable[Mapping[str, Any]],
    macro_evidence_state: str,
    cross_market_rows: Iterable[Mapping[str, Any]],
    aidy_signal_state: Mapping[str, Any] | None = None,
    quote_stale_after_seconds: int = 300,
    event_minutes_before: int = 60,
    event_minutes_after: int = 180,
    official_schedule_records: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    if not verify_rates_macro_state(rates_macro_state):
        raise ValueError("Day 28 rates/macro state digest or contract is invalid.")

    packet = build_context_packet_v3(
        as_of=as_of,
        symbol=symbol,
        feature_packet=feature_packet,
        price_structure_packet=price_structure_packet,
        event_rows=event_rows,
        macro_evidence_state=macro_evidence_state,
        cross_market_rows=cross_market_rows,
        aidy_signal_state=aidy_signal_state,
        quote_stale_after_seconds=quote_stale_after_seconds,
        event_minutes_before=event_minutes_before,
        event_minutes_after=event_minutes_after,
        official_schedule_records=official_schedule_records,
    )
    if str(rates_macro_state.get("as_of_utc") or "") != str(packet["as_of_utc"]):
        raise ValueError("Day 28 rates/macro state and context packet must share the same T.")
    if rates_macro_state.get("pit_reconstructable") is not True:
        raise ValueError("Day 28 context accepts PIT-reconstructable rates/macro state only.")
    if rates_macro_state.get("independent_confirmation_units") != 1:
        raise ValueError("Day 28 rates decomposition must count as exactly one evidence family.")
    if rates_macro_state.get("components_not_independent") is not True:
        raise ValueError("Day 28 context must label rates components as non-independent.")
    if rates_macro_state.get("directional_influence") != "provisional_unvalidated_j12":
        raise ValueError("Day 28 real-yield directional influence must remain provisional.")

    result = dict(packet)
    result.pop("context_hash", None)
    result["context_packet_version"] = CONTEXT_PACKET_VERSION_V4
    versions = dict(result.get("source_contract_versions") or {})
    versions["rates_decomposition"] = RATES_DECOMPOSITION_VERSION
    versions["macro_revision_intelligence"] = REVISION_INTELLIGENCE_VERSION
    result["source_contract_versions"] = versions
    result["rates_macro_context"] = dict(rates_macro_state)
    result["context_hash"] = compute_context_hash(result)
    return result


def verify_context_hash_v4(packet: Mapping[str, Any]) -> bool:
    if packet.get("context_packet_version") != CONTEXT_PACKET_VERSION_V4:
        return False
    rates = packet.get("rates_macro_context")
    if not isinstance(rates, Mapping) or not verify_rates_macro_state(rates):
        return False
    if rates.get("independent_confirmation_units") != 1:
        return False
    supplied = str(packet.get("context_hash") or "")
    return bool(supplied) and supplied == compute_context_hash(packet)
