"""Day09: fail-closed StrategySpec rule completeness and lookahead admission gate.

No claim of source-platform signal parity, broker executability, profitable trades
or commercial data rights. A rule-complete research candidate is not VERIFIED alpha.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from typing import Any

from aidy.strategy_lab_spec import Operand, Predicate, Signal, StrategySpec

SUPPORTED_SOURCE = ("histdata:generic_ascii_m1", "EST_FIXED_UTC_MINUS_05", "bid")
UNSUPPORTED_CANDLE_SOURCE = frozenset(("D1",))
COMPARISON_OPS = frozenset(("gt", "gte", "lt", "lte", "eq"))
CROSS_OPS = frozenset(("cross_above", "cross_below"))


@dataclass(frozen=True, order=True)
class RuleIssue:
    code: str
    location: str
    explanation: str


@dataclass(frozen=True)
class RuleAssessment:
    state: str
    issues: tuple[RuleIssue, ...]
    spec_sha256: str | None
    source_sha256_verified: bool

    @property
    def ready_for_later_reproduction(self) -> bool:
        # Does not mean source-platform parity or financial backtest verification.
        return self.state == "RULES_COMPLETE_SOURCE_MATCHED"

    def to_wire(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "ready_for_later_reproduction": self.ready_for_later_reproduction,
            "spec_sha256": self.spec_sha256,
            "source_sha256_verified": self.source_sha256_verified,
            "issues": [
                {"code": i.code, "location": i.location, "explanation": i.explanation}
                for i in self.issues
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_wire(), sort_keys=True, separators=(",", ":"))


def _same_operand(left: Operand, right: Operand) -> bool:
    return left == right


def _predicate_key(p: Predicate) -> tuple[Any, ...]:
    def operand_key(o: Operand) -> tuple[Any, ...]:
        return o.kind, o.reference, o.field, o.offset_closed_bars

    return operand_key(p.left), p.operator, operand_key(p.right)


def _bounds_contradiction(predicates: tuple[Predicate, ...]) -> bool:
    """Conclusive only: impossible numerical bounds on the SAME left operand."""
    grouped: dict[Operand, list[tuple[str, Decimal]]] = defaultdict(list)
    for p in predicates:
        if p.operator not in COMPARISON_OPS or p.right.kind != "constant":
            continue
        grouped[p.left].append((p.operator, Decimal(p.right.reference)))
    for bounds in grouped.values():
        lowers = [(n, op == "gt") for op, n in bounds if op in ("gt", "gte", "eq")]
        uppers = [(n, op == "lt") for op, n in bounds if op in ("lt", "lte", "eq")]
        if not lowers or not uppers:
            continue
        low, high = max(n for n, _ in lowers), min(n for n, _ in uppers)
        if low > high:
            return True
        if low == high and (
            any(n == low and strict for n, strict in lowers)
            or any(n == high and strict for n, strict in uppers)
        ):
            return True
    return False


def assess_rule_completeness(
    spec: StrategySpec, *, source_snapshot: bytes | None = None
) -> RuleAssessment:
    """Assess a parsed spec and optional independently supplied original source.

    Validation is rerun from canonical JSON to prevent an unchecked dataclass
    construction from bypassing Day08 strict field and operand checks.
    """
    issues: list[RuleIssue] = []

    def block(code: str, location: str, message: str) -> None:
        issues.append(RuleIssue(code, location, message))

    try:
        spec = StrategySpec.from_json(spec.to_json())
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        block("SCHEMA_INVALID", "$", f"Day08 strict schema rejection: {type(exc).__name__}")
        return RuleAssessment("BLOCKED", tuple(issues), None, False)
    digest = sha256(spec.to_json().encode("utf-8")).hexdigest()

    if spec.candidate_type != "complete_mechanical":
        block("INCOMPLETE_CANDIDATE", "candidate_type", "Indicators, variants and black boxes are not full mechanical systems.")
    if spec.origin.unresolved_questions:
        block("UNRESOLVED_INTERPRETATION", "origin.unresolved_questions", "Resolve every material source-rule question before reproduction.")
    if not spec.origin.source_snapshot_ref:
        block("NO_SOURCE_SNAPSHOT_REFERENCE", "origin.source_snapshot_ref", "Immutable original source location has not been supplied.")
    verified_source = False
    if source_snapshot is None:
        block("SOURCE_BYTES_NOT_CHECKED", "origin.source_sha256", "No trusted source bytes supplied for digest verification.")
    elif not isinstance(source_snapshot, bytes) or not source_snapshot:
        block("SOURCE_BYTES_INVALID", "origin.source_sha256", "Original source must be nonempty bytes.")
    elif sha256(source_snapshot).hexdigest() != spec.origin.source_sha256:
        block("SOURCE_HASH_MISMATCH", "origin.source_sha256", "Source bytes fail declared SHA-256.")
    else:
        verified_source = True

    if (spec.market.data_source, spec.market.source_clock, spec.market.price_basis) != SUPPORTED_SOURCE:
        block("UNQUALIFIED_DATA_CONTRACT", "market", "Only historical HistData native M1 bid/fixed-EST source is qualified in this slice.")
    if spec.market.signal_timeframe in UNSUPPORTED_CANDLE_SOURCE:
        block("D1_SESSION_UNQUALIFIED", "market.signal_timeframe", "Full source trading-day and maintenance schedule is not yet independently qualified.")

    if not (spec.long.entry.enabled or spec.short.entry.enabled):
        block("NO_ENABLED_ENTRIES", "long/short", "A mechanical trade strategy needs at least one entry side.")
    indicator_by_id = {i.id: i for i in spec.indicators}
    signal_timeframe = spec.market.signal_timeframe

    for i in spec.indicators:
        path = f"indicators.{i.id}"
        if i.timeframe != signal_timeframe:
            block("HTF_AVAILABILITY_UNQUALIFIED", path, "Cross-timeframe release/alignment semantics require platform-source parity proof.")
        if i.timeframe in UNSUPPORTED_CANDLE_SOURCE:
            block("D1_SESSION_UNQUALIFIED", path, "Daily candle close not yet calendar-qualified.")
        if i.additional_parameters:
            block("INDICATOR_PARAMETERS_UNSUPPORTED", path, "Only baseline period and OHLC field have frozen semantics.")
        if i.kind in ("RSI", "ATR"):
            block("INDICATOR_SEMANTICS_UNRESOLVED", path, "RSI/ATR smoothing, warmup and platform parity are not yet frozen.")
        if i.kind in ("EMA", "SMA") and i.price_field not in ("open", "high", "low", "close"):
            block("INDICATOR_PRICE_UNSUPPORTED", path, "Unrecognised moving-average input.")

    if spec.sizing.mode == "risk_percent_equity":
        assert spec.sizing.risk_percent_equity is not None
        if spec.sizing.risk_percent_equity > spec.portfolio.max_total_risk_percent:
            block("RISK_LIMIT_CONTRADICTION", "sizing", "Per-trade risk is greater than portfolio cap.")
    if spec.portfolio.max_positions > 1 or spec.portfolio.allow_hedging or spec.portfolio.allow_pyramiding:
        block("POSITION_POLICY_NOT_FROZEN", "portfolio", "Multi-position/hedging/pyramiding priority remains unqualified in v1.")

    if not spec.sessions.allowed:
        block("NO_SESSION_WINDOWS", "sessions.allowed", "Allowed trading sessions cannot be empty.")
    by_weekday: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for w in spec.sessions.allowed:
        if w.start_hhmm >= w.end_hhmm:
            block("OVERNIGHT_SESSION_AMBIGUOUS", "sessions.allowed", "Cross-midnight sessions require explicit next-day policy.")
        else:
            by_weekday[w.weekday].append((w.start_hhmm, w.end_hhmm))
    for weekday, ranges in by_weekday.items():
        ordered = sorted(ranges)
        if any(left[1] > right[0] for left, right in zip(ordered, ordered[1:])):
            block("OVERLAPPING_SESSIONS", f"sessions.allowed.weekday_{weekday}", "Overlapping windows have undefined priority.")

    for name, side, other in (("long", spec.long, spec.short), ("short", spec.short, spec.long)):
        if not side.entry.enabled:
            continue
        signal: Signal = side.entry
        exits = side.exit
        if exits.stop_loss is None:
            block("MISSING_PROTECTIVE_STOP", f"{name}.exit.stop_loss", "No reproducible maximum initial price risk.")
        if not any((exits.take_profit is not None, exits.trailing_stop is not None,
                    exits.maximum_holding_bars is not None,
                    exits.close_on_session_end, exits.close_on_opposite_signal,
                    bool(exits.partial_exits))):
            block("MISSING_EXIT_POLICY", f"{name}.exit", "No deterministic terminal exit defined.")
        if exits.close_on_opposite_signal and not other.entry.enabled:
            block("IMPOSSIBLE_OPPOSITE_EXIT", f"{name}.exit.close_on_opposite_signal", "Opposite side never emits a signal.")
        if spec.sessions.flat_outside_sessions and not exits.close_on_session_end:
            block("SESSION_FLAT_CONTRADICTION", f"{name}.exit.close_on_session_end", "Session policy requires flattening, but side never closes at session end.")
        if exits.trailing_stop is not None or exits.partial_exits or exits.close_on_opposite_signal:
            block("EXIT_PRIORITY_UNDEFINED", f"{name}.exit", "Trailing, partial or opposite exits require intrabar update/precedence policy absent from StrategySpec v1.")

        used: set[tuple[Any, ...]] = set()
        needed_warmup = 0
        for idx, p in enumerate(signal.predicates):
            location = f"{name}.entry.predicates.{idx}"
            if _same_operand(p.left, p.right):
                block("SELF_COMPARISON", location, "Comparing an operand to itself is trivial or impossible.")
            key = _predicate_key(p)
            if key in used:
                block("DUPLICATE_PREDICATE", location, "Repeated rule does not establish an independent condition.")
            used.add(key)
            if p.operator in CROSS_OPS and (p.left.kind == "constant" or p.right.kind == "constant"):
                block("CROSS_SEMANTICS_UNQUALIFIED", location, "Constant crossover semantics require a frozen source-platform reference.")
            for operand in (p.left, p.right):
                if operand.kind == "indicator":
                    indicator = indicator_by_id[operand.reference]
                    periods = indicator.period
                    # Indicator initialisation and crossover read previous CLOSED bar.
                    needed_warmup = max(needed_warmup, periods + operand.offset_closed_bars +
                                        (2 if p.operator in CROSS_OPS else 0))
                elif operand.kind == "price":
                    needed_warmup = max(needed_warmup, operand.offset_closed_bars + 1 +
                                        (1 if p.operator in CROSS_OPS else 0))
        if spec.warmup_closed_bars < needed_warmup:
            block("INSUFFICIENT_WARMUP", "warmup_closed_bars", f"Requires at least {needed_warmup} fully closed signal-timeframe bars.")
        if signal.combination == "ALL" and _bounds_contradiction(signal.predicates):
            block("IMPOSSIBLE_PRICE_BOUNDS", f"{name}.entry", "Conjunction of strict numeric bounds has no possible price.")
    if spec.long.entry.enabled and spec.short.entry.enabled and spec.long.entry == spec.short.entry:
        block("SIMULTANEOUS_LONG_SHORT", "long/short.entry", "Identical entry events without an explicit conflict-resolution policy.")
    return RuleAssessment("BLOCKED" if issues else "RULES_COMPLETE_SOURCE_MATCHED",
                          tuple(sorted(set(issues))), digest, verified_source)
