"""Validate raw HistData gold tick archives for preservation without reordering quotes.

Original compressed source bytes remain unchanged. Chronology anomalies are measured,
not silently fixed or presented as time-ordered backtest inputs.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from aidy.historical_spread import parse_tick_fields, tick_archive_meta

EST_FIXED = timezone(timedelta(hours=-5))
SECONDS_ONLY = re.compile(r"^\d{8} \d{6}$")


@dataclass(frozen=True)
class SourceTickAudit:
    source_zip_sha256: str
    payload_sha256: str
    tick_rows: int
    out_of_order_pairs: int
    second_precision_rows: int
    first_tick_utc: datetime
    last_tick_utc: datetime
    minimum_tick_utc: datetime
    maximum_tick_utc: datetime

    @property
    def chronological(self) -> bool:
        return self.out_of_order_pairs == 0


def audit_source_tick_zip(path: Path, expected_period: str) -> SourceTickAudit:
    if not re.fullmatch(r"20\d{4}", expected_period):
        raise ValueError("expected_period must be canonical YYYYMM")
    month = int(expected_period[4:])
    if month < 1 or month > 12:
        raise ValueError("expected_period month invalid")
    meta = tick_archive_meta(path)
    count = disorder = seconds_only = 0
    first = last = smallest = largest = None
    previous = None
    with zipfile.ZipFile(path) as zf, zf.open(meta.payload_name) as handle:
        reader = csv.reader(io.TextIOWrapper(handle, encoding="utf-8-sig", newline=""))
        for n, fields in enumerate(reader, 1):
            if not fields:
                continue
            if len(fields) < 3:
                raise ValueError(f"Missing bid/ask columns at source row {n}")
            ts = fields[0].strip()
            try:
                quote = parse_tick_fields(ts, fields[1], fields[2])
            except ValueError:
                if not SECONDS_ONLY.fullmatch(ts):
                    raise
                # The source's fixed-EST timezone is explicit; never use system DST.
                parsed = datetime.strptime(ts, "%Y%m%d %H%M%S").replace(tzinfo=EST_FIXED)
                quote = parse_tick_fields(
                    parsed.strftime("%Y%m%d %H%M%S") + "000", fields[1], fields[2]
                )
                seconds_only += 1
            timestamp = quote.source_tick_time_utc
            if timestamp.astimezone(EST_FIXED).strftime("%Y%m") != expected_period:
                raise ValueError(f"Source tick outside requested month at row {n}")
            if previous is not None and timestamp < previous:
                disorder += 1
            first = first or timestamp
            last = timestamp
            smallest = min(smallest, timestamp) if smallest is not None else timestamp
            largest = max(largest, timestamp) if largest is not None else timestamp
            previous = timestamp
            count += 1
    if count < 1000 or first is None or last is None or smallest is None or largest is None:
        raise ValueError("Source tick file has insufficient data")
    return SourceTickAudit(
        meta.source_file_sha256, meta.source_payload_sha256,
        count, disorder, seconds_only, first, last, smallest, largest,
    )
