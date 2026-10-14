"""Strict historical XAUUSD bar qualification primitives, research only.

No broker assumptions or interpolation. Calendar closure classification is deliberately
not guessed from a generic weekly schedule: verified session calendars must be supplied.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256

@dataclass(frozen=True)
class SourceContract:
    source: str
    symbol: str
    timeframe_minutes: int
    price_basis: str
    clock: str
    derivation: str
    archive_sha256: str

    def validate(self) -> None:
        if self.symbol != "XAUUSD" or self.timeframe_minutes != 1:
            raise ValueError("B01 v1 supports native XAUUSD M1 only")
        if self.price_basis not in ("bid", "ask", "mid"):
            raise ValueError("price basis must be explicit")
        if self.clock != "EST_FIXED_UTC_MINUS_05":
            raise ValueError("unqualified source clock")
        if len(self.archive_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.archive_sha256):
            raise ValueError("unqualified archive SHA256")
        if not self.source or not self.derivation:
            raise ValueError("missing source provenance")

@dataclass(frozen=True)
class Bar:
    open_time_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal

@dataclass(frozen=True)
class IntervalGap:
    start_utc: datetime
    end_utc: datetime
    missing_minutes: int
    classification: str = "UNCLASSIFIED"

def validate_bars(bars: list[Bar], contract: SourceContract) -> list[IntervalGap]:
    contract.validate()
    previous: datetime | None = None
    gaps = []
    for bar in bars:
        ts = bar.open_time_utc
        if ts.tzinfo is None or ts.utcoffset() != timedelta(0):
            raise ValueError("timestamp requires UTC timezone")
        if ts.second or ts.microsecond:
            raise ValueError("M1 bars must start at a minute boundary")
        vals = (bar.open, bar.high, bar.low, bar.close)
        if any(not isinstance(v, Decimal) or not v.is_finite() or v <= 0 for v in vals):
            raise ValueError("non-positive/non-finite OHLC")
        if bar.high < max(bar.open, bar.close, bar.low) or bar.low > min(bar.open, bar.close, bar.high):
            raise ValueError("invalid OHLC range")
        if previous is not None:
            seconds = (ts - previous).total_seconds()
            if seconds <= 0 or seconds % 60:
                raise ValueError("duplicate, unordered or non-minute timestamp")
            if seconds > 60:
                gaps.append(IntervalGap(previous + timedelta(minutes=1), ts, int(seconds // 60)-1))
        previous = ts
    return gaps

def fingerprint(contract: SourceContract, bars: list[Bar]) -> str:
    contract.validate()
    payload = {"contract": contract.__dict__ if hasattr(contract,"__dict__") else {
        "source":contract.source,"symbol":contract.symbol,"timeframe_minutes":contract.timeframe_minutes,
        "price_basis":contract.price_basis,"clock":contract.clock,"derivation":contract.derivation,
        "archive_sha256":contract.archive_sha256},
        "bars":[[b.open_time_utc.isoformat(),*[str(x) for x in (b.open,b.high,b.low,b.close)]] for b in bars]}
    return sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def closed_source_bar_available_at(open_time_utc:datetime,minutes:int) -> datetime:
    if open_time_utc.tzinfo is None or open_time_utc.utcoffset()!=timedelta(0):
        raise ValueError("UTC required")
    if minutes<=0: raise ValueError("duration must be positive")
    return open_time_utc + timedelta(minutes=minutes)
