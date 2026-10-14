"""TradingView chart CSV import for an EXACT Pine-script source hash.

The CSV is an untrusted artifact until an independently traceable TradingView
chart export is captured. Matching numbers establishes a mathematical parity
check, never provider authenticity from a filename or author-supplied string.
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256

from aidy.strategy_lab_pine_adapter import (
    PineSubset,
    compare_pine_to_spec,
)
from aidy.strategy_lab_written_rule_intake import ClosedIndicatorSample

HEADER = frozenset({
    "time", "close", "AIDY_FAST_EMA", "AIDY_SLOW_EMA", "AIDY_LONG_SIGNAL",
})
PLOT_SUFFIX = (
    'plot(fastEma, "AIDY_FAST_EMA", display=display.data_window)\n'
    'plot(slowEma, "AIDY_SLOW_EMA", display=display.data_window)\n'
    'plot(longSignal ? 1 : 0, "AIDY_LONG_SIGNAL", display=display.data_window)\n'
)
MAX_CSV_BYTES = 8_000_000
MAX_BARS = 20_000
TOL = Decimal("0.0005")


def _decimal(raw: str, field: str) -> Decimal:
    if not isinstance(raw, str):
        raise ValueError(f"{field}: required exact decimal text")  # noqa: TRY004
    try:
        x = Decimal(raw)
    except (ValueError, InvalidOperation) as exc:
        raise ValueError(f"{field}: invalid decimal") from exc
    if not x.is_finite() or x <= 0:
        raise ValueError(f"{field}: positive finite decimal required")
    return x


def _utc_open(raw: str) -> datetime:
    if not isinstance(raw, str):
        raise ValueError("export chart time missing")  # noqa: TRY004
    try:
        if raw.isdigit():
            stamp = datetime.fromtimestamp(int(raw), tz=UTC)
        else:
            stamp = datetime.fromisoformat(raw)
    except (OverflowError, ValueError) as exc:
        raise ValueError("unsupported chart export time") from exc
    if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
        raise ValueError("chart export times must be UTC, not local wall times")
    if stamp.second or stamp.microsecond or stamp.minute % 5 != 0:
        raise ValueError("chart bar opening time not aligned to UTC M5")
    return stamp.astimezone(UTC)


def _ema(closes: tuple[Decimal, ...], period: int) -> tuple[Decimal, ...]:
    """Pine ta.ema smoothing reference: seed at first non-NA source close."""
    alpha = Decimal(2) / (Decimal(period) + 1)
    current = closes[0]
    out = [current]
    for price in closes[1:]:
        current = alpha * price + (Decimal(1) - alpha) * current
        out.append(current)
    return tuple(out)


@dataclass(frozen=True)
class TvChartCsvCheck:
    state: str
    pine_source_sha256: str
    raw_chart_csv_sha256: str
    symbol_declared: str
    timeframe_declared: str
    bars: int
    warmup_bars_checked: int
    crossover_signal_count: int
    signals_utc: tuple[str, ...]
    numeric_ema_consistent: bool
    original_tradingview_export_authenticated: bool = False
    real_broker_fill_parity_qualified: bool = False

    def to_json(self) -> str:
        return json.dumps({
            **self.__dict__,
        }, sort_keys=True, separators=(",", ":"))


def verify_tv_chart_csv(
    admitted: PineSubset,
    csv_bytes: bytes,
    *,
    expected_csv_sha256: str,
    chart_symbol: str,
    chart_interval: str,
) -> TvChartCsvCheck:
    if not isinstance(admitted, PineSubset):
        raise ValueError("source-bound Pine strategy admission required")  # noqa: TRY004
    if not admitted.source_bytes.decode("utf-8").endswith(PLOT_SUFFIX):
        raise ValueError("Pine source lacks exact native chart CSV plot instrumentation")
    if not isinstance(csv_bytes, bytes) or not 0 < len(csv_bytes) <= MAX_CSV_BYTES:
        raise ValueError("chart CSV original source bytes missing/unbounded")
    fingerprint = sha256(csv_bytes).hexdigest()
    if fingerprint != expected_csv_sha256:
        raise ValueError("chart CSV original-byte SHA256 mismatch")
    if (chart_symbol != "OANDA:XAUUSD" or chart_interval != "5"):
        raise ValueError("Day22 reference chart requires explicit OANDA:XAUUSD M5")
    try:
        doc = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("chart CSV not UTF-8") from exc
    reader = csv.DictReader(io.StringIO(doc, newline=""))
    if reader.fieldnames is None or len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValueError("chart CSV missing or duplicate column names")
    if not HEADER <= set(reader.fieldnames):
        raise ValueError("chart CSV must contain all three plotted Pine signal columns")
    parsed = []
    for row in reader:
        if len(parsed) >= MAX_BARS or None in row:
            raise ValueError("unbounded or malformed chart CSV row")
        start = _utc_open(row["time"])
        if parsed and start - parsed[-1][0] != timedelta(minutes=5):
            raise ValueError("chart CSV is out-of-order, gapped or not M5")
        close = _decimal(row["close"], "close")
        fast = _decimal(row["AIDY_FAST_EMA"], "fast plot")
        slow = _decimal(row["AIDY_SLOW_EMA"], "slow plot")
        flag = row["AIDY_LONG_SIGNAL"]
        if flag not in ("0", "1"):
            raise ValueError("signal column requires literal numeric 0 or 1")
        parsed.append((start, close, fast, slow, flag == "1"))
    if len(parsed) < 350:
        raise ValueError("at least 350 contiguous M5 bars needed to audit EMA initialization")
    closes = tuple(x[1] for x in parsed)
    fast_ref = _ema(closes, admitted.fast_period)
    slow_ref = _ema(closes, admitted.slow_period)
    # For a middle-window CSV whose earlier history is unavailable, 300 closed
    # M5 bars of local warmup decay EMA initial-value differences below tolerance.
    for i, (_, _, f, s, _) in enumerate(parsed):
        if i >= 300 and (
            abs(f - fast_ref[i]) > TOL or abs(s - slow_ref[i]) > TOL
        ):
            raise ValueError("TradingView plotted EMA differs from independent OHLC EMA")
    trace = tuple(ClosedIndicatorSample(
        open_at + timedelta(minutes=5), f, s,
    ) for open_at, _, f, s, _ in parsed)
    expected_signals = set(compare_pine_to_spec(admitted, trace))
    for i, entry in enumerate(parsed):
        observed = entry[4]
        expected = trace[i].closed_at_utc in expected_signals
        if observed != expected:
            raise ValueError("TradingView plotted signal differs from typed source predicate")
    return TvChartCsvCheck(
        "CSV_VALUE_AND_SIGNAL_PARITY_UNATTESTED",
        admitted.original_sha256, fingerprint,
        chart_symbol, chart_interval, len(parsed), len(parsed) - 300,
        len(expected_signals),
        tuple(x.isoformat().replace("+00:00", "Z") for x in sorted(expected_signals)),
        True,
    )
