from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from aidy.feature_engine import build_feature_packet
from aidy.historical_cases import _feature_digest
from aidy.market_data_semantics import identity_from_feature_packet

SEMANTIC_FEATURE_PACKET_VERSION = "aidy_semantic_gold_feature_packet_v1"


def build_semantic_feature_packet(
    *,
    as_of: Any,
    symbol: str,
    candle_rows: Iterable[Mapping[str, Any]],
    mode: str,
    snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    packet = build_feature_packet(
        as_of=as_of,
        symbol=symbol,
        candle_rows=candle_rows,
        mode=mode,
        snapshot=snapshot,
    )
    identity = identity_from_feature_packet(packet)
    packet = dict(packet)
    packet.pop("feature_packet_digest", None)
    packet["semantic_feature_packet_version"] = SEMANTIC_FEATURE_PACKET_VERSION
    packet["market_data_semantic_identity"] = identity
    packet["market_data_semantic_identity_digest"] = identity["semantic_identity_digest"]
    packet["feature_packet_digest"] = _feature_digest(packet)
    return packet
