"""Independent Gold X9 v6.3 tutorial S9 real BID/ASK tick replay.

NOT original v6.2 EX5, NOT author-source parity, and NOT nine-strategy results.
All costs, broker point size, and execution assumptions are explicit.
Only accepts genuine original HistData single-month ZIPs and never modifies them.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import io
import json
import math
import re
import struct
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from aidy.strategy_lab_crossfire_tick_2021 import parse_tick

ROW = struct.Struct("<qIdd")
SOURCE_RE = re.compile(r"T_(20\d{4})\.zip$", re.I)


def checksum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for b in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def ordered_quotes(archive: Path, period: str, audit: dict, chunk_size: int = 150000):
    """External merge-sort source ticks by UTC instant, stable at equal timestamps.

    Source CSV may contain timestamp inversions. We never process future quotes
    before earlier ones or silently discard inverted records.
    """
    chunks = []
    buf = []
    prior = None
    inversions = 0
    count = 0
    day_cache = {}
    with tempfile.TemporaryDirectory(prefix="aidy-goldx9-") as folder:
        def flush():
            if not buf:
                return
            buf.sort(key=lambda r: (r[0], r[1]))
            p = Path(folder) / f"{len(chunks):05d}.bin"
            with p.open("wb") as w:
                for row in buf:
                    w.write(ROW.pack(*row))
            chunks.append(p)
            buf.clear()

        with zipfile.ZipFile(archive) as z:
            files = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if len(files) != 1:
                raise ValueError("Expected exactly one original HistData tick CSV in ZIP")
            with z.open(files[0]) as raw:
                for fields in csv.reader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")):
                    if not fields:
                        continue
                    epoch, micro, bid, ask = parse_tick(fields, month=period, day_cache=day_cache)
                    key = (epoch, micro)
                    if prior is not None and key < prior:
                        inversions += 1
                    prior = key
                    count += 1
                    buf.append((epoch, micro, bid, ask))
                    if len(buf) >= chunk_size:
                        flush()
        flush()
        if count < 1:
            raise ValueError("Source tick archive empty")
        audit.update(source_zip_sha256=checksum(archive), original_ticks=count,
                     source_order_inversions=inversions, sorted_chunks=len(chunks),
                     source_timezone="fixed EST UTC-05 from AIDY source adapter")

        def read_rows(path: Path):
            with path.open("rb") as r:
                while (b := r.read(ROW.size)):
                    if len(b) != ROW.size:
                        raise ValueError("Corrupt local sorted quote chunk")
                    yield ROW.unpack(b)

        yield from heapq.merge(*(read_rows(p) for p in chunks),
                              key=lambda r: (r[0], r[1]))


@dataclass
class Pending:
    side: int
    level: float
    pivot_hour: int
    created: int
    expires: int


@dataclass
class Position:
    side: int
    entry: float
    opened: int
    stop: float
    target: float
    lots: float
    pivot_hour: int
    ident: int
    salvage: bool = False


def iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat().replace("+00:00", "Z")


class S9Replay:
    def __init__(self, *, capital=10000.0, lots=0.01, contract_oz=100.0,
                 commission_per_lot_roundtrip=7.0, slippage_price=0.0,
                 point=0.01, max_spread_points=50.0, clearance_pct=0.1):
        if min(capital, lots, contract_oz, point) <= 0:
            raise ValueError("Account, contract, lots and point must be positive")
        if min(commission_per_lot_roundtrip, slippage_price, max_spread_points,
               clearance_pct) < 0:
            raise ValueError("Costs / limits cannot be negative")
        self.capital, self.lots, self.contract = capital, lots, contract_oz
        self.fee, self.slippage = commission_per_lot_roundtrip, slippage_price
        self.point, self.max_spread_points = point, max_spread_points
        self.clearance_pct = clearance_pct
        self.cash = capital
        self.equity_peak = capital
        self.max_drawdown_pct = 0.0
        self.last_equity = capital
        self.last_hour = None
        self.last_minute = None
        self.last_scan = None
        self.current_high = None
        self.current_low = None
        self.bars = []
        self.swing_high = None
        self.swing_low = None
        self.pending = {}
        self.last_pivot_filled = {}
        self.positions = []
        self.trades = []
        self.minute_marks = 0
        self.tick_count = 0
        self.blocked_spread = 0
        self.created_orders = 0
        self.filled_orders = 0
        self.expired_orders = 0
        self.ident = 0

    def _close(self, p: Position, at: int, bid: float, ask: float, reason: str):
        exit_price = max(0.0, bid - self.slippage) if p.side == 1 else ask + self.slippage
        gross = p.side * (exit_price - p.entry) * self.contract * p.lots
        cost = self.fee * p.lots
        net = gross - cost  # observed spread is already embedded in fill prices
        self.cash += net
        self.trades.append({
            "strategy": "GOLDX9_TUTORIAL_S9_RECONSTRUCTED",
            "id": p.ident, "direction": "buy" if p.side == 1 else "sell",
            "opened_utc": iso(p.opened), "closed_utc": iso(at),
            "entry": round(p.entry, 5), "exit": round(exit_price, 5),
            "lots": p.lots, "gross_usd": round(gross, 5),
            "commission_usd": round(cost, 5), "net_usd": round(net, 5),
            "exit_reason": reason, "pivot_hour_utc": iso(p.pivot_hour)
        })

    def _mark(self, bid: float, ask: float):
        floating = sum(p.side * ((bid if p.side == 1 else ask) - p.entry)
                       * self.contract * p.lots for p in self.positions)
        equity = self.cash + floating
        self.last_equity = equity
        self.equity_peak = max(self.equity_peak, equity)
        if self.equity_peak > 0:
            self.max_drawdown_pct = max(self.max_drawdown_pct,
                                        100 * (self.equity_peak - equity) / self.equity_peak)
        self.minute_marks += 1

    def _finish_hour(self):
        if self.last_hour is None:
            return
        self.bars.append((self.last_hour, self.current_high, self.current_low))
        if len(self.bars) < 11:
            return
        c = len(self.bars) - 6
        old = self.bars[c-5:c]
        new = self.bars[c+1:c+6]
        hour, hi, lo = self.bars[c]
        if all(hi > x[1] for x in old + new):
            self.swing_high = (hi, hour)
        if all(lo < x[2] for x in old + new):
            self.swing_low = (lo, hour)

    def _scan(self, epoch: int, bid: float, ask: float):
        # UTC proxy, not a claim of matching the original broker's day boundary.
        mins = (epoch % 86400) // 60
        if mins < 30 or mins >= 1410:
            return
        if (ask - bid) / self.point > self.max_spread_points:
            self.blocked_spread += 1
            return
        for side, pivot in ((1, self.swing_high), (-1, self.swing_low)):
            old = self.pending.get(side)
            if old and epoch >= old.expires:
                self.expired_orders += 1
                self.pending.pop(side)
                old = None
            if pivot is None or sum(p.side == side for p in self.positions) >= 10:
                continue
            level, pivot_hour = pivot
            if self.last_pivot_filled.get(side) == pivot_hour:
                continue
            reference = bid
            if abs(level-reference) < reference * (self.clearance_pct/100):
                continue
            intended = (level - reference*0.0008 if side == 1
                        else level + reference*0.0008)
            # 0.01 is a research point-size assumption, not an attested broker spec.
            rounded = round(intended / self.point) * self.point
            valid = (rounded > ask + self.point if side == 1
                     else rounded < bid - self.point)
            if not valid:
                continue
            if old and old.pivot_hour == pivot_hour and abs(old.level-rounded) < 5*self.point:
                continue
            self.pending[side] = Pending(side, rounded, pivot_hour, epoch,
                                         epoch + 15*3600)
            self.created_orders += 1

    def _manage(self, p: Position, bid: float, ask: float):
        price = bid if p.side == 1 else ask
        favourable = p.side * (price - p.entry) / p.entry
        adverse = -favourable
        if favourable >= 0.001:
            lock = p.entry * (1 + p.side * 0.00025)
            p.stop = max(p.stop, lock) if p.side == 1 else min(p.stop, lock)
        if favourable >= 0.002:
            trailed = price - p.side * p.entry * 0.002
            p.stop = max(p.stop, trailed) if p.side == 1 else min(p.stop, trailed)
        if adverse >= 0.01 and not p.salvage:
            # Research approximation of spoken salvage: exit on a modest rebound
            # while underwater, keeping initial hard SL in force.
            recovery = price + p.side * p.entry * 0.0015
            p.target = min(p.target, recovery) if p.side == 1 else max(p.target, recovery)
            p.salvage = True

    def on_tick(self, epoch: int, bid: float, ask: float):
        self.tick_count += 1
        hour = epoch // 3600 * 3600
        minute = epoch // 60
        if self.last_hour != hour:
            self._finish_hour()
            self.last_hour = hour
            self.current_high = self.current_low = bid
        else:
            self.current_high = max(self.current_high, bid)
            self.current_low = min(self.current_low, bid)
        minute_changed = self.last_minute != minute
        if minute_changed:
            self.last_minute = minute

        # Broker-side SL/TP are evaluated on EACH observed BID/ASK tick, not H1 OHLC.
        keep = []
        for p in self.positions:
            close_side = bid if p.side == 1 else ask
            if p.side * (close_side-p.stop) <= 0:
                self._close(p, epoch, bid, ask, "stop_or_breakeven")
            elif p.side * (close_side-p.target) >= 0:
                self._close(p, epoch, bid, ask, "take_profit_or_salvage")
            else:
                keep.append(p)
        self.positions = keep

        if minute_changed:
            for p in self.positions:
                self._manage(p, bid, ask)
            self._mark(bid, ask)

        scan = epoch // 900
        if scan != self.last_scan:
            self.last_scan = scan
            self._scan(epoch, bid, ask)

        for side, order in list(self.pending.items()):
            if epoch >= order.expires:
                self.expired_orders += 1
                self.pending.pop(side)
                continue
            eligible = ask >= order.level if side == 1 else bid <= order.level
            if not eligible or sum(p.side == side for p in self.positions) >= 10:
                continue
            entry = ask + self.slippage if side == 1 else max(0.0, bid-self.slippage)
            self.ident += 1
            p = Position(side=side, entry=entry, opened=epoch,
                         stop=entry * (1-side*0.02), target=entry * (1+side*0.007),
                         lots=self.lots, pivot_hour=order.pivot_hour, ident=self.ident)
            self.positions.append(p)
            self.last_pivot_filled[side] = order.pivot_hour
            self.filled_orders += 1
            self.pending.pop(side)

    def report(self, source_receipts: list[dict]) -> dict:
        wins = [t["net_usd"] for t in self.trades if t["net_usd"] > 0]
        losses = [t["net_usd"] for t in self.trades if t["net_usd"] < 0]
        profit = sum(wins)
        loss = -sum(losses)
        months = {}
        for t in self.trades:
            k = t["closed_utc"][:7]
            months[k] = round(months.get(k, 0.0) + t["net_usd"], 5)
        return {
            "classification": "INDEPENDENT_V63_TUTORIAL_S9_TICK_PATH_APPROXIMATION_NOT_V62",
            "source_provenance": source_receipts,
            "capital_usd": self.capital,
            "fixed_lots": self.lots, "contract_oz_per_lot_assumed": self.contract,
            "source_spread": "observed_bid_ask",
            "commission_usd_per_lot_roundtrip_assumed": self.fee,
            "adverse_slippage_price_per_side_assumed": self.slippage,
            "point_size_assumed": self.point,
            "clearance_pct_effective": self.clearance_pct,
            "midnight_exclusion": "UTC +/- 30min proxy",
            "scan": "15min quote-aligned; H1 causal confirmed swings; dynamic M1",
            "not_implemented": [
                "original v6.2 nine internal strategies", "native MetaTrader broker parity",
                "terminal stop/freeze/margin rejection", "broker swaps/financing",
                "native trailing take-profit", "original source lot scaling",
                "restart order recovery", "economic news filter"
            ],
            "observed_ticks": self.tick_count,
            "minute_equity_marks": self.minute_marks,
            "created_pending": self.created_orders,
            "filled_pending": self.filled_orders,
            "expired_pending": self.expired_orders,
            "blocked_spread_scans": self.blocked_spread,
            "closed_trades": len(self.trades),
            "open_positions_at_end": len(self.positions),
            "realised_net_usd": round(self.cash-self.capital, 4),
            "ending_cash_usd": round(self.cash, 4),
            "ending_marked_equity_usd": round(self.last_equity, 4),
            "marked_equity_return_pct": round(100*(self.last_equity-self.capital)/self.capital, 4),
            "max_observed_minute_equity_drawdown_pct": round(self.max_drawdown_pct, 4),
            "win_rate_pct": round(100*len(wins)/len(self.trades), 4) if self.trades else None,
            "profit_factor": round(profit/loss, 5) if loss else None,
            "monthly_realised_net_usd": months,
            "trade_ledger": "trades.csv",
            "account_reconciles": math.isclose(self.cash-self.capital,
                         sum(t["net_usd"] for t in self.trades),
                         abs_tol=0.02)
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", action="append", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--capital", type=float, default=10000)
    ap.add_argument("--lots", type=float, default=0.01)
    ap.add_argument("--contract", type=float, default=100)
    ap.add_argument("--commission-rt", type=float, default=7)
    ap.add_argument("--slippage-price", type=float, default=0)
    ap.add_argument("--point", type=float, default=0.01)
    ap.add_argument("--clearance-pct", type=float, default=0.1)
    args = ap.parse_args()
    engine = S9Replay(capital=args.capital, lots=args.lots,
                      contract_oz=args.contract, commission_per_lot_roundtrip=args.commission_rt,
                      slippage_price=args.slippage_price, point=args.point,
                      clearance_pct=args.clearance_pct)
    receipts = []
    previous = None
    for archive in args.archive:
        match = SOURCE_RE.search(archive.name)
        if not match:
            raise SystemExit("Archive must be original HISTDATA_COM_ASCII_XAUUSD_T_YYYYMM.zip")
        month = match.group(1)
        if previous and month <= previous:
            raise SystemExit("Archive months must be in ascending order")
        previous = month
        receipt = {"source_month": month}
        for epoch, micro, bid, ask in ordered_quotes(archive, month, receipt):
            engine.on_tick(epoch, bid, ask)
        receipts.append(receipt)
    args.output.mkdir(parents=True, exist_ok=True)
    out = engine.report(receipts)
    if not out["account_reconciles"]:
        raise SystemExit("Ledger reconciliation FAILED")
    (args.output / "summary.json").write_text(json.dumps(out, indent=2, sort_keys=True)+"\n")
    with (args.output / "trades.csv").open("w", newline="", encoding="utf-8") as h:
        fields = ["strategy", "id", "direction", "opened_utc", "closed_utc",
                  "entry", "exit", "lots", "gross_usd", "commission_usd", "net_usd",
                  "exit_reason", "pivot_hour_utc"]
        writer = csv.DictWriter(h, fieldnames=fields)
        writer.writeheader()
        writer.writerows(engine.trades)
    print("GOLDX9_REPLAY_FINISHED", json.dumps(out, sort_keys=True))


if __name__ == "__main__":
    main()
