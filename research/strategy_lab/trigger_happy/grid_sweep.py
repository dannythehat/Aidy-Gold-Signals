"""Trigger Happy parameter sweep on genuine source BID/ASK microsecond ticks.

Research only. Immutable source ZIP -> disk-stable timestamp derivative -> exact
tick replay for independent threshold/window experiments. No broker actions.

Dependency: numpy, numba (installed only in bounded GitHub Actions).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from numba import njit

from aidy.strategy_lab_crossfire_tick_2021 import parse_tick


WINDOWS_MS = (250, 500, 1000, 1500, 3000, 5000)
THRESHOLDS_USD = (2., 3., 4., 5., 7., 10., 15.)
FROZEN_VERSION = "TH-001-GRID-V01A-20261030"
SPREAD_CEILING = 0.8
LOTS_PER_LEG = .01
OUNCES_PER_LOT_ASSUMED = 100.
FEES_PER_LOT_SENSITIVITY = 10.


@njit(cache=False)
def replay(ts, bid, ask, window_us, jump, latency_us=200_000,
           stop_distance=4., tp1=2., tp2=4., tp3=8.,
           timeout_us=300_000_000, spread_ceiling=0.8,
           direction_multiplier=1):
    """Tick-for-tick contract matching backtest.simulate's frozen logic.

    Return per-config float array:
    [signals, fills, cancels, TP, STOP, TIME, closed_legs,
     total_pnl, long_pnl, short_pnl, long_fills, short_fills,
     total_closed_long_legs, total_closed_short_legs, max_abs_spike].
    """
    out = np.zeros(15, dtype=np.float64)
    start = 0
    last_signal_us = -10_000_000_000_000_000
    pending = False
    pending_us = -1
    active = False
    direction = 0
    entry = 0.
    entry_us = 0
    leg_open = np.zeros(3, dtype=np.bool_)
    targets = (tp1, tp2, tp3)
    max_abs_spike = 0.

    for i in range(ts.shape[0]):
        now = ts[i]
        b = bid[i]
        a = ask[i]
        spread = a - b
        mid = (b + a) / 2.
        filled_here = False
        closed_here = False

        if pending:
            age = now - pending_us
            if age > 3_000_000:
                pending = False
                out[2] += 1.
            elif age >= latency_us:
                if spread > spread_ceiling:
                    pending = False
                    out[2] += 1.
                else:
                    pending = False
                    active = True
                    entry = a if direction == 1 else b
                    entry_us = now
                    leg_open[0] = True
                    leg_open[1] = True
                    leg_open[2] = True
                    filled_here = True
                    out[1] += 1.
                    if direction == 1:
                        out[10] += 1.
                    else:
                        out[11] += 1.

        if active and not filled_here:
            executable = b if direction == 1 else a
            expired = now - entry_us >= timeout_us
            stop = executable <= entry - stop_distance if direction == 1 else executable >= entry + stop_distance
            for k in range(3):
                if not leg_open[k]:
                    continue
                profit = executable >= entry + targets[k] if direction == 1 else executable <= entry - targets[k]
                if stop:
                    close = executable
                    out[4] += 1.
                elif profit:
                    close = entry + targets[k] if direction == 1 else entry - targets[k]
                    out[3] += 1.
                elif expired:
                    close = executable
                    out[5] += 1.
                else:
                    continue
                move = (close - entry) * direction
                # For 0.01 lots @ hypothetical 100 oz/lot, this is $1 per $1 price move.
                dollars = move * LOTS_PER_LEG * OUNCES_PER_LOT_ASSUMED
                out[7] += dollars
                if direction == 1:
                    out[8] += dollars
                    out[12] += 1.
                else:
                    out[9] += dollars
                    out[13] += 1.
                out[6] += 1.
                leg_open[k] = False
                closed_here = True
            if not leg_open[0] and not leg_open[1] and not leg_open[2]:
                active = False

        # Quote event cannot anchor new trigger if spread ineligible.
        if spread > spread_ceiling:
            start = i + 1
            continue
        cutoff = now - window_us
        while start < i and ts[start] < cutoff:
            start += 1

        if (not active and not pending and not filled_here and not closed_here
                and now - last_signal_us >= 10_000_000 and start < i
                and now > ts[start]):
            anchor_mid = (bid[start] + ask[start]) / 2.
            delta = mid - anchor_mid
            if abs(delta) + 1e-9 >= jump:
                out[0] += 1.
                if abs(delta) > max_abs_spike:
                    max_abs_spike = abs(delta)
                pending = True
                pending_us = now
                direction = (1 if delta > 0 else -1) * direction_multiplier
                last_signal_us = now
                start = i + 1
                continue
    out[14] = max_abs_spike
    return out


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(2**20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_and_sort(archive: Path, month: str, working: Path):
    original = working / "source.csv"
    derived = working / "timestamp_stable_sorted.csv"
    before = None
    inversions = second_precision = n = 0
    with zipfile.ZipFile(archive) as zf:
        paths = [p for p in zf.namelist() if p.lower().endswith(".csv")]
        if len(paths) != 1:
            raise ValueError("Exactly one original source CSV required")
        with zf.open(paths[0]) as src, original.open("wb") as dest:
            for line in src:
                if not line.strip():
                    continue
                stamp = line.split(b",", 1)[0].decode("ascii")
                if not stamp[:6] == month:
                    raise ValueError("Source tick timestamp outside original source month")
                if before is not None and stamp < before:
                    inversions += 1
                before = stamp
                if len(stamp) == 15:
                    second_precision += 1
                n += 1
                dest.write(line)
    if n < 1000:
        raise ValueError("Source too short")
    with derived.open("wb") as dst:
        subprocess.run(
            ["sort", "--stable", "--field-separator=,", "--key=1,1",
             "--buffer-size=128M", "--temporary-directory=" + str(working),
             str(original)], env=dict(os.environ, LC_ALL="C"),
            stdout=dst, check=True,
        )
    return derived, {"original_tick_rows": n, "out_of_order_source_pairs": inversions,
                     "second_precision_rows": second_precision,
                     "original_zip_sha256": sha256(archive),
                     "sorted_csv_sha256": sha256(derived),
                     "source_clock": "HISTDATA_FIXED_EST_UTC_MINUS_05",
                     "original_archive_modified": False}


def load_source(path: Path, month: str, expected_rows: int):
    ts = np.empty(expected_rows, dtype=np.int64)
    bid = np.empty(expected_rows, dtype=np.float64)
    ask = np.empty(expected_rows, dtype=np.float64)
    day_cache = {}
    prev = -1
    with path.open("rt", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for i, fields in enumerate(reader):
            if i >= expected_rows:
                raise ValueError("Source has more rows than preservation count")
            instant, micros, b, a = parse_tick(fields, month=month, day_cache=day_cache)
            stamp_us = instant * 1_000_000 + micros
            if stamp_us < prev:
                raise ValueError("Derived tick timestamps not monotonic")
            prev = stamp_us
            ts[i], bid[i], ask[i] = stamp_us, b, a
    if i + 1 != expected_rows:
        raise ValueError("Source row count mismatch")
    return ts, bid, ask


def run_grid(ts, bid, ask, *, windows=WINDOWS_MS, thresholds=THRESHOLDS_USD):
    cases = []
    for w in windows:
        for jump in thresholds:
            v = replay(ts, bid, ask, w * 1000, jump)
            filled = int(v[1])
            closed = int(v[6])
            net = float(v[7])
            cases.append({
                "window_ms": int(w), "trigger_usd": float(jump),
                "signals": int(v[0]), "filled_bundles": filled,
                "canceled_bundles": int(v[2]), "closed_legs": closed,
                "tp_legs": int(v[3]), "stop_legs": int(v[4]), "timeout_legs": int(v[5]),
                "model_pnl_without_extra_fees_usd": round(net, 3),
                "fee10_model_net_usd": round(net - closed * .1, 3),
                "long_pnl_before_extra_fees_usd": round(float(v[8]), 3),
                "short_pnl_before_extra_fees_usd": round(float(v[9]), 3),
                "long_filled_bundles": int(v[10]), "short_filled_bundles": int(v[11]),
                "long_closed_legs": int(v[12]), "short_closed_legs": int(v[13]),
                "maximum_displacement_observed_on_signals": round(float(v[14]), 3),
                "trade_model": "bid_ask_next_tick_after_200ms_lat_3_leg_0_01lot_100oz_assumption",
                "paper_ready": False,
            })
    return cases


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--period", required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    with tempfile.TemporaryDirectory(prefix="th001_sweep_") as tmp:
        sorted_csv, provenance = verify_and_sort(args.archive, args.period, Path(tmp))
        ts, bid, ask = load_source(sorted_csv, args.period, provenance["original_tick_rows"])
        cases = run_grid(ts, bid, ask)
    baseline = next(x for x in cases if x["window_ms"] == 1500 and x["trigger_usd"] == 3.)
    report = {
        "version": FROZEN_VERSION, "month": args.period, "source": provenance,
        "spread_filter": SPREAD_CEILING, "size_lot_per_leg": LOTS_PER_LEG,
        "hypothetical_ounces_per_standard_lot": OUNCES_PER_LOT_ASSUMED,
        "fee_sensitivity_usd_per_lot_roundtrip": FEES_PER_LOT_SENSITIVITY,
        "latency_model_ms": 200, "stop": -4., "targets": [2., 4., 8.],
        "no_broker_fills_claimed": True, "no_prospective_validation_claimed": True,
        "not_paper_ready": True, "n_trials_in_month": len(cases),
        "baseline_3usd_1500ms": baseline, "cases": cases,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "grid.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("TH001_GRID_SWEEP_RESEARCH", json.dumps({
        "month": args.period, "quotes": provenance["original_tick_rows"],
        "trials": len(cases), "baseline": baseline,
        "positive_fee10_trials": sum(x["fee10_model_net_usd"] > 0 for x in cases),
        "top3_in_sample_fee10": sorted(cases, key=lambda x: x["fee10_model_net_usd"],
                                    reverse=True)[:3],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
