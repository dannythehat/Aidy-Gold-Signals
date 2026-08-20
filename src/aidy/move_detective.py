from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy.bigquery_exporter import FieldSpec, TableSpec
from aidy.historical_backfill import RETROSPECTIVE_PROVENANCE

MOVE_LABEL_VERSION = "aidy_move_label_v1"
MOVE_BUNDLE_VERSION = "aidy_move_bundle_v1"
MOVE_DISTRIBUTION_VERSION = "aidy_move_distribution_v1"
MOVE_DIGEST_ALGORITHM = "sha256"
SUPPORTED_SYMBOL = "XAUUSD"
SOURCE_TIMEFRAME = "M1"
DEFAULT_HORIZONS_MINUTES = (15, 60, 240)

QUIET_MAX_EXCURSION_BPS = Decimal(12)
MEANINGFUL_MOVE_BPS = Decimal(25)
SPIKE_EXCURSION_BPS = Decimal(40)
DIRECTIONAL_RETENTION_MIN = Decimal("0.50")
SPIKE_RETENTION_MAX = Decimal("0.25")

EVALUATION_CONTRACT_CLASS = "research_future_path_label"

RESEARCH_MOVE_LABELS = TableSpec(
    name="research_move_labels",
    partition_field="anchor_time_utc",
    clustering_fields=("symbol", "horizon_minutes", "path_class", "coverage_state"),
    fields=(
        FieldSpec("label_digest", "STRING", "REQUIRED"),
        FieldSpec("label_version", "STRING", "REQUIRED"),
        FieldSpec("contract_class", "STRING", "REQUIRED"),
        FieldSpec("evaluation_only", "BOOLEAN", "REQUIRED"),
        FieldSpec("future_derived", "BOOLEAN", "REQUIRED"),
        FieldSpec("pit_eligible", "BOOLEAN", "REQUIRED"),
        FieldSpec("decision_input_allowed", "BOOLEAN", "REQUIRED"),
        FieldSpec("symbol", "STRING", "REQUIRED"),
        FieldSpec("anchor_time_utc", "TIMESTAMP", "REQUIRED"),
        FieldSpec("anchor_price", "STRING", "REQUIRED"),
        FieldSpec("horizon_minutes", "INTEGER", "REQUIRED"),
        FieldSpec("horizon_end_utc", "TIMESTAMP", "REQUIRED"),
        FieldSpec("available_after_utc", "TIMESTAMP", "REQUIRED"),
        FieldSpec("coverage_state", "STRING", "REQUIRED"),
        FieldSpec("path_class", "STRING", "REQUIRED"),
        FieldSpec("thresholds", "JSON", "REQUIRED"),
        FieldSpec("path_stats", "JSON", "REQUIRED"),
        FieldSpec("source_provenance", "JSON", "REQUIRED"),
    ),
)


