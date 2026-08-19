from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

import httpx

from aidy.bigquery_exporter import FieldSpec, TableSpec

HISTDATA_SOURCE = "histdata"
HISTDATA_DATASET = "generic_ascii_m1"
HISTDATA_PRICE_BASIS = "bid"
HISTDATA_SOURCE_TIMEZONE = "EST_FIXED_UTC_MINUS_05"
RETROSPECTIVE_PROVENANCE = "retrospective_history"
DERIVATION_VERSION = "aidy_histdata_source_aligned_v1"
HISTDATA_BASE = "https://www.histdata.com"
HISTDATA_REFERER_PREFIX = (
    f"{HISTDATA_BASE}/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/"
)
HISTDATA_DOWNLOAD_URL = f"{HISTDATA_BASE}/get.php"
_SOURCE_TZ = timezone(timedelta(hours=-5))


class _TokenParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.token: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "input":
            return
        values = {name.lower(): value for name, value in attrs}
        if values.get("id") == "tk" and values.get("value"):
            self.token = unescape(str(values["value"])).strip()


_TIMEFRAME_MINUTES = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}
SUPPORTED_TIMEFRAMES = tuple(_TIMEFRAME_MINUTES)

RESEARCH_CANDLES = TableSpec(
    name="research_candles",
    partition_field="open_time_utc",
    clustering_fields=("symbol", "timeframe", "source", "provenance_class"),
    fields=(
        FieldSpec("research_identity", "STRING", "REQUIRED"),
        FieldSpec("candle_key", "STRING", "REQUIRED"),
        FieldSpec("chunk_key", "STRING", "REQUIRED"),
        FieldSpec("provenance_class", "STRING", "REQUIRED"),
        FieldSpec("pit_eligible", "BOOLEAN", "REQUIRED"),
        FieldSpec("symbol", "STRING", "REQUIRED"),
        FieldSpec("timeframe", "STRING", "REQUIRED"),
        FieldSpec("open_time_utc", "TIMESTAMP", "REQUIRED"),
        FieldSpec("source_open_time", "STRING", "REQUIRED"),
        FieldSpec("open", "STRING", "REQUIRED"),
        FieldSpec("high", "STRING", "REQUIRED"),
        FieldSpec("low", "STRING", "REQUIRED"),
        FieldSpec("close", "STRING", "REQUIRED"),
        FieldSpec("price_basis", "STRING", "REQUIRED"),
        FieldSpec("source", "STRING", "REQUIRED"),
        FieldSpec("source_dataset", "STRING", "REQUIRED"),
        FieldSpec("source_file", "STRING", "REQUIRED"),
        FieldSpec("source_file_sha256", "STRING", "REQUIRED"),
        FieldSpec("source_payload_sha256", "STRING", "REQUIRED"),
        FieldSpec("source_timezone", "STRING", "REQUIRED"),
        FieldSpec("ingested_at", "TIMESTAMP", "REQUIRED"),
        FieldSpec("derived_from_timeframe", "STRING"),
        FieldSpec("derivation_version", "STRING", "REQUIRED"),
        FieldSpec("input_rows", "INTEGER", "REQUIRED"),
        FieldSpec("backfill_run_id", "STRING", "REQUIRED"),
    ),
)

