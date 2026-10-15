"""Independent *signal-only proxy* for Drive S046; never an EA or profit test.

The original public indicator describes a wick beyond a completed session
range followed by a close back inside. Source-code/MT5 buffer parity is NOT
established here. The two cancellation settings are explicit research choices
(once per level and cancel after breakout), not assertions about MT5 defaults.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aidy.strategy_lab_history_reader import ClosedBar

SESSION_HOURS = (
    ("ASIA", 0, 8),
    ("LONDON", 7, 16),
    ("NEW_YORK", 12, 21),
)
RESOLUTION_MINUTES = 5
RULE_VERSION = "S046_session_sweep_public_description_PROXY_v1"


@dataclass(frozen=True)
class Signal:
    source_id: str
    session: str
    side: str
    level: str
    bar_open_utc: str
    confirmed_at_utc: str
    price_basis: str = "bid"


def scan_completed_session_sweeps(bars: Iterable[ClosedBar]) -> tuple[Signal, ...]:
    """Do not inspect any session boundary until its last M5 bar is closed.

    One self-contained UTC day at a time. Does NOT carry yesterday's active
    levels into today's trading; do not generalise the event count to the
    original MQL5 indicator without exact code-level parity.
    """
    seq = tuple(bars)
    if not seq:
        raise ValueError("Empty history is not evidence")
    day = seq[0].open_time_utc.date()
    if (any(bar.open_time_utc.tzinfo != UTC
            or bar.open_time_utc.date() != day
            or bar.price_basis != "bid"
            or bar.available_at_utc != bar.open_time_utc + timedelta(minutes=5)
            for bar in seq)
            or any(y.open_time_utc - x.open_time_utc != timedelta(minutes=5)
                   for x, y in pairwise(seq))):
        raise ValueError("Only continuous, fully closed, same-day UTC BID M5 allowed")
    start_day = datetime(day.year, day.month, day.day, tzinfo=UTC)
    signals: list[Signal] = []
    for label, start_hr, end_hr in SESSION_HOURS:
        start = start_day + timedelta(hours=start_hr)
        end = start_day + timedelta(hours=end_hr)
        session_bars = [bar for bar in seq if start <= bar.open_time_utc < end]
        if len(session_bars) != (end_hr-start_hr)*60//RESOLUTION_MINUTES:
            # A pre-registered day must include the exact session to claim
            # the level. In a 00:00-21:00 study all three levels exist, even
            # though New York has no subsequent M5 bars to inspect.
            raise ValueError("Full session history missing")
        hi: Decimal = max(bar.high for bar in session_bars)
        lo: Decimal = min(bar.low for bar in session_bars)
        high_active = True
        low_active = True
        for bar in seq:
            if bar.open_time_utc < end:
                continue
            # Sweep confirmation: crossing session extremes, then closing
            # strictly INSIDE the completed range on the SAME closed bar.
            # The two levels operate independently.
            if high_active:
                if bar.high > hi and lo < bar.close < hi:
                    signals.append(Signal(
                        "S046", label, "BEARISH", str(hi),
                        bar.open_time_utc.isoformat(),
                        bar.available_at_utc.isoformat(),
                    ))
                    high_active = False
                elif bar.close > hi:  # Explicit cancel-after-breakout mode
                    high_active = False
            if low_active:
                if bar.low < lo < bar.close < hi:
                    signals.append(Signal(
                        "S046", label, "BULLISH", str(lo),
                        bar.open_time_utc.isoformat(),
                        bar.available_at_utc.isoformat(),
                    ))
                    low_active = False
                elif bar.close < lo:
                    low_active = False
    return tuple(sorted(signals, key=lambda row: (row.confirmed_at_utc, row.session, row.side)))
