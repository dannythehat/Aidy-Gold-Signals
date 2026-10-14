"""Day14 isolated deterministic XAUUSD order lifecycle, never a live order.

A source-pinned Day12 QuoteTape and Day11 BrokerProfile feed the historical
market/limit simulator. No lookahead: quotes at or before closed signal are
ineligible. Orders cannot fill after expiry. Does not model stop/target paths.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Literal

from aidy.strategy_lab_bidask_execution import QuoteTape
from aidy.strategy_lab_broker_profile import BrokerProfile, qualify_broker_profile

OrderKind = Literal["market", "limit"]
Action = Literal["buy", "sell"]


def _canonical(data: dict) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("requires aware UTC timestamp")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class OrderIntent:
    strategy_version_id: str
    signal_id: str
    action: Action
    kind: OrderKind
    lots: Decimal
    signal_closed_at_utc: datetime
    expires_at_utc: datetime
    limit_price: Decimal | None = None


@dataclass(frozen=True, slots=True)
class OrderEvent:
    id: str
    order_id: str
    sequence: int
    state: str
    at_utc: datetime
    quote_index: int | None
    price: Decimal | None
    reason: str

    def to_wire(self) -> dict:
        return {"id": self.id, "order_id": self.order_id,
                "sequence": self.sequence, "state": self.state,
                "at_utc": _iso(self.at_utc), "quote_index": self.quote_index,
                "price": None if self.price is None else str(self.price),
                "reason": self.reason}


@dataclass(frozen=True, slots=True)
class OrderOutcome:
    order_id: str
    state: str
    action: Action
    kind: OrderKind
    lots: Decimal
    events: tuple[OrderEvent, ...]
    quote_snapshot_sha256: str
    broker_profile_sha256: str
    broker_attested: bool = False

    def to_json(self) -> str:
        return _canonical({
            "order_id": self.order_id, "state": self.state,
            "action": self.action, "kind": self.kind,
            "lots": str(self.lots),
            "events": [x.to_wire() for x in self.events],
            "quote_snapshot_sha256": self.quote_snapshot_sha256,
            "broker_profile_sha256": self.broker_profile_sha256,
            "broker_attested": self.broker_attested,
        })


def simulate_order(
    profile: BrokerProfile,
    source_bytes: bytes,
    tape: QuoteTape,
    intent: OrderIntent,
) -> OrderOutcome:
    clean_profile = BrokerProfile.from_json(profile.to_json())
    qualified = qualify_broker_profile(clean_profile, source_bytes)
    if qualified.state not in ("ILLUSTRATIVE_SOURCE_MATCHED",
                               "BROKER_EVIDENCE_MATCHED_UNATTESTED"):
        raise ValueError("unmatched broker evidence")
    verified_tape = QuoteTape.from_snapshot(tape.snapshot_bytes,
                                         expected_sha256=tape.snapshot_sha256)
    if verified_tape != tape:
        raise ValueError("tampered quote tape")
    if not intent.strategy_version_id.startswith("aidy-v1-"):
        raise ValueError("strategy must have a frozen version identity")
    if not intent.signal_id or not intent.signal_id.strip():
        raise ValueError("signal identity missing")
    if intent.action not in ("buy", "sell") or intent.kind not in ("market", "limit"):
        raise ValueError("unsupported action/order kind")
    if not clean_profile.is_valid_lot(intent.lots):
        raise ValueError("lot violates broker grid")
    closed = _utc(intent.signal_closed_at_utc)
    expires = _utc(intent.expires_at_utc)
    if expires <= closed or expires - closed > timedelta(days=7):
        raise ValueError("invalid expiry interval (maximum 7 days)")
    if intent.kind == "market" and intent.limit_price is not None:
        raise ValueError("market order must not contain a limit")
    if intent.kind == "limit" and (
        not isinstance(intent.limit_price, Decimal) or not intent.limit_price.is_finite()
        or intent.limit_price <= 0 or
        intent.limit_price % clean_profile.contract.tick_size != 0
    ):
        raise ValueError("limit must be positive exact tick-aligned Decimal")
    payload = {
        "schema": "aidy.order_intent.v1",
        "strategy_version_id": intent.strategy_version_id,
        "signal_id": intent.signal_id, "action": intent.action,
        "kind": intent.kind, "lots": str(intent.lots),
        "signal_closed_at_utc": _iso(closed),
        "expires_at_utc": _iso(expires),
        "limit_price": None if intent.limit_price is None else str(intent.limit_price),
        "quotes": tape.snapshot_sha256,
        "broker": qualified.profile_sha256,
    }
    oid = sha256(_canonical(payload).encode()).hexdigest()
    events: list[OrderEvent] = []

    def event(state: str, at: datetime, index: int | None,
              price: Decimal | None, reason: str) -> None:
        idx = len(events)
        basis = {"order_id":oid,"index":idx,"state":state,"at":_iso(at),
                 "quote_index":index,"price":str(price),"reason":reason}
        events.append(OrderEvent(sha256(_canonical(basis).encode()).hexdigest(),
                                 oid, idx, state, at, index, price, reason))

    event("created", closed, None, None, "closed_signal")
    event("pending", closed, None, None, "await_future_quote")
    for quote in tape.quotes:
        if quote.at_utc <= closed:
            continue
        if quote.at_utc > expires:
            break
        market_price = quote.ask if intent.action == "buy" else quote.bid
        if intent.kind == "market" or (
            (intent.action == "buy" and market_price <= intent.limit_price)
            or (intent.action == "sell" and market_price >= intent.limit_price)
        ):
            event("filled", quote.at_utc, quote.index, market_price,
                  "first_eligible_quote" if intent.kind == "market" else "limit_marketable")
            return OrderOutcome(oid,"filled",intent.action,intent.kind,intent.lots,
                                tuple(events),tape.snapshot_sha256,
                                qualified.profile_sha256 or "")
    event("expired", expires, None, None, "no_eligible_quote_before_expiry")
    return OrderOutcome(oid,"expired",intent.action,intent.kind,intent.lots,
                        tuple(events),tape.snapshot_sha256,
                        qualified.profile_sha256 or "")
