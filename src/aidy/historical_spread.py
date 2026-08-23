from __future__ import annotations

import csv
import io
import json
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx

from aidy.bigquery_exporter import FieldSpec, TableSpec
from aidy.historical_backfill import (
    HISTDATA_BASE,
    HISTDATA_DOWNLOAD_URL,
    RETROSPECTIVE_PROVENANCE,
    _token_from_html,
    _validate_zip,
)

DAY27_VERSION = "aidy_historical_spread_v1"
BASELINE_VERSION = "aidy_spread_weekday_clock15_baseline_v1"
STRATA_VERSION = "aidy_j3_input_strata_v1"
J3_VERSION = "aidy_j3_spread_liquidity_failure_v1"

SUPPORTED_SYMBOL = "XAUUSD"
HISTDATA_TICK_DATASET = "generic_ascii_tick"
HISTDATA_TICK_TIMEZONE = "EST_FIXED_UTC_MINUS_05"
HISTDATA_TICK_DERIVATION_VERSION = "aidy_histdata_tick_last_per_utc_minute_v1"
HISTDATA_TICK_REFERER_PREFIX = (
    f"{HISTDATA_BASE}/download-free-forex-historical-data/?/ascii/tick-data-quotes/"
)
_SOURCE_TZ = timezone(timedelta(hours=-5))
_MIN_BASELINE_BUCKET_N = 20
_MAX_ANCHOR_QUOTE_AGE_SECONDS = 120
_SLOT_MINUTES = 15

RESEARCH_BIDASK_MINUTE_QUOTES = TableSpec(
    name="research_bidask_minute_quotes",
    partition_field="minute_utc",
    clustering_fields=("symbol", "source", "weekday_utc", "clock_slot_15m"),
    fields=(
        FieldSpec("quote_identity", "STRING", "REQUIRED"),
        FieldSpec("provenance_class", "STRING", "REQUIRED"),
        FieldSpec("pit_eligible", "BOOLEAN", "REQUIRED"),
        FieldSpec("symbol", "STRING", "REQUIRED"),
        FieldSpec("minute_utc", "TIMESTAMP", "REQUIRED"),
        FieldSpec("source_tick_time_utc", "TIMESTAMP", "REQUIRED"),
        FieldSpec("bid", "STRING", "REQUIRED"),
        FieldSpec("ask", "STRING", "REQUIRED"),
        FieldSpec("mid", "STRING", "REQUIRED"),
        FieldSpec("spread", "STRING", "REQUIRED"),
        FieldSpec("spread_bps", "STRING", "REQUIRED"),
        FieldSpec("weekday_utc", "INTEGER", "REQUIRED"),
        FieldSpec("clock_slot_15m", "INTEGER", "REQUIRED"),
        FieldSpec("source", "STRING", "REQUIRED"),
        FieldSpec("source_dataset", "STRING", "REQUIRED"),
        FieldSpec("source_file", "STRING", "REQUIRED"),
        FieldSpec("source_file_sha256", "STRING", "REQUIRED"),
        FieldSpec("source_payload_sha256", "STRING", "REQUIRED"),
        FieldSpec("source_timezone", "STRING", "REQUIRED"),
        FieldSpec("derivation_version", "STRING", "REQUIRED"),
        FieldSpec("ingested_at", "TIMESTAMP", "REQUIRED"),
    ),
)