RESEARCH_BACKFILL_MANIFEST = TableSpec(
    name="research_backfill_manifest",
    partition_field="ingested_at",
    clustering_fields=("source", "symbol", "status"),
    fields=(
        FieldSpec("backfill_identity", "STRING", "REQUIRED"),
        FieldSpec("chunk_key", "STRING", "REQUIRED"),
        FieldSpec("source", "STRING", "REQUIRED"),
        FieldSpec("source_dataset", "STRING", "REQUIRED"),
        FieldSpec("symbol", "STRING", "REQUIRED"),
        FieldSpec("source_period", "STRING", "REQUIRED"),
        FieldSpec("request_signature", "STRING", "REQUIRED"),
        FieldSpec("requested_timeframes", "STRING", "REPEATED"),
        FieldSpec("derivation_version", "STRING", "REQUIRED"),
        FieldSpec("source_file", "STRING", "REQUIRED"),
        FieldSpec("source_file_sha256", "STRING", "REQUIRED"),
        FieldSpec("source_payload_sha256", "STRING", "REQUIRED"),
        FieldSpec("source_status_report_sha256", "STRING"),
        FieldSpec("source_timezone", "STRING", "REQUIRED"),
        FieldSpec("provenance_class", "STRING", "REQUIRED"),
        FieldSpec("pit_eligible", "BOOLEAN", "REQUIRED"),
        FieldSpec("first_open_time_utc", "TIMESTAMP", "REQUIRED"),
        FieldSpec("last_open_time_utc", "TIMESTAMP", "REQUIRED"),
        FieldSpec("m1_rows", "INTEGER", "REQUIRED"),
        FieldSpec("duplicate_rows", "INTEGER", "REQUIRED"),
        FieldSpec("gap_count", "INTEGER", "REQUIRED"),
        FieldSpec("max_gap_seconds", "INTEGER", "REQUIRED"),
        FieldSpec("timeframe_counts", "JSON", "REQUIRED"),
        FieldSpec("ingested_at", "TIMESTAMP", "REQUIRED"),
        FieldSpec("run_id", "STRING", "REQUIRED"),
        FieldSpec("status", "STRING", "REQUIRED"),
    ),
)


@dataclass(frozen=True, slots=True)
class HistDataPeriod:
    year: int
    month: int | None = None

    def __post_init__(self) -> None:
        if self.year < 2000:
            raise ValueError("HistData period year must be 2000 or later.")
        if self.month is not None and not 1 <= self.month <= 12:
            raise ValueError("HistData month must be between 1 and 12.")

    @property
    def key(self) -> str:
        return f"{self.year:04d}{self.month:02d}" if self.month is not None else f"{self.year:04d}"

    @property
    def referer(self) -> str:
        suffix = f"xauusd/{self.year}"
        if self.month is not None:
            suffix += f"/{self.month}"
        return HISTDATA_REFERER_PREFIX + suffix

    @property
    def expected_zip_name(self) -> str:
        return f"DAT_ASCII_XAUUSD_M1_{self.key}.zip"


@dataclass(frozen=True, slots=True)
class HistDataArchive:
    period: HistDataPeriod
    zip_name: str
    zip_sha256: str
    payload_name: str
    payload_sha256: str
    payload_text: str
    status_report_sha256: str | None


@dataclass(frozen=True, slots=True)
class SourceBar:
    source_time: datetime
    source_open_time: str
    open: str
    high: str
    low: str
    close: str

    @property
    def open_time_utc(self) -> datetime:
        return self.source_time.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class ParseStats:
    rows: int
    duplicate_rows: int
    gap_count: int
    max_gap_seconds: int


@dataclass(frozen=True, slots=True)
class ResearchCandle:
    symbol: str
    timeframe: str
    source_time: datetime
    source_open_time: str
    open: str
    high: str
    low: str
    close: str
    chunk_key: str
    source_file: str
    source_file_sha256: str
    source_payload_sha256: str
    ingested_at: datetime
    backfill_run_id: str
    derived_from_timeframe: str | None
    input_rows: int

    @property
    def open_time_utc(self) -> datetime:
        return self.source_time.astimezone(UTC)

    @property
    def candle_key(self) -> str:
        raw = (
            f"{HISTDATA_SOURCE}\0{self.symbol}\0{self.timeframe}\0"
            f"{self.open_time_utc.isoformat()}"
        )
        return sha256(raw.encode()).hexdigest()

    @property
    def research_identity(self) -> str:
        raw = "\0".join(
            (
                self.candle_key,
                self.source_file_sha256,
                self.source_payload_sha256,
                self.open,
                self.high,
                self.low,
                self.close,
                str(self.input_rows),
                DERIVATION_VERSION,
            )
        )
        return sha256(raw.encode()).hexdigest()

    def to_row(self) -> dict[str, object]:
        if self.ingested_at.tzinfo is None:
            raise ValueError("Research candle ingested_at must be timezone-aware.")
        if self.timeframe not in SUPPORTED_TIMEFRAMES:
            raise ValueError(f"Unsupported research timeframe: {self.timeframe}")
        return {
            "research_identity": self.research_identity,
            "candle_key": self.candle_key,
            "chunk_key": self.chunk_key,
            "provenance_class": RETROSPECTIVE_PROVENANCE,
            "pit_eligible": False,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "open_time_utc": self.open_time_utc.isoformat(),
            "source_open_time": self.source_open_time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "price_basis": HISTDATA_PRICE_BASIS,
            "source": HISTDATA_SOURCE,
            "source_dataset": HISTDATA_DATASET,
            "source_file": self.source_file,
            "source_file_sha256": self.source_file_sha256,
            "source_payload_sha256": self.source_payload_sha256,
            "source_timezone": HISTDATA_SOURCE_TIMEZONE,
            "ingested_at": self.ingested_at.astimezone(UTC).isoformat(),
            "derived_from_timeframe": self.derived_from_timeframe,
            "derivation_version": DERIVATION_VERSION,
            "input_rows": self.input_rows,
            "backfill_run_id": self.backfill_run_id,
        }


