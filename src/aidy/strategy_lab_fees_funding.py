"""B03 Day13: source-bound XAUUSD commission, slippage and overnight funding.

Separate research-only cash events; no broker attestation or external accounts.
Day12 price-side P&L already includes spread. Recalculate the frozen original
trade before calculating cash deductions. Never double-count spread stress.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256

from aidy.strategy_lab_bidask_execution import (
    QuoteTape,
    ResearchRoundTrip,
    SpreadScenario,
    research_round_trip,
)
from aidy.strategy_lab_broker_profile import (
    BrokerProfile,
    clock_server_time,
    qualify_broker_profile,
)

CENT = Decimal("0.01")


def _usd(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class CashEvent:
    kind: str
    at_utc: datetime
    usd: Decimal
    basis: str
    multiplier: int


@dataclass(frozen=True, slots=True)
class CostedRoundTrip:
    direction: str
    quantity_lots: Decimal
    entry_at_utc: datetime
    exit_at_utc: datetime
    quote_gross_usd: Decimal
    commission_usd: Decimal
    slippage_usd: Decimal
    funding_usd: Decimal
    net_usd: Decimal
    events: tuple[CashEvent, ...]
    quote_snapshot_sha256: str
    broker_profile_sha256: str
    original_round_trip_sha256: str
    broker_attested: bool = False
    provider_calendar_qualified: bool = False

    def to_wire(self) -> dict:
        def clean(v):
            if isinstance(v, Decimal):
                return format(v, "f")
            if isinstance(v, datetime):
                return v.astimezone(UTC).isoformat().replace("+00:00", "Z")
            if isinstance(v, dict):
                return {k: clean(item) for k, item in v.items()}
            if isinstance(v, (list, tuple)):
                return [clean(item) for item in v]
            return v
        return clean(asdict(self))

    def to_json(self) -> str:
        return json.dumps(self.to_wire(), sort_keys=True, separators=(",", ":"))


def _rollover_utc(profile: BrokerProfile, day: date) -> datetime:
    """Fail closed for DST duplicate/skipped local rollover times."""
    hhmm = profile.costs.rollover_hhmm
    if hhmm is None:
        raise ValueError("rollover HH:MM not supplied")
    hour, minute = (int(v) for v in hhmm.split(":"))
    anchor = datetime(day.year, day.month, day.day, 12, tzinfo=UTC)
    zone = clock_server_time(profile.clock, anchor).tzinfo
    if zone is None:
        raise ValueError("server timezone unavailable")
    local = datetime.combine(day, time(hour, minute), tzinfo=zone)
    zero = local.replace(fold=0).astimezone(UTC)
    one = local.replace(fold=1).astimezone(UTC)
    if zero != one:
        raise ValueError("ambiguous or missing DST rollover clock time")
    roundtrip = clock_server_time(profile.clock, zero)
    if (roundtrip.date(), roundtrip.hour, roundtrip.minute) != (day, hour, minute):
        raise ValueError("broker rollover clock could not be reconstructed")
    return zero


def _funding_events(profile: BrokerProfile, start: datetime, end: datetime,
                    direction: str, lots: Decimal) -> tuple[CashEvent, ...]:
    if start.utcoffset() != timedelta(0) or end.utcoffset() != timedelta(0):
        raise ValueError("entry and exit must use UTC timestamps")
    if end <= start or end - start > timedelta(days=31):
        raise ValueError("holding period must be positive and <=31 days")
    costs = profile.costs
    if any(x is None for x in (
        costs.rollover_hhmm, costs.triple_swap_weekday,
        costs.swap_long_usd_per_lot_per_rollover,
        costs.swap_short_usd_per_lot_per_rollover,
    )):
        raise ValueError("complete broker funding terms required")
    swap = (costs.swap_long_usd_per_lot_per_rollover if direction == "long"
            else costs.swap_short_usd_per_lot_per_rollover)
    assert swap is not None
    assert costs.triple_swap_weekday is not None
    first = clock_server_time(profile.clock, start).date() - timedelta(days=1)
    last = clock_server_time(profile.clock, end).date() + timedelta(days=1)
    events: list[CashEvent] = []
    current = first
    while current <= last:
        if current.weekday() < 5:
            instant = _rollover_utc(profile, current)
            if instant in (start, end):
                raise ValueError("rollover coincides with fill, broker ordering unknown")
            if start < instant < end:
                weight = 3 if current.weekday() == costs.triple_swap_weekday else 1
                amount = _usd(swap * lots * weight)
                events.append(CashEvent(
                    "swap_credit" if amount >= 0 else "swap_debit",
                    instant, amount, "declared_weekday_rollover_no_holiday_calendar",
                    weight,
                ))
        current += timedelta(days=1)
    return tuple(events)


def apply_research_costs(
    profile: BrokerProfile,
    broker_source_bytes: bytes,
    quote_tape: QuoteTape,
    round_trip: ResearchRoundTrip,
) -> CostedRoundTrip:
    """Price-side gross + signed commission/slippage/swap cash events, exact cents.

    Slippage is a separate ADVERSE SCENARIO applied once per transaction side.
    Source-matched broker labels are not evidence of actual Vantage fills.
    """
    validated = BrokerProfile.from_json(profile.to_json())
    source = qualify_broker_profile(validated, broker_source_bytes)
    if source.state not in ("ILLUSTRATIVE_SOURCE_MATCHED",
                            "BROKER_EVIDENCE_MATCHED_UNATTESTED"):
        raise ValueError("broker cost evidence missing or source-mismatched")
    if round_trip.costs_included or round_trip.real_broker_terms_qualified:
        raise ValueError("only Day12 uncosted research fills supported")
    if quote_tape.snapshot_sha256 != round_trip.observed_quote_snapshot_sha256:
        raise ValueError("quote snapshot differs from recorded trade")
    rebuilt = research_round_trip(
        validated, broker_source_bytes, quote_tape,
        direction=round_trip.direction,
        lots=format(round_trip.quantity_lots, "f"),
        entry_signal_closed_at_utc=round_trip.entry.signal_closed_at_utc,
        exit_signal_closed_at_utc=round_trip.exit.signal_closed_at_utc,
        scenario=SpreadScenario(round_trip.scenario_extra_ticks_per_side),
    )
    if rebuilt != round_trip:
        raise ValueError("uncosted fill fails frozen-source replay check")
    costs = validated.costs
    if costs.commission_usd_per_lot_per_side is None or costs.slippage_scenario_ticks is None:
        raise ValueError("commission or slippage scenario not defined")
    lots = round_trip.quantity_lots
    commission_each = _usd(-costs.commission_usd_per_lot_per_side * lots)
    slippage_each = _usd(-costs.slippage_scenario_ticks * validated.usd_per_tick(lots))
    entry_time, exit_time = round_trip.entry.filled_at_utc, round_trip.exit.filled_at_utc
    events: list[CashEvent] = [
        CashEvent("commission", entry_time, commission_each,
                  "per_lot_per_transaction_side_usd", 1),
        CashEvent("slippage_scenario", entry_time, slippage_each,
                  "additional_adverse_ticks_per_side", 1),
        CashEvent("commission", exit_time, commission_each,
                  "per_lot_per_transaction_side_usd", 1),
        CashEvent("slippage_scenario", exit_time, slippage_each,
                  "additional_adverse_ticks_per_side", 1),
    ]
    events.extend(_funding_events(validated, entry_time, exit_time,
                                  round_trip.direction, lots))
    events.sort(key=lambda event: (event.at_utc, event.kind))
    commission = sum((e.usd for e in events if e.kind == "commission"), Decimal(0))
    slippage = sum((e.usd for e in events if e.kind == "slippage_scenario"), Decimal(0))
    funding = sum((e.usd for e in events if e.kind.startswith("swap_")), Decimal(0))
    gross = _usd(round_trip.gross_quote_side_usd)
    net = _usd(gross + commission + slippage + funding)
    if net != gross + sum((e.usd for e in events), Decimal(0)):
        raise ValueError("cost cash events do not reconcile to net USD")
    return CostedRoundTrip(
        round_trip.direction, lots, entry_time, exit_time,
        gross, commission, slippage, funding, net,
        tuple(events), round_trip.observed_quote_snapshot_sha256,
        source.profile_sha256 or "", sha256(round_trip.to_json().encode()).hexdigest(),
    )