RESEARCH_BIDASK_MANIFEST = TableSpec(
    name="research_bidask_manifest",
    partition_field="ingested_at",
    clustering_fields=("symbol", "source", "source_period"),
    fields=(
        FieldSpec("manifest_digest", "STRING", "REQUIRED"),
        FieldSpec("version", "STRING", "REQUIRED"),
        FieldSpec("symbol", "STRING", "REQUIRED"),
        FieldSpec("source", "STRING", "REQUIRED"),
        FieldSpec("source_dataset", "STRING", "REQUIRED"),
        FieldSpec("source_period", "STRING", "REQUIRED"),
        FieldSpec("source_file", "STRING", "REQUIRED"),
        FieldSpec("source_file_sha256", "STRING", "REQUIRED"),
        FieldSpec("source_payload_sha256", "STRING", "REQUIRED"),
        FieldSpec("source_timezone", "STRING", "REQUIRED"),
        FieldSpec("tick_rows", "INTEGER", "REQUIRED"),
        FieldSpec("minute_quote_rows", "INTEGER", "REQUIRED"),
        FieldSpec("first_tick_utc", "TIMESTAMP", "REQUIRED"),
        FieldSpec("last_tick_utc", "TIMESTAMP", "REQUIRED"),
        FieldSpec("raw_bid_ask_preserved", "BOOLEAN", "REQUIRED"),
        FieldSpec("depth_included", "BOOLEAN", "REQUIRED"),
        FieldSpec("true_exchange_volume_claimed", "BOOLEAN", "REQUIRED"),
        FieldSpec("order_flow_claimed", "BOOLEAN", "REQUIRED"),
        FieldSpec("ingested_at", "TIMESTAMP", "REQUIRED"),
    ),
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Day 27 timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _decimal(value: Any, *, name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{name} must be a finite positive decimal.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a finite positive decimal.") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"{name} must be a finite positive decimal.")
    return parsed


def _fmt(value: Decimal | float | None) -> str | None:
    if value is None:
        return None
    dec = value if isinstance(value, Decimal) else Decimal(str(value))
    if dec == 0:
        return "0"
    with localcontext() as ctx:
        ctx.prec = 34
        quantized = dec.quantize(Decimal("0.000001"))
    text = format(quantized, "f").rstrip("0").rstrip(".")
    return text or "0"


def _json_obj(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise TypeError("Expected JSON object.")
        return parsed
    raise TypeError("Expected mapping or JSON object text.")


@dataclass(frozen=True, slots=True)
class HistDataTickPeriod:
    year: int
    month: int

    def __post_init__(self) -> None:
        if self.year < 2000 or not 1 <= self.month <= 12:
            raise ValueError("Invalid HistData tick period.")

    @property
    def key(self) -> str:
        return f"{self.year:04d}{self.month:02d}"

    @property
    def referer(self) -> str:
        return f"{HISTDATA_TICK_REFERER_PREFIX}xauusd/{self.year}/{self.month}"

    @property
    def cache_name(self) -> str:
        return f"HISTDATA_COM_ASCII_XAUUSD_T_{self.key}.zip"


@dataclass(frozen=True, slots=True)
class TickArchiveMeta:
    source_file: str
    source_file_sha256: str
    payload_name: str
    source_payload_sha256: str


@dataclass(frozen=True, slots=True)
class Tick:
    source_tick_time_utc: datetime
    bid: Decimal
    ask: Decimal

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / Decimal(2)

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid

    @property
    def spread_bps(self) -> Decimal:
        return self.spread / self.mid * Decimal(10000)


@dataclass(frozen=True, slots=True)
class MinuteQuote:
    minute_utc: datetime
    source_tick_time_utc: datetime
    bid: Decimal
    ask: Decimal
    source_file: str
    source_file_sha256: str
    source_payload_sha256: str
    ingested_at: datetime

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / Decimal(2)

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid

    @property
    def spread_bps(self) -> Decimal:
        return self.spread / self.mid * Decimal(10000)

    @property
    def weekday_utc(self) -> int:
        return self.minute_utc.weekday()

    @property
    def clock_slot_15m(self) -> int:
        return (self.minute_utc.hour * 60 + self.minute_utc.minute) // _SLOT_MINUTES

    @property
    def quote_identity(self) -> str:
        return sha256(
            "\0".join(
                (
                    "histdata",
                    HISTDATA_TICK_DATASET,
                    SUPPORTED_SYMBOL,
                    self.minute_utc.isoformat(),
                    self.source_tick_time_utc.isoformat(),
                    str(self.bid),
                    str(self.ask),
                    self.source_file_sha256,
                    self.source_payload_sha256,
                    HISTDATA_TICK_DERIVATION_VERSION,
                )
            ).encode()
        ).hexdigest()

    def to_row(self) -> dict[str, Any]:
        return {
            "quote_identity": self.quote_identity,
            "provenance_class": RETROSPECTIVE_PROVENANCE,
            "pit_eligible": False,
            "symbol": SUPPORTED_SYMBOL,
            "minute_utc": self.minute_utc.isoformat(),
            "source_tick_time_utc": self.source_tick_time_utc.isoformat(),
            "bid": _fmt(self.bid),
            "ask": _fmt(self.ask),
            "mid": _fmt(self.mid),
            "spread": _fmt(self.spread),
            "spread_bps": _fmt(self.spread_bps),
            "weekday_utc": self.weekday_utc,
            "clock_slot_15m": self.clock_slot_15m,
            "source": "histdata",
            "source_dataset": HISTDATA_TICK_DATASET,
            "source_file": self.source_file,
            "source_file_sha256": self.source_file_sha256,
            "source_payload_sha256": self.source_payload_sha256,
            "source_timezone": HISTDATA_TICK_TIMEZONE,
            "derivation_version": HISTDATA_TICK_DERIVATION_VERSION,
            "ingested_at": self.ingested_at.astimezone(UTC).isoformat(),
        }


def download_histdata_tick_period(
    period: HistDataTickPeriod,
    *,
    cache_dir: Path,
    client: httpx.Client | None = None,
) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    destination = cache_dir / period.cache_name
    if destination.exists() and destination.stat().st_size > 0:
        _validate_zip(destination.read_bytes())
        return destination
    owns_client = client is None
    if client is None:
        client = httpx.Client(
            follow_redirects=True,
            timeout=120.0,
            headers={"User-Agent": "AIDY-Signals-Historical-Spread-Research/1.0"},
        )
    try:
        page = client.get(period.referer)
        page.raise_for_status()
        token = _token_from_html(page.text)
        response = client.post(
            HISTDATA_DOWNLOAD_URL,
            data={
                "tk": token,
                "date": str(period.year),
                "datemonth": period.key,
                "platform": "ASCII",
                "timeframe": "T",
                "fxpair": SUPPORTED_SYMBOL,
            },
            headers={
                "Origin": HISTDATA_BASE,
                "Referer": period.referer,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        response.raise_for_status()
        _validate_zip(response.content)
        destination.write_bytes(response.content)
        return destination
    finally:
        if owns_client:
            client.close()


def _file_sha(path: Path) -> str:
    hasher = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def tick_archive_meta(path: Path) -> TickArchiveMeta:
    _validate_zip(path.read_bytes())
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if not name.endswith("/")]
        csv_members = [name for name in members if name.lower().endswith(".csv")]
        if len(csv_members) != 1:
            raise RuntimeError("HistData tick archive must contain exactly one CSV payload.")
        payload_name = csv_members[0]
        hasher = sha256()
        with archive.open(payload_name) as raw:
            for chunk in iter(lambda: raw.read(1024 * 1024), b""):
                hasher.update(chunk)
    return TickArchiveMeta(
        source_file=path.name,
        source_file_sha256=_file_sha(path),
        payload_name=payload_name,
        source_payload_sha256=hasher.hexdigest(),
    )


def parse_tick_fields(timestamp_text: str, bid_text: str, ask_text: str) -> Tick:
    try:
        source_time = datetime.strptime(timestamp_text.strip(), "%Y%m%d %H%M%S%f").replace(
            tzinfo=_SOURCE_TZ
        )
    except ValueError as exc:
        raise ValueError(f"Invalid HistData tick timestamp: {timestamp_text!r}") from exc
    bid = _decimal(bid_text.strip(), name="bid")
    ask = _decimal(ask_text.strip(), name="ask")
    if ask < bid:
        raise ValueError("HistData tick ask cannot be below bid.")
    return Tick(source_tick_time_utc=source_time.astimezone(UTC), bid=bid, ask=ask)


def iter_histdata_ticks(path: Path) -> Iterable[Tick]:
    meta = tick_archive_meta(path)
    previous: datetime | None = None
    with zipfile.ZipFile(path) as archive, archive.open(meta.payload_name) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        reader = csv.reader(text)
        for line_number, row in enumerate(reader, start=1):
            if not row:
                continue
            if len(row) < 3:
                raise ValueError(f"HistData tick line {line_number} has fewer than 3 fields.")
            tick = parse_tick_fields(row[0], row[1], row[2])
            if previous is not None and tick.source_tick_time_utc < previous:
                raise ValueError("HistData tick archive is not time ordered.")
            previous = tick.source_tick_time_utc
            yield tick


def collapse_to_minute_quotes(
    ticks: Iterable[Tick],
    *,
    meta: TickArchiveMeta,
    ingested_at: datetime,
) -> tuple[list[MinuteQuote], dict[str, Any]]:
    ingested = _utc(ingested_at)
    quotes: list[MinuteQuote] = []
    current_minute: datetime | None = None
    last_tick: Tick | None = None
    tick_rows = 0
    first_tick: datetime | None = None
    final_tick: datetime | None = None

    def append_last() -> None:
        nonlocal last_tick, current_minute
        if last_tick is None or current_minute is None:
            return
        quotes.append(
            MinuteQuote(
                minute_utc=current_minute,
                source_tick_time_utc=last_tick.source_tick_time_utc,
                bid=last_tick.bid,
                ask=last_tick.ask,
                source_file=meta.source_file,
                source_file_sha256=meta.source_file_sha256,
                source_payload_sha256=meta.source_payload_sha256,
                ingested_at=ingested,
            )
        )

    for tick in ticks:
        tick_rows += 1
        first_tick = first_tick or tick.source_tick_time_utc
        final_tick = tick.source_tick_time_utc
        minute = tick.source_tick_time_utc.replace(second=0, microsecond=0)
        if current_minute is None:
            current_minute = minute
        elif minute != current_minute:
            append_last()
            current_minute = minute
        last_tick = tick
    append_last()
    if not quotes or first_tick is None or final_tick is None:
        raise RuntimeError("HistData tick archive produced no quotes.")
    manifest = {
        "version": DAY27_VERSION,
        "symbol": SUPPORTED_SYMBOL,
        "source": "histdata",
        "source_dataset": HISTDATA_TICK_DATASET,
        "source_period": f"{first_tick.year:04d}-{first_tick.month:02d}",
        "source_file": meta.source_file,
        "source_file_sha256": meta.source_file_sha256,
        "source_payload_sha256": meta.source_payload_sha256,
        "source_timezone": HISTDATA_TICK_TIMEZONE,
        "tick_rows": tick_rows,
        "minute_quote_rows": len(quotes),
        "first_tick_utc": first_tick.isoformat(),
        "last_tick_utc": final_tick.isoformat(),
        "raw_bid_ask_preserved": True,
        "depth_included": False,
        "true_exchange_volume_claimed": False,
        "order_flow_claimed": False,
        "ingested_at": ingested.isoformat(),
    }
    manifest["manifest_digest"] = _digest(manifest)
    return quotes, manifest


def _mean_std(values: list[Decimal]) -> tuple[Decimal, Decimal]:
    with localcontext() as ctx:
        ctx.prec = 34
        mean = sum(values, Decimal(0)) / Decimal(len(values))
        if len(values) < 2:
            return mean, Decimal(0)
        variance = sum((value - mean) ** 2 for value in values) / Decimal(len(values) - 1)
        return mean, variance.sqrt()


def build_spread_baseline(
    minute_quotes: Iterable[MinuteQuote],
    *,
    min_bucket_n: int = _MIN_BASELINE_BUCKET_N,
) -> dict[str, Any]:
    if min_bucket_n < 2:
        raise ValueError("Baseline minimum bucket n must be at least 2.")
    groups: dict[tuple[int, int], list[Decimal]] = defaultdict(list)
    quote_ids: list[str] = []
    for quote in sorted(minute_quotes, key=lambda item: (item.minute_utc, item.quote_identity)):
        groups[(quote.weekday_utc, quote.clock_slot_15m)].append(quote.spread_bps)
        quote_ids.append(quote.quote_identity)
    payload_groups: dict[str, Any] = {}
    for (weekday, slot), values in sorted(groups.items()):
        mean, std = _mean_std(values)
        state = "known" if len(values) >= min_bucket_n and std > 0 else "insufficient"
        payload_groups[f"{weekday}:{slot}"] = {
            "weekday_utc": weekday,
            "clock_slot_15m": slot,
            "sample_n": len(values),
            "state": state,
            "mean_spread_bps": _fmt(mean) if state == "known" else None,
            "std_spread_bps": _fmt(std) if state == "known" else None,
        }
    baseline: dict[str, Any] = {
        "baseline_version": BASELINE_VERSION,
        "symbol": SUPPORTED_SYMBOL,
        "source": "histdata",
        "source_dataset": HISTDATA_TICK_DATASET,
        "clock_bucket_minutes": _SLOT_MINUTES,
        "weekday_basis": "UTC_monday_0",
        "minimum_bucket_n": min_bucket_n,
        "outcome_fields_used": False,
        "quote_identity_digest": _digest(quote_ids),
        "groups": payload_groups,
    }
    baseline["baseline_digest"] = _digest(baseline)
    return baseline


def verify_spread_baseline(baseline: Mapping[str, Any]) -> bool:
    body = dict(baseline)
    supplied = str(body.pop("baseline_digest", ""))
    return bool(supplied) and supplied == _digest(body)


def _latest_quote_before(
    quotes: list[MinuteQuote], *, as_of: datetime, max_age_seconds: int
) -> MinuteQuote | None:
    eligible = [
        quote
        for quote in quotes
        if quote.source_tick_time_utc <= as_of
        and 0 <= (as_of - quote.source_tick_time_utc).total_seconds() <= max_age_seconds
    ]
    return max(eligible, key=lambda item: item.source_tick_time_utc) if eligible else None


def build_case_covariates(
    cases: Iterable[Mapping[str, Any]],
    minute_quotes: Iterable[MinuteQuote],
    baseline: Mapping[str, Any],
    *,
    max_quote_age_seconds: int = _MAX_ANCHOR_QUOTE_AGE_SECONDS,
) -> list[dict[str, Any]]:
    if not verify_spread_baseline(baseline):
        raise ValueError("Day 27 baseline digest does not match contents.")
    if baseline.get("outcome_fields_used") is not False:
        raise ValueError("Day 27 baseline must be frozen without outcomes.")
    quotes = sorted(minute_quotes, key=lambda item: item.source_tick_time_utc)
    groups = baseline.get("groups")
    if not isinstance(groups, Mapping):
        raise TypeError("Day 27 baseline groups must be an object.")
    result: list[dict[str, Any]] = []
    for case in sorted(cases, key=lambda item: (str(item.get("as_of_utc")), str(item.get("case_id")))):
        case_id = str(case.get("case_id") or "")
        as_of = _utc(str(case.get("as_of_utc") or ""))
        input_boundary = _json_obj(case.get("input_boundary"))
        feature = _json_obj(input_boundary.get("feature"))
        summary = _json_obj(feature.get("summary"))
        h1 = _json_obj(summary.get("H1")) if summary.get("H1") is not None else {}
        atr_raw = h1.get("atr_14_bps")
        atr = None if atr_raw in (None, "", "unknown") else _decimal(atr_raw, name="h1_atr_14_bps")
        setup = _json_obj(input_boundary.get("setup"))
        regime = _json_obj(input_boundary.get("regime"))
        labels = _json_obj(regime.get("labels"))
        normalized_trade_spec = input_boundary.get("normalized_trade_spec")
        quote = _latest_quote_before(quotes, as_of=as_of, max_age_seconds=max_quote_age_seconds)
        state = "unknown"
        spread_z: Decimal | None = None
        baseline_key: str | None = None
        quote_age: int | None = None
        if quote is not None:
            baseline_key = f"{quote.weekday_utc}:{quote.clock_slot_15m}"
            bucket = groups.get(baseline_key)
            if isinstance(bucket, Mapping) and bucket.get("state") == "known":
                mean = _decimal(bucket.get("mean_spread_bps"), name="baseline_mean")
                std = _decimal(bucket.get("std_spread_bps"), name="baseline_std")
                with localcontext() as ctx:
                    ctx.prec = 34
                    spread_z = (quote.spread_bps - mean) / std
                state = "known"
            else:
                state = "baseline_insufficient"
            quote_age = int((as_of - quote.source_tick_time_utc).total_seconds())
        result.append(
            {
                "case_id": case_id,
                "as_of_utc": as_of.isoformat(),
                "state": state,
                "quote_identity": None if quote is None else quote.quote_identity,
                "source_tick_time_utc": None if quote is None else quote.source_tick_time_utc.isoformat(),
                "quote_age_seconds": quote_age,
                "spread_bps": None if quote is None else _fmt(quote.spread_bps),
                "spread_z": _fmt(spread_z),
                "baseline_key": baseline_key,
                "baseline_digest": baseline["baseline_digest"],
                "h1_atr_14_bps": None if atr is None else _fmt(atr),
                "setup_detector_state": setup.get("detector_state"),
                "candidate_setup_ids": list(setup.get("candidate_setup_ids") or []),
                "session": labels.get("session"),
                "outcome_geometry_available": normalized_trade_spec is not None,
                "future_evaluation_read": False,
            }
        )
    return result


def _rank_terciles(items: list[dict[str, Any]], field: str) -> dict[str, str]:
    ranked = sorted(items, key=lambda item: (Decimal(str(item[field])), str(item["case_id"])))
    n = len(ranked)
    return {
        str(item["case_id"]): (
            "low" if index * 3 < n else "mid" if index * 3 < n * 2 else "high"
        )
        for index, item in enumerate(ranked)
    }


def freeze_j3_strata(covariates: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    eligible = [
        dict(item)
        for item in covariates
        if item.get("state") == "known"
        and item.get("spread_z") is not None
        and item.get("h1_atr_14_bps") is not None
        and item.get("outcome_geometry_available") is True
    ]
    if not eligible:
        assignments: list[dict[str, Any]] = []
    else:
        spread = _rank_terciles(eligible, "spread_z")
        volatility = _rank_terciles(eligible, "h1_atr_14_bps")
        assignments = [
            {
                "case_id": str(item["case_id"]),
                "as_of_utc": str(item["as_of_utc"]),
                "spread_z": str(item["spread_z"]),
                "spread_tercile": spread[str(item["case_id"])],
                "h1_atr_14_bps": str(item["h1_atr_14_bps"]),
                "volatility_tercile": volatility[str(item["case_id"])],
                "session": item.get("session"),
                "baseline_digest": item.get("baseline_digest"),
            }
            for item in sorted(eligible, key=lambda item: str(item["case_id"]))
        ]
    frozen: dict[str, Any] = {
        "strata_version": STRATA_VERSION,
        "normalization": BASELINE_VERSION,
        "spread_tercile_rule": "rank_tercile_by_normalized_spread_z_v1",
        "volatility_tercile_rule": "rank_tercile_by_input_h1_atr_14_bps_v1",
        "future_outcomes_used_for_strata": False,
        "eligible_cases": len(assignments),
        "assignments": assignments,
    }
    frozen["strata_digest"] = _digest(frozen)
    return frozen


def verify_j3_strata(strata: Mapping[str, Any]) -> bool:
    body = dict(strata)
    supplied = str(body.pop("strata_digest", ""))
    return bool(supplied) and supplied == _digest(body)


def _percentile(values: list[Decimal], fraction: Decimal) -> Decimal:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    with localcontext() as ctx:
        ctx.prec = 34
        position = fraction * Decimal(len(ordered) - 1)
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        weight = position - Decimal(lower)
        return ordered[lower] * (Decimal(1) - weight) + ordered[upper] * weight


def _distribution(values: list[Decimal]) -> dict[str, Any]:
    return {
        "n": len(values),
        "p25": None if not values else _fmt(_percentile(values, Decimal("0.25"))),
        "median": None if not values else _fmt(_percentile(values, Decimal("0.5"))),
        "p75": None if not values else _fmt(_percentile(values, Decimal("0.75"))),
        "values": [_fmt(value) for value in sorted(values)],
    }


def run_j3(
    cases: Iterable[Mapping[str, Any]],
    frozen_strata: Mapping[str, Any],
    *,
    minimum_cell_n_for_gate_review: int = 10,
) -> dict[str, Any]:
    if not verify_j3_strata(frozen_strata):
        raise ValueError("Day 27 frozen strata digest does not match contents.")
    if frozen_strata.get("future_outcomes_used_for_strata") is not False:
        raise ValueError("J3 strata must be frozen before outcome analysis.")
    case_map = {str(case.get("case_id")): case for case in cases}
    groups: dict[tuple[int, str, str], dict[str, list[Decimal]]] = defaultdict(
        lambda: {"mfe_r": [], "mae_r": []}
    )
    session_mix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    outcome_cases = 0
    for assignment in frozen_strata.get("assignments") or []:
        case_id = str(assignment["case_id"])
        case = case_map.get(case_id)
        if case is None:
            raise ValueError(f"Frozen J3 case {case_id} is missing.")
        future = _json_obj(case.get("future_evaluation"))
        bundle = future.get("trade_outcome_bundle")
        if bundle is None:
            continue
        bundle = _json_obj(bundle)
        outcomes = bundle.get("outcomes")
        if not isinstance(outcomes, list):
            continue
        used = False
        for outcome in outcomes:
            if not isinstance(outcome, Mapping) or outcome.get("coverage_state") != "complete":
                continue
            metrics = outcome.get("metrics")
            if not isinstance(metrics, Mapping):
                continue
            mfe = metrics.get("mfe_r")
            mae = metrics.get("mae_r")
            if mfe is None or mae is None:
                continue
            horizon = int(outcome["horizon_minutes"])
            key = (
                horizon,
                str(assignment["volatility_tercile"]),
                str(assignment["spread_tercile"]),
            )
            groups[key]["mfe_r"].append(Decimal(str(mfe)))
            groups[key]["mae_r"].append(Decimal(str(mae)))
            used = True
        if used:
            outcome_cases += 1
            session_mix[str(assignment["spread_tercile"])][
                str(assignment.get("session") or "unknown")
            ] += 1

    cells: list[dict[str, Any]] = []
    for (horizon, vol, spread), values in sorted(groups.items()):
        cells.append(
            {
                "horizon_minutes": horizon,
                "volatility_tercile": vol,
                "spread_tercile": spread,
                "mfe_r": _distribution(values["mfe_r"]),
                "mae_r": _distribution(values["mae_r"]),
            }
        )
    minimum_observed_cell_n = min((cell["mfe_r"]["n"] for cell in cells), default=0)
    evidence_state = (
        "descriptive_only_insufficient_for_gate"
        if minimum_observed_cell_n < minimum_cell_n_for_gate_review
        else "descriptive_sample_floor_met_gate_still_provisional"
    )
    result: dict[str, Any] = {
        "j3_version": J3_VERSION,
        "strata_digest": frozen_strata["strata_digest"],
        "normalization": BASELINE_VERSION,
        "control": "spread_z_within_input_h1_atr_volatility_tercile",
        "time_of_day_weekday_controlled": True,
        "raw_session_activity_treated_as_alpha": False,
        "outcome_cases": outcome_cases,
        "cells": cells,
        "session_mix_by_spread_tercile": {
            key: dict(sorted(value.items())) for key, value in sorted(session_mix.items())
        },
        "minimum_cell_n_for_gate_review": minimum_cell_n_for_gate_review,
        "minimum_observed_cell_n": minimum_observed_cell_n,
        "evidence_state": evidence_state,
        "proposed_trading_gate": None,
        "gate_status": "provisional_no_gate",
        "predictive_edge_claimed": False,
        "depth_claimed": False,
        "true_exchange_volume_claimed": False,
        "order_flow_claimed": False,
    }
    result["j3_digest"] = _digest(result)
    return result


def verify_j3(result: Mapping[str, Any]) -> bool:
    body = dict(result)
    supplied = str(body.pop("j3_digest", ""))
    return bool(supplied) and supplied == _digest(body)
