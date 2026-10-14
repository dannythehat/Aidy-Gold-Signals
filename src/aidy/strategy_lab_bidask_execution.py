"""B03 Day12: deterministic, source-pinned bid/ask next-quote research fills.

Research only. Requires a Day11 source-matched profile and an immutable quote
snapshot. Not a live broker, stop-order, intrabar, cost or P&L ledger engine.
"""
from __future__ import annotations

import bisect
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy.strategy_lab_broker_profile import BrokerProfile, qualify_broker_profile

TAPE_VERSION = "aidy.quote_tape.v1"
MAX_TAPE_BYTES = 20_000_000
MAX_QUOTES = 100_000
HASH = re.compile(r"^[0-9a-f]{64}$")
SOURCE_CLASSES = frozenset({"internal_fixture", "histdata_retrospective_bid_ask"})
DECIMAL_ZERO = Decimal(0)


def _utc_iso(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("quote timestamp must be ISO UTC with Z")
    try:
        instant = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("invalid quote UTC datetime") from exc
    if instant.tzinfo is None or instant.utcoffset() != timedelta(0):
        raise ValueError("quote timestamp is not UTC")
    return instant.astimezone(UTC)


def _closed_at(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("signal closed at must be an aware UTC instant")
    return value.astimezone(UTC)


def _decimal(value: Any, name: str, *, zero_ok: bool = False) -> Decimal:
    if isinstance(value, (bool, float)) or not isinstance(value, (str, int, Decimal)):
        raise ValueError(f"{name}: exact decimal string required")
    try:
        number = Decimal(str(value))
    except (ValueError, InvalidOperation) as exc:
        raise ValueError(f"{name}: invalid number") from exc
    if not number.is_finite() or number < 0 or (number == 0 and not zero_ok):
        raise ValueError(f"{name}: positive finite number required")
    return number


def _hash(value: Any, name: str) -> str:
    if not isinstance(value, str) or HASH.fullmatch(value) is None:
        raise ValueError(f"{name}: SHA256 hex required")
    return value


def _no_duplicates(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"duplicate quote field: {key}")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class BidAskQuote:
    at_utc: datetime
    bid: Decimal
    ask: Decimal
    index: int

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid


@dataclass(frozen=True, slots=True)
class QuoteTape:
    quotes: tuple[BidAskQuote, ...]
    snapshot_sha256: str
    source_archive_sha256: str
    source_class: str
    symbol: str
    source_clock: str
    source_identity: str
    snapshot_bytes: bytes

    @classmethod
    def from_snapshot(cls, raw: bytes, *, expected_sha256: str) -> QuoteTape:
        if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_TAPE_BYTES:
            raise ValueError("snapshot must be nonempty, bounded original bytes")
        _hash(expected_sha256, "expected_sha256")
        digest = sha256(raw).hexdigest()
        if digest != expected_sha256:
            raise ValueError("snapshot SHA256 mismatch")
        try:
            wire = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates,
                              parse_constant=lambda _: (_ for _ in ()).throw(
                                  ValueError("nonfinite source JSON")
                              ))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid quote snapshot JSON") from exc
        if not isinstance(wire, dict) or set(wire) != {
            "schema_version", "source_class", "symbol", "source_clock",
            "source_archive_sha256", "source_identity", "quotes",
        }:
            raise ValueError("unexpected quote snapshot schema")
        if wire["schema_version"] != TAPE_VERSION:
            raise ValueError("unsupported quote snapshot version")
        if wire["source_class"] not in SOURCE_CLASSES:
            raise ValueError("quote class must be explicit")
        if wire["symbol"] != "XAUUSD":
            raise ValueError("only XAUUSD quotes supported")
        source_clock = wire["source_clock"]
        if source_clock not in ("UTC", "EST_FIXED_UTC_MINUS_05"):
            raise ValueError("quote clock is not independently defined")
        origin = wire["source_identity"]
        if not isinstance(origin, str) or not origin.strip() or origin.strip() != origin:
            raise ValueError("source identity required")
        archive = _hash(wire["source_archive_sha256"], "source_archive_sha256")
        if not isinstance(wire["quotes"], list) or not 1 <= len(wire["quotes"]) <= MAX_QUOTES:
            raise ValueError("snapshot quote count outside safety bounds")
        quotes = []
        previous: datetime | None = None
        for i, item in enumerate(wire["quotes"]):
            if not isinstance(item, dict) or set(item) != {"time_utc", "bid", "ask"}:
                raise ValueError("missing or unexpected quote fields")
            at = _utc_iso(item["time_utc"])
            bid = _decimal(item["bid"], "bid")
            ask = _decimal(item["ask"], "ask")
            if ask < bid:
                raise ValueError("crossed quote: ask below bid")
            if previous is not None and at <= previous:
                raise ValueError("quotes must be strictly ordered; source anomalies need separate qualification")
            quotes.append(BidAskQuote(at, bid, ask, i))
            previous = at
        return cls(tuple(quotes), digest, archive, wire["source_class"], "XAUUSD",
                   source_clock, origin, raw)


@dataclass(frozen=True, slots=True)
class SpreadScenario:
    """Observed or deterministic adverse widening by N broker ticks PER side."""

    extra_ticks_per_side: int = 0

    def validate(self) -> None:
        if type(self.extra_ticks_per_side) is not int or not 0 <= self.extra_ticks_per_side <= 10000:
            raise ValueError("extra_ticks_per_side must be nonnegative integer <=10000")


@dataclass(frozen=True, slots=True)
class SideFill:
    action: str
    position_direction: str
    transaction_side: str
    signal_closed_at_utc: datetime
    filled_at_utc: datetime
    quote_index: int
    base_bid: Decimal
    base_ask: Decimal
    effective_bid: Decimal
    effective_ask: Decimal
    fill_price: Decimal
    observed_spread: Decimal
    effective_spread: Decimal
    quote_snapshot_sha256: str
    broker_profile_sha256: str
    derived_from_real_broker: bool = False


@dataclass(frozen=True, slots=True)
class ResearchRoundTrip:
    entry: SideFill
    exit: SideFill
    direction: str
    quantity_lots: Decimal
    gross_quote_side_usd: Decimal
    gross_ticks: Decimal
    observed_quote_snapshot_sha256: str
    quote_source_class: str
    broker_source_state: str
    scenario_extra_ticks_per_side: int
    costs_included: bool = False
    real_broker_terms_qualified: bool = False

    def to_wire(self) -> dict[str, Any]:
        def plain(value: Any) -> Any:
            if isinstance(value, Decimal):
                return format(value, "f")
            if isinstance(value, datetime):
                return value.isoformat().replace("+00:00", "Z")
            if isinstance(value, dict):
                return {key: plain(item) for key, item in value.items()}
            return value
        return plain(asdict(self))

    def to_json(self) -> str:
        return json.dumps(self.to_wire(), sort_keys=True, separators=(",", ":"))


def _quote_after(tape: QuoteTape, at_utc: datetime, max_lag_seconds: int) -> BidAskQuote:
    if type(max_lag_seconds) is not int or not 1 <= max_lag_seconds <= 300:
        raise ValueError("max_lag_seconds must be integer 1..300")
    at = _closed_at(at_utc)
    # Signals only know a closed bar's data. Quotes at the close timestamp
    # are deliberately excluded, preventing same-timestamp lookahead.
    times = [quote.at_utc for quote in tape.quotes]
    pos = bisect.bisect_right(times, at)
    if pos == len(times):
        raise ValueError("no quote after closed signal")
    quote = tape.quotes[pos]
    if quote.at_utc - at > timedelta(seconds=max_lag_seconds):
        raise ValueError("next quote stale/unavailable: session or market gap")
    return quote


def _fill(tape: QuoteTape, profile: BrokerProfile, signal: datetime, *,
          action: str, direction: str, scenario: SpreadScenario,
          max_lag_seconds: int, profile_sha256: str) -> SideFill:
    quote = _quote_after(tape, signal, max_lag_seconds)
    # An adverse stress is transparent, never relabelled an actual quote.
    offset = Decimal(scenario.extra_ticks_per_side) * profile.contract.tick_size
    bid, ask = quote.bid - offset, quote.ask + offset
    if bid <= 0:
        raise ValueError("stress scenario creates non-positive bid")
    transaction_side = "buy" if (
        (action == "entry" and direction == "long") or
        (action == "exit" and direction == "short")
    ) else "sell"
    executed_price = ask if transaction_side == "buy" else bid
    return SideFill(
        action, direction, transaction_side, _closed_at(signal), quote.at_utc,
        quote.index, quote.bid, quote.ask, bid, ask, executed_price,
        quote.spread, ask - bid, tape.snapshot_sha256, profile_sha256,
    )


def research_round_trip(
    profile: BrokerProfile,
    broker_source_bytes: bytes,
    quote_tape: QuoteTape,
    *, direction: str,
    lots: str,
    entry_signal_closed_at_utc: datetime,
    exit_signal_closed_at_utc: datetime,
    scenario: SpreadScenario | None = None,
    max_lag_seconds: int = 60,
) -> ResearchRoundTrip:
    """Emit quote-side-only long/short research fills, never a live order.

    Source-attestation states remain explicitly unqualified: a matching JSON
    labelled as a terminal export is NOT an independent broker source check.
    """
    validated = BrokerProfile.from_json(profile.to_json())
    qualification = qualify_broker_profile(validated, broker_source_bytes)
    if qualification.state not in ("ILLUSTRATIVE_SOURCE_MATCHED",
                                   "BROKER_EVIDENCE_MATCHED_UNATTESTED"):
        raise ValueError("broker profile evidence not source-matched or costs incomplete")
    if not isinstance(quote_tape, QuoteTape):
        raise ValueError("expected frozen QuoteTape")
    # Recheck quote data after dataclass construction so external callers cannot
    # bypass the source parser by manually constructing trusted-looking objects.
    # Verify original bytes and parsed values, not merely a user-supplied hash.
    # Manual dataclass reconstruction cannot forge a matching snapshot.
    if quote_tape != QuoteTape.from_snapshot(
        quote_tape.snapshot_bytes, expected_sha256=quote_tape.snapshot_sha256
    ):
        raise ValueError("quote tape differs from pinned original source bytes")
    if direction not in ("long", "short"):
        raise ValueError("direction must be long or short")
    if not validated.is_valid_lot(lots):
        raise ValueError("invalid lot volume for broker contract")
    qty = _decimal(lots, "lots")
    scenario = scenario or SpreadScenario()
    scenario.validate()
    entry_closed = _closed_at(entry_signal_closed_at_utc)
    exit_closed = _closed_at(exit_signal_closed_at_utc)
    if exit_closed <= entry_closed:
        raise ValueError("exit signal cannot precede entry signal")
    fingerprint = qualification.profile_sha256
    if fingerprint is None:
        raise ValueError("broker profile fingerprint missing")
    entry = _fill(quote_tape, validated, entry_closed, action="entry",
                  direction=direction, scenario=scenario,
                  max_lag_seconds=max_lag_seconds, profile_sha256=fingerprint)
    if exit_closed < entry.filled_at_utc:
        raise ValueError("exit signal precedes entry fill")
    exit_fill = _fill(quote_tape, validated, exit_closed, action="exit",
                      direction=direction, scenario=scenario,
                      max_lag_seconds=max_lag_seconds, profile_sha256=fingerprint)
    if exit_fill.quote_index <= entry.quote_index:
        raise ValueError("exit fill must use a later independent quote")
    sign = Decimal(1) if direction == "long" else Decimal(-1)
    move = (exit_fill.fill_price - entry.fill_price) * sign
    gross = move * validated.contract.contract_ounces_per_lot * qty
    ticks = move / validated.contract.tick_size
    return ResearchRoundTrip(
        entry, exit_fill, direction, qty, gross, ticks,
        quote_tape.snapshot_sha256, quote_tape.source_class,
        qualification.state, scenario.extra_ticks_per_side,
    )
