"""Day22 provider CSV capture contract tests with explicitly SYNTHETIC payloads."""
from __future__ import annotations

import csv
import io
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest
from test_strategy_lab_pine_adapter import make_spec

from aidy.strategy_lab_pine_adapter import admit_pine_subset
from aidy.strategy_lab_tv_chart_csv import (
    _ema,
    verify_tv_chart_csv,
)

ROOT = Path(__file__).parents[1] / "research" / "strategy_lab" / "fixtures"
ORIGINAL = ROOT / "day22_tradingview_exportable_v6.pine.txt"
REF = "research/strategy_lab/fixtures/day22_tradingview_exportable_v6.pine.txt"
START = datetime(2026, 10, 5, 12, tzinfo=UTC)


def parsed_strategy():
    code = ORIGINAL.read_bytes()
    spec = make_spec(code)
    spec["origin"]["source_snapshot_ref"] = REF
    return admit_pine_subset(
        code, source_sha256=sha256(code).hexdigest(),
        source_ref=REF, spec_json=json.dumps(spec, sort_keys=True),
    )


def rows():
    levels = (
        [Decimal(2650)] * 100 + [Decimal(2630)] * 80
        + [Decimal(2670)] * 90 + [Decimal(2630)] * 70
        + [Decimal(2670)] * 80
    )
    fast, slow = _ema(tuple(levels), 10), _ema(tuple(levels), 30)
    out = []
    for i, close in enumerate(levels):
        signal = (i > 0 and fast[i-1] <= slow[i-1] and fast[i] > slow[i])
        out.append({
            "time": (START + timedelta(minutes=5*i)).isoformat().replace("+00:00", "Z"),
            "close": format(close, "f"),
            "AIDY_FAST_EMA": format(fast[i], "f"),
            "AIDY_SLOW_EMA": format(slow[i], "f"),
            "AIDY_LONG_SIGNAL": "1" if signal else "0",
        })
    return out


def raw_csv(records=None):
    records = rows() if records is None else records
    buf = io.StringIO(newline="")
    out = csv.DictWriter(buf, fieldnames=list(records[0]))
    out.writeheader()
    out.writerows(records)
    return buf.getvalue().encode()


def examine(original=None, *, pin=None, symbol="OANDA:XAUUSD", interval="5", obj=None):
    original = raw_csv() if original is None else original
    return verify_tv_chart_csv(
        parsed_strategy() if obj is None else obj, original,
        expected_csv_sha256=sha256(original).hexdigest() if pin is None else pin,
        chart_symbol=symbol, chart_interval=interval,
    )


def test_exportable_exact_pine_source_is_admitted_and_sha_pinned():
    spec = parsed_strategy()
    assert spec.fast_period == 10
    assert spec.slow_period == 30
    assert len(spec.original_sha256) == 64


def test_synthetic_trace_parity_is_not_claimed_as_tradingview_authentication():
    report = examine()
    assert report.state == "CSV_VALUE_AND_SIGNAL_PARITY_UNATTESTED"
    assert report.bars == 420
    assert report.warmup_bars_checked == 120
    assert report.crossover_signal_count >= 2
    assert report.numeric_ema_consistent
    assert len(report.signals_utc) == report.crossover_signal_count
    assert not report.original_tradingview_export_authenticated
    assert not report.real_broker_fill_parity_qualified
    assert json.loads(report.to_json())["state"] == report.state


def test_both_model_and_csv_give_deterministic_replay():
    assert examine() == examine()
    assert examine().raw_chart_csv_sha256 == sha256(raw_csv()).hexdigest()


def test_wrong_original_csv_sha_rejected_before_parsing():
    original = raw_csv()
    with pytest.raises(ValueError, match="SHA256"):
        examine(original, pin="f"*64)


@pytest.mark.parametrize("missing", ["time", "close", "AIDY_FAST_EMA",
                                    "AIDY_SLOW_EMA", "AIDY_LONG_SIGNAL"])
def test_missing_native_indicator_plot_column_rejected(missing):
    changed = rows()
    for row in changed:
        del row[missing]
    with pytest.raises(ValueError, match="three plotted"):
        examine(raw_csv(changed))


def test_duplicate_header_rejected():
    original = raw_csv().replace(
        b"time,close,", b"time,time,close,", 1
    )
    with pytest.raises(ValueError, match="duplicate"):
        examine(original)


@pytest.mark.parametrize(("column", "value"), [
    ("time", "2026-10-05T12:01:00Z"),
    ("time", "2026-10-05T12:00:00+03:00"),
    ("close", "-100"), ("AIDY_FAST_EMA", "NaN"),
    ("AIDY_SLOW_EMA", "Infinity"),
    ("AIDY_LONG_SIGNAL", "True"),
    ("AIDY_LONG_SIGNAL", "2"),
])
def test_bad_provider_chart_row_fails_closed(column, value):
    changed = rows()
    changed[320][column] = value
    with pytest.raises(ValueError):
        examine(raw_csv(changed))


def test_modified_signal_marker_fails_even_when_sha_is_recomputed():
    changed = rows()
    changed[355]["AIDY_LONG_SIGNAL"] = (
        "0" if changed[355]["AIDY_LONG_SIGNAL"] == "1" else "1"
    )
    with pytest.raises(ValueError, match="plotted signal"):
        examine(raw_csv(changed))


def test_modified_indicator_value_fails_against_independent_ohlc():
    changed = rows()
    changed[315]["AIDY_FAST_EMA"] = str(Decimal(changed[315]["AIDY_FAST_EMA"]) + 1)
    with pytest.raises(ValueError, match="plotted EMA"):
        examine(raw_csv(changed))


@pytest.mark.parametrize(("symbol", "interval"), [
    ("FX:XAUUSD", "5"), ("OANDA:XAUUSD", "15"), ("BTCUSDT", "5"),
])
def test_wrong_chart_provider_or_resolution_rejected(symbol, interval):
    with pytest.raises(ValueError, match="OANDA:XAUUSD M5"):
        examine(symbol=symbol, interval=interval)


def test_noncontiguous_market_session_gap_does_not_silently_create_bars():
    changed = rows()
    changed[300]["time"] = "2026-10-07T13:00:00Z"
    with pytest.raises(ValueError, match="out-of-order, gapped"):
        examine(raw_csv(changed))


def test_no_early_bar_signal_acceptance_on_short_traces():
    with pytest.raises(ValueError, match="350"):
        examine(raw_csv(rows()[:100]))


def test_odd_pine_script_or_forged_hash_refused():
    obj = parsed_strategy()
    with pytest.raises(ValueError, match="source"):
        examine(obj=replace(obj,source_bytes=obj.source_bytes+b"\n"))
    with pytest.raises(ValueError):
        examine(obj=replace(obj,source_sha256="a"*64))  # noqa: F821


def test_read_csv_untrusted_even_if_all_numbers_pass():
    good = examine()
    assert "UNATTESTED" in good.state
    assert good.original_tradingview_export_authenticated is False