def chunk_key(*, symbol: str, period: HistDataPeriod) -> str:
    raw = f"{HISTDATA_SOURCE}\0{HISTDATA_DATASET}\0{symbol}\0{period.key}"
    return sha256(raw.encode()).hexdigest()


def _token_from_html(html: str) -> str:
    parser = _TokenParser()
    parser.feed(html)
    token = (parser.token or "").strip()
    if not token:
        raise RuntimeError("HistData download page did not expose the expected download token.")
    return token


def download_histdata_period(
    period: HistDataPeriod,
    *,
    cache_dir: Path,
    client: httpx.Client | None = None,
) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    destination = cache_dir / period.expected_zip_name
    if destination.exists() and destination.stat().st_size > 0:
        _validate_zip(destination.read_bytes())
        return destination

    owns_client = client is None
    if client is None:
        client = httpx.Client(
            follow_redirects=True,
            timeout=60.0,
            headers={"User-Agent": "AIDY-Signals-Research-Backfill/1.0"},
        )
    try:
        page = client.get(period.referer)
        page.raise_for_status()
        token = _token_from_html(page.text)
        form = {
            "tk": token,
            "date": str(period.year),
            "datemonth": period.key,
            "platform": "ASCII",
            "timeframe": "M1",
            "fxpair": "XAUUSD",
        }
        response = client.post(
            HISTDATA_DOWNLOAD_URL,
            data=form,
            headers={
                "Origin": HISTDATA_BASE,
                "Referer": period.referer,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        response.raise_for_status()
        raw = response.content
        _validate_zip(raw)
        destination.write_bytes(raw)
        return destination
    finally:
        if owns_client:
            client.close()


def _validate_zip(raw: bytes) -> None:
    if len(raw) < 100:
        raise RuntimeError("HistData response was too small to be a valid archive.")
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        raise RuntimeError("HistData response was not a ZIP archive.")


def read_histdata_archive(path: Path, period: HistDataPeriod) -> HistDataArchive:
    raw = path.read_bytes()
    _validate_zip(raw)
    zip_digest = sha256(raw).hexdigest()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = [name for name in archive.namelist() if not name.endswith("/")]
        csv_members = [name for name in members if name.lower().endswith(".csv")]
        if len(csv_members) != 1:
            raise RuntimeError(
                f"HistData archive must contain exactly one CSV payload; found {len(csv_members)}."
            )
        payload_name = csv_members[0]
        payload_raw = archive.read(payload_name)
        try:
            payload_text = payload_raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            payload_text = payload_raw.decode("latin-1")
        report_members = [
            name for name in members if name.lower().endswith(".txt") and name != payload_name
        ]
        status_digest = None
        if report_members:
            report_bytes = b"\0".join(archive.read(name) for name in sorted(report_members))
            status_digest = sha256(report_bytes).hexdigest()
    return HistDataArchive(
        period=period,
        zip_name=path.name,
        zip_sha256=zip_digest,
        payload_name=payload_name,
        payload_sha256=sha256(payload_raw).hexdigest(),
        payload_text=payload_text,
        status_report_sha256=status_digest,
    )


def _decimal(value: str, *, field: str, line_number: int) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid {field} at HistData line {line_number}: {value!r}") from exc
    if not parsed.is_finite():
        raise ValueError(f"Non-finite {field} at HistData line {line_number}: {value!r}")
    return parsed


def _parse_source_time(raw: str, *, line_number: int) -> datetime:
    try:
        parsed = datetime.strptime(f"{raw}-0500", "%Y%m%d %H%M%S%z")
    except ValueError as exc:
        raise ValueError(f"Invalid HistData timestamp at line {line_number}: {raw!r}") from exc
    if parsed.second != 0:
        raise ValueError(f"HistData M1 timestamp is not minute-aligned at line {line_number}.")
    return parsed.astimezone(_SOURCE_TZ)


def parse_histdata_m1(payload_text: str) -> tuple[list[SourceBar], ParseStats]:
    reader = csv.reader(io.StringIO(payload_text), delimiter=";")
    bars: list[SourceBar] = []
    duplicate_rows = 0
    gap_count = 0
    max_gap_seconds = 0
    previous: SourceBar | None = None

    for line_number, row in enumerate(reader, start=1):
        if not row or all(not value.strip() for value in row):
            continue
        if len(row) < 5:
            raise ValueError(
                f"HistData M1 row {line_number} has {len(row)} fields; expected at least 5."
            )
        source_open_time = row[0].strip()
        source_time = _parse_source_time(source_open_time, line_number=line_number)
        values = [value.strip() for value in row[1:5]]
        open_dec, high_dec, low_dec, close_dec = (
            _decimal(value, field=field, line_number=line_number)
            for value, field in zip(values, ("open", "high", "low", "close"), strict=True)
        )
        if high_dec < max(open_dec, low_dec, close_dec):
            raise ValueError(f"HistData high invariant failed at line {line_number}.")
        if low_dec > min(open_dec, high_dec, close_dec):
            raise ValueError(f"HistData low invariant failed at line {line_number}.")
        candidate = SourceBar(
            source_time=source_time,
            source_open_time=source_open_time,
            open=values[0],
            high=values[1],
            low=values[2],
            close=values[3],
        )
        if previous is not None:
            delta_seconds = int((candidate.source_time - previous.source_time).total_seconds())
            if delta_seconds < 0:
                raise ValueError(f"HistData M1 rows are out of order at line {line_number}.")
            if delta_seconds == 0:
                if candidate != previous:
                    raise ValueError(
                        f"Conflicting duplicate HistData M1 candle at line {line_number}."
                    )
                duplicate_rows += 1
                continue
            if delta_seconds > 60:
                gap_count += 1
                max_gap_seconds = max(max_gap_seconds, delta_seconds)
        bars.append(candidate)
        previous = candidate

    if not bars:
        raise RuntimeError("HistData payload contained no M1 candles.")
    return bars, ParseStats(
        rows=len(bars),
        duplicate_rows=duplicate_rows,
        gap_count=gap_count,
        max_gap_seconds=max_gap_seconds,
    )


def _source_bucket_start(source_time: datetime, timeframe: str) -> datetime:
    if source_time.tzinfo != _SOURCE_TZ:
        source_time = source_time.astimezone(_SOURCE_TZ)
    if timeframe == "D1":
        return source_time.replace(hour=0, minute=0, second=0, microsecond=0)
    minutes = _TIMEFRAME_MINUTES[timeframe]
    minute_of_day = source_time.hour * 60 + source_time.minute
    bucket_minute = (minute_of_day // minutes) * minutes
    return source_time.replace(
        hour=bucket_minute // 60,
        minute=bucket_minute % 60,
        second=0,
        microsecond=0,
    )


def _aggregate_group(
    group: list[SourceBar],
    *,
    timeframe: str,
    symbol: str,
    source_file: str,
    source_file_sha256: str,
    source_payload_sha256: str,
    chunk: str,
    ingested_at: datetime,
    backfill_run_id: str,
) -> ResearchCandle:
    high_bar = max(group, key=lambda item: Decimal(item.high))
    low_bar = min(group, key=lambda item: Decimal(item.low))
    start = _source_bucket_start(group[0].source_time, timeframe)
    return ResearchCandle(
        symbol=symbol,
        timeframe=timeframe,
        source_time=start,
        source_open_time=start.strftime("%Y%m%d %H%M%S"),
        open=group[0].open,
        high=high_bar.high,
        low=low_bar.low,
        close=group[-1].close,
        chunk_key=chunk,
        source_file=source_file,
        source_file_sha256=source_file_sha256,
        source_payload_sha256=source_payload_sha256,
        ingested_at=ingested_at,
        backfill_run_id=backfill_run_id,
        derived_from_timeframe="M1",
        input_rows=len(group),
    )


def build_research_candles(
    bars: list[SourceBar],
    *,
    timeframes: Iterable[str],
    symbol: str,
    archive: HistDataArchive,
    ingested_at: datetime,
    backfill_run_id: str,
) -> dict[str, list[ResearchCandle]]:
    if ingested_at.tzinfo is None:
        raise ValueError("Backfill ingested_at must be timezone-aware.")
    requested = tuple(dict.fromkeys(value.upper() for value in timeframes))
    invalid = [value for value in requested if value not in SUPPORTED_TIMEFRAMES]
    if invalid:
        raise ValueError("Unsupported research timeframes: " + ", ".join(invalid))
    if not requested:
        raise ValueError("At least one research timeframe is required.")

    chunk = chunk_key(symbol=symbol, period=archive.period)
    result: dict[str, list[ResearchCandle]] = {}
    if "M1" in requested:
        result["M1"] = [
            ResearchCandle(
                symbol=symbol,
                timeframe="M1",
                source_time=bar.source_time,
                source_open_time=bar.source_open_time,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                chunk_key=chunk,
                source_file=archive.zip_name,
                source_file_sha256=archive.zip_sha256,
                source_payload_sha256=archive.payload_sha256,
                ingested_at=ingested_at,
                backfill_run_id=backfill_run_id,
                derived_from_timeframe=None,
                input_rows=1,
            )
            for bar in bars
        ]

    for timeframe in requested:
        if timeframe == "M1":
            continue
        grouped: list[ResearchCandle] = []
        current_key: datetime | None = None
        current_group: list[SourceBar] = []
        for bar in bars:
            key = _source_bucket_start(bar.source_time, timeframe)
            if current_key is None:
                current_key = key
            if key != current_key:
                grouped.append(
                    _aggregate_group(
                        current_group,
                        timeframe=timeframe,
                        symbol=symbol,
                        source_file=archive.zip_name,
                        source_file_sha256=archive.zip_sha256,
                        source_payload_sha256=archive.payload_sha256,
                        chunk=chunk,
                        ingested_at=ingested_at,
                        backfill_run_id=backfill_run_id,
                    )
                )
                current_group = []
                current_key = key
            current_group.append(bar)
        if current_group:
            grouped.append(
                _aggregate_group(
                    current_group,
                    timeframe=timeframe,
                    symbol=symbol,
                    source_file=archive.zip_name,
                    source_file_sha256=archive.zip_sha256,
                    source_payload_sha256=archive.payload_sha256,
                    chunk=chunk,
                    ingested_at=ingested_at,
                    backfill_run_id=backfill_run_id,
                )
            )
        result[timeframe] = grouped
    return result


def request_signature(timeframes: Iterable[str]) -> str:
    requested = tuple(sorted(dict.fromkeys(value.upper() for value in timeframes)))
    if not requested:
        raise ValueError("Backfill request requires at least one timeframe.")
    invalid = [value for value in requested if value not in SUPPORTED_TIMEFRAMES]
    if invalid:
        raise ValueError("Unsupported research timeframes: " + ", ".join(invalid))
    raw = "\0".join((",".join(requested), DERIVATION_VERSION))
    return sha256(raw.encode()).hexdigest()


def backfill_identity(
    *,
    archive: HistDataArchive,
    symbol: str,
    timeframes: Iterable[str],
) -> str:
    requested = tuple(sorted(dict.fromkeys(value.upper() for value in timeframes)))
    raw = "\0".join(
        (
            chunk_key(symbol=symbol, period=archive.period),
            archive.zip_sha256,
            archive.payload_sha256,
            request_signature(requested),
        )
    )
    return sha256(raw.encode()).hexdigest()


def manifest_row(
    *,
    archive: HistDataArchive,
    symbol: str,
    timeframes: Iterable[str],
    stats: ParseStats,
    candles: dict[str, list[ResearchCandle]],
    ingested_at: datetime,
    run_id: str,
    status: str = "success",
) -> dict[str, object]:
    requested = tuple(dict.fromkeys(value.upper() for value in timeframes))
    if not candles or not candles.get("M1"):
        raise ValueError("Manifest requires parsed M1 research candles.")
    all_candles = [candle for values in candles.values() for candle in values]
    counts = {timeframe: len(candles.get(timeframe, ())) for timeframe in requested}
    first_open = min(candle.open_time_utc for candle in all_candles)
    last_open = max(candle.open_time_utc for candle in all_candles)
    return {
        "backfill_identity": backfill_identity(
            archive=archive, symbol=symbol, timeframes=requested
        ),
        "chunk_key": chunk_key(symbol=symbol, period=archive.period),
        "source": HISTDATA_SOURCE,
        "source_dataset": HISTDATA_DATASET,
        "symbol": symbol,
        "source_period": archive.period.key,
        "request_signature": request_signature(requested),
        "requested_timeframes": list(requested),
        "derivation_version": DERIVATION_VERSION,
        "source_file": archive.zip_name,
        "source_file_sha256": archive.zip_sha256,
        "source_payload_sha256": archive.payload_sha256,
        "source_status_report_sha256": archive.status_report_sha256,
        "source_timezone": HISTDATA_SOURCE_TIMEZONE,
        "provenance_class": RETROSPECTIVE_PROVENANCE,
        "pit_eligible": False,
        "first_open_time_utc": first_open.isoformat(),
        "last_open_time_utc": last_open.isoformat(),
        "m1_rows": stats.rows,
        "duplicate_rows": stats.duplicate_rows,
        "gap_count": stats.gap_count,
        "max_gap_seconds": stats.max_gap_seconds,
        "timeframe_counts": counts,
        "ingested_at": ingested_at.astimezone(UTC).isoformat(),
        "run_id": run_id,
        "status": status,
    }


def planned_periods(
    start_year: int,
    end_year: int,
    *,
    current_date: datetime,
) -> tuple[HistDataPeriod, ...]:
    if start_year > end_year:
        raise ValueError("Backfill start_year cannot be after end_year.")
    if end_year > current_date.year:
        raise ValueError("Backfill cannot request future years.")
    periods: list[HistDataPeriod] = []
    for year in range(start_year, end_year + 1):
        if year < current_date.year:
            periods.append(HistDataPeriod(year))
            continue
        for month in range(1, current_date.month + 1):
            periods.append(HistDataPeriod(year, month))
    return tuple(periods)


def merge_sql(*, project: str, dataset: str) -> str:
    columns = [field.name for field in RESEARCH_CANDLES.fields]
    column_sql = ", ".join(f"`{name}`" for name in columns)
    values_sql = ", ".join(f"S.`{name}`" for name in columns)
    return f"""
MERGE `{project}.{dataset}.{RESEARCH_CANDLES.name}` AS T
USING (
  SELECT {column_sql}
  FROM `{project}.{dataset}._stage_{RESEARCH_CANDLES.name}`
  WHERE _backfill_run_id = @run_id
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY research_identity ORDER BY _backfill_run_id
  ) = 1
) AS S
ON T.research_identity = S.research_identity
WHEN NOT MATCHED THEN
  INSERT ({column_sql}) VALUES ({values_sql})
""".strip()


def manifest_merge_sql(*, project: str, dataset: str) -> str:
    columns = [field.name for field in RESEARCH_BACKFILL_MANIFEST.fields]
    column_sql = ", ".join(f"`{name}`" for name in columns)
    values_sql = ", ".join(f"S.`{name}`" for name in columns)
    return f"""
MERGE `{project}.{dataset}.{RESEARCH_BACKFILL_MANIFEST.name}` AS T
USING (
  SELECT {column_sql}
  FROM `{project}.{dataset}._stage_{RESEARCH_BACKFILL_MANIFEST.name}`
  WHERE _backfill_run_id = @run_id
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY backfill_identity ORDER BY _backfill_run_id
  ) = 1
) AS S
ON T.backfill_identity = S.backfill_identity
WHEN NOT MATCHED THEN
  INSERT ({column_sql}) VALUES ({values_sql})
""".strip()


def stage_fields(spec: TableSpec) -> tuple[FieldSpec, ...]:
    return (FieldSpec("_backfill_run_id", "STRING", "REQUIRED"),) + spec.fields