@dataclass(frozen=True, slots=True)
class EvaluationCandle:
    research_identity: str
    open_time_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    source: str | None
    source_file_sha256: str | None
    source_payload_sha256: str | None


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"Invalid evaluation timestamp: {value}") from exc
    else:
        raise TypeError("Evaluation timestamps must be timezone-aware datetime or ISO-8601 text.")
    if parsed.tzinfo is None:
        raise ValueError("Evaluation timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _decimal(value: Any, *, name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise TypeError(f"{name} must be a finite positive decimal.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a finite positive decimal.") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"{name} must be a finite positive decimal.")
    return parsed


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _bps(delta: Decimal, anchor: Decimal) -> Decimal:
    return (delta / anchor) * Decimal(10000)


def _row_to_candle(row: Mapping[str, Any]) -> EvaluationCandle:
    if row.get("provenance_class") != RETROSPECTIVE_PROVENANCE:
        raise ValueError("Move Detective accepts retrospective_history research rows only.")
    if row.get("pit_eligible") is not False:
        raise ValueError("Move Detective research rows must have pit_eligible=false.")
    if str(row.get("symbol") or "") != SUPPORTED_SYMBOL:
        raise ValueError(f"Move Detective supports only {SUPPORTED_SYMBOL}.")
    if str(row.get("timeframe") or "") != SOURCE_TIMEFRAME:
        raise ValueError("Move Detective v1 requires retrospective M1 research candles.")

    identity = str(row.get("research_identity") or "").strip()
    if not identity:
        raise ValueError("Research rows require research_identity provenance.")

    open_time = _utc(row.get("open_time_utc"))
    open_price = _decimal(row.get("open"), name="open")
    high = _decimal(row.get("high"), name="high")
    low = _decimal(row.get("low"), name="low")
    close = _decimal(row.get("close"), name="close")
    if high < max(open_price, close) or low > min(open_price, close) or high < low:
        raise ValueError("Research row has impossible OHLC geometry.")

    return EvaluationCandle(
        research_identity=identity,
        open_time_utc=open_time,
        open=open_price,
        high=high,
        low=low,
        close=close,
        source=None if row.get("source") is None else str(row.get("source")),
        source_file_sha256=(
            None if row.get("source_file_sha256") is None else str(row.get("source_file_sha256"))
        ),
        source_payload_sha256=(
            None
            if row.get("source_payload_sha256") is None
            else str(row.get("source_payload_sha256"))
        ),
    )


def _normalize_rows(rows: Iterable[Mapping[str, Any]]) -> dict[datetime, EvaluationCandle]:
    by_time: dict[datetime, EvaluationCandle] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise TypeError("Research candle inputs must be objects.")
        candle = _row_to_candle(raw)
        if candle.open_time_utc in by_time:
            raise ValueError(
                "Move Detective requires one explicitly selected research revision per M1 timestamp."
            )
        by_time[candle.open_time_utc] = candle
    return dict(sorted(by_time.items()))


def _thresholds() -> dict[str, str]:
    return {
        "quiet_max_excursion_bps": _decimal_text(QUIET_MAX_EXCURSION_BPS),
        "meaningful_move_bps": _decimal_text(MEANINGFUL_MOVE_BPS),
        "spike_excursion_bps": _decimal_text(SPIKE_EXCURSION_BPS),
        "directional_retention_min": _decimal_text(DIRECTIONAL_RETENTION_MIN),
        "spike_retention_max": _decimal_text(SPIKE_RETENTION_MAX),
    }


def _source_provenance(candles: list[EvaluationCandle]) -> dict[str, Any]:
    identities = [candle.research_identity for candle in candles]
    return {
        "provenance_class": RETROSPECTIVE_PROVENANCE,
        "source_timeframe": SOURCE_TIMEFRAME,
        "research_identity_count": len(identities),
        "research_identities_digest": _digest(identities),
        "sources": sorted({candle.source for candle in candles if candle.source}),
        "source_file_sha256": sorted(
            {candle.source_file_sha256 for candle in candles if candle.source_file_sha256}
        ),
        "source_payload_sha256": sorted(
            {candle.source_payload_sha256 for candle in candles if candle.source_payload_sha256}
        ),
    }


def _crossing_minute(
    candles: list[EvaluationCandle],
    *,
    anchor_price: Decimal,
    direction: str,
) -> int | None:
    for minute, candle in enumerate(candles, start=1):
        if direction == "up":
            excursion = _bps(candle.high - anchor_price, anchor_price)
        else:
            excursion = _bps(anchor_price - candle.low, anchor_price)
        if excursion >= MEANINGFUL_MOVE_BPS:
            return minute
    return None


def _path_class(
    *,
    max_up_bps: Decimal,
    max_down_bps: Decimal,
    terminal_return_bps: Decimal,
    up_crossing_minute: int | None,
    down_crossing_minute: int | None,
) -> str:
    if (
        max_up_bps < QUIET_MAX_EXCURSION_BPS
        and max_down_bps < QUIET_MAX_EXCURSION_BPS
    ):
        return "quiet"

    up_meaningful = max_up_bps >= MEANINGFUL_MOVE_BPS
    down_meaningful = max_down_bps >= MEANINGFUL_MOVE_BPS
    if up_meaningful and down_meaningful:
        if up_crossing_minute == down_crossing_minute:
            return "two_sided_intrabar_order_unknown"
        if up_crossing_minute is not None and down_crossing_minute is not None:
            if up_crossing_minute < down_crossing_minute:
                return "reversal_up_to_down"
            return "reversal_down_to_up"
        return "complex"

    up_retention = (
        max(terminal_return_bps, Decimal(0)) / max_up_bps
        if max_up_bps > 0
        else Decimal(0)
    )
    down_retention = (
        max(-terminal_return_bps, Decimal(0)) / max_down_bps
        if max_down_bps > 0
        else Decimal(0)
    )

    if (
        max_up_bps >= SPIKE_EXCURSION_BPS
        and not down_meaningful
        and up_retention <= SPIKE_RETENTION_MAX
    ):
        return "spike_up_reverted"
    if (
        max_down_bps >= SPIKE_EXCURSION_BPS
        and not up_meaningful
        and down_retention <= SPIKE_RETENTION_MAX
    ):
        return "spike_down_reverted"
    if up_meaningful and not down_meaningful and up_retention >= DIRECTIONAL_RETENTION_MIN:
        return "directional_up"
    if down_meaningful and not up_meaningful and down_retention >= DIRECTIONAL_RETENTION_MIN:
        return "directional_down"
    if not up_meaningful and not down_meaningful:
        return "subthreshold_chop"
    return "complex"


def _complete_path_stats(
    candles: list[EvaluationCandle],
    *,
    anchor_price: Decimal,
) -> tuple[str, dict[str, Any]]:
    max_high = max(candle.high for candle in candles)
    min_low = min(candle.low for candle in candles)
    terminal_close = candles[-1].close
    max_up_bps = max(_bps(max_high - anchor_price, anchor_price), Decimal(0))
    max_down_bps = max(_bps(anchor_price - min_low, anchor_price), Decimal(0))
    terminal_return_bps = _bps(terminal_close - anchor_price, anchor_price)
    total_range_bps = _bps(max_high - min_low, anchor_price)

    max_up_minute = next(
        minute for minute, candle in enumerate(candles, start=1) if candle.high == max_high
    )
    max_down_minute = next(
        minute for minute, candle in enumerate(candles, start=1) if candle.low == min_low
    )
    up_cross = _crossing_minute(candles, anchor_price=anchor_price, direction="up")
    down_cross = _crossing_minute(candles, anchor_price=anchor_price, direction="down")

    travel = Decimal(0)
    previous = anchor_price
    for candle in candles:
        travel += abs(candle.close - previous)
        previous = candle.close
    close_path_travel_bps = _bps(travel, anchor_price)
    efficiency = (
        abs(terminal_return_bps) / close_path_travel_bps
        if close_path_travel_bps > 0
        else Decimal(0)
    )
    up_retention = (
        max(terminal_return_bps, Decimal(0)) / max_up_bps
        if max_up_bps > 0
        else Decimal(0)
    )
    down_retention = (
        max(-terminal_return_bps, Decimal(0)) / max_down_bps
        if max_down_bps > 0
        else Decimal(0)
    )

    path_class = _path_class(
        max_up_bps=max_up_bps,
        max_down_bps=max_down_bps,
        terminal_return_bps=terminal_return_bps,
        up_crossing_minute=up_cross,
        down_crossing_minute=down_cross,
    )
    stats = {
        "max_up_bps": _decimal_text(max_up_bps),
        "max_down_bps": _decimal_text(max_down_bps),
        "terminal_return_bps": _decimal_text(terminal_return_bps),
        "total_range_bps": _decimal_text(total_range_bps),
        "close_path_travel_bps": _decimal_text(close_path_travel_bps),
        "close_path_efficiency": _decimal_text(efficiency),
        "up_terminal_retention_ratio": _decimal_text(up_retention),
        "down_terminal_retention_ratio": _decimal_text(down_retention),
        "time_to_max_up_seconds": max_up_minute * 60,
        "time_to_max_down_seconds": max_down_minute * 60,
        "first_meaningful_up_seconds": None if up_cross is None else up_cross * 60,
        "first_meaningful_down_seconds": None if down_cross is None else down_cross * 60,
    }
    return path_class, stats


def compute_move_label_digest(label: Mapping[str, Any]) -> str:
    body = dict(label)
    body.pop("label_digest", None)
    return _digest(body)


def verify_move_label_digest(label: Mapping[str, Any]) -> bool:
    supplied = str(label.get("label_digest") or "")
    return bool(supplied) and supplied == compute_move_label_digest(label)


def _build_horizon_label(
    *,
    anchor_time: datetime,
    anchor_price: Decimal,
    horizon_minutes: int,
    rows_by_time: Mapping[datetime, EvaluationCandle],
) -> dict[str, Any]:
    if horizon_minutes <= 0:
        raise ValueError("Move Detective horizons must be positive whole minutes.")

    horizon_end = anchor_time + timedelta(minutes=horizon_minutes)
    required_times = [
        anchor_time + timedelta(minutes=minute)
        for minute in range(1, horizon_minutes + 1)
    ]
    candles = [rows_by_time[stamp] for stamp in required_times if stamp in rows_by_time]
    missing_minutes = [
        minute
        for minute, stamp in enumerate(required_times, start=1)
        if stamp not in rows_by_time
    ]
    coverage_state = "complete" if not missing_minutes else "incomplete"

    if coverage_state == "complete":
        path_class, stats = _complete_path_stats(candles, anchor_price=anchor_price)
    else:
        path_class = "unknown"
        stats = {
            "expected_rows": horizon_minutes,
            "observed_rows": len(candles),
            "missing_minutes": missing_minutes,
        }

    label: dict[str, Any] = {
        "label_version": MOVE_LABEL_VERSION,
        "label_digest_algorithm": MOVE_DIGEST_ALGORITHM,
        "contract_class": EVALUATION_CONTRACT_CLASS,
        "evaluation_only": True,
        "future_derived": True,
        "pit_eligible": False,
        "decision_input_allowed": False,
        "symbol": SUPPORTED_SYMBOL,
        "anchor_time_utc": anchor_time.isoformat(),
        "anchor_price": _decimal_text(anchor_price),
        "horizon_minutes": horizon_minutes,
        "horizon_end_utc": horizon_end.isoformat(),
        "available_after_utc": horizon_end.isoformat(),
        "coverage_state": coverage_state,
        "path_class": path_class,
        "thresholds": _thresholds(),
        "path_stats": stats,
        "source_provenance": _source_provenance(candles),
    }
    label["label_digest"] = compute_move_label_digest(label)
    return label


def compute_move_bundle_digest(bundle: Mapping[str, Any]) -> str:
    body = dict(bundle)
    body.pop("bundle_digest", None)
    return _digest(body)


def verify_move_bundle_digest(bundle: Mapping[str, Any]) -> bool:
    supplied = str(bundle.get("bundle_digest") or "")
    return bool(supplied) and supplied == compute_move_bundle_digest(bundle)


def build_move_bundle(
    *,
    anchor_time: datetime | str,
    anchor_price: Any,
    research_rows: Iterable[Mapping[str, Any]],
    horizons_minutes: Iterable[int] = DEFAULT_HORIZONS_MINUTES,
) -> dict[str, Any]:
    """Label future XAUUSD paths for evaluation without creating decision-time evidence."""

    anchor = _utc(anchor_time)
    price = _decimal(anchor_price, name="anchor_price")
    horizons = sorted({int(value) for value in horizons_minutes})
    if not horizons or any(value <= 0 for value in horizons):
        raise ValueError("Move Detective requires at least one positive horizon.")

    rows_by_time = _normalize_rows(research_rows)
    labels = [
        _build_horizon_label(
            anchor_time=anchor,
            anchor_price=price,
            horizon_minutes=horizon,
            rows_by_time=rows_by_time,
        )
        for horizon in horizons
    ]
    bundle: dict[str, Any] = {
        "move_bundle_version": MOVE_BUNDLE_VERSION,
        "bundle_digest_algorithm": MOVE_DIGEST_ALGORITHM,
        "contract_class": EVALUATION_CONTRACT_CLASS,
        "evaluation_only": True,
        "future_derived": True,
        "pit_eligible": False,
        "decision_input_allowed": False,
        "symbol": SUPPORTED_SYMBOL,
        "anchor_time_utc": anchor.isoformat(),
        "anchor_price": _decimal_text(price),
        "horizons_minutes": horizons,
        "available_after_utc": (anchor + timedelta(minutes=max(horizons))).isoformat(),
        "labels": labels,
    }
    bundle["bundle_digest"] = compute_move_bundle_digest(bundle)
    return bundle


def move_label_storage_row(label: Mapping[str, Any]) -> dict[str, Any]:
    if label.get("label_version") != MOVE_LABEL_VERSION or not verify_move_label_digest(label):
        raise ValueError("Only valid Day 12 move labels can be materialized for research storage.")
    if (
        label.get("evaluation_only") is not True
        or label.get("future_derived") is not True
        or label.get("pit_eligible") is not False
        or label.get("decision_input_allowed") is not False
    ):
        raise ValueError("Move-label storage contract requires evaluation-only future-derived rows.")
    return {
        "label_digest": label["label_digest"],
        "label_version": label["label_version"],
        "contract_class": label["contract_class"],
        "evaluation_only": True,
        "future_derived": True,
        "pit_eligible": False,
        "decision_input_allowed": False,
        "symbol": label["symbol"],
        "anchor_time_utc": label["anchor_time_utc"],
        "anchor_price": label["anchor_price"],
        "horizon_minutes": label["horizon_minutes"],
        "horizon_end_utc": label["horizon_end_utc"],
        "available_after_utc": label["available_after_utc"],
        "coverage_state": label["coverage_state"],
        "path_class": label["path_class"],
        "thresholds": label["thresholds"],
        "path_stats": label["path_stats"],
        "source_provenance": label["source_provenance"],
    }


def move_label_distribution(labels: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    horizon_counts: dict[int, Counter[str]] = {}
    coverage_counts: Counter[str] = Counter()
    label_count = 0
    for label in labels:
        if label.get("label_version") != MOVE_LABEL_VERSION or not verify_move_label_digest(label):
            raise ValueError("Distribution input contains an invalid move label.")
        horizon = int(label["horizon_minutes"])
        horizon_counts.setdefault(horizon, Counter())[str(label.get("path_class") or "unknown")] += 1
        coverage_counts[str(label.get("coverage_state") or "unknown")] += 1
        label_count += 1

    return {
        "distribution_version": MOVE_DISTRIBUTION_VERSION,
        "label_version": MOVE_LABEL_VERSION,
        "evaluation_only": True,
        "future_derived": True,
        "pit_eligible": False,
        "label_count": label_count,
        "coverage_counts": dict(sorted(coverage_counts.items())),
        "path_class_counts_by_horizon": {
            str(horizon): dict(sorted(counts.items()))
            for horizon, counts in sorted(horizon_counts.items())
        },
        "outcome_causality_included": False,
    }
