"""Read one immutable HistData source tick ZIP to UTC H1 BID + observed ASK.

Historical archive remains byte-unchanged in Cloudflare R2. Source is fixed EST
UTC-05 all year. All raw quotes in a month are validated. Chronology inversions
are handled by an explicitly separate per-minute derived view using earliest/
latest (timestamp, original line) order; raw source SHA never changes.
No broker Vantage execution parity claim, no trading or cloud writes.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

FORMAT = "aidy.crossfire.2021.tick_utc_h1_bidask_v1"
TIME = re.compile(r"^\d{8} \d{6}\d{0,6}$")
SOURCE_OFFSET_SECONDS = 5 * 3600
MINUTES_IN_HOUR = 60


def parse_tick(raw: list[str], *, month: str, day_cache: dict[str, int]) -> tuple[int, int, float, float]:
    if len(raw) < 3:
        raise ValueError("Source quote missing timestamp, BID or ASK")
    stamp = raw[0].strip()
    if not TIME.fullmatch(stamp) or stamp[:6] != month:
        raise ValueError("Timestamp invalid or outside fixed-EST source month")
    day_text = stamp[:8]
    if day_text not in day_cache:
        dt = datetime(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]), tzinfo=UTC)
        day_cache[day_text] = int(dt.timestamp())
    hh, minute, second = int(stamp[9:11]), int(stamp[11:13]), int(stamp[13:15])
    if hh > 23 or minute > 59 or second > 59:
        raise ValueError("Invalid source tick clock")
    micro = int(stamp[15:].ljust(6, "0")) if stamp[15:] else 0
    instant = (day_cache[day_text] + SOURCE_OFFSET_SECONDS
               + 3600*hh + 60*minute + second)
    try:
        bid, ask = float(raw[1]), float(raw[2])
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid BID/ASK source decimal") from exc
    if not all(math.isfinite(x) and x > 0 for x in (bid, ask)) or ask < bid:
        raise ValueError("BID/ASK invalid or reversed")
    return instant, micro, bid, ask


def derive_month_zip(path: Path, period: str) -> tuple[list[dict], dict]:
    if not re.fullmatch(r"20\d{4}", period) or not 1 <= int(period[-2:]) <= 12:
        raise ValueError("Invalid source YYYYMM")
    if not path.is_file():
        raise ValueError("Original monthly archive missing")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    with zipfile.ZipFile(path) as zf:
        source_files = [f for f in zf.namelist() if f.lower().endswith(".csv")]
        if len(source_files) != 1:
            raise ValueError("Expected exactly one original tick CSV")
        payload_name = source_files[0]
        payload_sha = hashlib.sha256()
        with zf.open(payload_name) as source:
            for block in iter(lambda: source.read(1024*1024), b""):
                payload_sha.update(block)
        # Only ~45,000 occupied UTC minutes/month retained, NOT all ~5m ticks.
        minutes: dict[int, dict] = {}
        day_cache: dict[str, int] = {}
        prior = None
        rows = inversions = seconds_only = 0
        with zf.open(payload_name) as source:
            for line_number, line in enumerate(io.TextIOWrapper(
                source, encoding="utf-8-sig", newline="",
            ), 1):
                if not line.strip():
                    continue
                fields = next(csv.reader([line]))
                epoch, micro, bid, ask = parse_tick(fields, month=period, day_cache=day_cache)
                tickkey = epoch * 1000000 + micro
                if prior is not None and tickkey < prior:
                    inversions += 1
                prior = tickkey
                rows += 1
                if len(fields[0].strip()) == 15:
                    seconds_only += 1
                minute = epoch // 60 * 60
                item = minutes.get(minute)
                order = (tickkey, line_number)
                if item is None:
                    minutes[minute] = {
                        "open_order": order, "close_order": order,
                        "open_bid": bid, "open_ask": ask,
                        "close_bid": bid, "close_ask": ask,
                        "high_bid": bid, "low_bid": bid,
                        "max_spread": ask-bid,
                    }
                else:
                    item["high_bid"] = max(item["high_bid"], bid)
                    item["low_bid"] = min(item["low_bid"], bid)
                    item["max_spread"] = max(item["max_spread"], ask-bid)
                    if order < item["open_order"]:
                        item.update(open_order=order, open_bid=bid, open_ask=ask)
                    if order >= item["close_order"]:
                        item.update(close_order=order, close_bid=bid, close_ask=ask)
    if rows < 1000 or not minutes:
        raise ValueError("Insufficient original source ticks for month")
    grouped: dict[int, list[tuple[int, dict]]] = {}
    for minute, item in minutes.items():
        grouped.setdefault(minute // 3600 * 3600, []).append((minute, item))
    hourly = []
    partial = 0
    for hour, values in sorted(grouped.items()):
        values.sort(key=lambda x: x[0])
        if len(values) != MINUTES_IN_HOUR or any(
            m != hour + i*60 for i, (m, _) in enumerate(values)
        ):
            partial += 1
            continue
        first = values[0][1]
        last = values[-1][1]
        hourly.append({
            "open_time_utc": datetime.fromtimestamp(hour, UTC).isoformat(),
            "open": first["open_bid"],
            "high": max(x["high_bid"] for _, x in values),
            "low": min(x["low_bid"] for _, x in values),
            "close": last["close_bid"],
            "m1_count": 60,
            "observed_open_ask": first["open_ask"],
            "observed_open_spread": first["open_ask"]-first["open_bid"],
            "observed_max_spread": max(x["max_spread"] for _,x in values),
        })
    if len(hourly) < 200:
        raise ValueError("Insufficient complete true source-derived H1 BID hours")
    receipt = {
        "source_month_fixed_est": period, "input_zip_sha256": sha,
        "original_csv_payload_sha256": payload_sha.hexdigest(),
        "source_tick_rows": rows, "source_order_inversions": inversions,
        "seconds_only_source_times": seconds_only,
        "occupied_source_minutes": len(minutes),
        "complete_utc_h1": len(hourly), "excluded_incomplete_h1": partial,
        "first_h1_utc": hourly[0]["open_time_utc"],
        "last_h1_utc": hourly[-1]["open_time_utc"],
        "derived_h1_sha256": hashlib.sha256(json.dumps(
            hourly, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest(),
        "normalisation": FORMAT,
        "broker_ask_executable": False,
        "raw_source_modified": False,
        "broker_swap_schedule_attested": False,
    }
    return hourly, receipt


def write_period(path: Path, period: str, output: Path) -> dict:
    rows, receipt = derive_month_zip(path, period)
    output.mkdir(parents=True, exist_ok=True)
    with (output/"hourly.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output/"receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    return receipt
