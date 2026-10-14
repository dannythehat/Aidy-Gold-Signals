"""Acquire original HistData XAUUSD tick ZIPs to a private R2 research prefix.

Year-scoped; verify every source tick before upload; never touch live/research BigQuery.
Per-month errors are recorded and do not erase successfully archived months.
"""
import argparse
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from aidy.historical_spread import (
    HistDataTickPeriod,
    download_histdata_tick_period,
    iter_histdata_ticks,
    tick_archive_meta,
)

parser = argparse.ArgumentParser()
parser.add_argument("--year", type=int, required=True)
args = parser.parse_args()
if not 2020 <= args.year <= 2026:
    raise SystemExit("Year not in approved 2020-2026 research window")

root = Path("artifacts") / str(args.year)
root.mkdir(parents=True, exist_ok=True)
months = range(1, 10) if args.year == 2026 else range(1, 13)
results = []

for month in months:
    period = HistDataTickPeriod(args.year, month)
    outcome = {"period": period.key}
    try:
        path = download_histdata_tick_period(period, cache_dir=root)
        meta = tick_archive_meta(path)
        first = last = None
        count = 0
        for tick in iter_histdata_ticks(path):
            count += 1
            first = first or tick.source_tick_time_utc
            last = tick.source_tick_time_utc
        if not count:
            raise ValueError("empty genuine tick archive")
        key = f"strategy-lab/histdata/xauusd/ticks/{period.key}/{path.name}"
        cmd = [
            "npx", "--yes", "wrangler@4", "r2", "object", "put",
            "aidy-memory-test/" + key,
            "--remote", "--file", str(path),
            "--content-type", "application/zip",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode:
            raise RuntimeError("R2_UPLOAD_NOT_CONFIRMED")
        outcome.update({
            "status": "ARCHIVED_R2",
            "bucket": "aidy-memory-test", "object_key": key,
            "source_zip_sha256": meta.source_file_sha256,
            "source_payload_sha256": meta.source_payload_sha256,
            "zip_bytes": path.stat().st_size,
            "tick_rows": count,
            "first_tick_utc": first.isoformat(),
            "last_tick_utc": last.isoformat(),
        })
        # The durable copy is R2; retain only manifest as GitHub artifact.
        path.unlink()
    except Exception as exc:
        outcome.update({"status": "FAILED", "error_type": type(exc).__name__,
                        "message": str(exc) if str(exc) in ("R2_UPLOAD_NOT_CONFIRMED", "empty genuine tick archive") else "source download, validation or archive error"})
    results.append(outcome)
    (root / "manifest.json").write_text(json.dumps({
        "year": args.year,
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "status": "PASS" if all(x["status"] == "ARCHIVED_R2" for x in results) else "PARTIAL",
        "months": results,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"{period.key}: {outcome['status']}", flush=True)
    time.sleep(2)

if any(x["status"] != "ARCHIVED_R2" for x in results):
    raise SystemExit(1)
