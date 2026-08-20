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
from aidy.move_detective import build_move_bundle

TRADE_OUTCOME_VERSION = "aidy_trade_outcome_v1"
TRADE_OUTCOME_BUNDLE_VERSION = "aidy_trade_outcome_bundle_v1"
TRADE_OUTCOME_DISTRIBUTION_VERSION = "aidy_trade_outcome_distribution_v1"
TRADE_OUTCOME_DIGEST_ALGORITHM = "sha256"
TRADE_OUTCOME_CONTRACT_CLASS = "research_future_trade_outcome"
SUPPORTED_SYMBOL = "XAUUSD"
SOURCE_TIMEFRAME = "M1"
DEFAULT_HORIZONS_MINUTES = (15, 60, 240)
MAX_TARGETS = 3

RESEARCH_TRADE_OUTCOMES = TableSpec(
    name="research_trade_outcomes",
    partition_field="anchor_time_utc",
    clustering_fields=("symbol", "direction", "horizon_minutes", "coverage_state"),
    fields=(
        FieldSpec("outcome_digest", "STRING", "REQUIRED"),
        FieldSpec("outcome_version", "STRING", "REQUIRED"),
        FieldSpec("contract_class", "STRING", "REQUIRED"),
        FieldSpec("evaluation_only", "BOOLEAN", "REQUIRED"),
        FieldSpec("future_derived", "BOOLEAN", "REQUIRED"),
        FieldSpec("pit_eligible", "BOOLEAN", "REQUIRED"),
        FieldSpec("decision_input_allowed", "BOOLEAN", "REQUIRED"),
        FieldSpec("realized_pnl_included", "BOOLEAN", "REQUIRED"),
        FieldSpec("symbol", "STRING", "REQUIRED"),
        FieldSpec("direction", "STRING", "REQUIRED"),
        FieldSpec("anchor_time_utc", "TIMESTAMP", "REQUIRED"),
        FieldSpec("horizon_minutes", "INTEGER", "REQUIRED"),
        FieldSpec("horizon_end_utc", "TIMESTAMP", "REQUIRED"),
        FieldSpec("available_after_utc", "TIMESTAMP", "REQUIRED"),
        FieldSpec("coverage_state", "STRING", "REQUIRED"),
        FieldSpec("outcome_state", "STRING", "REQUIRED"),
        FieldSpec("trade_spec", "JSON", "REQUIRED"),
        FieldSpec("metrics", "JSON", "REQUIRED"),
        FieldSpec("level_analysis", "JSON", "REQUIRED"),
        FieldSpec("path_behavior", "JSON", "REQUIRED"),
        FieldSpec("source_provenance", "JSON", "REQUIRED"),
    ),
)


@dataclass(frozen=True, slots=True)
class OutcomeCandle:
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
            raise ValueError(f"Invalid outcome timestamp: {value}") from exc
    else:
        raise TypeError("Outcome timestamps must be timezone-aware datetime or ISO-8601 text.")
    if parsed.tzinfo is None:
        raise ValueError("Outcome timestamps must be timezone-aware.")
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


def _bps(delta: Decimal, entry: Decimal) -> Decimal:
    return (delta / entry) * Decimal(10000)


