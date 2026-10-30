"""One-month genuine-source R2 tick pilot; read-only, no broker/production writes.

Preserves original HistData ZIP byte-for-byte. Stable-sort raw CSV to a temporary
derived file, then run causal research-only Trigger Happy quote replay.
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
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from aidy.strategy_lab_crossfire_tick_2021 import parse_tick
from research.strategy_lab.trigger_happy.backtest import Config, Quote, simulate


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def input_report_and_sort(archive: Path, period: str, scratch: Path) -> tuple[Path, dict]:
    """Original payload is never reordered in-place or persisted to R2."""
    if not (len(period) == 6 and period.isdigit()
            and 2020 <= int(period[:4]) <= 2030
            and 1 <= int(period[4:]) <= 12):
        raise ValueError("Invalid YYYYMM source period")
    original = scratch / "original_source_order.csv"
    derived = scratch / "derived_timestamp_sorted.csv"
    count = out_of_order = second_only = 0
    prev_stamp = None
    digest = hashlib.sha256()
    with zipfile.ZipFile(archive) as zf:
        entries = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if len(entries) != 1:
            raise ValueError("Original source ZIP must contain exactly one CSV")
        with zf.open(entries[0]) as src, original.open("wb") as output:
            for line in src:
                digest.update(line)
                if not line.strip():
                    continue
                # Decode only enough to audit timestamp and source order.
                stamp = line.split(b",", 1)[0].decode("ascii", errors="strict")
                if prev_stamp is not None and stamp < prev_stamp:
                    out_of_order += 1
                prev_stamp = stamp
                second_only += len(stamp) == 15
                count += 1
                output.write(line)
    if count < 1000:
        raise ValueError("Original source has insufficient ticks")
    environ = dict(os.environ, LC_ALL="C")
    with derived.open("wb") as dest:
        subprocess.run(["sort", "--stable", "--field-separator=,",
                        "--key=1,1", "--buffer-size=128M",
                        "--temporary-directory=" + str(scratch),
                        str(original)], stdout=dest, env=environ, check=True)
    # To avoid accidental reuse of an unverified derivative, save its hash.
    report = {
        "month": period, "original_zip_sha256": sha256_file(archive),
        "source_payload_sha256": digest.hexdigest(),
        "derived_sorted_csv_sha256": sha256_file(derived),
        "original_source_tick_rows": count,
        "source_order_inversions_observed": out_of_order,
        "seconds_only_timestamps_observed": second_only,
        "time_contract": "HISTDATA_FIXED_EST_UTC_MINUS_05",
        "derivation": "LC_ALL_C_STABLE_TIMESTAMP_SORT_V1",
        "raw_original_modified": False,
        "broker_order_executed": False,
    }
    return derived, report


def quotes_from_sorted(path: Path, period: str, stats: dict):
    cache: dict[str, int] = {}
    prev = None
    with path.open("rt", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            epoch, micro, bid, ask = parse_tick(row, month=period, day_cache=cache)
            instant_us = epoch * 1_000_000 + micro
            if prev is not None and instant_us < prev:
                raise ValueError("Non-monotonic timestamp after chronological derivation")
            prev = instant_us
            stats["parsed_ticks"] += 1
            yield Quote(instant_us, bid, ask)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--period", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="th001_source_sort_") as tempdir:
        derived, provenance = input_report_and_sort(
            args.archive, args.period, Path(tempdir))
        stats = {"parsed_ticks": 0}
        result = simulate(quotes_from_sorted(derived, args.period, stats), Config())
        if stats["parsed_ticks"] != provenance["original_source_tick_rows"]:
            raise AssertionError("Derived replay lost source ticks")
    total = result["summary"]["closed_net_pnl_usd_model"]
    model_fee_per_lot = 10.0  # sensitivity assumption, NOT Vantage fee evidence
    costed = total - len(result["closed_legs"]) * 0.01 * model_fee_per_lot
    monthly = Counter()
    direction_counts = Counter()
    reasons = Counter()
    for leg in result["closed_legs"]:
        month = datetime.fromtimestamp(leg["exit_us"] / 1e6, UTC).strftime("%Y-%m")
        monthly[month] += leg["net_pnl_usd"]
        direction_counts[leg["direction"]] += 1
        reasons[leg["exit_reason"]] += 1
    provenance["parsed_sorted_ticks"] = stats["parsed_ticks"]
    provenance["source_data_precision_caveat"] = (
        "HAS_SECOND_ONLY_ROWS - SUBSECOND_EVIDENCE_PARTIAL"
        if provenance["seconds_only_timestamps_observed"]
        else "SOURCE_TIMESTAMP_HAS_FRACTIONAL_SECOND_FIELDS"
    )
    provenance["original_source_independently_attested_by_broker"] = False
    provenance["research_only"] = True
    summary = {
        **result["summary"], "source": provenance,
        "price_pnl_0_additional_fees_usd": round(total, 6),
        "sensitivity_fee_10usd_per_lot_roundtrip_usd": round(costed, 6),
        "target_exit_reasons": dict(reasons),
        "closed_legs_direction_count": dict(direction_counts),
        "closed_gross_monthly_usd": dict(sorted(monthly.items())),
        "sample_status": "EXPLORATORY_ONE_MONTH_NOT_HOLDOUT",
        "performance_claim_ready": False,
        "paper_ready": False,
    }
    (args.out / "source_and_summary.json").write_text(
        json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (args.out / "trades_and_signals.json").write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("TRIGGER_HAPPY_REAL_SOURCE_EXPLORATORY", json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
