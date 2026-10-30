"""Trigger Happy TH-001: causal, research-only bid/ask tick event simulator.

This is NOT a broker order executor, an HFT latency model, or a qualified backtest.
Input must be separately verified and chronologically normalized raw subsecond ticks.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Quote:
    ts_us: int
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid


@dataclass(frozen=True)
class Config:
    window_ms: int = 1500
    trigger_usd: float = 3.0
    max_spread_usd: float = 0.80
    latency_ms: int = 200
    max_entry_wait_ms: int = 3000
    cooldown_ms: int = 10000
    timeout_ms: int = 300000
    stop_usd: float = 4.0
    targets_usd: tuple[float, ...] = (2.0, 4.0, 8.0)
    lot_per_leg: float = 0.01
    assumed_oz_per_lot: float = 100.0
    roundtrip_fee_usd_per_lot: float = 0.0  # optimistic PLACEHOLDER, not validated


def _check_config(cfg: Config) -> None:
    if not (cfg.window_ms > 0 and cfg.latency_ms > 0
            and cfg.max_entry_wait_ms >= cfg.latency_ms
            and cfg.cooldown_ms >= 0 and cfg.timeout_ms > 0):
        raise ValueError("Invalid timing configuration")
    if not all(math.isfinite(x) and x > 0 for x in (
            cfg.trigger_usd, cfg.max_spread_usd, cfg.stop_usd,
            cfg.lot_per_leg, cfg.assumed_oz_per_lot)):
        raise ValueError("Invalid positive price/contract parameter")
    if not cfg.targets_usd or any(not math.isfinite(x) or x <= 0 for x in cfg.targets_usd):
        raise ValueError("Invalid take-profit targets")
    if not math.isfinite(cfg.roundtrip_fee_usd_per_lot) or cfg.roundtrip_fee_usd_per_lot < 0:
        raise ValueError("Invalid model fee")


def simulate(quotes: Iterable[Quote], cfg: Config = Config()) -> dict:
    """Process quotes once, in causal order. Returns closed legs and open inventory.

    Quote timestamps are integer UTC microseconds. Equal timestamps are accepted
    but cannot alone establish a trigger; negative timestamp movement is rejected.
    Stop gaps use observed bid/ask, never magically the stop price.
    """
    _check_config(cfg)
    history: deque[Quote] = deque()
    signals: list[dict] = []
    legs: list[dict] = []
    pending: dict | None = None
    position: dict | None = None
    last_signal_us = -10**30
    prior_us: int | None = None
    last_quote: Quote | None = None
    received = rejected_spread = canceled_fills = 0
    volume_per_leg = cfg.lot_per_leg * cfg.assumed_oz_per_lot

    for q in quotes:
        received += 1
        if not isinstance(q.ts_us, int) or isinstance(q.ts_us, bool):
            raise ValueError("Timestamp must be integer UTC microseconds")
        if prior_us is not None and q.ts_us < prior_us:
            raise ValueError("Nonchronological tick stream: normalize a separate derived copy")
        prior_us = q.ts_us
        if not (math.isfinite(q.bid) and math.isfinite(q.ask)
                and q.bid > 0 and q.ask >= q.bid):
            raise ValueError("Invalid bid/ask geometry")
        last_quote = q
        filled_here = False
        closed_here = False

        # Pending order cannot be executed on its own triggering quote.
        if pending is not None:
            age = q.ts_us - pending["signal_us"]
            if age > cfg.max_entry_wait_ms * 1000:
                pending["status"] = "canceled_entry_timeout"
                pending = None
                canceled_fills += 1
            elif age >= cfg.latency_ms * 1000:
                if q.spread > cfg.max_spread_usd:
                    pending["status"] = "canceled_entry_spread"
                    pending = None
                    canceled_fills += 1
                else:
                    p = pending
                    entry = q.ask if p["direction"] == "LONG" else q.bid
                    p.update(status="filled", entry_us=q.ts_us, entry_price=entry,
                             entry_bid=q.bid, entry_ask=q.ask, entry_spread=q.spread,
                             modeled_latency_ms=age / 1000)
                    position = {"signal": p, "entry_us": q.ts_us,
                                "entry": entry, "direction": p["direction"],
                                "open_targets": set(cfg.targets_usd)}
                    pending = None
                    filled_here = True

        # Mark all three independent legs using executable quote sides.
        if position is not None and not filled_here:
            d = position["direction"]
            entry = position["entry"]
            executable = q.bid if d == "LONG" else q.ask
            timed_out = q.ts_us - position["entry_us"] >= cfg.timeout_ms * 1000
            for target in sorted(tuple(position["open_targets"])):
                stop = (executable <= entry - cfg.stop_usd) if d == "LONG" else (
                    executable >= entry + cfg.stop_usd)
                profit = (executable >= entry + target) if d == "LONG" else (
                    executable <= entry - target)
                if stop:
                    exit_price, cause = executable, "STOP"
                elif profit:
                    # Price-improving fills are not invented; target limit is credited.
                    exit_price = entry + target if d == "LONG" else entry - target
                    cause = "TP"
                elif timed_out:
                    exit_price, cause = executable, "TIME"
                else:
                    continue
                move = (exit_price - entry) * (1 if d == "LONG" else -1)
                fee = cfg.roundtrip_fee_usd_per_lot * cfg.lot_per_leg
                legs.append({
                    "signal_id": position["signal"]["id"], "direction": d,
                    "trigger_us": position["signal"]["signal_us"],
                    "entry_us": position["entry_us"], "exit_us": q.ts_us,
                    "entry": entry, "exit": exit_price, "target_offset_usd": target,
                    "exit_reason": cause, "price_pnl_usd": move,
                    "gross_pnl_usd": move * volume_per_leg,
                    "fee_usd": fee, "net_pnl_usd": move * volume_per_leg - fee,
                })
                position["open_targets"].remove(target)
                closed_here = True
            if not position["open_targets"]:
                position = None

        # A quote with an extreme spread is ineligible to anchor a new signal.
        if q.spread > cfg.max_spread_usd:
            rejected_spread += 1
            history.clear()
            continue
        cutoff = q.ts_us - cfg.window_ms * 1000
        while history and history[0].ts_us < cutoff:
            history.popleft()

        if (position is None and pending is None and not filled_here and not closed_here
                and q.ts_us - last_signal_us >= cfg.cooldown_ms * 1000
                and history and q.ts_us > history[0].ts_us):
            displacement = q.mid - history[0].mid
            if abs(displacement) + 1e-9 >= cfg.trigger_usd:
                d = "LONG" if displacement > 0 else "SHORT"
                signal = {
                    "id": len(signals) + 1, "signal_us": q.ts_us,
                    "anchor_us": history[0].ts_us,
                    "anchor_mid": history[0].mid,
                    "trigger_mid": q.mid, "trigger_bid": q.bid,
                    "trigger_ask": q.ask, "trigger_spread": q.spread,
                    "direction": d, "displacement_usd": displacement,
                    "status": "pending",
                }
                signals.append(signal)
                pending = signal
                last_signal_us = q.ts_us
                history.clear()
                continue
        history.append(q)

    open_legs: list[dict] = []
    if position is not None and last_quote is not None:
        exit_mark = last_quote.bid if position["direction"] == "LONG" else last_quote.ask
        direction = 1 if position["direction"] == "LONG" else -1
        for target in sorted(position["open_targets"]):
            open_legs.append({
                "signal_id": position["signal"]["id"],
                "target_offset_usd": target,
                "last_mark_us": last_quote.ts_us,
                "unrealized_pnl_usd": (
                    (exit_mark - position["entry"]) * direction * volume_per_leg
                ),
            })
    if pending is not None:
        pending["status"] = "unfilled_at_data_end"
    net = sum(l["net_pnl_usd"] for l in legs)
    return {
        "strategy": "TRIGGER_HAPPY_TH_001_V0_1_RESEARCH_ONLY",
        "configuration": asdict(cfg),
        "summary": {
            "quotes": received, "signals": len(signals),
            "filled_signals": sum(s["status"] == "filled" for s in signals),
            "canceled_entries": canceled_fills,
            "ineligible_spread_quotes": rejected_spread,
            "closed_legs": len(legs), "open_legs": len(open_legs),
            "closed_net_pnl_usd_model": round(net, 6),
            "closed_winning_legs": sum(l["net_pnl_usd"] > 0 for l in legs),
            "fee_validation": "UNVERIFIED_MODEL_PARAMETER",
            "broker_execution_validation": False,
            "historical_data_validation": False,
        },
        "signals": signals, "closed_legs": legs, "open_legs": open_legs,
    }


def load_csv(path: Path):
    """Read verified/sorted derived tick stream with ts_us,bid,ask columns."""
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or not {"ts_us", "bid", "ask"} <= set(reader.fieldnames):
            raise ValueError("CSV columns required: ts_us,bid,ask")
        for row in reader:
            yield Quote(int(row["ts_us"]), float(row["bid"]), float(row["ask"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True,
                        help="Separately source-verified, monotonically sorted tick CSV")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--latency-ms", type=int, default=200)
    parser.add_argument("--fee-per-lot", type=float, default=0.0)
    parser.add_argument("--max-spread-usd", type=float, default=0.80)
    args = parser.parse_args()
    cfg = Config(latency_ms=args.latency_ms,
                 roundtrip_fee_usd_per_lot=args.fee_per_lot,
                 max_spread_usd=args.max_spread_usd)
    report = simulate(load_csv(args.csv), cfg)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(json.dumps(report["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
