"""AIDY Strategy Lab B02 canonical StrategySpec v1 — strict typed rule representation.

This is a data-only research contract, NOT a signal interpreter or backtest engine.
Parsing rejects unknown fields and executable expressions; no arbitrary source runs.
Day09 separately grades rule completeness and resolvable ambiguities.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date, time
from decimal import Decimal, InvalidOperation
from typing import Any

SCHEMA_VERSION = "aidy.strategy_spec.v1"
TIMEFRAMES = frozenset({"M1", "M5", "M15", "H1", "H4", "D1"})
PRICE_FIELDS = frozenset({"open", "high", "low", "close"})
OPS = frozenset({"gt", "gte", "lt", "lte", "eq", "cross_above", "cross_below"})
STRATEGY_TYPES = frozenset({
    "complete_mechanical", "partial_indicator", "variant", "opaque_black_box"
})
SOURCE_LANGUAGES = frozenset({"written_rules", "pine", "mql4", "mql5", "python"})
DISTANCE_MODES = frozenset({"price", "ticks", "percent", "atr_multiple"})
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
SHA_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _mapping(value: Any, keys: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{name} must contain exactly {sorted(keys)}")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name} requires a nonblank, trimmed string")
    return value


def _choice(value: Any, choices: frozenset[str], name: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"unsupported {name}: {value!r}")
    return value


def _id(value: Any, name: str) -> str:
    text = _string(value, name)
    if ID_PATTERN.fullmatch(text) is None:
        raise ValueError(f"{name} must match lower-case canonical identifier")
    return text


def _hash(value: Any) -> str:
    if not isinstance(value, str) or SHA_PATTERN.fullmatch(value) is None:
        raise ValueError("source_sha256 requires real 64-character hexadecimal digest")
    return value


def _int(value: Any, name: str, *, minimum: int = 0, maximum: int = 100_000) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} requires integer between {minimum} and {maximum}")
    return value


def _decimal(value: Any, name: str, *, allow_zero: bool = False) -> Decimal:
    # Integers are allowed but binary floats and bools are not — money/risk exactness.
    if isinstance(value, (bool, float)) or not isinstance(value, (str, int, Decimal)):
        raise ValueError(f"{name} requires exact decimal text or integer")  # noqa: TRY004
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} requires finite decimal") from exc
    if not parsed.is_finite() or parsed < 0 or (not allow_zero and parsed == 0):
        raise ValueError(f"{name} must be positive finite decimal")
    return parsed


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name} must be true or false")
    return value


def _array(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")  # noqa: TRY004
    return value


def _optional(value: Any, convert: Any) -> Any:
    return None if value is None else convert(value)


@dataclass(frozen=True, slots=True)
class Origin:
    author: str
    source_url: str | None
    source_language: str
    source_sha256: str
    source_snapshot_ref: str | None
    licence: str
    claimed_performance: str | None
    interpretation_notes: tuple[str, ...]
    unresolved_questions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Market:
    symbol: str
    signal_timeframe: str
    data_source: str
    source_clock: str
    price_basis: str


@dataclass(frozen=True, slots=True)
class Indicator:
    id: str
    kind: str
    timeframe: str
    price_field: str
    period: int
    additional_parameters: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class Operand:
    kind: str
    reference: str
    field: str
    offset_closed_bars: int


@dataclass(frozen=True, slots=True)
class Predicate:
    left: Operand
    operator: str
    right: Operand


@dataclass(frozen=True, slots=True)
class Signal:
    enabled: bool
    combination: str
    predicates: tuple[Predicate, ...]


@dataclass(frozen=True, slots=True)
class Distance:
    mode: str
    value: Decimal
    indicator_id: str | None


@dataclass(frozen=True, slots=True)
class PartialExit:
    fraction_percent: Decimal
    target: Distance


@dataclass(frozen=True, slots=True)
class ExitPlan:
    stop_loss: Distance | None
    take_profit: Distance | None
    trailing_stop: Distance | None
    partial_exits: tuple[PartialExit, ...]
    maximum_holding_bars: int | None
    close_on_opposite_signal: bool
    close_on_session_end: bool


@dataclass(frozen=True, slots=True)
class Side:
    entry: Signal
    exit: ExitPlan


@dataclass(frozen=True, slots=True)
class SessionWindow:
    weekday: int
    start_hhmm: str
    end_hhmm: str


@dataclass(frozen=True, slots=True)
class Sessions:
    timezone: str
    allowed: tuple[SessionWindow, ...]
    excluded_dates: tuple[str, ...]
    flat_outside_sessions: bool


@dataclass(frozen=True, slots=True)
class Sizing:
    mode: str
    fixed_lots: Decimal | None
    risk_percent_equity: Decimal | None


@dataclass(frozen=True, slots=True)
class Portfolio:
    max_positions: int
    allow_hedging: bool
    allow_pyramiding: bool
    max_total_risk_percent: Decimal


@dataclass(frozen=True, slots=True)
class Execution:
    signal_evaluation: str
    entry_execution: str


@dataclass(frozen=True, slots=True)
class StrategySpec:
    schema_version: str
    strategy_id: str
    revision: int
    title: str
    candidate_type: str
    origin: Origin
    market: Market
    warmup_closed_bars: int
    indicators: tuple[Indicator, ...]
    long: Side
    short: Side
    sessions: Sessions
    sizing: Sizing
    portfolio: Portfolio
    execution: Execution

    def to_wire(self) -> dict[str, Any]:
        def convert(item: Any) -> Any:
            if isinstance(item, Decimal):
                return format(item, "f")
            if isinstance(item, tuple):
                return [convert(x) for x in item]
            if isinstance(item, list):
                return [convert(x) for x in item]
            if isinstance(item, dict):
                return {k: convert(v) for k, v in item.items()}
            return item

        result = convert(asdict(self))
        # Additional indicator params are stable wire-level objects, not arrays
        # of key-value pairs; this preserves strict JSON API interoperability.
        for indicator in result["indicators"]:
            indicator["additional_parameters"] = dict(indicator["additional_parameters"])
        return result

    def to_json(self) -> str:
        return json.dumps(self.to_wire(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> StrategySpec:
        def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            output: dict[str, Any] = {}
            for key, val in pairs:
                if key in output:
                    raise ValueError(f"duplicate JSON key {key!r}")
                output[key] = val
            return output
        try:
            obj = json.loads(text, object_pairs_hook=reject_duplicate,
                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid StrategySpec JSON") from exc
        return cls.from_wire(obj)

    @classmethod
    def from_wire(cls, obj: Any) -> StrategySpec:
        data = _mapping(obj, set(cls.__dataclass_fields__), "StrategySpec")
        if data["schema_version"] != SCHEMA_VERSION:
            raise ValueError("unsupported StrategySpec schema_version")
        sid = _id(data["strategy_id"], "strategy_id")
        revision = _int(data["revision"], "revision", minimum=1)
        title = _string(data["title"], "title")
        candidate = _choice(data["candidate_type"], STRATEGY_TYPES, "candidate_type")

        o = _mapping(data["origin"], set(Origin.__dataclass_fields__), "origin")
        source_url = _optional(o["source_url"], lambda x: _string(x, "source_url"))
        if source_url is not None and not source_url.startswith(("https://", "http://")):
            raise ValueError("source_url must be http(s)")
        origin = Origin(
            _string(o["author"], "author"), source_url,
            _choice(o["source_language"], SOURCE_LANGUAGES, "source_language"),
            _hash(o["source_sha256"]),
            _optional(o["source_snapshot_ref"], lambda x: _string(x, "source_snapshot_ref")),
            _string(o["licence"], "licence"),
            _optional(o["claimed_performance"], lambda x: _string(x, "claimed_performance")),
            tuple(_string(x, "interpretation note") for x in _array(o["interpretation_notes"], "interpretation_notes")),
            tuple(_string(x, "unresolved question") for x in _array(o["unresolved_questions"], "unresolved_questions")),
        )
        m = _mapping(data["market"], set(Market.__dataclass_fields__), "market")
        market = Market(
            _choice(m["symbol"], frozenset({"XAUUSD"}), "symbol"),
            _choice(m["signal_timeframe"], TIMEFRAMES, "signal_timeframe"),
            _string(m["data_source"], "data_source"),
            _choice(m["source_clock"], frozenset({"EST_FIXED_UTC_MINUS_05", "UTC"}), "source_clock"),
            _choice(m["price_basis"], frozenset({"bid", "ask", "mid"}), "price_basis"),
        )

        indicator_rows = _array(data["indicators"], "indicators")
        indicators = []
        ids: set[str] = set()
        for row in indicator_rows:
            i = _mapping(row, set(Indicator.__dataclass_fields__), "indicator")
            identifier = _id(i["id"], "indicator.id")
            if identifier in ids:
                raise ValueError("duplicate indicator ID")
            ids.add(identifier)
            params = i["additional_parameters"]
            if not isinstance(params, dict):
                raise ValueError("additional_parameters must be object")  # noqa: TRY004
            additional = []
            for key, val in sorted(params.items()):
                _id(key, "indicator parameter")
                additional.append((key, format(_decimal(val, key, allow_zero=True), "f")))
            indicators.append(Indicator(
                identifier, _choice(i["kind"], frozenset({"SMA", "EMA", "RSI", "ATR"}), "indicator"),
                _choice(i["timeframe"], TIMEFRAMES, "indicator timeframe"),
                _choice(i["price_field"], PRICE_FIELDS, "indicator price field"),
                _int(i["period"], "indicator.period", minimum=1, maximum=10000),
                tuple(additional),
            ))
        warmup = _int(data["warmup_closed_bars"], "warmup", minimum=1, maximum=100000)

        def operand(value: Any) -> Operand:
            v = _mapping(value, set(Operand.__dataclass_fields__), "operand")
            kind = _choice(v["kind"], frozenset({"price", "indicator", "constant"}), "operand kind")
            ref = _string(v["reference"], "operand.reference")
            field = _string(v["field"], "operand.field")
            offset = _int(v["offset_closed_bars"], "offset_closed_bars", maximum=100000)
            if kind == "price" and (ref != "XAUUSD" or field not in PRICE_FIELDS):
                raise ValueError("price operand requires XAUUSD OHLC reference")
            if kind == "indicator" and (ref not in ids or field != "value"):
                raise ValueError("unknown indicator reference or output field")
            if kind == "constant":
                if field != "value" or offset != 0:
                    raise ValueError("constant cannot have field mismatch or historical offset")
                ref = format(_decimal(ref, "constant", allow_zero=True), "f")
            return Operand(kind, ref, field, offset)

        def signal(value: Any) -> Signal:
            v = _mapping(value, set(Signal.__dataclass_fields__), "signal")
            enabled = _bool(v["enabled"], "signal.enabled")
            combination = _choice(v["combination"], frozenset({"ALL", "ANY"}), "signal.combination")
            rules = []
            for row in _array(v["predicates"], "predicates"):
                p = _mapping(row, set(Predicate.__dataclass_fields__), "predicate")
                rules.append(Predicate(operand(p["left"]), _choice(p["operator"], OPS, "operator"),
                                       operand(p["right"])))
            if enabled != bool(rules):
                raise ValueError("enabled signal must have rules; disabled signal must not")
            return Signal(enabled, combination, tuple(rules))

        def distance(value: Any) -> Distance:
            v = _mapping(value, set(Distance.__dataclass_fields__), "distance")
            mode = _choice(v["mode"], DISTANCE_MODES, "distance.mode")
            unit = _decimal(v["value"], "distance.value")
            iid = _optional(v["indicator_id"], lambda x: _id(x, "distance.indicator_id"))
            if (mode == "atr_multiple") != (iid is not None):
                raise ValueError("ATR distance requires explicit indicator ID, other distances forbid one")
            if iid is not None and iid not in ids:
                raise ValueError("distance references unknown indicator")
            if mode == "percent" and unit > 100:
                raise ValueError("percent distance above 100")
            return Distance(mode, unit, iid)

        def side(value: Any) -> Side:
            v = _mapping(value, set(Side.__dataclass_fields__), "side")
            e = _mapping(v["exit"], set(ExitPlan.__dataclass_fields__), "exit")
            partials = []
            for row in _array(e["partial_exits"], "partial_exits"):
                p = _mapping(row, set(PartialExit.__dataclass_fields__), "partial_exit")
                partials.append(PartialExit(_decimal(p["fraction_percent"], "partial fraction"),
                                            distance(p["target"])))
            if sum((p.fraction_percent for p in partials), Decimal(0)) > 100:
                raise ValueError("partial exits exceed 100% of position")
            exits = ExitPlan(
                _optional(e["stop_loss"], distance), _optional(e["take_profit"], distance),
                _optional(e["trailing_stop"], distance), tuple(partials),
                _optional(e["maximum_holding_bars"],
                          lambda x: _int(x, "maximum_holding_bars", minimum=1)),
                _bool(e["close_on_opposite_signal"], "close_on_opposite_signal"),
                _bool(e["close_on_session_end"], "close_on_session_end"),
            )
            entry = signal(v["entry"])
            if not entry.enabled and any((exits.stop_loss is not None,
                    exits.take_profit is not None, exits.trailing_stop is not None,
                    exits.partial_exits, exits.maximum_holding_bars is not None)):
                raise ValueError("disabled side may not configure active exits")
            return Side(entry, exits)

        long, short = side(data["long"]), side(data["short"])
        s = _mapping(data["sessions"], set(Sessions.__dataclass_fields__), "sessions")
        # Exact timezone rule declarations; no broker timezone is inferred.
        tz = _choice(s["timezone"], frozenset({"UTC", "EST_FIXED_UTC_MINUS_05"}),
                     "sessions.timezone")
        sessions = []
        for row in _array(s["allowed"], "sessions.allowed"):
            w = _mapping(row, set(SessionWindow.__dataclass_fields__), "session window")
            weekday = _int(w["weekday"], "weekday", maximum=6)
            start = _string(w["start_hhmm"], "start_hhmm")
            end = _string(w["end_hhmm"], "end_hhmm")
            for clock in (start, end):
                try:
                    parsed = time.fromisoformat(clock)
                except ValueError as exc:
                    raise ValueError("invalid session HH:MM") from exc
                if len(clock) != 5 or parsed.second != 0:
                    raise ValueError("session clocks require HH:MM minute precision")
            if start == end:
                raise ValueError("zero-length session")
            sessions.append(SessionWindow(weekday, start, end))
        excluded = []
        for value in _array(s["excluded_dates"], "sessions.excluded_dates"):
            day = _string(value, "excluded date")
            try:
                date.fromisoformat(day)
            except ValueError as exc:
                raise ValueError("invalid excluded date") from exc
            if len(day) != 10:
                raise ValueError("excluded dates must be YYYY-MM-DD")
            excluded.append(day)
        if len(set(excluded)) != len(excluded):
            raise ValueError("duplicate session exclusion")
        sessions_contract = Sessions(tz, tuple(sessions), tuple(excluded),
                                     _bool(s["flat_outside_sessions"], "flat_outside_sessions"))

        z = _mapping(data["sizing"], set(Sizing.__dataclass_fields__), "sizing")
        mode = _choice(z["mode"], frozenset({"fixed_lots", "risk_percent_equity"}), "sizing.mode")
        fixed = _optional(z["fixed_lots"], lambda x: _decimal(x, "fixed_lots"))
        risk = _optional(z["risk_percent_equity"], lambda x: _decimal(x, "risk_percent_equity"))
        if (mode == "fixed_lots" and (fixed is None or risk is not None)) or (
            mode == "risk_percent_equity" and (risk is None or fixed is not None)
        ):
            raise ValueError("sizing must explicitly specify exactly its chosen value")
        if risk is not None and risk > 100:
            raise ValueError("risk_percent_equity above 100")
        sizing = Sizing(mode, fixed, risk)
        p = _mapping(data["portfolio"], set(Portfolio.__dataclass_fields__), "portfolio")
        portfolio = Portfolio(
            _int(p["max_positions"], "max_positions", minimum=1, maximum=1000),
            _bool(p["allow_hedging"], "allow_hedging"),
            _bool(p["allow_pyramiding"], "allow_pyramiding"),
            _decimal(p["max_total_risk_percent"], "max_total_risk_percent"),
        )
        if portfolio.max_total_risk_percent > 100:
            raise ValueError("max_total_risk_percent above 100")
        e = _mapping(data["execution"], set(Execution.__dataclass_fields__), "execution")
        execution = Execution(
            _choice(e["signal_evaluation"], frozenset({"closed_bar_only"}), "signal_evaluation"),
            _choice(e["entry_execution"], frozenset({"next_tradable_quote"}), "entry_execution"),
        )
        return cls(SCHEMA_VERSION, sid, revision, title, candidate, origin, market, warmup,
                   tuple(indicators), long, short, sessions_contract, sizing, portfolio, execution)
