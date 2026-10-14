"""Day16 deterministic XAUUSD positions: risk lot-grid, available margin, partial exits.

Illustrative USD-only linear contract; no real broker attestation or leverage
policy claim. State mutation is local to a research simulation instance.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from aidy.strategy_lab_broker_profile import BrokerProfile, qualify_broker_profile

CENT = Decimal("0.01")


@dataclass(frozen=True)
class Position:
    identifier: str
    direction: str
    lots_open: Decimal
    lots_remaining: Decimal
    entry_price: Decimal
    stop_price: Decimal
    reserved_margin_usd: Decimal
    risk_per_lot_usd: Decimal
    realized_usd: Decimal = Decimal(0)


class Portfolio:
    def __init__(self, broker: BrokerProfile, original_bytes: bytes, *,
                 equity_usd: Decimal, max_positions: int,
                 max_total_risk_percent: Decimal) -> None:
        validated=BrokerProfile.from_json(broker.to_json())
        evidence=qualify_broker_profile(validated, original_bytes)
        if evidence.state not in ("ILLUSTRATIVE_SOURCE_MATCHED",
                                  "BROKER_EVIDENCE_MATCHED_UNATTESTED"):
            raise ValueError("unqualified broker terms")
        if (not isinstance(equity_usd,Decimal) or equity_usd <= 0
            or not equity_usd.is_finite() or type(max_positions) is not int
            or not 1<=max_positions<=1000 or not isinstance(max_total_risk_percent,Decimal)
            or not 0<max_total_risk_percent<=100):
            raise ValueError("invalid portfolio risk/equity limits")
        self.broker=validated
        self.starting_equity=equity_usd
        self.equity=equity_usd
        self.max_positions=max_positions
        self.max_total_risk_percent=max_total_risk_percent
        self.positions: dict[str,Position]={}
        self.realized_total=Decimal(0)

    @staticmethod
    def _positive(value: Decimal) -> None:
        if not isinstance(value,Decimal) or not value.is_finite() or value<=0:
            raise ValueError("positive finite Decimal required")

    @property
    def risk_open_usd(self) -> Decimal:
        return sum((p.risk_per_lot_usd*p.lots_remaining for p in self.positions.values()),Decimal(0))

    @property
    def reserved_margin_usd(self) -> Decimal:
        return sum((p.reserved_margin_usd for p in self.positions.values()),Decimal(0))

    @property
    def free_margin_usd(self) -> Decimal:
        return self.equity-self.reserved_margin_usd

    def size_for_risk(self, entry: Decimal, stop: Decimal, risk_percent: Decimal) -> Decimal:
        for amount in (entry,stop,risk_percent):
            self._positive(amount)
        if risk_percent>self.max_total_risk_percent:
            raise ValueError("requested risk exceeds whole portfolio risk cap")
        delta=abs(entry-stop)
        if delta<=0:
            raise ValueError("protective stop must differ from entry")
        per_lot=delta*self.broker.contract.contract_ounces_per_lot
        allowed=self.equity*risk_percent/Decimal(100)
        c=self.broker.contract
        # Floor to valid step relative to minimum, never round exposure UP.
        count=((allowed/per_lot-c.volume_min_lots)/c.volume_step_lots).to_integral_value(rounding=ROUND_FLOOR)
        if count<0:
            raise ValueError("risk budget too small for minimum broker lot")
        lots=min(c.volume_min_lots+count*c.volume_step_lots,c.volume_max_lots)
        if not self.broker.is_valid_lot(lots):
            raise ValueError("computed lot violates broker grid")
        return lots

    def open(self, identifier: str, direction: str, entry: Decimal,
             stop: Decimal, risk_percent: Decimal) -> Position:
        if not identifier or identifier in self.positions:
            raise ValueError("position ID missing/duplicate")
        if direction not in ("long","short"):
            raise ValueError("invalid position direction")
        self._positive(entry)
        self._positive(stop)
        if (direction=="long" and stop>=entry) or (direction=="short" and stop<=entry):
            raise ValueError("protective stop must be adverse to the entry")
        if len(self.positions)>=self.max_positions:
            raise ValueError("maximum positions reached")
        qty=self.size_for_risk(entry,stop,risk_percent)
        per_lot=abs(entry-stop)*self.broker.contract.contract_ounces_per_lot
        requested_risk=per_lot*qty
        portfolio_cap=self.equity*self.max_total_risk_percent/Decimal(100)
        if self.risk_open_usd+requested_risk>portfolio_cap:
            raise ValueError("combined position risk cap exceeded")
        margin=self.broker.initial_margin_usd(entry,format(qty,"f"))
        if self.reserved_margin_usd+margin>self.equity:
            raise ValueError("insufficient free margin")
        p=Position(identifier,direction,qty,qty,entry,stop,margin,per_lot)
        self.positions[identifier]=p
        return p

    def reduce(self, identifier: str, close_lots: Decimal,
               exit_price: Decimal) -> Decimal:
        from dataclasses import replace

        self._positive(close_lots)
        self._positive(exit_price)
        if identifier not in self.positions:
            raise KeyError("position unavailable")
        p=self.positions[identifier]
        if close_lots>p.lots_remaining:
            raise ValueError("cannot close more than remaining lots")
        c=self.broker.contract
        if (close_lots/c.volume_step_lots)%1:
            raise ValueError("partial close not on lot increment")
        remain=p.lots_remaining-close_lots
        if remain and remain<c.volume_min_lots:
            raise ValueError("partial close would create untradeable dust")
        sign=Decimal(1) if p.direction=="long" else Decimal(-1)
        raw=(exit_price-p.entry_price)*sign*c.contract_ounces_per_lot*close_lots
        pnl=raw.quantize(CENT,rounding=ROUND_HALF_UP)
        # Retain exact margin for remaining size, avoid cent drift on multiple reductions.
        left_margin=p.reserved_margin_usd*remain/p.lots_remaining
        updated=replace(p,lots_remaining=remain,
                        reserved_margin_usd=left_margin,
                        realized_usd=p.realized_usd+pnl)
        self.realized_total+=pnl
        self.equity+=pnl
        if remain==0:
            del self.positions[identifier]
        else:
            self.positions[identifier]=updated
        return pnl