def _row_to_candle(row: Mapping[str, Any]) -> OutcomeCandle:
    if row.get("provenance_class") != RETROSPECTIVE_PROVENANCE:
        raise ValueError("Trade outcomes accept retrospective_history research rows only.")
    if row.get("pit_eligible") is not False:
        raise ValueError("Trade outcome research rows must have pit_eligible=false.")
    if str(row.get("symbol") or "") != SUPPORTED_SYMBOL:
        raise ValueError(f"Trade outcomes support only {SUPPORTED_SYMBOL}.")
    if str(row.get("timeframe") or "") != SOURCE_TIMEFRAME:
        raise ValueError("Trade outcomes v1 require retrospective M1 research candles.")

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

    return OutcomeCandle(
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


def _normalize_rows(rows: Iterable[Mapping[str, Any]]) -> dict[datetime, OutcomeCandle]:
    by_time: dict[datetime, OutcomeCandle] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise TypeError("Research candle inputs must be objects.")
        candle = _row_to_candle(raw)
        if candle.open_time_utc in by_time:
            raise ValueError(
                "Trade outcomes require one explicitly selected research revision per M1 timestamp."
            )
        by_time[candle.open_time_utc] = candle
    return dict(sorted(by_time.items()))


def _normalize_trade_spec(
    *, direction: str, entry: Any, stop_loss: Any, targets: Iterable[Any]
) -> tuple[str, Decimal, Decimal, tuple[Decimal, ...], dict[str, Any]]:
    normalized_direction = str(direction).strip().lower()
    if normalized_direction not in {"long", "short"}:
        raise ValueError("Trade outcome direction must be long or short.")
    entry_price = _decimal(entry, name="entry")
    stop_price = _decimal(stop_loss, name="stop_loss")
    target_prices = tuple(_decimal(value, name="target") for value in targets)
    if not 1 <= len(target_prices) <= MAX_TARGETS:
        raise ValueError("Trade outcomes require between one and three targets.")
    if len(set(target_prices)) != len(target_prices):
        raise ValueError("Trade outcome targets must be unique.")

    if normalized_direction == "long":
        if stop_price >= entry_price:
            raise ValueError("Long stop_loss must be below entry.")
        if any(target <= entry_price for target in target_prices):
            raise ValueError("Long targets must be above entry.")
        if list(target_prices) != sorted(target_prices):
            raise ValueError("Long targets must be strictly increasing.")
    else:
        if stop_price <= entry_price:
            raise ValueError("Short stop_loss must be above entry.")
        if any(target >= entry_price for target in target_prices):
            raise ValueError("Short targets must be below entry.")
        if list(target_prices) != sorted(target_prices, reverse=True):
            raise ValueError("Short targets must be strictly decreasing.")

    risk_distance = abs(entry_price - stop_price)
    spec = {
        "direction": normalized_direction,
        "entry": _decimal_text(entry_price),
        "stop_loss": _decimal_text(stop_price),
        "targets": [_decimal_text(value) for value in target_prices],
        "risk_distance": _decimal_text(risk_distance),
    }
    spec["trade_spec_digest"] = _digest(spec)
    return normalized_direction, entry_price, stop_price, target_prices, spec


def _source_provenance(candles: list[OutcomeCandle]) -> dict[str, Any]:
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


def _favorable_adverse(
    candle: OutcomeCandle, *, direction: str, entry: Decimal
) -> tuple[Decimal, Decimal]:
    if direction == "long":
        return max(candle.high - entry, Decimal(0)), max(entry - candle.low, Decimal(0))
    return max(entry - candle.low, Decimal(0)), max(candle.high - entry, Decimal(0))


def _level_hit(candle: OutcomeCandle, *, direction: str, level_type: str, price: Decimal) -> bool:
    if level_type == "stop":
        return candle.low <= price if direction == "long" else candle.high >= price
    return candle.high >= price if direction == "long" else candle.low <= price


def _metrics(
    candles: list[OutcomeCandle], *, direction: str, entry: Decimal, stop_loss: Decimal
) -> dict[str, Any]:
    risk_distance = abs(entry - stop_loss)
    excursions = [
        _favorable_adverse(candle, direction=direction, entry=entry) for candle in candles
    ]
    mfe = max(favorable for favorable, _ in excursions)
    mae = max(adverse for _, adverse in excursions)
    mfe_minute = next(
        minute
        for minute, (favorable, _) in enumerate(excursions, start=1)
        if favorable == mfe
    )
    mae_minute = next(
        minute for minute, (_, adverse) in enumerate(excursions, start=1) if adverse == mae
    )
    terminal_close = candles[-1].close
    terminal_delta = (
        terminal_close - entry if direction == "long" else entry - terminal_close
    )
    return {
        "mfe_price": _decimal_text(mfe),
        "mae_price": _decimal_text(mae),
        "mfe_bps": _decimal_text(_bps(mfe, entry)),
        "mae_bps": _decimal_text(_bps(mae, entry)),
        "mfe_r": _decimal_text(mfe / risk_distance),
        "mae_r": _decimal_text(mae / risk_distance),
        "time_to_mfe_seconds": mfe_minute * 60,
        "time_to_mae_seconds": mae_minute * 60,
        "terminal_close": _decimal_text(terminal_close),
        "terminal_favorable_delta": _decimal_text(terminal_delta),
        "terminal_favorable_bps": _decimal_text(_bps(terminal_delta, entry)),
        "terminal_favorable_r": _decimal_text(terminal_delta / risk_distance),
    }


def _level_analysis(
    candles: list[OutcomeCandle],
    *,
    anchor_time: datetime,
    direction: str,
    stop_loss: Decimal,
    targets: tuple[Decimal, ...],
) -> dict[str, Any]:
    levels: list[tuple[str, str, Decimal]] = [("stop", "stop", stop_loss)]
    levels.extend(
        (f"target_{index}", "target", target)
        for index, target in enumerate(targets, start=1)
    )
    first_hits: dict[str, int | None] = {name: None for name, _, _ in levels}

    for minute, candle in enumerate(candles, start=1):
        for name, level_type, price in levels:
            if first_hits[name] is None and _level_hit(
                candle, direction=direction, level_type=level_type, price=price
            ):
                first_hits[name] = minute

    events: dict[str, dict[str, Any]] = {}
    for name, level_type, price in levels:
        minute = first_hits[name]
        events[name] = {
            "level_type": level_type,
            "price": _decimal_text(price),
            "hit": minute is not None,
            "first_hit_minute": minute,
            "time_to_level_seconds": None if minute is None else minute * 60,
            "first_hit_at_utc": (
                None
                if minute is None
                else (anchor_time + timedelta(minutes=minute)).isoformat()
            ),
        }

    groups_by_minute: dict[int, list[str]] = {}
    for name, minute in first_hits.items():
        if minute is not None:
            groups_by_minute.setdefault(minute, []).append(name)
    ordering_groups = [
        {"minute": minute, "levels": sorted(names)}
        for minute, names in sorted(groups_by_minute.items())
    ]
    ambiguous_groups = [group for group in ordering_groups if len(group["levels"]) > 1]

    stop_minute = first_hits["stop"]
    target_minutes = [
        minute for name, minute in first_hits.items() if name.startswith("target_") and minute is not None
    ]
    first_target_minute = min(target_minutes) if target_minutes else None
    if stop_minute is None and first_target_minute is None:
        stop_target_order = "neither"
    elif stop_minute is None:
        stop_target_order = "target_only"
    elif first_target_minute is None:
        stop_target_order = "stop_only"
    elif stop_minute < first_target_minute:
        stop_target_order = "stop_before_any_target"
    elif first_target_minute < stop_minute:
        stop_target_order = "target_before_stop"
    else:
        stop_target_order = "same_bar_order_unknown"

    targets_before_stop = 0
    for index in range(1, len(targets) + 1):
        minute = first_hits[f"target_{index}"]
        if minute is None:
            continue
        if stop_minute is None or minute < stop_minute:
            targets_before_stop = index
        elif minute == stop_minute:
            break

    return {
        "events": events,
        "first_hit_groups": ordering_groups,
        "intrabar_order_state": (
            "ambiguous" if ambiguous_groups else "deterministic"
        ),
        "ambiguous_first_hit_groups": ambiguous_groups,
        "stop_target_order": stop_target_order,
        "targets_strictly_before_stop": targets_before_stop,
    }


def compute_trade_outcome_digest(outcome: Mapping[str, Any]) -> str:
    body = dict(outcome)
    body.pop("outcome_digest", None)
    return _digest(body)


def verify_trade_outcome_digest(outcome: Mapping[str, Any]) -> bool:
    supplied = str(outcome.get("outcome_digest") or "")
    return bool(supplied) and supplied == compute_trade_outcome_digest(outcome)


def _build_horizon_outcome(
    *,
    anchor_time: datetime,
    direction: str,
    entry: Decimal,
    stop_loss: Decimal,
    targets: tuple[Decimal, ...],
    trade_spec: Mapping[str, Any],
    horizon_minutes: int,
    rows_by_time: Mapping[datetime, OutcomeCandle],
    raw_rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    if horizon_minutes <= 0:
        raise ValueError("Trade outcome horizons must be positive whole minutes.")
    horizon_end = anchor_time + timedelta(minutes=horizon_minutes)
    required_times = [
        anchor_time + timedelta(minutes=minute) for minute in range(1, horizon_minutes + 1)
    ]
    candles = [rows_by_time[stamp] for stamp in required_times if stamp in rows_by_time]
    missing_minutes = [
        minute
        for minute, stamp in enumerate(required_times, start=1)
        if stamp not in rows_by_time
    ]
    coverage_state = "complete" if not missing_minutes else "incomplete"

    if coverage_state == "complete":
        metrics = _metrics(candles, direction=direction, entry=entry, stop_loss=stop_loss)
        level_analysis = _level_analysis(
            candles,
            anchor_time=anchor_time,
            direction=direction,
            stop_loss=stop_loss,
            targets=targets,
        )
        outcome_state = str(level_analysis["stop_target_order"])
        move_label = build_move_bundle(
            anchor_time=anchor_time,
            anchor_price=entry,
            research_rows=raw_rows,
            horizons_minutes=(horizon_minutes,),
        )["labels"][0]
        path_behavior = {
            "move_label_version": move_label["label_version"],
            "move_label_digest": move_label["label_digest"],
            "path_class": move_label["path_class"],
            "path_stats": move_label["path_stats"],
        }
    else:
        outcome_state = "unknown"
        metrics = {
            "expected_rows": horizon_minutes,
            "observed_rows": len(candles),
            "missing_minutes": missing_minutes,
        }
        level_analysis = {"state": "unknown_due_incomplete_horizon"}
        path_behavior = {"path_class": "unknown"}

    outcome: dict[str, Any] = {
        "outcome_version": TRADE_OUTCOME_VERSION,
        "outcome_digest_algorithm": TRADE_OUTCOME_DIGEST_ALGORITHM,
        "contract_class": TRADE_OUTCOME_CONTRACT_CLASS,
        "evaluation_only": True,
        "future_derived": True,
        "pit_eligible": False,
        "decision_input_allowed": False,
        "realized_pnl_included": False,
        "symbol": SUPPORTED_SYMBOL,
        "direction": direction,
        "anchor_time_utc": anchor_time.isoformat(),
        "horizon_minutes": horizon_minutes,
        "horizon_end_utc": horizon_end.isoformat(),
        "available_after_utc": horizon_end.isoformat(),
        "coverage_state": coverage_state,
        "outcome_state": outcome_state,
        "trade_spec": dict(trade_spec),
        "metrics": metrics,
        "level_analysis": level_analysis,
        "path_behavior": path_behavior,
        "source_provenance": _source_provenance(candles),
    }
    outcome["outcome_digest"] = compute_trade_outcome_digest(outcome)
    return outcome


def build_trade_outcome_bundle(
    *,
    anchor_time: datetime | str,
    direction: str,
    entry: Any,
    stop_loss: Any,
    targets: Iterable[Any],
    research_rows: Iterable[Mapping[str, Any]],
    horizons_minutes: Iterable[int] = DEFAULT_HORIZONS_MINUTES,
) -> dict[str, Any]:
    anchor = _utc(anchor_time)
    normalized_direction, entry_price, stop_price, target_prices, trade_spec = (
        _normalize_trade_spec(
            direction=direction,
            entry=entry,
            stop_loss=stop_loss,
            targets=targets,
        )
    )
    raw_rows = list(research_rows)
    rows_by_time = _normalize_rows(raw_rows)
    horizons = tuple(sorted(set(int(value) for value in horizons_minutes)))
    if not horizons or any(value <= 0 for value in horizons):
        raise ValueError("Trade outcome bundle requires positive horizons.")

    labels = [
        _build_horizon_outcome(
            anchor_time=anchor,
            direction=normalized_direction,
            entry=entry_price,
            stop_loss=stop_price,
            targets=target_prices,
            trade_spec=trade_spec,
            horizon_minutes=horizon,
            rows_by_time=rows_by_time,
            raw_rows=raw_rows,
        )
        for horizon in horizons
    ]
    bundle: dict[str, Any] = {
        "trade_outcome_bundle_version": TRADE_OUTCOME_BUNDLE_VERSION,
        "evaluation_only": True,
        "future_derived": True,
        "pit_eligible": False,
        "decision_input_allowed": False,
        "realized_pnl_included": False,
        "symbol": SUPPORTED_SYMBOL,
        "anchor_time_utc": anchor.isoformat(),
        "available_after_utc": max(label["available_after_utc"] for label in labels),
        "trade_spec": trade_spec,
        "outcomes": labels,
    }
    bundle["bundle_digest"] = _digest(bundle)
    return bundle


def verify_trade_outcome_bundle_digest(bundle: Mapping[str, Any]) -> bool:
    body = dict(bundle)
    supplied = str(body.pop("bundle_digest", ""))
    return bool(supplied) and supplied == _digest(body)


def trade_outcome_storage_row(outcome: Mapping[str, Any]) -> dict[str, object]:
    if not verify_trade_outcome_digest(outcome):
        raise ValueError("Storage accepts only valid Day 13 trade outcomes.")
    if (
        outcome.get("evaluation_only") is not True
        or outcome.get("future_derived") is not True
        or outcome.get("pit_eligible") is not False
        or outcome.get("decision_input_allowed") is not False
    ):
        raise ValueError("Trade outcome storage requires the evaluation-only leakage boundary.")
    return {
        field.name: outcome[field.name]
        for field in RESEARCH_TRADE_OUTCOMES.fields
    }


def trade_outcome_distribution(outcomes: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    items = list(outcomes)
    for item in items:
        if not verify_trade_outcome_digest(item):
            raise ValueError("Distribution received an invalid trade outcome digest.")
        if item.get("pit_eligible") is not False or item.get("evaluation_only") is not True:
            raise ValueError("Distribution accepts evaluation-only trade outcomes.")

    coverage = Counter(str(item["coverage_state"]) for item in items)
    states = Counter(str(item["outcome_state"]) for item in items)
    by_direction = Counter(str(item["direction"]) for item in items)
    ambiguous = sum(
        1
        for item in items
        if item["coverage_state"] == "complete"
        and item["level_analysis"].get("intrabar_order_state") == "ambiguous"
    )
    complete = [item for item in items if item["coverage_state"] == "complete"]
    mfe_values = [Decimal(str(item["metrics"]["mfe_r"])) for item in complete]
    mae_values = [Decimal(str(item["metrics"]["mae_r"])) for item in complete]
    result = {
        "distribution_version": TRADE_OUTCOME_DISTRIBUTION_VERSION,
        "outcome_version": TRADE_OUTCOME_VERSION,
        "evaluation_only": True,
        "future_derived": True,
        "pit_eligible": False,
        "realized_pnl_included": False,
        "outcome_count": len(items),
        "coverage_counts": dict(sorted(coverage.items())),
        "outcome_state_counts": dict(sorted(states.items())),
        "direction_counts": dict(sorted(by_direction.items())),
        "intrabar_ambiguous_outcomes": ambiguous,
        "complete_average_mfe_r": (
            None if not mfe_values else _decimal_text(sum(mfe_values) / Decimal(len(mfe_values)))
        ),
        "complete_average_mae_r": (
            None if not mae_values else _decimal_text(sum(mae_values) / Decimal(len(mae_values)))
        ),
        "outcome_causality_included": False,
    }
    result["distribution_digest"] = _digest(result)
    return result
