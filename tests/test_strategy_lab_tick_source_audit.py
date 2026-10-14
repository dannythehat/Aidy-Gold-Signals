"""Synthetic-archive safety tests for preserving real irregular quote sources as-is."""
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

import pytest

from aidy.strategy_lab_tick_source_audit import audit_source_tick_zip


def zip_source(tmp_path: Path, period: str, rows: list[str]) -> Path:
    path = tmp_path / f"HISTDATA_COM_ASCII_XAUUSD_T_{period}.zip"
    with ZipFile(path, "w") as z:
        z.writestr(f"HISTDATA_COM_ASCII_XAUUSD_T_{period}.csv",
                   "\n".join(rows) + "\n")
    return path


def rows(n=1002, *, year=2020, month=10, seconds_only=False):
    start = datetime(year, month, 1, tzinfo=UTC)
    result = []
    for i in range(n):
        stamp = start.replace(hour=(i // 3600), minute=(i // 60) % 60, second=i % 60)
        raw = stamp.strftime("%Y%m%d %H%M%S")
        if not seconds_only:
            raw += "000"
        result.append(f"{raw},2650.5,2650.7,0")
    return result


def test_regular_1002_ticks_are_fully_qualified(tmp_path):
    source = zip_source(tmp_path, "202010", rows())
    audit = audit_source_tick_zip(source, "202010")
    assert audit.tick_rows == 1002
    assert audit.chronological
    assert audit.out_of_order_pairs == 0
    assert audit.second_precision_rows == 0
    assert len(audit.source_zip_sha256) == 64
    assert len(audit.payload_sha256) == 64


def test_nonmonotonic_source_preserved_not_pretended_sorted(tmp_path):
    data = rows()
    data[500], data[501] = data[501], data[500]
    source = zip_source(tmp_path, "202010", data)
    original = source.read_bytes()
    audit = audit_source_tick_zip(source, "202010")
    assert not audit.chronological
    assert audit.out_of_order_pairs == 1
    assert audit.tick_rows == 1002
    assert source.read_bytes() == original


def test_explicit_source_second_precision_is_observed(tmp_path):
    source = zip_source(tmp_path, "202606", rows(year=2026, month=6, seconds_only=True))
    audit = audit_source_tick_zip(source, "202606")
    assert audit.second_precision_rows == 1002
    assert audit.maximum_tick_utc.second == 41
    assert audit.maximum_tick_utc.microsecond == 0
    assert audit.chronological


@pytest.mark.parametrize("bad", [
    "20201001 000001000,2652.0,2651.9,0",
    "20201001 000001000,-1,2651.9,0",
    "20201001 000001000,2652.0,NaN,0",
    "20201001 000001000,",
    "20201101 000001000,2650.5,2650.7,0",
    "NOT_A_SOURCE_TIME,2650.5,2650.7,0",
])
def test_archive_with_bad_geometry_or_timestamp_must_not_pass(tmp_path, bad):
    data = rows()
    data[500] = bad
    source = zip_source(tmp_path, "202010", data)
    with pytest.raises(ValueError):
        audit_source_tick_zip(source, "202010")


def test_reject_too_few_ticks(tmp_path):
    source = zip_source(tmp_path, "202010", rows(n=2))
    with pytest.raises(ValueError, match="insufficient"):
        audit_source_tick_zip(source, "202010")


def test_reject_wrong_period_label(tmp_path):
    source = zip_source(tmp_path, "202010", rows())
    with pytest.raises(ValueError):
        audit_source_tick_zip(source, "202013")
