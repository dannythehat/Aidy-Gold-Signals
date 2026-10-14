"""Research-only historical XAUUSD data reader. Never infers absent minute prices.

Uses source EST fixed UTC-05, NOT broker MT5 server time. All emitted bars are
fully closed and made only from verified native HistData M1 rows. No writes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, Iterable, Mapping

from aidy.strategy_lab_data_quality import Bar, SourceContract, validate_bars

SOURCE_ZONE = timezone(timedelta(hours=-5))
SUPPORTED_MINUTES = frozenset((1, 5, 15, 60, 240, 1440))
TABLE = "aidy-signals.aidy_analytics_test.research_candles"
MAX_WINDOW_MINUTES = 10080
EXPECTED_SOURCE = "histdata"
EXPECTED_DATASET = "generic_ascii_m1"
EXPECTED_DERIVATION = "aidy_histdata_source_aligned_v1"
EXPECTED_CLOCK = "EST_FIXED_UTC_MINUS_05"


def _utc(ts: datetime) -> datetime:
    if not isinstance(ts, datetime) or ts.tzinfo is None or ts.utcoffset() != timedelta(0):
        raise ValueError("aware UTC datetime required")
    if ts.second or ts.microsecond:
        raise ValueError("minute-aligned datetime required")
    return ts.astimezone(UTC)


@dataclass(frozen=True)
class Window:
    start_utc: datetime
    end_utc: datetime
    as_of_utc: datetime
    timeframe_minutes: int = 1
    expected_digest: str | None = None

    def validate(self) -> None:
        start, end, as_of = _utc(self.start_utc), _utc(self.end_utc), _utc(self.as_of_utc)
        minutes = int((end - start).total_seconds() // 60)
        if minutes <= 0 or minutes > MAX_WINDOW_MINUTES:
            raise ValueError("window must be positive and at most seven days")
        if (end - start).total_seconds() != minutes * 60:
            raise ValueError("non-whole-minute range")
        if self.timeframe_minutes not in SUPPORTED_MINUTES:
            raise ValueError("unsupported timeframe")
        if as_of < end:
            raise ValueError("future or open candle data not allowed")
        if minutes % self.timeframe_minutes:
            raise ValueError("incomplete timeframe at window boundary")
        for instant in (start, end):
            local = instant.astimezone(SOURCE_ZONE)
            if (local.hour * 60 + local.minute) % self.timeframe_minutes:
                raise ValueError("window not aligned to fixed EST source candle boundary")
        if self.expected_digest is not None and (
            len(self.expected_digest) != 64
            or any(c not in "0123456789abcdef" for c in self.expected_digest)
        ):
            raise ValueError("bad expected digest")


@dataclass(frozen=True)
class ClosedBar:
    open_time_utc: datetime
    available_at_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    price_basis: str = "bid"


@dataclass(frozen=True)
class ReadResult:
    bars: tuple[ClosedBar, ...]
    native_m1_rows: int
    input_digest: str
    source_archive_hashes: tuple[str, ...]
    provenance: str = "retrospective_history"
    pit_eligible: bool = False


def _decimal(value: Any) -> Decimal:
    try:
        d = Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation) as exc:
        raise ValueError("invalid raw source OHLC") from exc
    if not d.is_finite() or d <= 0:
        raise ValueError("non-positive/nonfinite source OHLC")
    return d


def _sha(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        c not in "0123456789abcdef" for c in value
    ):
        raise ValueError("source archive/payload SHA256 absent or invalid")
    return value


def _read_rows(rows: Iterable[Mapping[str, Any]], window: Window) -> ReadResult:
    """Validate external BigQuery row mappings; no implicit sorting or gap repair."""
    window.validate()
    native: list[Bar] = []
    archives: set[str] = set()
    canonical: list[list[str]] = []
    expected_count = int((window.end_utc - window.start_utc).total_seconds() // 60)
    for raw in rows:
        if len(native) >= expected_count:
            raise ValueError("more records than expected: duplicate/foreign source")
        ts = _utc(raw["open_time_utc"])
        if not window.start_utc <= ts < window.end_utc:
            raise ValueError("row outside requested interval")
        expected_local = ts.astimezone(SOURCE_ZONE).strftime("%Y%m%d %H%M%S")
        if raw["source_open_time"] != expected_local:
            raise ValueError("HistData fixed-EST timestamp mismatch")
        if any((raw["source"] != EXPECTED_SOURCE,
                raw["symbol"] != "XAUUSD",
                raw["timeframe"] != "M1",
                raw["price_basis"] != "bid",
                raw["source_dataset"] != EXPECTED_DATASET,
                raw["source_timezone"] != EXPECTED_CLOCK,
                raw["derivation_version"] != EXPECTED_DERIVATION,
                raw["provenance_class"] != "retrospective_history",
                raw["pit_eligible"] is not False,
                raw["derived_from_timeframe"] is not None,
                int(raw["input_rows"]) != 1)):
            raise ValueError("source/timeframe/provenance mismatch")
        archive_sha = _sha(raw["source_file_sha256"])
        payload_sha = _sha(raw["source_payload_sha256"])
        if not raw["source_file"] or not raw["research_identity"]:
            raise ValueError("source file and research identity required")
        contract = SourceContract(
            EXPECTED_SOURCE, "XAUUSD", 1, "bid", EXPECTED_CLOCK,
            EXPECTED_DERIVATION, archive_sha
        )
        contract.validate()
        bar = Bar(ts, *(_decimal(raw[k]) for k in ("open", "high", "low", "close")))
        native.append(bar)
        archives.add(archive_sha)
        canonical.append([ts.isoformat(), raw["research_identity"],
                          archive_sha, payload_sha, raw["source_file"],
                          *[str(v) for v in (bar.open, bar.high, bar.low, bar.close)]])
    if len(native) != expected_count:
        raise ValueError("missing native M1 rows (includes market closures): no calendar inference")
    # Without a trusted source session calendar, every minute in a requested
    # continuous window MUST be present. Do not manufacture a market-open flag.
    gaps = validate_bars(native, SourceContract(
        EXPECTED_SOURCE, "XAUUSD", 1, "bid", EXPECTED_CLOCK,
        EXPECTED_DERIVATION, sorted(archives)[0]
    ))
    if gaps:
        raise ValueError("unclassified M1 gaps; cannot infer closed period")
    if native[0].open_time_utc != window.start_utc:
        raise ValueError("missing first requested minute")
    digest_payload = {"scope":[window.start_utc.isoformat(),window.end_utc.isoformat()],
                      "source_clock":EXPECTED_CLOCK,"native":canonical}
    digest = sha256(json.dumps(digest_payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    if window.expected_digest is not None and window.expected_digest != digest:
        raise ValueError("frozen M1 data digest mismatch")
    result: list[ClosedBar] = []
    stride = window.timeframe_minutes
    for offset in range(0, len(native), stride):
        group = native[offset:offset+stride]
        opened = group[0].open_time_utc
        closed = opened + timedelta(minutes=stride)
        if closed > window.as_of_utc:
            raise ValueError("future candle lookahead")
        result.append(ClosedBar(opened, closed, group[0].open,
                                max(row.high for row in group),
                                min(row.low for row in group), group[-1].close))
    return ReadResult(tuple(result),len(native),digest,tuple(sorted(archives)))


def read_bigquery_window(client: Any, window: Window) -> tuple[ReadResult, str]:
    """Read real native M1 rows with bounded, parameterized SELECT-only BigQuery."""
    from google.cloud import bigquery

    window.validate()
    expected_count = int((window.end_utc - window.start_utc).total_seconds() // 60)
    sql = f"""
        SELECT open_time_utc, open, high, low, close,
               source, symbol, timeframe, price_basis, source_dataset,
               source_timezone, source_open_time, derivation_version,
               provenance_class, pit_eligible, source_file,
               source_file_sha256, source_payload_sha256,
               derived_from_timeframe, input_rows, research_identity
        FROM `{TABLE}`
        WHERE symbol='XAUUSD' AND timeframe='M1' AND source='histdata'
          AND open_time_utc >= @start AND open_time_utc < @end
        ORDER BY open_time_utc
        LIMIT @limit
    """
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start","TIMESTAMP",window.start_utc),
            bigquery.ScalarQueryParameter("end","TIMESTAMP",window.end_utc),
            bigquery.ScalarQueryParameter("limit","INT64",expected_count+1),
        ],
        use_query_cache=False,
        maximum_bytes_billed=1_000_000_000,
    )
    dry = client.query(sql,job_config=bigquery.QueryJobConfig(
        query_parameters=config.query_parameters, dry_run=True,
        use_query_cache=False))
    if int(dry.total_bytes_processed or 0) > 1_000_000_000:
        raise RuntimeError("BigQuery estimated-cost limit")
    job = client.query(sql,job_config=config)
    rows = list(job.result(timeout=120))
    return _read_rows(rows,window),job.job_id
