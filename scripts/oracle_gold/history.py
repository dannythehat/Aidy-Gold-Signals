"""Immutable, read-only yearly history snapshots; no cloud writes or repair."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from scripts.strategy_lab.s010_run_12month_history import retrieve_month


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def write_snapshot(out, rows, receipts, identity):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if (out / "manifest.json").exists():
        raise ValueError("Immutable snapshot already exists")
    times = [r["open_time_utc"] for r in rows]
    if not rows or times != sorted(set(times)):
        raise ValueError("Missing, duplicated or unordered history")
    if any(r["m1_count"] != 60 for r in rows):
        raise ValueError("Incomplete H1 admitted")
    manifest = {"schema": "oracle.gold.year_snapshot.v1", "identity": identity,
                "rows_sha256": digest(rows), "receipts": receipts,
                "rows": len(rows), "first_utc": times[0], "last_utc": times[-1],
                "source_months_verified": len(receipts),
                "calendar_market_completeness_verified": False,
                "exclusion": "Only occupied hours with all 60 M1 present admitted; gaps are not repaired",
                "h1_gap_count": sum((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds()
                                    != 3600 for a, b in zip(times, times[1:])),
                "broker_parity": False, "sealed_oos": False}
    manifest["sha256"] = digest(manifest)
    (out / "rows.json").write_text(json.dumps(rows, sort_keys=True) + "\n")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    with (out / "hourly.csv").open("w", newline="") as stream:
        w = csv.DictWriter(stream, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return manifest


def load_snapshot(root):
    root = Path(root)
    m = json.loads((root / "manifest.json").read_text())
    expected = m.pop("sha256")
    if digest(m) != expected:
        raise ValueError("Manifest tampered")
    m["sha256"] = expected
    rows = json.loads((root / "rows.json").read_text())
    if digest(rows) != m["rows_sha256"] or len(rows) != m["rows"]:
        raise ValueError("Snapshot rows tampered")
    return rows, m


def bigquery_year(year, out):
    from google.cloud import bigquery
    from google.oauth2 import service_account
    info = json.loads(os.environ["AIDY_GCP_SERVICE_ACCOUNT_JSON"])
    client = bigquery.Client(project=info["project_id"], location="EU",
        credentials=service_account.Credentials.from_service_account_info(info))
    rows, receipts = [], []
    for month in range(1, 13):
        start = datetime(year, month, 1, tzinfo=UTC)
        end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=UTC)
        values, receipt = retrieve_month(client, start, end)
        rows.extend(values)
        receipts.append(receipt)
        print("SOURCE_MONTH", year, month, len(values), receipt["query_job_id"], flush=True)
    return write_snapshot(out, rows, receipts, f"BIGQUERY_HISTDATA_M1_BID_{year}")


def r2_year(year, root, out):
    rows, receipts = [], []
    for month in range(1, 13):
        period = f"{year}{month:02d}"
        folder = Path(root) / f"oracle-gold-r2-{period}"
        receipt = json.loads((folder / "receipt.json").read_text())
        with (folder / "hourly.csv").open() as f:
            values = list(csv.DictReader(f))
        values = [{k: (v if k == "open_time_utc" else int(v) if k == "m1_count" else float(v))
                   for k, v in r.items()} for r in values]
        if (receipt["source_month_fixed_est"] != period
                or receipt["complete_utc_h1"] != len(values)
                or receipt["derived_h1_sha256"] != digest(values)
                or receipt["raw_source_modified"] is not False):
            raise ValueError("R2 monthly receipt mismatch")
        receipts.append(receipt)
        # Fixed EST month can extend into the next UTC year. Explicit UTC filter.
        rows.extend(r for r in values if r["open_time_utc"].startswith(str(year)))
    rows.sort(key=lambda r: r["open_time_utc"])
    return write_snapshot(out, rows, receipts, f"R2_HISTDATA_TICKS_H1_BID_{year}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--r2-root", type=Path)
    args = p.parse_args()
    try:
        m = (r2_year(args.year, args.r2_root, args.out) if args.r2_root
             else bigquery_year(args.year, args.out))
        print("SNAPSHOT_VERIFIED", json.dumps(m, sort_keys=True), flush=True)
    except Exception as exc:
        args.out.mkdir(parents=True, exist_ok=True)
        # No exception text: auth/service messages can contain sensitive context.
        (args.out / "BLOCKED.json").write_text(json.dumps({"year": args.year,
            "status": "BLOCKED_DATA_ACCESS_OR_INTEGRITY", "error_type": type(exc).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
