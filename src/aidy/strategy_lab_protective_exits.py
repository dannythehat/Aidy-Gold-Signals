"""Day15 stop/target exit simulation with conservative intrabar ambiguity.

Inputs are explicitly finished bid/ask OHLC bars after entry, not future
information at signal time. Stop gaps fill at adverse opening executable side;
target gaps do not award price improvement beyond target.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256


@dataclass(frozen=True)
class QuoteBar:
    open_at_utc: datetime
    close_at_utc: datetime
    bid_open: Decimal
    bid_high: Decimal
    bid_low: Decimal
    bid_close: Decimal
    ask_open: Decimal
    ask_high: Decimal
    ask_low: Decimal
    ask_close: Decimal

    def validate(self) -> None:
        if (self.open_at_utc.tzinfo is None or self.close_at_utc.tzinfo is None
            or self.open_at_utc.utcoffset().total_seconds() != 0
            or self.close_at_utc.utcoffset().total_seconds() != 0
            or self.close_at_utc <= self.open_at_utc):
            raise ValueError("closed UTC bar boundaries required")
        for prefix in ("bid", "ask"):
            o, h, lo, c = (getattr(self, f"{prefix}_{part}")
                            for part in ("open", "high", "low", "close"))
            if not all(isinstance(x, Decimal) and x.is_finite() and x > 0 for x in (o,h,lo,c)):
                raise ValueError("bid/ask OHLC must be positive finite Decimal")
            if lo > min(o,c) or h < max(o,c):
                raise ValueError("invalid side OHLC range")
        if any(getattr(self,f"bid_{part}") > getattr(self,f"ask_{part}")
               for part in ("open","high","low","close")):
            raise ValueError("crossed bid/ask OHLC")


@dataclass(frozen=True)
class ProtectedPosition:
    direction: str
    entry_at_utc: datetime
    entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal

    def validate(self) -> None:
        if self.direction not in ("long","short"):
            raise ValueError("unknown position direction")
        if self.entry_at_utc.tzinfo is None or self.entry_at_utc.utcoffset().total_seconds()!=0:
            raise ValueError("entry time must be UTC aware")
        for value in (self.entry_price,self.stop_price,self.target_price):
            if not isinstance(value,Decimal) or not value.is_finite() or value<=0:
                raise ValueError("invalid position price")
        if self.direction=="long" and not self.stop_price < self.entry_price < self.target_price:
            raise ValueError("long protective levels inverted")
        if self.direction=="short" and not self.target_price < self.entry_price < self.stop_price:
            raise ValueError("short protective levels inverted")


@dataclass(frozen=True)
class ProtectiveExit:
    reason: str
    fill_price: Decimal
    bar_close_utc: datetime
    bar_index: int
    ambiguous: bool
    gap_at_open: bool
    audit_sha256: str


def resolve_protective_exit(position: ProtectedPosition, bars: tuple[QuoteBar,...]) -> ProtectiveExit | None:
    """Reject ambiguous input; use adverse stop-first when both touched.

    Conservative bar data cannot prove stop/target intrabar ordering. No claim
    of executable liquidity in broker gaps, only deterministic research policy.
    """
    position.validate()
    last = position.entry_at_utc
    if not isinstance(bars, tuple) or not bars:
        raise ValueError("at least one post-entry closed bid/ask bar required")
    for index, bar in enumerate(bars):
        bar.validate()
        if bar.open_at_utc < last or bar.close_at_utc <= position.entry_at_utc:
            raise ValueError("out-of-sequence or pre-entry bar")
        last = bar.close_at_utc
        side = "bid" if position.direction=="long" else "ask"
        o = getattr(bar, f"{side}_open")
        hi = getattr(bar,f"{side}_high")
        lo = getattr(bar,f"{side}_low")
        if position.direction=="long":
            gap_stop = o<=position.stop_price
            gap_target = o>=position.target_price
            touched_stop=lo<=position.stop_price
            touched_target=hi>=position.target_price
        else:
            gap_stop = o>=position.stop_price
            gap_target = o<=position.target_price
            touched_stop=hi>=position.stop_price
            touched_target=lo<=position.target_price
        if gap_stop:
            reason,price="stop_gap",o
        elif gap_target:
            reason,price="target_gap",position.target_price
        elif touched_stop:
            reason,price=("stop_ambiguous" if touched_target else "stop"),position.stop_price
        elif touched_target:
            reason,price="target",position.target_price
        else:
            continue
        ambiguity = touched_stop and touched_target and not (gap_stop or gap_target)
        data = {
            "policy":"aidy.protective_exit.adverse_first.v1",
            "direction":position.direction,
            "entry":str(position.entry_price),
            "stop":str(position.stop_price),
            "target":str(position.target_price),
            "bar_index":index,"bar_close_utc":bar.close_at_utc.isoformat(),
            "reason":reason,"fill_price":str(price),
            "full_bar":{k:(str(v) if isinstance(v,Decimal) else v.isoformat())
                        for k,v in asdict(bar).items()},
        }
        digest=sha256(json.dumps(data,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        return ProtectiveExit(reason,price,bar.close_at_utc,index,ambiguity,
                              gap_stop or gap_target,digest)
    return None
