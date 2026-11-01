"""G005 frozen source real-tick parser and genuine 2026 source receipt guard tests.

Synthetic tests only protect parsing and chronology; real results require R2
source hash comparison with preexisting immutable 2026 original proof.
"""
import zipfile
from pathlib import Path
import pytest

from scripts.gold_hunter_g005_2026_tick_source import (
    minutes_from_zip, validate_original_source, MONTHS,
)
from scripts.gold_hunter_g005_2026_original_tick_replay import (
    verified_2026_m1, PERIODS
)

def sample_zip(tmp_path):
    path=tmp_path/"source.zip"
    ticks=[
      "20260102 110030000000,1900.0,1900.3",
      "20260102 110010000000,1899.5,1899.8",
      "20260102 110055000000,1900.5,1900.9",
      "20260102 110005000000,1899.9,1900.2",
      "20260102 110055000000,1900.4,1900.8",
      "20260102 110105000000,1900.2,1900.6",
    ]
    with zipfile.ZipFile(path,"w") as zf:
        zf.writestr("some_original_tick.csv","\n".join(ticks)+"\n")
    return path

def test_parser_uses_chronological_original_ticks_not_file_line_order(tmp_path):
    path=sample_zip(tmp_path)
    rows, n=minutes_from_zip(path,"202601")
    assert n==6 and len(rows)==2
    first=rows[0]
    assert first["ticks"]==5
    assert first["bid_o"]==pytest.approx(1899.9)
    assert first["bid_c"]==pytest.approx(1900.4)
    assert first["bid_h"]==pytest.approx(1900.5)
    assert first["bid_l"]==pytest.approx(1899.5)
    assert first["ask_h"]==pytest.approx(1900.9)
    assert first["ask_l"]==pytest.approx(1899.8)

def test_reject_unverified_tiny_unmatched_sources(tmp_path):
    with pytest.raises(ValueError):
        validate_original_source(sample_zip(tmp_path),"202601",{})

def test_refuse_period_outside_existing_source_archive(tmp_path):
    with pytest.raises(ValueError,match="Unexpected"):
        validate_original_source(sample_zip(tmp_path),"202610",{})

def test_year_months_include_december_2025_for_fixed_est_seam():
    assert MONTHS==PERIODS
    assert PERIODS[0]=="202512"
    assert PERIODS[-1]=="202609"
    assert len(PERIODS)==10

def test_2026_source_reader_fail_closed_on_missing_month(tmp_path):
    with pytest.raises(ValueError,match="Missing tick source"):
        verified_2026_m1(tmp_path)
