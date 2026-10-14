"""Day 11: source-bound XAUUSD broker contract profiles (no broker connections).

This is a strict, versioned data contract. It does not simulate fills, calculate
overnight cash flows or attest a broker's real-world settings without independent
broker observations. No credentials, account IDs or trading authority are needed.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

VERSION = "aidy.broker_profile.v1"
PROFILE_ID = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
SHA = re.compile(r"^[0-9a-f]{64}$")
UTC_OFFSET = re.compile(r"^UTC([+-])(\d{2}):(\d{2})$")
CLOCK_MODELS = frozenset({"fixed_utc_offset", "iana_timezone"})
EVIDENCE_KINDS = frozenset({"internal_fixture", "broker_terminal_export", "official_broker_contract"})


def _object(obj: Any, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(obj, dict) or set(obj) != fields:
        raise ValueError(f"{name} must contain exactly {sorted(fields)}")
    return obj


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{name}: required trimmed nonempty text")
    return value


def _id(value: Any, name: str) -> str:
    value = _text(value, name)
    if PROFILE_ID.fullmatch(value) is None:
        raise ValueError(f"{name}: canonical lower-case ID required")
    return value


def _dec(value: Any, name: str, *, allow_negative: bool = False,
         allow_zero: bool = False) -> Decimal:
    if isinstance(value, (bool, float)) or not isinstance(value, (str, int, Decimal)):
        raise ValueError(f"{name}: use exact decimal text/integer, never float or bool")
    try:
        number = Decimal(str(value))
    except (ValueError, InvalidOperation) as exc:
        raise ValueError(f"{name}: invalid decimal") from exc
    if not number.is_finite() or (not allow_negative and number < 0) or (
        not allow_negative and not allow_zero and number == 0
    ):
        raise ValueError(f"{name}: out of permitted range")
    return number


def _integer(value: Any, name: str, lower: int, upper: int) -> int:
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f"{name}: integer outside [{lower},{upper}]")
    return value


def _stamp(value: Any, name: str) -> datetime:
    raw = _text(value, name)
    if not raw.endswith("Z"):
        raise ValueError(f"{name}: exact UTC Z suffix required")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name}: invalid ISO timestamp") from exc
    if dt.tzinfo is None or dt.utcoffset() != timedelta(0):
        raise ValueError(f"{name}: UTC timestamp required")
    return dt.astimezone(UTC)


def _time_hhmm(value: Any) -> str:
    val = _text(value, "rollover_hhmm")
    if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", val) is None:
        raise ValueError("rollover_hhmm: HH:MM required")
    return val


@dataclass(frozen=True, slots=True)
class SymbolContract:
    symbol: str
    quote_currency: str
    profit_currency: str
    margin_currency: str
    contract_ounces_per_lot: Decimal
    tick_size: Decimal
    point_size: Decimal
    price_digits: int
    tick_value_profit_currency_per_lot: Decimal
    volume_min_lots: Decimal
    volume_max_lots: Decimal
    volume_step_lots: Decimal
    stops_level_ticks: int
    freeze_level_ticks: int


@dataclass(frozen=True, slots=True)
class MarginTerms:
    calculation: str
    leverage_ratio: Decimal


@dataclass(frozen=True, slots=True)
class Costs:
    commission_usd_per_lot_per_side: Decimal | None
    swap_long_usd_per_lot_per_rollover: Decimal | None
    swap_short_usd_per_lot_per_rollover: Decimal | None
    triple_swap_weekday: int | None
    rollover_hhmm: str | None
    slippage_scenario_ticks: Decimal | None


@dataclass(frozen=True, slots=True)
class ServerClock:
    clock_model: str
    zone: str
    observed_utc: str
    observed_server_hhmm: str


@dataclass(frozen=True, slots=True)
class Provenance:
    evidence_kind: str
    source_reference: str
    source_sha256: str
    captured_at_utc: str
    evidence_label: str


@dataclass(frozen=True, slots=True)
class BrokerProfile:
    schema_version: str
    profile_id: str
    revision: int
    broker_id: str
    account_type: str
    account_currency: str
    contract: SymbolContract
    margin: MarginTerms
    costs: Costs
    clock: ServerClock
    provenance: Provenance

    def to_wire(self) -> dict[str, Any]:
        def normalise(v: Any) -> Any:
            if isinstance(v, Decimal):
                return format(v, "f")
            if isinstance(v, dict):
                return {k: normalise(item) for k, item in v.items()}
            return v
        return normalise(asdict(self))

    def to_json(self) -> str:
        return json.dumps(self.to_wire(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, value: str) -> BrokerProfile:
        def no_duplicate(items: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, item in items:
                if key in result:
                    raise ValueError(f"duplicate broker-profile JSON key {key!r}")
                result[key] = item
            return result
        try:
            parsed = json.loads(value, object_pairs_hook=no_duplicate,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON constant")))
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError("invalid broker-profile JSON") from exc
        return cls.from_wire(parsed)

    @classmethod
    def from_wire(cls, value: Any) -> BrokerProfile:
        v = _object(value, set(cls.__dataclass_fields__), "broker profile")
        if v["schema_version"] != VERSION:
            raise ValueError("unsupported broker schema")
        profile_id = _id(v["profile_id"], "profile_id")
        revision = _integer(v["revision"], "revision", 1, 100000)
        broker = _id(v["broker_id"], "broker_id")
        account_type = _id(v["account_type"], "account_type")
        if v["account_currency"] != "USD":
            raise ValueError("only USD account currency is qualified; FX conversions require a later gate")

        c = _object(v["contract"], set(SymbolContract.__dataclass_fields__), "contract")
        if (c["symbol"], c["quote_currency"], c["profit_currency"],
            c["margin_currency"]) != ("XAUUSD", "USD", "USD", "USD"):
            raise ValueError("XAUUSD quote/profit/margin must be explicit USD for Day11")
        ounces = _dec(c["contract_ounces_per_lot"], "contract_ounces_per_lot")
        tick = _dec(c["tick_size"], "tick_size")
        point = _dec(c["point_size"], "point_size")
        digits = _integer(c["price_digits"], "price_digits", 0, 8)
        tick_value = _dec(c["tick_value_profit_currency_per_lot"], "tick_value")
        minimum = _dec(c["volume_min_lots"], "volume_min_lots")
        maximum = _dec(c["volume_max_lots"], "volume_max_lots")
        step = _dec(c["volume_step_lots"], "volume_step_lots")
        stops = _integer(c["stops_level_ticks"], "stops_level_ticks", 0, 100000)
        freeze = _integer(c["freeze_level_ticks"], "freeze_level_ticks", 0, 100000)
        if tick != point * (tick / point).to_integral_value() or tick < point:
            raise ValueError("tick_size must be an integer multiple of point_size")
        if tick != Decimal(1).scaleb(-digits) * (tick / Decimal(1).scaleb(-digits)).to_integral_value():
            raise ValueError("tick_size cannot violate price_digits")
        if tick_value != ounces * tick:
            raise ValueError("tick value inconsistent with contract size and quoted USD tick")
        if maximum < minimum or ((maximum - minimum) / step) % 1 != 0:
            raise ValueError("invalid volume grid; max must be reachable from min")
        contract = SymbolContract("XAUUSD", "USD", "USD", "USD", ounces, tick, point,
                                  digits, tick_value, minimum, maximum, step, stops, freeze)

        m = _object(v["margin"], set(MarginTerms.__dataclass_fields__), "margin")
        if m["calculation"] != "notional_usd_divided_by_leverage":
            raise ValueError("margin model not independently supported")
        leverage = _dec(m["leverage_ratio"], "leverage_ratio")
        if leverage < 1 or leverage > 10000:
            raise ValueError("leverage must lie within 1–10000")
        margin = MarginTerms("notional_usd_divided_by_leverage", leverage)

        raw_costs = _object(v["costs"], set(Costs.__dataclass_fields__), "costs")
        def cost(name: str, signed: bool = False) -> Decimal | None:
            raw = raw_costs[name]
            return None if raw is None else _dec(raw, name, allow_zero=True, allow_negative=signed)
        commission = cost("commission_usd_per_lot_per_side")
        swap_long = cost("swap_long_usd_per_lot_per_rollover", True)
        swap_short = cost("swap_short_usd_per_lot_per_rollover", True)
        slippage = cost("slippage_scenario_ticks")
        triple_raw = raw_costs["triple_swap_weekday"]
        rollover_raw = raw_costs["rollover_hhmm"]
        triple = None if triple_raw is None else _integer(triple_raw, "triple_swap_weekday", 0, 6)
        rollover = None if rollover_raw is None else _time_hhmm(rollover_raw)
        if any(x is None for x in (swap_long, swap_short, triple, rollover)) and any(
            x is not None for x in (swap_long, swap_short, triple, rollover)
        ):
            raise ValueError("swap amounts, triple weekday, and rollover time must be all present or all absent")
        costs = Costs(commission, swap_long, swap_short, triple, rollover, slippage)

        clk = _object(v["clock"], set(ServerClock.__dataclass_fields__), "clock")
        if clk["clock_model"] not in CLOCK_MODELS:
            raise ValueError("unsupported server clock model")
        zone = _text(clk["zone"], "server zone")
        if clk["clock_model"] == "fixed_utc_offset":
            match = UTC_OFFSET.fullmatch(zone)
            if zone != "UTC" and match is None:
                raise ValueError("fixed clock requires UTC or UTC±HH:MM")
            if match:
                hours, minutes = int(match[2]), int(match[3])
                if hours > 14 or minutes >= 60 or (hours == 14 and minutes):
                    raise ValueError("invalid fixed GMT offset")
        else:
            if zone == "UTC" or UTC_OFFSET.fullmatch(zone):
                raise ValueError("IANA clock model requires explicit IANA timezone name")
            try:
                ZoneInfo(zone)
            except ZoneInfoNotFoundError as exc:
                raise ValueError("unknown IANA server timezone") from exc
        observed_utc = _stamp(clk["observed_utc"], "clock.observed_utc")
        server_hhmm = _time_hhmm(clk["observed_server_hhmm"])
        clock = ServerClock(clk["clock_model"], zone,
                            observed_utc.isoformat().replace("+00:00", "Z"), server_hhmm)
        if clock_server_time(clock, observed_utc).strftime("%H:%M") != server_hhmm:
            raise ValueError("observed server clock not consistent with declared source timezone")

        p = _object(v["provenance"], set(Provenance.__dataclass_fields__), "provenance")
        if p["evidence_kind"] not in EVIDENCE_KINDS:
            raise ValueError("unsupported broker source evidence")
        source_ref = _text(p["source_reference"], "source_reference")
        sha = p["source_sha256"]
        if not isinstance(sha, str) or SHA.fullmatch(sha) is None:
            raise ValueError("broker source needs original SHA-256 digest")
        captured = _stamp(p["captured_at_utc"], "captured_at_utc")
        if captured < observed_utc:
            raise ValueError("broker source captured before claimed clock observation")
        label = _text(p["evidence_label"], "evidence_label")
        if p["evidence_kind"] == "internal_fixture" and label != "illustrative_not_live":
            raise ValueError("fixtures must explicitly identify themselves")
        provenance = Provenance(p["evidence_kind"], source_ref, sha,
            captured.isoformat().replace("+00:00", "Z"), label)
        return cls(VERSION, profile_id, revision, broker, account_type, "USD",
                   contract, margin, costs, clock, provenance)

    def is_valid_lot(self, quantity: Any) -> bool:
        try:
            qty = _dec(quantity, "lots")
        except ValueError:
            return False
        c = self.contract
        return (c.volume_min_lots <= qty <= c.volume_max_lots
                and (qty - c.volume_min_lots) % c.volume_step_lots == 0)

    def usd_per_tick(self, quantity: Any) -> Decimal:
        if not self.is_valid_lot(quantity):
            raise ValueError("invalid lot size or step")
        return self.contract.tick_value_profit_currency_per_lot * _dec(quantity, "lots")

    def initial_margin_usd(self, quote_usd_per_ounce: Any, quantity: Any) -> Decimal:
        if not self.is_valid_lot(quantity):
            raise ValueError("invalid lot size or step")
        price = _dec(quote_usd_per_ounce, "quote_usd_per_ounce")
        return self.contract.contract_ounces_per_lot * price * _dec(quantity, "lots") / self.margin.leverage_ratio


def clock_server_time(clock: ServerClock, at_utc: datetime) -> datetime:
    if at_utc.tzinfo is None or at_utc.utcoffset() != timedelta(0):
        raise ValueError("UTC-aware time required")
    if clock.clock_model == "iana_timezone":
        return at_utc.astimezone(ZoneInfo(clock.zone))
    if clock.zone == "UTC":
        return at_utc
    match = UTC_OFFSET.fullmatch(clock.zone)
    if match is None:
        raise ValueError("invalid fixed UTC clock zone")
    delta = timedelta(hours=int(match[2]), minutes=int(match[3]))
    if match[1] == "-":
        delta = -delta
    return at_utc.astimezone(timezone(delta))


@dataclass(frozen=True, slots=True)
class BrokerQualification:
    state: str
    profile_sha256: str | None
    evidence_sha256: str | None
    evidence_fields_matched: bool
    real_broker_terms_qualified: bool
    issues: tuple[str, ...]

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def qualify_broker_profile(profile: BrokerProfile, source_bytes: bytes | None,
                           *, required_costs: bool = True) -> BrokerQualification:
    """Bind complete broker fields to immutable evidence JSON without claiming live parity.

    A terminal-export-labelled document alone is NOT a trusted attestation or
    a licence to trade. The real_broker_terms_qualified flag is always false
    until a separate external broker confirmation gate exists.
    """
    try:
        profile = BrokerProfile.from_json(profile.to_json())
    except (ValueError, TypeError, KeyError, AttributeError):
        return BrokerQualification("BLOCKED", None, None, False, False, ("SCHEMA_INVALID",))
    digest = sha256(profile.to_json().encode()).hexdigest()
    problems: list[str] = []
    source_sha = None
    observed_match = False
    if source_bytes is None or not isinstance(source_bytes, bytes) or not source_bytes:
        problems.append("SOURCE_BYTES_MISSING")
    else:
        source_sha = sha256(source_bytes).hexdigest()
        if source_sha != profile.provenance.source_sha256:
            problems.append("SOURCE_SHA_MISMATCH")
        else:
            try:
                doc = json.loads(source_bytes.decode("utf-8"))
                doc = _object(doc, {"evidence_kind", "broker_id", "account_type",
                                    "account_currency", "contract", "margin",
                                    "costs", "clock"}, "broker evidence document")
                wire = profile.to_wire()
                observed_match = all(doc[key] == wire[key] for key in doc if key != "evidence_kind")
                if not observed_match:
                    problems.append("SOURCE_FIELDS_MISMATCH")
                if doc["evidence_kind"] != profile.provenance.evidence_kind:
                    problems.append("SOURCE_KIND_MISMATCH")
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError, KeyError, TypeError):
                problems.append("SOURCE_EVIDENCE_INVALID")
    if required_costs and any(v is None for v in asdict(profile.costs).values()):
        problems.append("COST_TERMS_INCOMPLETE")
    if problems:
        state = "BLOCKED"
    elif profile.provenance.evidence_kind == "internal_fixture":
        state = "ILLUSTRATIVE_SOURCE_MATCHED"
    else:
        state = "BROKER_EVIDENCE_MATCHED_UNATTESTED"
    return BrokerQualification(state, digest, source_sha, observed_match,
                               False, tuple(sorted(set(problems))))
