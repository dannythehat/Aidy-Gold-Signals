"""Day22 restricted Pine Script v6 source importer and signal parity gate.

Only a precisely enumerated closed-bar EMA-cross strategy subset is parsed as
DATA. No Pine, JavaScript or user-supplied code is ever run. Reproduction of
TradingView-original signals requires independently captured provider evidence;
a self-labelled or synthetic trace never becomes verified platform parity.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Any

from aidy.strategy_lab_spec import StrategySpec
from aidy.strategy_lab_written_rule_intake import (
    ClosedIndicatorSample,
    _is_supported_cross,
    evaluate_closed_indicator_cross,
)

SCHEMA = "aidy.pine_subset.v1"
MAX_SOURCE_BYTES = 25_000
PINE_SOURCE_RE = re.compile(
    r'\A//@version=6\n'
    r'strategy\("(?P<title>[A-Za-z0-9 _-]{3,80})", overlay=true, '
    r'process_orders_on_close=false, calc_on_every_tick=false, '
    r'calc_on_order_fills=false, pyramiding=0\)\n'
    r'fastEma = ta\.ema\(close, (?P<fast>[1-9][0-9]{0,2})\)\n'
    r'slowEma = ta\.ema\(close, (?P<slow>[1-9][0-9]{0,2})\)\n'
    r'longSignal = barstate\.isconfirmed and ta\.crossover\(fastEma, slowEma\)\n'
    r'if longSignal\n'
    r'    strategy\.entry\("Long", strategy\.long\)'
    r'(?:\nplot\(fastEma, "AIDY_FAST_EMA", display=display\.data_window\)'
    r'\nplot\(slowEma, "AIDY_SLOW_EMA", display=display\.data_window\)'
    r'\nplot\(longSignal \? 1 : 0, "AIDY_LONG_SIGNAL", display=display\.data_window\))?'
    r'\n?\Z',
)
FIXTURE_SOURCE = "internal_synthetic"


@dataclass(frozen=True)
class PineSubset:
    source_bytes: bytes
    original_sha256: str
    spec_json: str
    spec_sha256: str
    source_ref: str
    pine_version: int
    fast_period: int
    slow_period: int
    next_tick_execution: bool = True
    complete_strategy_ported: bool = False
    original_platform_parity_verified: bool = False

    def to_json(self) -> str:
        return json.dumps({
            "schema": SCHEMA, "source_sha256": self.original_sha256,
            "spec_sha256": self.spec_sha256, "source_ref": self.source_ref,
            "pine_version": self.pine_version, "fast_period": self.fast_period,
            "slow_period": self.slow_period,
            "next_tick_execution": self.next_tick_execution,
            "complete_strategy_ported": self.complete_strategy_ported,
            "original_platform_parity_verified": self.original_platform_parity_verified,
        }, sort_keys=True, separators=(",", ":"))


def _parse(source: bytes) -> tuple[int, int]:
    if not isinstance(source, bytes) or not 0 < len(source) <= MAX_SOURCE_BYTES:
        raise ValueError("Pine source must be nonempty bounded original bytes")
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Pine source must be valid UTF-8") from exc
    match = PINE_SOURCE_RE.fullmatch(text)
    if match is None:
        raise ValueError("UNSUPPORTED_PINE_SYNTAX_OR_ORDER_SETTINGS")
    fast, slow = int(match["fast"]), int(match["slow"])
    if not 1 <= fast < slow <= 500:
        raise ValueError("unsupported Pine EMA lengths")
    return fast, slow


def admit_pine_subset(
    source: bytes, *, source_sha256: str, source_ref: str,
    spec_json: str,
) -> PineSubset:
    """Bind exact original Pine text to explicitly supplied typed signal spec.

    The admitted source is only a signal fragment: it DOES NOT contain the
    stop, target, sizing or session rules in the broader Day20 StrategySpec.
    Those remain separate review obligations, not ported Pine semantics.
    """
    if not isinstance(source_sha256, str) or sha256(source).hexdigest() != source_sha256:
        raise ValueError("original Pine source SHA256 mismatch")
    fast, slow = _parse(source)
    if not isinstance(source_ref, str) or not source_ref.strip():
        raise ValueError("original source reference missing")
    spec = StrategySpec.from_json(spec_json)
    if not (_is_supported_cross(spec)
            and spec.origin.source_language == "pine"
            and spec.origin.source_sha256 == source_sha256
            and spec.origin.source_snapshot_ref == source_ref
            and not spec.origin.unresolved_questions
            and spec.market.symbol == "XAUUSD"
            and spec.market.signal_timeframe == "M5"
            and spec.execution.entry_execution == "next_tradable_quote"
            and tuple(i.period for i in spec.indicators) == (fast, slow)):
        raise ValueError("Pine script signal is not consistent with typed StrategySpec")
    return PineSubset(
        source, source_sha256, spec.to_json(),
        sha256(spec.to_json().encode()).hexdigest(),
        source_ref, 6, fast, slow,
    )


def pine_predicate_signals(
    admitted: PineSubset, trace: tuple[ClosedIndicatorSample, ...],
) -> tuple:
    """Revalidate source and use an isolated direct Pine crossover predicate."""
    if not isinstance(admitted, PineSubset):
        raise ValueError("invalid imported Pine adapter")  # noqa: TRY004
    fresh = admit_pine_subset(
        admitted.source_bytes, source_sha256=admitted.original_sha256,
        source_ref=admitted.source_ref, spec_json=admitted.spec_json,
    )
    if fresh != admitted:
        raise ValueError("tampered source-bound Pine adapter")
    spec = StrategySpec.from_json(admitted.spec_json)
    if not isinstance(trace, tuple) or len(trace) <= spec.warmup_closed_bars:
        raise ValueError("not enough closed M5 indicator values")
    previous = None
    for bar in trace:
        if not isinstance(bar, ClosedIndicatorSample):
            raise ValueError("invalid closed trace record")  # noqa: TRY004
        when = bar.closed_at_utc
        if (when.tzinfo is None or when.utcoffset() != timedelta(0)
                or (previous is not None and when - previous != timedelta(minutes=5))):
            raise ValueError("closed-bar UTC M5 chronology missing/out-of-order")
        if any(not isinstance(x, Decimal) or not x.is_finite() or x <= 0
               for x in (bar.fast_ema, bar.slow_ema)):
            raise ValueError("invalid positive finite indicator value")
        previous = when
    results = []
    # Pine ta.crossover(a,b) is previous a<=b and current a>b.
    for i in range(spec.warmup_closed_bars, len(trace)):
        if trace[i-1].fast_ema <= trace[i-1].slow_ema and (
            trace[i].fast_ema > trace[i].slow_ema
        ):
            results.append(trace[i].closed_at_utc)
    return tuple(results)


def compare_pine_to_spec(
    admitted: PineSubset, trace: tuple[ClosedIndicatorSample, ...],
) -> tuple:
    actual = pine_predicate_signals(admitted, trace)
    reference = evaluate_closed_indicator_cross(
        StrategySpec.from_json(admitted.spec_json), trace,
    )
    if actual != reference:
        raise ValueError("Pine/StrategySpec predicate divergence")
    return actual


@dataclass(frozen=True)
class PineReferenceResult:
    status: str
    source_sha256: str
    reference_sha256: str
    signal_count: int
    matched: bool
    real_tradingview_capture_qualified: bool = False
    complete_strategy_parity_qualified: bool = False


def compare_pine_reference(
    admitted: PineSubset, reference_raw: bytes, *,
    expected_reference_sha256: str,
) -> PineReferenceResult:
    """Verify original reference bytes and every row; never authenticate self-labels.

    Reference JSON must be externally obtained/saved; a claimed provider name
    alone is NOT trusted evidence that TradingView generated these values.
    """
    if not isinstance(reference_raw, bytes) or not 0 < len(reference_raw) <= 2_000_000:
        raise ValueError("original reference trace bytes missing")
    digest = sha256(reference_raw).hexdigest()
    if digest != expected_reference_sha256:
        raise ValueError("Pine reference trace SHA256 mismatch")
    def unique(items: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for key, value in items:
            if key in obj:
                raise ValueError("duplicate Pine reference field")
            obj[key] = value
        return obj
    try:
        payload = json.loads(reference_raw.decode(), object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid Pine reference JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "schema", "origin", "original_source_sha256", "chart_symbol",
        "chart_timeframe", "captured_reference", "bars",
    } or payload["schema"] != "aidy.pine_signal_trace.v1":
        raise ValueError("Pine reference schema missing/incomplete")
    if payload["original_source_sha256"] != admitted.original_sha256:
        raise ValueError("Pine original-source reference identity differs")
    if (payload["chart_symbol"] != "XAUUSD" or payload["chart_timeframe"] != "M5"
        or payload["origin"] not in (FIXTURE_SOURCE, "tradingview_user_export_unattested")
        or not isinstance(payload["captured_reference"], str)
        or not payload["captured_reference"].strip()):
        raise ValueError("Pine reference origin/chart not qualified")
    records = payload["bars"]
    if not isinstance(records, list) or not 51 <= len(records) <= 20_000:
        raise ValueError("Pine reference trace must include closed warmup")
    from datetime import datetime
    trace = []
    flags = []
    for row in records:
        if not isinstance(row, dict) or set(row) != {"closed_at_utc", "fast_ema", "slow_ema", "long_signal"}:
            raise ValueError("reference row missing fields")
        raw_time = row["closed_at_utc"]
        if not isinstance(raw_time, str) or not raw_time.endswith("Z"):
            raise ValueError("reference row has non-UTC clock")
        dt = datetime.fromisoformat(raw_time)
        if type(row["long_signal"]) is not bool:
            raise ValueError("reference signal must be exact boolean")
        try:
            f, s = Decimal(row["fast_ema"]), Decimal(row["slow_ema"])
        except (TypeError, ValueError, ArithmeticError) as exc:
            raise ValueError("invalid exact source indicator decimals") from exc
        trace.append(ClosedIndicatorSample(dt, f, s))
        flags.append(row["long_signal"])
    out = compare_pine_to_spec(admitted, tuple(trace))
    actual = {x for x in out}
    correct = tuple(t.closed_at_utc in actual for t in trace)
    if tuple(flags) != correct:
        raise ValueError("Pine signal flags disagree with original reference rows")
    # Deliberate unqualified status: external capture's actual provenance
    # cannot be authenticated merely by putting 'tradingview' in a JSON file.
    return PineReferenceResult(
        status="INTERNAL_FIXTURE_PARITY_ONLY" if payload["origin"] == FIXTURE_SOURCE
               else "USER_REFERENCE_MATCHED_BUT_NOT_PROVIDER_AUTHENTICATED",
        source_sha256=admitted.original_sha256, reference_sha256=digest,
        signal_count=len(out), matched=True,
    )
