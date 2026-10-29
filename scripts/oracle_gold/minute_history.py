"""One authenticated M1 snapshot per source-year; no cloud writes or repair.

Earlier H1 snapshots/replays remain immutable. Finer source resolution is a new
acquisition, reused across all fixed-unit source accounts and chart timeframes.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from aidy.strategy_lab_crossfire_tick_2021 import parse_tick
from scripts.oracle_gold.history import digest

TABLE = "aidy-signals.aidy_analytics_test.research_candles"
CAP = 1_500_000_000
FIELDS = ["open_time_utc", "open", "high", "low", "close"]
ROOT = Path(__file__).resolve().parents[2]


def prior_month(year, month):
    report = json.loads((ROOT/f"reports/gold_oracle/batch01/{year}/report.json").read_text())
    return report["manifest"]["receipts"][month-1]


def write(root, rows, receipts, identity, year):
    root.mkdir(parents=True, exist_ok=True)
    if (root/"manifest.json").exists():
        raise ValueError("Immutable minute snapshot exists")
    times = [r["open_time_utc"] for r in rows]
    if not rows or times != sorted(set(times)):
        raise ValueError("Minute source unordered or duplicate")
    for r in rows:
        stamp = datetime.fromisoformat(r["open_time_utc"])
        if stamp.utcoffset() is None or stamp.utcoffset().total_seconds() != 0 or stamp.second or stamp.microsecond:
            raise ValueError("Minute time is not aligned UTC")
        if not all(math.isfinite(r[k]) for k in FIELDS[1:]) or not (0 < r["low"] <= min(r["open"], r["close"]) <= max(r["open"], r["close"]) <= r["high"]):
            raise ValueError("Invalid minute source OHLC")
    m = {"schema": "oracle.gold.minute_snapshot.v1", "identity": identity, "year": year,
         "rows": len(rows), "rows_sha256": digest(rows), "receipts": receipts,
         "first_utc": times[0], "last_utc": times[-1], "calendar_complete": False,
         "ask_ohlc_available": False, "publisher_volume_available": False,
         "raw_source_modified": False, "sealed_oos": False}
    m["sha256"] = digest(m)
    with (root/"minute.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    (root/"manifest.json").write_text(json.dumps(m, sort_keys=True, indent=2)+"\n")
    return m


def load(root):
    m = json.loads((root/"manifest.json").read_text())
    expected = m.pop("sha256")
    if digest(m) != expected:
        raise ValueError("Minute manifest changed")
    m["sha256"] = expected
    with (root/"minute.csv").open() as f:
        rows = [{k: v if k == "open_time_utc" else float(v) for k, v in r.items()} for r in csv.DictReader(f)]
    if digest(rows) != m["rows_sha256"] or len(rows) != m["rows"]:
        raise ValueError("Minute rows changed")
    return rows, m


def bigquery(year, root):
    from google.cloud import bigquery
    from google.oauth2 import service_account
    info = json.loads(os.environ["AIDY_GCP_SERVICE_ACCOUNT_JSON"])
    client = bigquery.Client(project=info["project_id"], location="EU",
                            credentials=service_account.Credentials.from_service_account_info(info))
    rows, receipts = [], []
    for month in range(1, 13):
        start, end = datetime(year, month, 1, tzinfo=UTC), datetime(year+(month == 12), month % 12+1, 1, tzinfo=UTC)
        sql = f"""SELECT open_time_utc, SAFE_CAST(open AS FLOAT64) AS open,
          SAFE_CAST(high AS FLOAT64) AS high, SAFE_CAST(low AS FLOAT64) AS low,
          SAFE_CAST(close AS FLOAT64) AS close, source_file_sha256, source_payload_sha256,
          COALESCE(source='histdata' AND price_basis='bid' AND source_dataset='generic_ascii_m1'
            AND source_timezone='EST_FIXED_UTC_MINUS_05' AND derivation_version='aidy_histdata_source_aligned_v1'
            AND provenance_class='retrospective_history' AND pit_eligible=FALSE
            AND derived_from_timeframe IS NULL AND input_rows=1
            AND research_identity IS NOT NULL AND source_file IS NOT NULL
            AND source_open_time=FORMAT_TIMESTAMP('%Y%m%d %H%M%S', TIMESTAMP_SUB(open_time_utc,INTERVAL 5 HOUR),'UTC')
            AND REGEXP_CONTAINS(source_file_sha256,r'^[0-9a-f]{{64}}$')
            AND REGEXP_CONTAINS(source_payload_sha256,r'^[0-9a-f]{{64}}$'),FALSE) AS source_valid
          FROM `{TABLE}` WHERE symbol='XAUUSD' AND timeframe='M1'
            AND open_time_utc>=@start AND open_time_utc<@end ORDER BY open_time_utc"""
        params = [bigquery.ScalarQueryParameter("start", "TIMESTAMP", start), bigquery.ScalarQueryParameter("end", "TIMESTAMP", end)]
        dry = client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params, dry_run=True, use_query_cache=False))
        if int(dry.total_bytes_processed or 0) > CAP:
            raise ValueError("Minute monthly scan exceeds cap")
        job = client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params, maximum_bytes_billed=CAP, use_query_cache=False))
        values, archives, payloads = [], set(), set()
        for r in job.result(timeout=240):
            if not r["source_valid"]:
                raise ValueError("Minute original source provenance failed")
            values.append({"open_time_utc": r["open_time_utc"].isoformat(), **{k: float(r[k]) for k in FIELDS[1:]}})
            archives.add(r["source_file_sha256"])
            payloads.add(r["source_payload_sha256"])
        if not values:
            raise ValueError("Missing original minute source month")
        previous = prior_month(year, month)
        if len(values) != previous["observed_native_m1_rows"] or sorted(archives) != previous["source_archive_sha256"]:
            raise ValueError("Historical warehouse source identity changed since batch01")
        receipts.append({"year": year, "month": month, "query_job_id": job.job_id,
            "rows": len(values), "rows_sha256": digest(values), "archive_sha256": sorted(archives),
            "payload_sha256": sorted(payloads), "read_only": True})
        rows.extend(values)
        print("MINUTE_SOURCE_MONTH", year, month, len(values), flush=True)
    return write(root, rows, receipts, f"BIGQUERY_ORIGINAL_HISTDATA_BID_M1_{year}", year)


def r2_month(archive, period, root):
    raw_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    previous_receipt = prior_month(int(period[:4]), int(period[4:]))
    if raw_sha != previous_receipt["input_zip_sha256"]:
        raise ValueError("Original R2 archive changed since batch01")
    minutes, day_cache = {}, {}
    inversions = count = 0
    previous = None
    with zipfile.ZipFile(archive) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError("Original tick payload ambiguous")
        payload_sha = hashlib.sha256()
        with z.open(names[0]) as f:
            for block in iter(lambda: f.read(1024*1024), b""):
                payload_sha.update(block)
        with z.open(names[0]) as f:
            for line_num, line in enumerate(io.TextIOWrapper(f, encoding="utf-8-sig", newline=""), 1):
                if not line.strip():
                    continue
                epoch, micro, bid, _ask = parse_tick(next(csv.reader([line])), month=period, day_cache=day_cache)
                order = (epoch*1_000_000+micro, line_num)
                if previous is not None and order[0] < previous:
                    inversions += 1
                previous = order[0]
                count += 1
                minute = epoch//60*60
                if minute not in minutes:
                    minutes[minute] = [order, order, bid, bid, bid, bid]
                else:
                    item = minutes[minute]
                    item[3], item[4] = max(item[3], bid), min(item[4], bid)
                    if order < item[0]:
                        item[0], item[2] = order, bid
                    if order >= item[1]:
                        item[1], item[5] = order, bid
    rows = [{"open_time_utc": datetime.fromtimestamp(t, UTC).isoformat(),
             "open": v[2], "high": v[3], "low": v[4], "close": v[5]} for t, v in sorted(minutes.items())]
    receipt = {"period": period, "original_archive_sha256": raw_sha, "payload_sha256": payload_sha.hexdigest(),
               "original_tick_rows": count, "source_inversions": inversions, "rows_sha256": digest(rows),
               "clock": "EST_FIXED_UTC_MINUS_05", "chronology": "separate (timestamp,source_line) derivative", "raw_modified": False}
    if payload_sha.hexdigest() != previous_receipt["original_csv_payload_sha256"] or count != previous_receipt["source_tick_rows"]:
        raise ValueError("Original R2 payload differs from batch01")
    return write(root, rows, [receipt], "R2_ORIGINAL_TICKS_BID_M1_"+period, int(period[:4]))


def combine(root, year, out):
    rows, receipts = [], []
    for month in range(1, 13):
        values, m = load(root/f"oracle-minute-{year}{month:02d}")
        rows.extend(r for r in values if r["open_time_utc"].startswith(str(year)))
        receipts.extend(m["receipts"])
    rows.sort(key=lambda r: r["open_time_utc"])
    return write(out, rows, receipts, f"R2_ORIGINAL_TICKS_BID_M1_{year}", year)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=("bigquery", "r2-month", "combine"))
    p.add_argument("--year", type=int)
    p.add_argument("--period")
    p.add_argument("--archive", type=Path)
    p.add_argument("--root", type=Path)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    try:
        m = bigquery(a.year, a.out) if a.mode == "bigquery" else r2_month(a.archive, a.period, a.out) if a.mode == "r2-month" else combine(a.root, a.year, a.out)
        print("MINUTE_SNAPSHOT_VERIFIED", m["rows"], m["rows_sha256"], flush=True)
    except Exception as exc:  # noqa: BLE001 - never print credential-bearing service exception text
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out/"BLOCKED.json").write_text(json.dumps({"status": "BLOCKED_SOURCE_ACCESS_OR_INTEGRITY", "error_type": type(exc).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
