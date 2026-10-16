"""AIDY account-level XAUUSD margin and forced-stopout research gate.

This builds on the already-tested B03 Day11 BrokerProfile, Day12 immutable
actual BID/ASK quote-source tape, and Day13 broker-server rollover events.
No MT5 sessions, accounts, broker credentials, or execution orders.

IMPORTANT: a complete QuoteTape does not prove broker-executable prices. A
source-labelled 'histdata_retrospective_bid_ask' remains THIRD-PARTY historical
quotes, not authenticated Vantage quotes. Stopout threshold is a caller-declared
scenario, never automatically broker-certified.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256

from aidy.strategy_lab_bidask_execution import QuoteTape, _quote_after
from aidy.strategy_lab_broker_profile import BrokerProfile, qualify_broker_profile
from aidy.strategy_lab_fees_funding import _funding_events

CENT = Decimal("0.01")
ZERO = Decimal(0)
PCT = Decimal(100)


def cents(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def d(value: str | Decimal) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("use decimal text, never floating-point broker inputs")
    try:
        v = Decimal(str(value))
    except ArithmeticError as exc:
        raise ValueError("invalid decimal input") from exc
    if not v.is_finite():
        raise ValueError("non-finite price or margin input")
    return v


@dataclass(frozen=True, slots=True)
class StopOutScenario:
    """Explicit source-neutral stopout hypothesis; no fictional attestation."""

    margin_call_percent: Decimal
    stopout_percent: Decimal
    source_reference: str
    provider_attested: bool = False

    def validate(self) -> None:
        if (not isinstance(self.margin_call_percent, Decimal)
                or not isinstance(self.stopout_percent, Decimal)
                or not ZERO < self.stopout_percent <= self.margin_call_percent <= Decimal(1000)
                or not self.source_reference.strip()
                or self.provider_attested is not False):
            raise ValueError("unknown, forged or invalid broker stopout terms")


@dataclass(frozen=True, slots=True)
class MarginEvent:
    at_utc: str
    event: str
    bid: str
    ask: str
    cash_usd: str
    marked_equity_usd: str
    used_margin_usd: str
    margin_level_percent: str
    description: str


@dataclass(frozen=True, slots=True)
class MarginReplay:
    status: str
    direction: str
    lots: str
    entry_utc: str
    exit_utc: str
    entry_price: str
    exit_price: str
    initial_cash_usd: str
    ending_cash_usd: str
    realised_net_pnl_usd: str
    funding_cash_usd: str
    commission_cash_usd: str
    execution_slippage_ticks_per_side: str
    stopout_triggered: bool
    margin_call_observed: bool
    event_log: tuple[MarginEvent, ...]
    quote_snapshot_sha256: str
    broker_profile_sha256: str
    quote_source_class: str
    broker_execution_verified: bool = False
    stopout_rules_broker_attested: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def replay_margin_path(
    profile: BrokerProfile,
    broker_original_source_bytes: bytes,
    quotes: QuoteTape,
    stopout: StopOutScenario,
    *,
    direction: str,
    lots: str,
    entry_signal_closed_at_utc: datetime,
    planned_exit_signal_closed_at_utc: datetime,
    initial_cash_usd: str,
    max_gap_seconds: int = 3600,
) -> MarginReplay:
    """Single trade account replay with marked liquidation and financing cash.

    Uses the source's first later quote after a signal and checks *each*
    successive quote for stop-out BEFORE acting on the planned strategy exit.
    A forced exit cancels the future strategy trade path. Price-side spread
    is included exactly once in buy-ask/sell-bid cash accounting; slippage is
    only additional adverse price movement. Rollovers are priced before a
    later quote, with the Day13 timezone/DST/triple-swap rules. An uncovered
    quote gap > max_gap_seconds blocks the research run rather than guessing
    whether an earlier stopout was missed. Does not model weekend closures,
    price spikes between supplied ticks, or broker liquidity/impact.
    """
    stopout.validate()
    if direction not in ("long", "short"):
        raise ValueError("direction must be explicitly long or short")
    if type(max_gap_seconds) is not int or not 1 <= max_gap_seconds <= 3600:
        raise ValueError("invalid maximum quote-gap coverage")
    if (entry_signal_closed_at_utc.tzinfo is None
            or entry_signal_closed_at_utc.utcoffset() != timedelta(0)
            or planned_exit_signal_closed_at_utc.tzinfo is None
            or planned_exit_signal_closed_at_utc.utcoffset() != timedelta(0)
            or planned_exit_signal_closed_at_utc <= entry_signal_closed_at_utc):
        raise ValueError("closed signal timestamps must be ordered UTC")
    cash = d(initial_cash_usd)
    if cash <= 0:
        raise ValueError("positive reference account required")
    validated = BrokerProfile.from_json(profile.to_json())
    qualification = qualify_broker_profile(validated, broker_original_source_bytes)
    if qualification.state not in (
        "ILLUSTRATIVE_SOURCE_MATCHED", "BROKER_EVIDENCE_MATCHED_UNATTESTED"
    ):
        raise ValueError("broker contract terms not even source-matched")
    if not isinstance(quotes, QuoteTape) or quotes != QuoteTape.from_snapshot(
        quotes.snapshot_bytes, expected_sha256=quotes.snapshot_sha256,
    ):
        raise ValueError("unaltered original quote bytes required")
    if not validated.is_valid_lot(lots):
        raise ValueError("not on original broker contract lot grid")
    if not all((
        validated.costs.commission_usd_per_lot_per_side is not None,
        validated.costs.slippage_scenario_ticks is not None,
        validated.costs.swap_long_usd_per_lot_per_rollover is not None,
        validated.costs.swap_short_usd_per_lot_per_rollover is not None,
        validated.costs.triple_swap_weekday is not None,
        validated.costs.rollover_hhmm is not None,
    )):
        raise ValueError("swap, commission, slippage or server rollover unknown")
    lots_d = d(lots)
    oz = lots_d * validated.contract.contract_ounces_per_lot
    commission_each = cents(validated.costs.commission_usd_per_lot_per_side * lots_d)
    adverse = validated.costs.slippage_scenario_ticks * validated.contract.tick_size
    entry_quote = _quote_after(quotes, entry_signal_closed_at_utc, 300)
    entry_price = entry_quote.ask + adverse if direction == "long" else entry_quote.bid - adverse
    if entry_price <= 0:
        raise ValueError("invalid market-side entry after slippage")
    used_entry_margin = validated.initial_margin_usd(entry_price, lots)
    cash -= commission_each
    if used_entry_margin > cash:
        raise ValueError("entry would be rejected for insufficient broker margin")
    entry_stamp = entry_quote.at_utc
    exit_quote = _quote_after(quotes, planned_exit_signal_closed_at_utc, 300)
    if exit_quote.index <= entry_quote.index:
        raise ValueError("exit must follow entry in immutable tape")
    funding = _funding_events(validated, entry_stamp, exit_quote.at_utc,
                              direction, lots_d)
    by_rollover = list(funding)
    funding_index = 0
    funding_total = ZERO
    event_log: list[MarginEvent] = []
    margin_called = False
    stopout_hit = False
    previous = entry_stamp
    final = None
    final_exit_price = ZERO
    final_exit_time = None

    def margin_at(bid: Decimal, ask: Decimal) -> tuple[Decimal, Decimal, Decimal]:
        liquidation_price = bid if direction == "long" else ask
        unrealised = (liquidation_price - entry_price) * oz * (
            Decimal(1) if direction == "long" else Decimal(-1))
        equity = cash + unrealised
        used = validated.initial_margin_usd(liquidation_price, lots)
        return equity, used, equity / used * PCT

    for quote in quotes.quotes[entry_quote.index:exit_quote.index + 1]:
        if quote.at_utc < entry_stamp:
            continue
        if quote.at_utc - previous > timedelta(seconds=max_gap_seconds):
            raise ValueError("unobserved historical quote gap: stopout timing unknown")
        previous = quote.at_utc
        while funding_index < len(by_rollover) and by_rollover[funding_index].at_utc <= quote.at_utc:
            f = by_rollover[funding_index]
            if f.at_utc <= entry_stamp:
                raise ValueError("funding improperly booked before position opened")
            cash += f.usd
            funding_total += f.usd
            funding_index += 1
        equity, margin, level = margin_at(quote.bid, quote.ask)
        if level <= stopout.stopout_percent:
            event = "FORCED_STOPOUT"
            stopout_hit = True
        elif level <= stopout.margin_call_percent:
            event = "MARGIN_WARNING"
            margin_called = True
        else:
            event = "MARKED"
        if level <= stopout.margin_call_percent:
            margin_called = True
        event_log.append(MarginEvent(
            quote.at_utc.isoformat(), event,
            format(quote.bid, "f"), format(quote.ask, "f"),
            format(cents(cash), "f"), format(cents(equity), "f"),
            format(cents(margin), "f"), format(level.quantize(Decimal("0.001")), "f"),
            "source-quote mark; scenario broker terms",
        ))
        if stopout_hit or quote.index == exit_quote.index:
            # Liquidating SELL long at bid; covering short by BUY at ask.
            final_exit_price = quote.bid - adverse if direction == "long" else quote.ask + adverse
            final_exit_time = quote.at_utc
            cash += (final_exit_price - entry_price) * oz * (
                Decimal(1) if direction == "long" else Decimal(-1))
            cash -= commission_each
            final = quote
            break
    if final is None or final_exit_time is None:
        raise ValueError("no final exit quote after valid replay")
    return MarginReplay(
        "RESEARCH_FORCED_STOPOUT" if stopout_hit else "RESEARCH_NORMAL_EXIT",
        direction, format(lots_d, "f"),
        entry_stamp.isoformat(), final_exit_time.isoformat(),
        format(entry_price, "f"), format(final_exit_price, "f"),
        format(d(initial_cash_usd), "f"),
        format(cents(cash), "f"),
        format(cents(cash-d(initial_cash_usd)), "f"),
        format(cents(funding_total), "f"),
        format(-2*commission_each, "f"),
        format(validated.costs.slippage_scenario_ticks, "f"),
        stopout_hit, margin_called, tuple(event_log),
        quotes.snapshot_sha256,
        qualification.profile_sha256 or sha256(validated.to_json().encode()).hexdigest(),
        quotes.source_class,
    )
