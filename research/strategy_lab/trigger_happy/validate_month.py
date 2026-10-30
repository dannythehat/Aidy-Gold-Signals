"""Previously unexamined TH001 source months: evaluate two selection-frozen cases.

These months PRECEDE the discovery cohort chronologically, so this is a
previously-unexamined historical replication, NOT forward out-of-sample or a
live-paper trading approval.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from research.strategy_lab.trigger_happy.grid_sweep import (
    load_source,
    replay,
    verify_and_sort,
)


def case_result(ts, bid, ask, cfg: dict):
    v = replay(
        ts, bid, ask, cfg["window_ms"] * 1000, float(cfg["jump_usd"]),
        cfg["latency_ms"] * 1000, float(cfg["stop_usd"]),
        *[float(t) for t in cfg["targets"]],
        cfg["expiry_s"] * 1_000_000, float(cfg["spread_ceiling_usd"]),
        -1 if cfg["direction_rule"] == "FADE" else 1,
    )
    n = int(v[6])
    net = float(v[7])
    return {
        "id": cfg["id"], "direction_rule": cfg["direction_rule"],
        "filled": int(v[1]), "signals": int(v[0]), "closed_legs": n,
        "tp_legs": int(v[3]), "stop_legs": int(v[4]), "time_legs": int(v[5]),
        "long_fills": int(v[10]), "short_fills": int(v[11]),
        "raw_bidask_net_usd": round(net, 3),
        "fee10_net_usd": round(net - n * .1, 3),
        "fee10_plus_extra_slip050_net_usd": round(net - n * .6, 3),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--period", required=True)
    p.add_argument("--candidates", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    manifest = json.loads(args.candidates.read_text())
    if args.period not in manifest["validation_months_not_used_in_selection"]:
        raise ValueError("Not a predeclared validation source month")
    if len(manifest["selected"]) != 2:
        raise ValueError("Frozen two-config selection corrupted")
    with tempfile.TemporaryDirectory(prefix="th001_validation_") as tempdir:
        sorted_csv, source = verify_and_sort(args.archive, args.period, Path(tempdir))
        ts, bid, ask = load_source(sorted_csv, args.period, source["original_tick_rows"])
        cases = [case_result(ts, bid, ask, p) for p in manifest["selected"]]
        baseline = case_result(ts, bid, ask, {
            "id": "ORIGINAL_FOLLOW_BASELINE",
            "direction_rule": "FOLLOW", "window_ms": 1500,
            "jump_usd": 3., "latency_ms": 200,
            "targets": [2., 4., 8.], "stop_usd": 4.,
            "expiry_s": 300, "spread_ceiling_usd": .8,
        })
    doc = {
        "cohort": "PREVIOUSLY_UNEXAMINED_HISTORICAL_BACKWARD_VALIDATION",
        "source_month": args.period, "source": source,
        "frozen_candidate_sha": manifest["frozen_content_sha256"],
        "selected_cases": cases, "original_baseline": baseline,
        "never_traded": True, "broker_fill_not_verified": True,
        "not_formal_prospective_or_chronologically_forward_holdout": True,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "validation_month.json").write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n")
    print("TH001_VALIDATION_MONTH", json.dumps({
        "month": args.period, "sha": manifest["frozen_content_sha256"],
        "quotes": source["original_tick_rows"], "original_sha": source["original_zip_sha256"],
        "selected": cases, "baseline": baseline,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
