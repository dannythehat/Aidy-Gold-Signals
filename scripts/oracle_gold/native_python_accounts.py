"""Run pinned original Python strategies/engines, never their acquisition drivers.

Input is the already authenticated research cache. Source functions, quantity
rules and lifecycle are unchanged. Compatible research runtime and explicit
account/cost comparisons are not assertions about a broker's executable terms.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import sys
import tomllib
from dataclasses import asdict, replace
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd

from scripts.oracle_gold.history import digest
from scripts.oracle_gold.minute_history import load
from scripts.oracle_gold.pine_fixed_accounts import csv_out

ROOT = Path(__file__).resolve().parents[2]
PINS = ROOT/"research/gold_oracle/phase04/python_source_pins.json"
os.environ.setdefault("MPLBACKEND", "Agg")
COSTS = {"common_base": .47, "common_stress": 1.44}


def verify(ident, root):
    pin = json.loads(PINS.read_text())[ident]
    syntax = []
    for name, expected in pin["files"].items():
        raw = (root/name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("Original source/dependency changed: "+name)
        if name.endswith(".py"):
            compile(raw, str(root/name), "exec")  # syntax only, no script execution
            syntax.append(name)
    lock = None
    if (root/"pyproject.toml").exists():
        from packaging.requirements import Requirement
        from packaging.specifiers import SpecifierSet
        project = tomllib.loads((root/"pyproject.toml").read_text())["project"]
        deps = []
        for text in project["dependencies"]:
            req = Requirement(text)
            try:
                installed = importlib.metadata.version(req.name)
            except importlib.metadata.PackageNotFoundError:
                installed = None
            deps.append({"declared": text, "installed": installed,
                         "satisfied": installed is not None and installed in req.specifier})
        python_ok = platform.python_version() in SpecifierSet(project["requires-python"])
        lock = {"python_required": project["requires-python"], "python_satisfied": python_ok,
                "dependencies": deps, "all_satisfied": python_ok and all(d["satisfied"] for d in deps)}
    return {"source": pin, "original_python_files_compiled": syntax, "source_declared_runtime_lock": lock,
            "python_runtime": platform.python_version(), "pandas": pd.__version__,
            "numpy": np.__version__, "backtrader": bt.__version__,
            "acquisition_or_optimiser_drivers_executed": False}


def snapshots(root):
    expected = json.loads((ROOT/"research/gold_oracle/phase03/minute_cache_receipt.json").read_text())["frozen_snapshots"]
    rows, manifests = [], []
    for year in (2023, 2024, 2025):
        values, manifest = load(root/str(year))
        for field in ("rows_sha256", "sha256"):
            if manifest[field] != expected[str(year)][field]:
                raise ValueError("Authenticated minute cache changed")
        rows.extend(values)
        manifests.append(manifest)
    x = pd.DataFrame(rows)
    x.index = pd.to_datetime(x.pop("open_time_utc"), utc=True)
    return x, manifests


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    sys.modules[name] = obj  # Backtrader's native metaclass resolves its defining module.
    spec.loader.exec_module(obj)
    return obj


def daily(frame):
    """Observed UTC daily OHLC; no synthetic noise, volume or missing bars.

    Strategy has no clock filter. Use each observed day's actual first quote
    time for its next-open fill, rather than pretending a missing00:00 quote.
    Calendar/data-feed substitution is explicitly part of the AIDY application.
    """
    groups = frame.groupby(frame.index.normalize())
    x = groups.agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    x.index = pd.DatetimeIndex([group.index[0] for _, group in groups])
    return x


class CashCost(bt.CommInfoBase):
    params = (("stocklike", True), ("commtype", bt.CommInfoBase.COMM_FIXED), ("per_unit_side", 0.))

    def _getcommission(self, size, price, pseudoexec):
        return abs(size)*self.p.per_unit_side


class Observe(bt.Analyzer):
    """Observation only: no order, sizing or strategy-method overrides."""
    def start(self):
        self.fills, self.trades, self.rejections = [], [], []

    def notify_order(self, order):
        if order.status == order.Completed:
            self.fills.append({"utc": bt_time(order.executed.dt),
                "quantity_delta": float(order.executed.size), "price": float(order.executed.price),
                "commission": float(order.executed.comm)})
        elif order.status in (order.Margin, order.Rejected, order.Canceled):
            self.rejections.append({"utc": self.strategy.data.datetime.datetime(0).isoformat(),
                                    "status": order.getstatusname()})

    def notify_trade(self, trade):
        if trade.isclosed:
            self.trades.append({"entry_utc": bt_time(trade.dtopen),
                "exit_utc": bt_time(trade.dtclose),
                "side": "LONG", "gross_usd": float(trade.pnl),
                "net_usd": float(trade.pnlcomm), "commission_usd": float(trade.commission)})


def bt_time(value):
    stamp = pd.Timestamp(bt.num2date(value))
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
    return stamp.round("min").isoformat()


def s016(frame, root, variant, capital, cost):
    path = "strategies/gold_donchian_channel_strategy.py" if variant == "entry20_risk1" else "src/gold_donchian_channel_strategy.py"
    original = module(root/path, "oracle_s016_"+variant).GoldDonchianBreakoutStrategy
    engine = bt.Cerebro(stdstats=False)
    engine.addstrategy(original)
    data = bt.feeds.PandasData(dataname=daily(frame), volume=-1, openinterest=-1)
    engine.adddata(data)
    engine.broker.setcash(capital)
    if cost == "source_declared":
        engine.broker.setcommission(commission=.00001)
    else:
        engine.broker.addcommissioninfo(CashCost(per_unit_side=COSTS[cost]/2))
    engine.addanalyzer(Observe, _name="aidy_observation")
    strategy = engine.run()[0]
    obs = strategy.analyzers.aidy_observation
    # Rebuild minute cash/holdings directly from native executed orders.
    cash, units, entry = capital, 0., 0.
    delta = pd.Series(0., index=frame.index)
    quantities = pd.Series(0., index=frame.index)
    for fill in obs.fills:
        stamp = pd.Timestamp(fill["utc"])
        assert stamp in frame.index
        delta.loc[stamp] += -fill["quantity_delta"]*fill["price"]-fill["commission"]
        quantities.loc[stamp] += fill["quantity_delta"]
        cash -= fill["quantity_delta"]*fill["price"]+fill["commission"]
        units += fill["quantity_delta"]
        if fill["quantity_delta"] > 0:
            entry = fill["price"]
    equity = capital+delta.cumsum()+quantities.cumsum()*frame.close
    if abs(float(equity.iloc[-1])-engine.broker.getvalue()) > 1e-5:
        raise ValueError("Native Backtrader cash/marked-equity observer parity failed")
    realised = sum(t["net_usd"] for t in obs.trades)
    # Native open position stays open; no added end liquidation.
    return obs.trades, equity, {"native_engine": "BACKTRADER_ORIGINAL_CLASS_UNCHANGED",
        "params": dict(strategy.params._getkwargs()), "order_fills": obs.fills,
        "rejected_or_cancelled_orders": obs.rejections, "native_final_equity": engine.broker.getvalue(),
        "native_cash": cash, "native_open_units": units, "native_open_entry": entry,
        "native_closed_net": realised, "observer_final_equity_parity": True,
        "input_application": "AIDY_AUTHENTIC_XAUUSD_OBSERVED_UTC_DAILY; original loader synthetic index OHLC not used",
        "funding": "Native fully paid stocklike cash engine; not evidence for CFD financing",
        "same_family_as_other_S016_variant": True}


def s019_setup(frame, root):
    sys.path.insert(0, str(root.resolve()))
    from mtf_smc.config import StrategyConfig
    from mtf_smc.strategy.entries import generate_setups
    cfg = StrategyConfig()
    setups, _ = generate_setups(frame, cfg)
    checks = []
    for year in (2024, 2025):
        cut = pd.Timestamp(f"{year}-01-01", tz="UTC")
        partial, _ = generate_setups(frame.loc[frame.index < cut], cfg)
        full_known = [asdict(s) for s in setups if s.decided_ts <= cut]
        part_known = [asdict(s) for s in partial if s.decided_ts <= cut]
        checks.append({"cut": cut.isoformat(), "full_known": len(full_known),
                       "partial_known": len(part_known), "same": full_known == part_known})
    return cfg, setups, checks


def s019(frame, cfg, setups, capital, cost):
    from mtf_smc.engine.backtester import simulate
    from mtf_smc.engine.costs import CostModel
    from mtf_smc.risk.instrument import XAUUSD
    cfg = replace(cfg, initial_equity=capital)
    inst = XAUUSD
    if cost != "source_declared":
        # Explicit AIDY common fee overlay. All entries/exits charged halfRT
        # as spread, zero extra stop slippage/commission; source swap retained
        # and separately identified as unverified publisher placeholder.
        inst = replace(inst, base_spread_price=COSTS[cost], commission_per_lot_per_side=0.,
                       base_slippage_price=0., stop_slippage_price=0.)
    cm = CostModel(inst)
    native, _, final = simulate(frame, setups, cfg, inst, cm)
    records = []
    cash_delta = pd.Series(0., index=frame.index)
    unrealised = pd.Series(0., index=frame.index)
    for t in native:
        r = asdict(t)
        records.append({"entry_utc": t.entry_ts.isoformat(), "exit_utc": t.exit_ts.isoformat(),
            "side": t.direction.upper(), "gross_usd": t.gross_money, "net_usd": t.net_money,
            "lots": t.lots, "net_without_unverified_source_swap_usd": t.net_money-t.cost_swap,
            "source_swap_placeholder_usd": t.cost_swap, "exit_reason": t.exit_reason,
            "entry_ref": t.entry_ref, "entry_price": t.entry_price, "initial_stop": t.initial_stop,
            "R": t.realized_R, "fills": json.dumps(r["fills"], default=str, sort_keys=True)})
        remaining = t.lots
        mpu = inst.money_per_price_unit_per_lot
        fee = cm.half_spread*mpu*t.lots+cm.commission_one_side(t.lots)
        cash_delta.loc[t.entry_ts] -= fee
        previous = t.entry_ts
        for fill in t.fills[1:]:
            mask = (frame.index >= previous)&(frame.index < fill.ts)
            sign = 1 if t.direction == "long" else -1
            unrealised.loc[mask] += (frame.close.loc[mask]-t.entry_ref)*sign*mpu*remaining
            slip = cm.eff_stop_slippage if fill.reason in ("stop","be_stop") else 0.
            cash_delta.loc[fill.ts] += (fill.ref-t.entry_ref)*sign*mpu*fill.lots - (cm.half_spread+slip)*mpu*fill.lots-cm.commission_one_side(fill.lots)
            remaining = round(remaining-fill.lots,8)
            previous = fill.ts
        cash_delta.loc[t.exit_ts] += t.cost_swap
    equity = capital+cash_delta.cumsum()+unrealised
    if abs(float(equity.iloc[-1])-final) > 1e-5:
        raise ValueError("Source event/funding cost reconstruction does not reconcile")
    return records, equity, {"native_engine": "ORIGINAL_MTF_SMC_SIMULATE_UNCHANGED",
        "config": asdict(cfg), "instrument_source_model": asdict(inst), "source_setups": len(setups),
        "observer_final_equity_parity": True, "native_final_equity": final,
        "native_open_units": 0, "native_end_liquidation": "Original simulate force-closes at end; unchanged",
        "funding": "Original per-night placeholders retained; not broker-verified. Costs include these separately identified assumptions.",
        "source_sizing_equity": "Original closed-trade equity, not observer marked equity; unchanged",
        "gap_fills": "Original stop/limit-level OHLC model, not verified bid/ask/gap execution",
        "source_runtime_exact_dependency_lock_verified": False}


def statistics(ident, variant, scope, capital, cost, trades, equity, details):
    monthly, previous = [], capital
    for month, group in equity.groupby(equity.index.strftime("%Y-%m"), sort=True):
        end = float(group.iloc[-1])
        monthly.append({"month": month, "start_equity": previous, "end_equity": end,
                        "net_usd": end-previous, "return_pct": (end/previous-1)*100})
        previous = end
    years = []
    for year in (2023,2024,2025):
        ms = [m for m in monthly if m["month"].startswith(str(year))]
        years.append({"year": year, "net_usd": sum(m["net_usd"] for m in ms),
            "return_pct": (ms[-1]["end_equity"]/ms[0]["start_equity"]-1)*100,
            "closed_trades": sum(t["exit_utc"].startswith(str(year)) for t in trades),
            "negative_months": sum(m["net_usd"] < 0 for m in ms)})
    net = float(equity.iloc[-1])-capital
    closed = sum(t["net_usd"] for t in trades)
    winner = max([0.]+[t["net_usd"] for t in trades])
    win = sum(t["net_usd"] for t in trades if t["net_usd"] > 0)
    loss = -sum(t["net_usd"] for t in trades if t["net_usd"] < 0)
    dd = float(((equity/np.maximum.accumulate(np.r_[capital,equity.to_numpy()])[1:])-1).min()*100)
    return {"id": ident, "variant": variant, "account_scope": scope, "initial_capital": capital,
        "cost_scenario": cost, "net_marked_usd": net, "net_closed_usd": closed,
        "closed_trades": len(trades), "long_trades": sum(t["side"]=="LONG" for t in trades),
        "short_trades": sum(t["side"]=="SHORT" for t in trades), "profit_factor": win/loss if loss else None,
        "largest_winner_usd": winner, "closed_net_without_largest_winner_usd": closed-winner,
        "minute_close_marked_drawdown_pct": dd, "worst_month_pct": min(m["return_pct"] for m in monthly),
        "profitable_months": sum(m["net_usd"]>0 for m in monthly), "monthly": monthly, "years": years,
        "full_calendar_certified": False, "native_broker_qualified": False, "sealed_oos": False,
        "source_rules_modified": False, "details": details, "trade_records_sha256": digest(trades)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--snapshots", required=True, type=Path)
    p.add_argument("--sources", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--ids", nargs="+", default=["S016","S019"])
    a = p.parse_args()
    if a.out.exists() and any(a.out.iterdir()):
        raise ValueError("Refusing to overwrite an earlier attempt")
    a.out.mkdir(parents=True,exist_ok=True)
    (a.out/"launch.json").write_text(json.dumps({"adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__,
        "backtrader": bt.__version__, "ids": a.ids},indent=2)+"\n")
    frame, manifests = snapshots(a.snapshots)
    models, failures, sources = {}, [], {}
    for ident in a.ids:
        try:
            sources[ident] = verify(ident,a.sources/ident)
            variants = ("entry20_risk1","entry95_risk2") if ident=="S016" else ("default_cascade_D1_H1_M15",)
            if ident=="S019":
                cfg, setups, checks = s019_setup(frame,a.sources/ident)
            for variant in variants:
                s016_checks = []
                if ident=="S016":
                    _, _, full = s016(frame,a.sources/ident,variant,10_000_000.,"source_declared")
                    for year in (2024,2025):
                        cut = pd.Timestamp(f"{year}-01-01",tz="UTC")
                        _, _, part = s016(frame.loc[frame.index<cut],a.sources/ident,variant,10_000_000.,"source_declared")
                        expected = [f for f in full["order_fills"] if pd.Timestamp(f["utc"])<cut]
                        s016_checks.append({"cut":cut.isoformat(),"same":expected==part["order_fills"],
                            "full_known_fills":len(expected),"partial_fills":len(part["order_fills"])})
                for scope, capital in (("ORIGINAL_CAPITAL",10_000_000. if ident=="S016" else 100_000.),("STANDARDISED_CAPITAL_COMPARISON",10_000.)):
                    for cost in ("source_declared","common_base","common_stress"):
                        key = f"{ident}_{variant}_{scope}_{cost}"
                        try:
                            if ident=="S016":
                                trades, equity, details = s016(frame,a.sources/ident,variant,capital,cost)
                                details["signal_and_execution_prefix_checks"] = s016_checks
                            else:
                                trades, equity, details = s019(frame,cfg,setups,capital,cost)
                                details["signal_prefix_checks"] = checks
                                details["source_runtime_exact_dependency_lock_verified"] = sources[ident]["source_declared_runtime_lock"]["all_satisfied"]
                            result = statistics(ident,variant,scope,capital,cost,trades,equity,details)
                            csv_out(a.out/(key+"_trades.csv"),trades)
                            csv_out(a.out/(key+"_monthly.csv"),result["monthly"])
                            models[key]=result
                            print("NATIVE_ACCOUNT",key,result["closed_trades"],result["net_marked_usd"],flush=True)
                        except Exception as exc:  # noqa: BLE001 - preserve each failure, continue other accounts
                            failures.append({"case":key,"error_type":type(exc).__name__,"message":str(exc)})
                            (a.out/"case_failures.json").write_text(json.dumps(failures,indent=2)+"\n")
                            print("CASE_FAILED",key,type(exc).__name__,flush=True)
        except Exception as exc:  # noqa: BLE001 - dependency/source failure is not a financial rejection
            failures.append({"id":ident,"error_type":type(exc).__name__,"message":str(exc)})
            print("SOURCE_OR_DEPENDENCY_BLOCKED",ident,type(exc).__name__,flush=True)
    report={"schema":"oracle.gold.phase04.native_python_accounts.v1", "models":models,
        "failed_attempts":failures,"source_manifests":sources,"input_manifests":manifests,
        "native_rules_unchanged":True,"all83_backtested":False,
        "notes":"S016 parameter variants are one family. Standard10k accounts are separately labelled comparisons, never additional strategies. Native model funding/fills remain distinct from real broker terms."}
    report["sha256"]=digest(report)
    (a.out/"report.json").write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+"\n")


if __name__ == "__main__":
    main()
