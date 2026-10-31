"""Fail-closed checks before downloading any existing 2022 Gold archive."""
import json
from pathlib import Path
import pandas as pd
import pytest
from scripts.gold_hunter_dev_ny_orb_2022 import MONTHS,START,END,load_months

def test_original_2022_twelve_fixed_est_months():
    assert len(MONTHS)==12 and len(set(MONTHS))==12
    assert MONTHS[0]=="202201" and MONTHS[-1]=="202212"
    assert str(START)=="2022-01-01 00:00:00+00:00"
    assert str(END)=="2023-01-01 00:00:00+00:00"

def test_unverified_historical_source_is_blocker(tmp_path):
    with pytest.raises(ValueError,match="missing"):
        load_months(tmp_path)

def test_untrusted_month_manifest_is_not_accepted(tmp_path):
    folder=tmp_path/"ny-orb-source-202201"
    folder.mkdir()
    (folder/"receipt.json").write_text(json.dumps({
       "source_month_fixed_est":"202201",
       "input_zip_sha256":"x"*64,
       "raw_source_modified":True,
       "broker_ask_executable":False,
       "complete_utc_h1":400
    }))
    (folder/"hourly.csv").write_text("open_time_utc,open\n")
    with pytest.raises(ValueError,match="provenance"):
        load_months(tmp_path)
