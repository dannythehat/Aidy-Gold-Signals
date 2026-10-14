"""Day23 source-bound MQL4/MQL5 closed-candle entry/exit predicate intake.

Accept a deliberately narrow two-function pure MQL4/MQL5 grammar as DATA.
Never compile, invoke, load or run customer MQL. This is NOT an EA interpreter,
native MT4/MT5 runtime claim, trade/execution adapter, or full strategy port.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256

from aidy.strategy_lab_spec import StrategySpec
from aidy.strategy_lab_written_rule_intake import (
    ClosedIndicatorSample,
    _is_supported_cross,
    evaluate_closed_indicator_cross,
)

SCHEMA = "aidy.mql_closed_cross_subset.v1"
MAX_SOURCE_BYTES = 16_384
ARGS = "double fast_prev, double slow_prev, double fast_now, double slow_now"
# Entire source is matched, not extracted from an otherwise executable EA.
# This explicitly rejects includes, macros, event handlers, orders, indicators,
# DLL calls, network access, dynamic library links and any other MQL statements.
PATTERN = re.compile(
    r"\A#property strict\r?\n"
    r"bool LongEntry\(" + ARGS + r"\)\s*\{\s*"
    r"return fast_prev <= slow_prev && fast_now > slow_now;\s*\}"
    r"\s*bool LongExit\(" + ARGS + r"\)\s*\{\s*"
    r"return fast_prev >= slow_prev && fast_now < slow_now;\s*\}"
    r"\s*\Z",
    re.ASCII,
)
LANGS = frozenset({"mql4": ".mq4", "mql5": ".mq5"}.items())


@dataclass(frozen=True)
class MqlClosedCross:
    source_bytes: bytes
    source_sha256: str
    source_ref: str
    spec_json: str
    spec_sha256: str
    source_language: str
    subset_schema: str = SCHEMA
    untrusted_mql_executed: bool = False
    complete_ea_ported: bool = False
    native_metatrader_parity_verified: bool = False

    def to_json(self) -> str:
        return json.dumps({
            "schema": self.subset_schema,
            "source_sha256": self.source_sha256,
            "source_ref": self.source_ref,
            "spec_sha256": self.spec_sha256,
            "source_language": self.source_language,
            "entry_predicate": "closed_ema_cross_above",
            "exit_predicate": "closed_ema_cross_below",
            "untrusted_mql_executed": False,
            "complete_ea_ported": False,
            "native_metatrader_parity_verified": False,
        }, sort_keys=True, separators=(",", ":"))


def _validate_source(source: bytes) -> None:
    if not isinstance(source, bytes) or not 0 < len(source) <= MAX_SOURCE_BYTES:
        raise ValueError("original MQL source must be bounded nonempty bytes")
    try:
        raw = source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("original MQL source must be UTF-8") from exc
    if "\x00" in raw or PATTERN.fullmatch(raw) is None:
        raise ValueError("UNSUPPORTED_MQL_SOURCE_OR_ORDER_SEMANTICS")


def admit_mql_closed_cross(
    source_bytes: bytes, spec_json: str, *,
    expected_source_sha256: str, source_ref: str, source_language: str,
) -> MqlClosedCross:
    """Check immutable original source, typed rules and exact pure grammar."""
    if not isinstance(source_bytes, bytes) or sha256(source_bytes).hexdigest() != expected_source_sha256:
        raise ValueError("original MQL source SHA256 mismatch")
    if source_language not in {"mql4", "mql5"}:
        raise ValueError("unsupported MQL source language")
    extension = ".mq4" if source_language == "mql4" else ".mq5"
    if (not isinstance(source_ref, str) or not source_ref.endswith(extension)
            or not source_ref.strip()):
        raise ValueError("source reference requires correct original MQL extension")
    _validate_source(source_bytes)
    spec = StrategySpec.from_json(spec_json)
    if (not _is_supported_cross(spec)
            or spec.origin.source_language != source_language
            or spec.origin.source_sha256 != expected_source_sha256
            or spec.origin.source_snapshot_ref != source_ref
            or spec.origin.unresolved_questions
            or spec.market.symbol != "XAUUSD"
            or spec.market.signal_timeframe != "M5"
            or spec.execution.signal_evaluation != "closed_bar_only"
            or spec.execution.entry_execution != "next_tradable_quote"
            or not spec.long.exit.close_on_opposite_signal):
        raise ValueError("source predicates inconsistent with typed StrategySpec")
    return MqlClosedCross(
        source_bytes, expected_source_sha256, source_ref, spec.to_json(),
        sha256(spec.to_json().encode()).hexdigest(), source_language,
    )


def evaluate_mql_closed_cross(
    admitted: MqlClosedCross, trace: tuple[ClosedIndicatorSample, ...],
) -> dict:
    """Return event TIMESTAMPS only; never simulate actual MT fills or SL/TP."""
    if not isinstance(admitted, MqlClosedCross):
        raise ValueError("invalid MQL adapter type")  # noqa: TRY004
    fresh = admit_mql_closed_cross(
        admitted.source_bytes, admitted.spec_json,
        expected_source_sha256=admitted.source_sha256,
        source_ref=admitted.source_ref, source_language=admitted.source_language,
    )
    if fresh != admitted:
        raise ValueError("tampered MQL evidence")
    spec = StrategySpec.from_json(admitted.spec_json)
    if not isinstance(trace, tuple) or len(trace) <= spec.warmup_closed_bars:
        raise ValueError("insufficient fully closed indicator bars")
    previous = None
    for sample in trace:
        if not isinstance(sample, ClosedIndicatorSample):
            raise ValueError("not a closed MQL indicator sample")  # noqa: TRY004
        ts = sample.closed_at_utc
        if (ts.tzinfo is None or ts.utcoffset() != timedelta(0)
                or previous is not None and ts - previous != timedelta(minutes=5)):
            raise ValueError("disordered or missing UTC M5 closed bars")
        previous = ts
        if any(not isinstance(x, Decimal) or not x.is_finite() or x <= 0
               for x in (sample.fast_ema, sample.slow_ema)):
            raise ValueError("invalid closed MQL EMA value")

    entries = []
    exits = []
    # Separate independent positional interpretation of the accepted MQL
    # fixed predicates. We deliberately do not call/eval customer source.
    for i in range(spec.warmup_closed_bars, len(trace)):
        old, now = trace[i-1], trace[i]
        if old.fast_ema <= old.slow_ema and now.fast_ema > now.slow_ema:
            entries.append(now.closed_at_utc)
        if old.fast_ema >= old.slow_ema and now.fast_ema < now.slow_ema:
            exits.append(now.closed_at_utc)
    ref = evaluate_closed_indicator_cross(spec, trace)
    if tuple(entries) != ref:
        raise ValueError("MQL and independent StrategySpec entry parity mismatch")
    return {
        "schema": SCHEMA,
        "source_language": admitted.source_language,
        "source_sha256": admitted.source_sha256,
        "spec_sha256": admitted.spec_sha256,
        "entry_signals_utc": [d.isoformat().replace("+00:00", "Z") for d in entries],
        "opposite_cross_exit_signals_utc": [
            d.isoformat().replace("+00:00", "Z") for d in exits
        ],
        "entry_count": len(entries),
        "opposite_cross_exit_count": len(exits),
        "evaluation_scope": "closed_ema_predicates_only",
        "full_exit_order_management_verified": False,
        "native_mt4_mt5_execution_parity_verified": False,
        "untrusted_mql_executed": False,
        "complete_ea_ported": False,
    }
