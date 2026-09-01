from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from aidy.databento_gc import DATABENTO_DATASET, GC_CONTINUOUS_SYMBOL
from aidy.gc_shadow_spine import digest
from aidy.market_sessions import session_code_at

MICROSTRUCTURE_VERSION = "aidy_gc_microstructure_v1"
BASELINE_VERSION = "aidy_gc_microstructure_weekday_clock15_v1"
J2_VERSION = "aidy_j2_gc_volume_incremental_v1"
J3_RICH_VERSION = "aidy_j3_gc_liquidity_repeat_v1"
DAY42_EXPERIMENT_PLAN_VERSION = "aidy_day42_j2_j3_experiment_plan_v1"
PROVENANCE_CLASS = "retrospective_history"
TBBO_SCHEMA = "tbbo"
CLOCK_BUCKET_MINUTES = 15
MIN_BASELINE_BUCKET_N = 20
VALID_AGGRESSOR_SIDES = frozenset({"A", "B", "N"})


class MicrostructureError(ValueError):
    """Raised when genuine GC microstructure evidence cannot be verified safely."""


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _positive_decimal(value: Any, *, name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise MicrostructureError(f"{name} must be a positive finite decimal.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise MicrostructureError(f"{name} must be a positive finite decimal.") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise MicrostructureError(f"{name} must be a positive finite decimal.")
    return parsed


def _timestamp(value: Any, *, name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError as exc:
            raise MicrostructureError(f"{name} must be an ISO-8601 timestamp.") from exc
    elif isinstance(value, int) and not isinstance(value, bool):
        parsed = datetime.fromtimestamp(value / 1_000_000_000, tz=UTC)
    else:
        raise MicrostructureError(f"{name} must be a timestamp.")
    if parsed.tzinfo is None:
        raise MicrostructureError(f"{name} must be timezone-aware.")
    return parsed.astimezone(UTC)


def _first_present(mapping: Mapping[str, Any], names: Sequence[str]) -> Any:
    for name in names:
        if name in mapping and mapping[name] is not None:
            return mapping[name]
    return None


def _raw_contract(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    symbol = value.strip().upper()
    if not symbol or symbol == GC_CONTINUOUS_SYMBOL.upper() or not symbol.startswith("GC"):
        return None
    return symbol


def _instrument_id(row: Mapping[str, Any]) -> int | None:
    header = row.get("hd")
    raw = header.get("instrument_id") if isinstance(header, Mapping) else row.get("instrument_id")
    if isinstance(raw, bool):
        return None
    try:
        parsed = int(str(raw))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _event_timestamp(row: Mapping[str, Any]) -> Any:
    value = _first_present(row, ("ts_event", "ts_recv"))
    header = row.get("hd")
    if value is None and isinstance(header, Mapping):
        value = _first_present(header, ("ts_event", "ts_recv"))
    return value


def _top_bbo(row: Mapping[str, Any]) -> tuple[Any, Any, Any, Any]:
    levels = row.get("levels")
    if isinstance(levels, list) and levels and isinstance(levels[0], Mapping):
        top = levels[0]
        return (
            _first_present(top, ("bid_px", "bid_px_00", "bid_price")),
            _first_present(top, ("ask_px", "ask_px_00", "ask_price")),
            _first_present(top, ("bid_sz", "bid_sz_00", "bid_size")),
            _first_present(top, ("ask_sz", "ask_sz_00", "ask_size")),
        )
    return (
        _first_present(row, ("bid_px_00", "bid_px", "bid_price")),
        _first_present(row, ("ask_px_00", "ask_px", "ask_price")),
        _first_present(row, ("bid_sz_00", "bid_sz", "bid_size")),
        _first_present(row, ("ask_sz_00", "ask_sz", "ask_size")),
    )


def _mean(values: Sequence[Decimal]) -> Decimal:
    if not values:
        raise MicrostructureError("Cannot calculate a mean from an empty series.")
    with localcontext() as ctx:
        ctx.prec = 34
        return sum(values, Decimal(0)) / Decimal(len(values))


def _median(values: Sequence[Decimal]) -> Decimal:
    if not values:
        raise MicrostructureError("Cannot calculate a median from an empty series.")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def _mean_std(values: Sequence[Decimal]) -> tuple[Decimal, Decimal]:
    mean = _mean(values)
    if len(values) < 2:
        return mean, Decimal(0)
    with localcontext() as ctx:
        ctx.prec = 34
        variance = sum((value - mean) ** 2 for value in values) / Decimal(len(values) - 1)
        return mean, variance.sqrt()


def _fmt(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value == 0:
        return "0"
    with localcontext() as ctx:
        ctx.prec = 34
        text = format(value.quantize(Decimal("0.000000001")), "f").rstrip("0").rstrip(".")
    return text or "0"


@dataclass(frozen=True, slots=True)
class TbboTrade:
    observed_at: datetime
    instrument_id: int
    contract_symbol: str
    price: Decimal
    size: Decimal
    aggressor_side: str
    bid: Decimal
    ask: Decimal
    bid_size: Decimal
    ask_size: Decimal
    source_digest: str
    provider: str = "Databento"
    dataset: str = DATABENTO_DATASET
    schema: str = TBBO_SCHEMA
    continuous_symbol: str = GC_CONTINUOUS_SYMBOL
    provenance_class: str = PROVENANCE_CLASS
    pit_eligible: bool = False

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
    def signed_volume(self) -> Decimal | None:
        if self.aggressor_side == "B":
            return self.size
        if self.aggressor_side == "A":
            return -self.size
        return None

    def as_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "microstructure_version": MICROSTRUCTURE_VERSION,
            "provider": self.provider,
            "dataset": self.dataset,
            "schema": self.schema,
            "continuous_symbol": self.continuous_symbol,
            "instrument_id": self.instrument_id,
            "contract_symbol": self.contract_symbol,
            "observed_at_utc": self.observed_at.astimezone(UTC).isoformat(),
            "price": str(self.price),
            "size": str(self.size),
            "aggressor_side": self.aggressor_side,
            "bid": str(self.bid),
            "ask": str(self.ask),
            "bid_size": str(self.bid_size),
            "ask_size": str(self.ask_size),
            "spread": str(self.spread),
            "spread_bps": str(self.spread_bps),
            "source_digest": self.source_digest,
            "provenance_class": self.provenance_class,
            "pit_eligible": self.pit_eligible,
            "genuine_trade": True,
            "genuine_pretrade_bbo": True,
            "depth_claimed": False,
            "order_book_imbalance_claimed": False,
            "aggressor_side_unknown_never_imputed": True,
        }
        body["trade_digest"] = digest(body)
        return body


@dataclass(frozen=True, slots=True)
class MinuteMicrostructure:
    minute_utc: datetime
    contract_symbol: str
    session: str
    trade_count: int
    trade_volume: Decimal
    buy_aggressor_volume: Decimal
    sell_aggressor_volume: Decimal
    unknown_side_volume: Decimal
    known_side_volume: Decimal
    signed_trade_imbalance: Decimal | None
    vwap: Decimal
    last_trade_price: Decimal
    mean_spread_bps: Decimal
    median_spread_bps: Decimal
    session_vwap: Decimal
    anchored_vwap: Decimal
    anchor_identity: str
    source_trade_digests: tuple[str, ...]

    @property
    def unknown_side_fraction(self) -> Decimal:
        return self.unknown_side_volume / self.trade_volume

    @property
    def vwap_distance_bps(self) -> Decimal:
        return (self.last_trade_price - self.anchored_vwap) / self.anchored_vwap * Decimal(10000)

    @property
    def weekday_utc(self) -> int:
        return self.minute_utc.weekday()

    @property
    def clock_slot_15m(self) -> int:
        return (self.minute_utc.hour * 60 + self.minute_utc.minute) // CLOCK_BUCKET_MINUTES

    def as_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "microstructure_version": MICROSTRUCTURE_VERSION,
            "minute_utc": self.minute_utc.astimezone(UTC).isoformat(),
            "contract_symbol": self.contract_symbol,
            "session": self.session,
            "weekday_utc": self.weekday_utc,
            "clock_slot_15m": self.clock_slot_15m,
            "trade_count": self.trade_count,
            "trade_volume": _fmt(self.trade_volume),
            "buy_aggressor_volume": _fmt(self.buy_aggressor_volume),
            "sell_aggressor_volume": _fmt(self.sell_aggressor_volume),
            "unknown_side_volume": _fmt(self.unknown_side_volume),
            "known_side_volume": _fmt(self.known_side_volume),
            "signed_trade_imbalance": _fmt(self.signed_trade_imbalance),
            "unknown_side_fraction": _fmt(self.unknown_side_fraction),
            "vwap": _fmt(self.vwap),
            "last_trade_price": _fmt(self.last_trade_price),
            "mean_spread_bps": _fmt(self.mean_spread_bps),
            "median_spread_bps": _fmt(self.median_spread_bps),
            "session_vwap": _fmt(self.session_vwap),
            "anchored_vwap": _fmt(self.anchored_vwap),
            "anchor_identity": self.anchor_identity,
            "vwap_distance_bps": _fmt(self.vwap_distance_bps),
            "source_trade_digests": list(self.source_trade_digests),
            "genuine_exchange_trade_volume": True,
            "genuine_pretrade_bbo_spread": True,
            "signed_trade_flow_only": True,
            "unknown_aggressor_side_imputed": False,
            "depth_claimed": False,
            "order_book_imbalance_claimed": False,
            "outcome_fields_used": False,
            "pit_eligible": False,
            "provenance_class": PROVENANCE_CLASS,
        }
        body["minute_digest"] = digest(body)
        return body


def parse_databento_tbbo_jsonl(
    payload: str,
    *,
    contract_by_instrument_id: Mapping[int, str],
) -> list[TbboTrade]:
    """Parse genuine Databento TBBO rows without inventing depth or aggressor side."""

    if not contract_by_instrument_id:
        raise MicrostructureError("Databento TBBO parsing requires an instrument-to-GC map.")
    trades: list[TbboTrade] = []
    for line_number, raw_line in enumerate(payload.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MicrostructureError(
                f"Databento TBBO line {line_number} contains malformed JSON."
            ) from exc
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        action = row.get("action")
        if action is not None and str(action).upper() != "T":
            raise MicrostructureError("TBBO contains a non-trade action.")
        side = str(row.get("side") or "").upper()
        if side not in VALID_AGGRESSOR_SIDES:
            raise MicrostructureError("TBBO trade side must be A, B or N.")
        instrument_id = _instrument_id(row)
        if instrument_id is None:
            raise MicrostructureError("TBBO trade is missing a valid instrument ID.")
        mapped_contract = _raw_contract(contract_by_instrument_id.get(instrument_id))
        inline_contract = (
            _raw_contract(row.get("symbol"))
            or _raw_contract(row.get("raw_symbol"))
            or _raw_contract(row.get("stype_out_symbol"))
        )
        contract = inline_contract or mapped_contract
        if contract is None:
            raise MicrostructureError("TBBO trade lacks an auditable raw GC contract identity.")
        if mapped_contract is not None and inline_contract is not None and mapped_contract != inline_contract:
            raise MicrostructureError("TBBO inline and symbology-resolved contract identities conflict.")
        observed_at = _timestamp(_event_timestamp(row), name="TBBO event timestamp")
        price = _positive_decimal(row.get("price"), name="TBBO trade price")
        size = _positive_decimal(row.get("size"), name="TBBO trade size")
        bid_raw, ask_raw, bid_size_raw, ask_size_raw = _top_bbo(row)
        bid = _positive_decimal(bid_raw, name="TBBO best bid")
        ask = _positive_decimal(ask_raw, name="TBBO best ask")
        bid_size = _positive_decimal(bid_size_raw, name="TBBO best bid size")
        ask_size = _positive_decimal(ask_size_raw, name="TBBO best ask size")
        if ask < bid:
            raise MicrostructureError("TBBO best ask cannot be below best bid.")
        if price < Decimal(100) or price > Decimal(100000):
            raise MicrostructureError("TBBO GC trade price is outside the sanity envelope.")
        source_body = {
            "dataset": DATABENTO_DATASET,
            "schema": TBBO_SCHEMA,
            "continuous_symbol": GC_CONTINUOUS_SYMBOL,
            "instrument_id": instrument_id,
            "contract_symbol": contract,
            "row": row,
        }
        trades.append(
            TbboTrade(
                observed_at=observed_at,
                instrument_id=instrument_id,
                contract_symbol=contract,
                price=price,
                size=size,
                aggressor_side=side,
                bid=bid,
                ask=ask,
                bid_size=bid_size,
                ask_size=ask_size,
                source_digest=digest(source_body),
            )
        )
    return trades


def _minute_from_trades(
    minute: datetime,
    contract: str,
    trades: Sequence[TbboTrade],
    *,
    cumulative_price_volume: Decimal,
    cumulative_volume: Decimal,
    anchor_identity: str,
) -> MinuteMicrostructure:
    ordered = sorted(trades, key=lambda item: (item.observed_at, item.source_digest))
    volume = sum((item.size for item in ordered), Decimal(0))
    buy = sum((item.size for item in ordered if item.aggressor_side == "B"), Decimal(0))
    sell = sum((item.size for item in ordered if item.aggressor_side == "A"), Decimal(0))
    unknown = sum((item.size for item in ordered if item.aggressor_side == "N"), Decimal(0))
    known = buy + sell
    signed = None if known == 0 else (buy - sell) / known
    price_volume = sum((item.price * item.size for item in ordered), Decimal(0))
    vwap = price_volume / volume
    cumulative_price_volume += price_volume
    cumulative_volume += volume
    session_vwap = cumulative_price_volume / cumulative_volume
    spreads = [item.spread_bps for item in ordered]
    session = session_code_at(minute)
    return MinuteMicrostructure(
        minute_utc=minute,
        contract_symbol=contract,
        session=session,
        trade_count=len(ordered),
        trade_volume=volume,
        buy_aggressor_volume=buy,
        sell_aggressor_volume=sell,
        unknown_side_volume=unknown,
        known_side_volume=known,
        signed_trade_imbalance=signed,
        vwap=vwap,
        last_trade_price=ordered[-1].price,
        mean_spread_bps=_mean(spreads),
        median_spread_bps=_median(spreads),
        session_vwap=session_vwap,
        anchored_vwap=session_vwap,
        anchor_identity=anchor_identity,
        source_trade_digests=tuple(item.source_digest for item in ordered),
    )


def aggregate_tbbo_minutes(trades: Iterable[TbboTrade]) -> list[MinuteMicrostructure]:
    """Aggregate genuine trades to minute features and deterministic session-anchored VWAP."""

    groups: dict[tuple[datetime, str], list[TbboTrade]] = defaultdict(list)
    for trade in trades:
        minute = trade.observed_at.astimezone(UTC).replace(second=0, microsecond=0)
        groups[(minute, trade.contract_symbol)].append(trade)
    if not groups:
        return []

    result: list[MinuteMicrostructure] = []
    cumulative: dict[str, tuple[str, Decimal, Decimal]] = {}
    for (minute, contract), group in sorted(groups.items(), key=lambda item: item[0]):
        session = session_code_at(minute)
        anchor_identity = f"{contract}:{minute.date().isoformat()}:{session}"
        prior_anchor, prior_pv, prior_volume = cumulative.get(
            contract,
            (anchor_identity, Decimal(0), Decimal(0)),
        )
        if prior_anchor != anchor_identity:
            prior_pv = Decimal(0)
            prior_volume = Decimal(0)
        row = _minute_from_trades(
            minute,
            contract,
            group,
            cumulative_price_volume=prior_pv,
            cumulative_volume=prior_volume,
            anchor_identity=anchor_identity,
        )
        minute_pv = row.vwap * row.trade_volume
        cumulative[contract] = (
            anchor_identity,
            prior_pv + minute_pv,
            prior_volume + row.trade_volume,
        )
        result.append(row)
    return result


def _metric_baseline(values: Sequence[Decimal], *, minimum_n: int) -> dict[str, Any]:
    mean, std = _mean_std(values)
    state = "known" if len(values) >= minimum_n and std > 0 else "insufficient"
    return {
        "sample_n": len(values),
        "state": state,
        "mean": _fmt(mean) if state == "known" else None,
        "std": _fmt(std) if state == "known" else None,
    }


def build_weekday_clock_baseline(
    minutes: Iterable[MinuteMicrostructure],
    *,
    minimum_bucket_n: int = MIN_BASELINE_BUCKET_N,
) -> dict[str, Any]:
    """Freeze outcome-blind weekday × 15-minute reference distributions."""

    if minimum_bucket_n < 2:
        raise MicrostructureError("Baseline minimum bucket N must be at least 2.")
    groups: dict[tuple[int, int], list[MinuteMicrostructure]] = defaultdict(list)
    minute_ids: list[str] = []
    for minute in sorted(minutes, key=lambda item: (item.minute_utc, item.contract_symbol)):
        groups[(minute.weekday_utc, minute.clock_slot_15m)].append(minute)
        minute_ids.append(str(minute.as_dict()["minute_digest"]))
    payload: dict[str, Any] = {}
    for (weekday, slot), rows in sorted(groups.items()):
        signed_values = [
            row.signed_trade_imbalance
            for row in rows
            if row.signed_trade_imbalance is not None
        ]
        payload[f"{weekday}:{slot}"] = {
            "weekday_utc": weekday,
            "clock_slot_15m": slot,
            "volume": _metric_baseline(
                [row.trade_volume for row in rows], minimum_n=minimum_bucket_n
            ),
            "spread_bps": _metric_baseline(
                [row.mean_spread_bps for row in rows], minimum_n=minimum_bucket_n
            ),
            "signed_trade_imbalance": (
                _metric_baseline(signed_values, minimum_n=minimum_bucket_n)
                if signed_values
                else {"sample_n": 0, "state": "insufficient", "mean": None, "std": None}
            ),
            "vwap_distance_bps": _metric_baseline(
                [row.vwap_distance_bps for row in rows], minimum_n=minimum_bucket_n
            ),
        }
    baseline: dict[str, Any] = {
        "baseline_version": BASELINE_VERSION,
        "dataset": DATABENTO_DATASET,
        "schema": TBBO_SCHEMA,
        "continuous_symbol": GC_CONTINUOUS_SYMBOL,
        "clock_bucket_minutes": CLOCK_BUCKET_MINUTES,
        "weekday_basis": "UTC_monday_0",
        "minimum_bucket_n": minimum_bucket_n,
        "outcome_fields_used": False,
        "ordinary_session_activity_can_count_as_alpha": False,
        "minute_identity_digest": digest(minute_ids),
        "groups": payload,
        "depth_claimed": False,
        "order_book_imbalance_claimed": False,
        "aggressor_side_unknown_never_imputed": True,
    }
    baseline["baseline_digest"] = digest(baseline)
    return baseline


def verify_weekday_clock_baseline(baseline: Mapping[str, Any]) -> bool:
    try:
        body = dict(baseline)
        supplied = str(body.pop("baseline_digest", ""))
        return (
            bool(supplied)
            and supplied == digest(body)
            and body.get("baseline_version") == BASELINE_VERSION
            and body.get("outcome_fields_used") is False
            and body.get("ordinary_session_activity_can_count_as_alpha") is False
        )
    except (KeyError, TypeError, ValueError):
        return False


def _zscore(value: Decimal, metric: Mapping[str, Any]) -> str | None:
    if metric.get("state") != "known":
        return None
    mean = _positive_or_zero_decimal(metric.get("mean"), name="baseline mean")
    std = _positive_decimal(metric.get("std"), name="baseline std")
    return _fmt((value - mean) / std)


def _positive_or_zero_decimal(value: Any, *, name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise MicrostructureError(f"{name} must be a non-negative finite decimal.") from exc
    if not parsed.is_finite() or parsed < 0:
        raise MicrostructureError(f"{name} must be a non-negative finite decimal.")
    return parsed


def normalize_minute(
    minute: MinuteMicrostructure,
    baseline: Mapping[str, Any],
) -> dict[str, Any]:
    if not verify_weekday_clock_baseline(baseline):
        raise MicrostructureError("Day 42 baseline digest or outcome-blind boundary is invalid.")
    groups = baseline.get("groups")
    if not isinstance(groups, Mapping):
        raise MicrostructureError("Day 42 baseline groups are missing.")
    key = f"{minute.weekday_utc}:{minute.clock_slot_15m}"
    bucket = groups.get(key)
    if not isinstance(bucket, Mapping):
        return {
            "minute_digest": minute.as_dict()["minute_digest"],
            "baseline_digest": baseline["baseline_digest"],
            "baseline_key": key,
            "state": "baseline_missing",
            "volume_z": None,
            "spread_z": None,
            "signed_trade_imbalance_z": None,
            "vwap_distance_z": None,
            "ordinary_session_activity_can_count_as_alpha": False,
        }
    volume_metric = bucket.get("volume")
    spread_metric = bucket.get("spread_bps")
    signed_metric = bucket.get("signed_trade_imbalance")
    vwap_metric = bucket.get("vwap_distance_bps")
    if not all(isinstance(item, Mapping) for item in (volume_metric, spread_metric, signed_metric, vwap_metric)):
        raise MicrostructureError("Day 42 baseline metric bucket is malformed.")
    volume_z = _zscore(minute.trade_volume, volume_metric)
    spread_z = _zscore(minute.mean_spread_bps, spread_metric)
    signed_z = (
        None
        if minute.signed_trade_imbalance is None
        else _zscore(minute.signed_trade_imbalance, signed_metric)
    )
    vwap_z = _zscore(minute.vwap_distance_bps, vwap_metric)
    state = "known" if volume_z is not None and spread_z is not None else "baseline_insufficient"
    result = {
        "minute_digest": minute.as_dict()["minute_digest"],
        "baseline_digest": baseline["baseline_digest"],
        "baseline_key": key,
        "state": state,
        "volume_z": volume_z,
        "spread_z": spread_z,
        "signed_trade_imbalance_z": signed_z,
        "vwap_distance_z": vwap_z,
        "ordinary_session_activity_can_count_as_alpha": False,
        "outcome_fields_used_for_normalization": False,
    }
    result["normalization_digest"] = digest(result)
    return result


def day42_experiment_plan() -> dict[str, Any]:
    """Frozen J2/J3 shadow experiment contract; outcome thresholds are not tuned here."""

    body: dict[str, Any] = {
        "plan_version": DAY42_EXPERIMENT_PLAN_VERSION,
        "j2_version": J2_VERSION,
        "j3_version": J3_RICH_VERSION,
        "source_dataset": DATABENTO_DATASET,
        "source_schema": TBBO_SCHEMA,
        "baseline_version": BASELINE_VERSION,
        "chronological_split_manifest_version": "aidy_chronological_split_manifest_v1",
        "replay_harness_version": "aidy_frozen_replay_cpcv_v1",
        "purge_required": True,
        "embargo_required": True,
        "day32_trial_registry_required": True,
        "j2_hypothesis": (
            "Matched-clock genuine GC trade participation/flow features add incremental outcome "
            "information beyond the frozen baseline context."
        ),
        "j2_null_hypothesis": (
            "After frozen baseline controls, genuine GC volume/flow/VWAP features add no "
            "incremental outcome information."
        ),
        "j3_hypothesis": (
            "Matched-clock genuine GC spread/liquidity state is associated with setup failure "
            "after controlling for the frozen volatility context."
        ),
        "j3_null_hypothesis": (
            "After frozen volatility and clock/weekday controls, genuine GC spread/liquidity "
            "state does not differentiate setup failure."
        ),
        "minimum_independent_evaluation_n": 30,
        "ordinary_session_activity_can_count_as_alpha": False,
        "null_or_insufficient_result_allowed": True,
        "single_result_can_promote_gate": False,
        "predictive_edge_claimed": False,
        "features_shadow_only": True,
        "formal_forward_evidence_created": False,
        "depth_claimed": False,
        "order_book_imbalance_claimed": False,
        "mbo_allowed": False,
        "mbp10_allowed": False,
    }
    body["plan_digest"] = digest(body)
    return body


def run_shadow_experiment(
    *,
    experiment: str,
    eligible_rows: Sequence[Mapping[str, Any]],
    split_binding: Mapping[str, Any],
    minimum_independent_n: int = 30,
) -> dict[str, Any]:
    """Run the pre-registered Day 42 evaluation and retain null/insufficient outcomes.

    This intentionally does not invent a predictive model. Rows must already contain a
    preregistered scalar `incremental_statistic` measured on an evaluation cohort. The
    Day 42 acceptance run can therefore finish honestly as insufficient when no genuine
    outcome-linked cohort exists yet, while the same contract can later report a null or
    descriptive non-null statistic without silently changing the evaluation rule.
    """

    if experiment not in {"J2", "J3"}:
        raise MicrostructureError("Day 42 experiment must be J2 or J3.")
    if minimum_independent_n < 2:
        raise MicrostructureError("Day 42 minimum independent N must be at least 2.")
    if split_binding.get("manifest_version") != "aidy_chronological_split_manifest_v1":
        raise MicrostructureError("Day 42 requires the Day 37 chronological split contract.")
    if split_binding.get("purge_required") is not True or split_binding.get("embargo_required") is not True:
        raise MicrostructureError("Day 42 J2/J3 require purge and embargo.")
    if split_binding.get("holdout_tuning_allowed") is not False:
        raise MicrostructureError("Day 42 cannot tune on holdout.")

    usable: list[Decimal] = []
    episode_ids: set[str] = set()
    for row in eligible_rows:
        episode_id = str(row.get("independent_episode_id") or "")
        statistic = row.get("incremental_statistic")
        if not episode_id or statistic is None:
            continue
        if episode_id in episode_ids:
            continue
        episode_ids.add(episode_id)
        try:
            value = Decimal(str(statistic))
        except (InvalidOperation, ValueError) as exc:
            raise MicrostructureError("Day 42 incremental statistic must be finite.") from exc
        if not value.is_finite():
            raise MicrostructureError("Day 42 incremental statistic must be finite.")
        usable.append(value)

    effective_n = len(usable)
    statistic_mean = None if not usable else _mean(usable)
    if effective_n < minimum_independent_n:
        result_state = "insufficient"
    elif statistic_mean == 0:
        result_state = "null"
    else:
        result_state = "descriptive_non_null"
    result: dict[str, Any] = {
        "experiment": experiment,
        "experiment_version": J2_VERSION if experiment == "J2" else J3_RICH_VERSION,
        "split_digest": split_binding.get("split_digest"),
        "purge_required": True,
        "embargo_required": True,
        "holdout_tuning_allowed": False,
        "raw_rows": len(eligible_rows),
        "effective_independent_n": effective_n,
        "minimum_independent_evaluation_n": minimum_independent_n,
        "mean_incremental_statistic": _fmt(statistic_mean),
        "result_state": result_state,
        "ordinary_session_activity_can_count_as_alpha": False,
        "proposed_trading_gate": None,
        "gate_promoted": False,
        "predictive_edge_claimed": False,
        "features_shadow_only": True,
        "formal_forward_evidence_created": False,
    }
    result["result_digest"] = digest(result)
    return result
