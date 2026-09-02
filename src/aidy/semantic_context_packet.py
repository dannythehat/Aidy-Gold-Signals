from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from aidy.context_packet import build_context_packet, compute_context_hash
from aidy.market_data_semantics import identity_from_feature_packet, verify_semantic_identity
from aidy.semantic_feature_packet import SEMANTIC_FEATURE_PACKET_VERSION

SEMANTIC_CONTEXT_PACKET_VERSION = "aidy_semantic_market_context_v1"


def build_semantic_context_packet(
    *,
    as_of: Any,
    symbol: str,
    feature_packet: Mapping[str, Any],
    event_rows: Iterable[Mapping[str, Any]],
    macro_evidence_state: str,
    cross_market_rows: Iterable[Mapping[str, Any]],
    aidy_signal_state: Mapping[str, Any] | None = None,
    quote_stale_after_seconds: int = 300,
    event_minutes_before: int = 60,
    event_minutes_after: int = 180,
) -> dict[str, Any]:
    if feature_packet.get("semantic_feature_packet_version") != SEMANTIC_FEATURE_PACKET_VERSION:
        raise ValueError("Twelve Data decision context requires semantic Gold feature packet v1")
    embedded = feature_packet.get("market_data_semantic_identity")
    if not isinstance(embedded, Mapping) or not verify_semantic_identity(embedded):
        raise ValueError("semantic Gold feature packet lacks a valid market-data identity")
    inferred = identity_from_feature_packet(feature_packet)
    if embedded.get("semantic_identity_digest") != inferred.get("semantic_identity_digest"):
        raise ValueError("embedded Gold semantic identity does not match source-link provenance")
    if feature_packet.get("market_data_semantic_identity_digest") != embedded.get(
        "semantic_identity_digest"
    ):
        raise ValueError("Gold semantic identity digest does not match embedded identity")

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
    packet = dict(packet)
    packet.pop("context_hash", None)
    packet["semantic_context_packet_version"] = SEMANTIC_CONTEXT_PACKET_VERSION
    packet["market_data_semantic_identity_digest"] = embedded["semantic_identity_digest"]
    packet["provenance"] = dict(packet["provenance"])
    packet["provenance"]["gold_market_data_semantic_identity"] = dict(embedded)
    packet["context_hash"] = compute_context_hash(packet)
    return packet
