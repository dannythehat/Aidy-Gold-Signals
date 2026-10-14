"""Day07 reader tests: no lookahead, no missing data repair, fixed EST not US DST."""
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from aidy.strategy_lab_history_reader import (
    SOURCE_ZONE,
    Window,
    _read_rows,
)

START = datetime(2025, 1, 6, 14, tzinfo=UTC)
SHA = "a" * 64


def window(minutes=15, timeframe=5, at=START, as_of=None, digest=None):
    return Window(at, at + timedelta(minutes=minutes),
                  as_of or at + timedelta(minutes=minutes), timeframe, digest)


def rows(start=START, count=15):
    result = []
    for i in range(count):
        ts = start + timedelta(minutes=i)
        p = 2650 + i
        result.append({
            "open_time_utc": ts, "open": str(p), "high": str(p + 2),
            "low": str(p - 1), "close": str(p + 1),
            "source": "histdata", "symbol": "XAUUSD", "timeframe": "M1",
            "price_basis": "bid", "source_dataset": "generic_ascii_m1",
            "source_timezone": "EST_FIXED_UTC_MINUS_05",
            "source_open_time": ts.astimezone(SOURCE_ZONE).strftime("%Y%m%d %H%M%S"),
            "derivation_version": "aidy_histdata_source_aligned_v1",
            "provenance_class": "retrospective_history", "pit_eligible": False,
            "source_file": "source_2025.zip", "source_file_sha256": SHA,
            "source_payload_sha256": "b" * 64, "derived_from_timeframe": None,
            "input_rows": 1, "research_identity": str(i),
        })
    return result


def test_realistic_m5_aggregate_and_time_availability():
    result = _read_rows(rows(), window())
    assert result.native_m1_rows == 15
    assert len(result.bars) == 3
    assert result.bars[0].open == Decimal(2650)
    assert result.bars[0].high == Decimal(2656)
    assert result.bars[0].low == Decimal(2649)
    assert result.bars[0].close == Decimal(2655)
    assert result.bars[0].available_at_utc == START + timedelta(minutes=5)
    assert result.pit_eligible is False
    assert result.source_archive_hashes == (SHA,)


def test_m1_m15_and_reproducible_digest():
    m1 = _read_rows(rows(), window(timeframe=1))
    m15 = _read_rows(rows(), window(timeframe=15))
    assert len(m1.bars) == 15 and len(m15.bars) == 1
    assert m1.input_digest == m15.input_digest
    verified = window(timeframe=15, digest=m15.input_digest)
    assert _read_rows(rows(), verified).input_digest == m15.input_digest


@pytest.mark.parametrize("change", ["open", "research_identity", "source_file_sha256"])
def test_frozen_input_detects_change(change):
    original = _read_rows(rows(), window())
    changed = rows()
    changed[0][change] = "b" * 64 if change == "source_file_sha256" else "9999"
    with pytest.raises(ValueError):
        _read_rows(changed, window(digest=original.input_digest))


@pytest.mark.parametrize("kind", ["gap", "duplicate", "unordered", "short", "bad_ohlc",
                                  "bad_source_clock", "bad_price_basis", "pit",
                                  "future_source_timestamp", "bad_archive_hash"])
def test_negative_data_cases_fail_closed(kind):
    data = rows()
    if kind == "gap":
        data.pop(6)
    elif kind == "duplicate":
        data[4] = dict(data[3])
    elif kind == "unordered":
        data[3], data[4] = data[4], data[3]
    elif kind == "short":
        data.pop(0)
    elif kind == "bad_ohlc":
        data[3]["high"] = "-1"
    elif kind == "bad_source_clock":
        data[4]["source_timezone"] = "America/New_York"
    elif kind == "bad_price_basis":
        data[4]["price_basis"] = "mid"
    elif kind == "pit":
        data[4]["pit_eligible"] = True
    elif kind == "future_source_timestamp":
        data[0]["source_open_time"] = "20250106 140000"
    elif kind == "bad_archive_hash":
        data[4]["source_file_sha256"] = "not a hash"
    with pytest.raises(ValueError):
        _read_rows(data, window())


def test_no_open_candles_or_out_of_range_timeframes():
    with pytest.raises(ValueError):
        window(as_of=START + timedelta(minutes=10)).validate()
    with pytest.raises(ValueError):
        window(timeframe=7).validate()
    with pytest.raises(ValueError):
        window(minutes=16, timeframe=5).validate()
    with pytest.raises(ValueError):
        window(minutes=1, timeframe=1,
               at=START + timedelta(seconds=20)).validate()


def test_source_clock_is_fixed_utc_minus_five_not_dst():
    winter = datetime(2025, 1, 6, 12, tzinfo=UTC)
    summer = datetime(2025, 7, 1, 12, tzinfo=UTC)
    assert winter.astimezone(SOURCE_ZONE).hour == 7
    assert summer.astimezone(SOURCE_ZONE).hour == 7
    assert summer.astimezone(timezone(timedelta(hours=-4))).hour == 8


def test_source_daily_bucket_alignment_and_offset():
    # Fixed EST daily midnight is 05:00Z in winter AND summer.
    at = datetime(2025, 7, 1, 5, tzinfo=UTC)
    Window(at, at + timedelta(days=1),
           at + timedelta(days=1), 1440).validate()
    with pytest.raises(ValueError):
        Window(datetime(2025, 7, 1, 4, tzinfo=UTC),
               datetime(2025, 7, 2, 4, tzinfo=UTC),
               datetime(2025, 7, 2, 4, tzinfo=UTC), 1440).validate()


def test_h4_alignment_is_not_utc_modulo_four():
    # EST 08:00 is 13:00 UTC. A 12:00 UTC open is source 07:00.
    at = datetime(2025, 1, 6, 13, tzinfo=UTC)
    Window(at, at + timedelta(hours=4),
           at + timedelta(hours=4), 240).validate()
    with pytest.raises(ValueError):
        Window(datetime(2025, 1, 6, 12, tzinfo=UTC),
               datetime(2025, 1, 6, 16, tzinfo=UTC),
               datetime(2025, 1, 6, 16, tzinfo=UTC), 240).validate()


def test_unqualified_native_bar_cannot_look_like_ask_fill():
    data = rows()
    data[0]["price_basis"] = "ask"
    with pytest.raises(ValueError):
        _read_rows(data, window())
