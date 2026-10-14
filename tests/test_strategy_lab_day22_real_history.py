"""Offline regression for Day22 real-history-qualified Pine internal parity audit."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.strategy_lab_history_reader import ClosedBar, ReadResult
from scripts.strategy_lab.day22_real_history_ema_audit import audit_closed_bars


def example_read() -> ReadResult:
    start = datetime(2025, 1, 6, 11, tzinfo=UTC)
    # Controlled prices: fast below slow at candle 49 then a sharp recovery.
    closes = [Decimal(2650) - Decimal(i) / 10 for i in range(50)]
    closes.extend(Decimal(2645) + Decimal(j) * 2 for j in range(40))
    bars = tuple(
        ClosedBar(start + timedelta(minutes=5*i),
                  start + timedelta(minutes=5*(i+1)),
                  close, close + 1, close - 1, close)
        for i, close in enumerate(closes)
    )
    return ReadResult(bars, len(bars) * 5, "b" * 64, ("a" * 64,))


def test_real_history_audit_uses_source_pinned_independent_ema_and_cross():
    evidence = audit_closed_bars(example_read())
    assert evidence["status"] == "PASS"
    assert evidence["signal_count"] >= 1
    assert evidence["signals_utc"] == sorted(evidence["signals_utc"])
    assert evidence["closed_m5_count"] == 90
    assert evidence["native_m1_count"] == 450
    assert len(evidence["pine_source_sha256"]) == 64
    assert evidence["external_tradingview_parity_qualified"] is False
    assert evidence["broker_fills_qualified"] is False
    assert evidence["customer_login_required"] is False


@pytest.mark.parametrize("field", ["native_m1_rows", "input_digest", "source_archive_hashes",
                                     "pit_eligible", "provenance"])
def test_unqualified_historical_identity_is_rejected(field):
    before = example_read()
    bad = {
        "native_m1_rows": 444,
        "input_digest": "",
        "source_archive_hashes": (),
        "pit_eligible": True,
        "provenance": "invented_vendor_claim",
    }
    with pytest.raises(ValueError, match="unqualified"):
        audit_closed_bars(replace(before, **{field: bad[field]}))


def test_gapped_unclosed_and_other_quote_side_rejected():
    original = example_read()
    examples = (
        replace(original.bars[4], available_at_utc=original.bars[4].open_time_utc),
        replace(original.bars[4], open_time_utc=original.bars[4].open_time_utc + timedelta(minutes=1)),
        replace(original.bars[4], price_basis="ask"),
    )
    for altered in examples:
        bars = list(original.bars)
        bars[4] = altered
        with pytest.raises(ValueError):
            audit_closed_bars(replace(original, bars=tuple(bars)))


def test_insufficient_closed_warmup_rejected():
    original = example_read()
    with pytest.raises(ValueError, match="unqualified"):
        audit_closed_bars(replace(original, bars=original.bars[:50], native_m1_rows=250))
