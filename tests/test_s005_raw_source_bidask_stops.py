"""S005 bid/ask original raw-tick chronology adversarial contracts."""
from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.strategy_lab.s005_actual_bidask_tick_stop_scan import (
    _digest_sha, aggregate, source_month_scan,
)

def _fixed_manifest(tmp_path:Path):
    # Includes >20k ORIGINAL format ticks, otherwise the raw-tick reader
    # will correctly reject a fake short archive.
    buf=io.StringIO()
    for i in range(20001):
        if i < 10000:
            bid,ask=2600.,2600.2
        else:
            bid,ask=2597.,2603.
        buf.write(f"20250101 000000{i:06d},{bid},{ask}\n")
    f=tmp_path/"original_202501.zip"
    with zipfile.ZipFile(f,"w",zipfile.ZIP_DEFLATED) as out:
        out.writestr("source.csv",buf.getvalue())
    start=int(datetime(2025,1,1,5,tzinfo=UTC).timestamp())
    request=[
        {"id":"S005-LONG-0","start_epoch_utc":start,
         "end_epoch_utc_exclusive":start+60,
         "stop_test_quote_side":"BID",
         "initial_stop_at_original_python_entry":2598.0},
        {"id":"S005-SHORT-0","start_epoch_utc":start,
         "end_epoch_utc_exclusive":start+60,
         "stop_test_quote_side":"ASK",
         "initial_stop_at_original_python_entry":2602.0},
    ]
    request+=[
        {"id":f"S005-OTHER-{k}","start_epoch_utc":start+300*24*3600,
         "end_epoch_utc_exclusive":start+(300*24*3600)+60,
         "stop_test_quote_side":"BID",
         "initial_stop_at_original_python_entry":1.0} for k in range(495)]
    receipts=[{"source_period":f"2025{x:02d}",
        "sha256_original_zip":"1"*64} for x in range(1,13)]+[
        {"source_period":f"2026{x:02d}",
         "sha256_original_zip":"1"*64} for x in range(1,10)]+[
        {"source_period":"202412","sha256_original_zip":"1"*64}]
    receipts=[dict(r,sha256_original_zip=hashlib.sha256(f.read_bytes()).hexdigest())
              if r["source_period"]=="202501" else r for r in receipts]
    data={"schema":"aidy.s005.source_pinned_497_original_stop_tick_request.v1",
      "requests":request,
      "real_source_original_monthly_zip_receipts":receipts}
    data["sha256"]=_digest_sha(data)
    return f,data


def test_original_source_bid_ask_first_crosses_correct_side(tmp_path):
    zipfile_path,manifest=_fixed_manifest(tmp_path)
    r=source_month_scan(zipfile_path,"202501",manifest)
    assert r["original_tick_rows_processed"]==20001
    assert r["source_minutes_with_out_of_order_micros"]==0
    assert r["trade_ids_covered_with_quotes"]==2
    states={x["id"]:x for x in r["states"]}
    assert states["S005-LONG-0"]["entry_quote"]["bid"]==2600
    assert states["S005-LONG-0"]["entry_quote"]["ask"]==2600.2
    long=states["S005-LONG-0"]["first_source_stop_crossing"]
    short=states["S005-SHORT-0"]["first_source_stop_crossing"]
    assert long["bid"]==2597. and long["price_used"]==2597.
    assert short["ask"]==2603. and short["price_used"]==2603.
    assert long["side"]=="BID"
    assert short["side"]=="ASK"
    assert r["not_native_MT5_deal_or_equity"]


def test_quote_zip_corruption_fails_closed(tmp_path):
    f,manifest=_fixed_manifest(tmp_path)
    manifest["real_source_original_monthly_zip_receipts"][1]["sha256_original_zip"]="2"*64
    # original manifest is unsigned after tampering, even if raw file exists
    with pytest.raises(ValueError,match="Tampered"):
        source_month_scan(f,"202501",manifest)


def test_missing_original_months_cannot_prove_full_replay():
    with pytest.raises(ValueError,match="Missing original months"):
        aggregate({"requests":[],"real_source_original_monthly_zip_receipts":[]},[])


def test_source_sha_contract_detects_modified_byte(tmp_path):
    f,manifest=_fixed_manifest(tmp_path)
    with f.open("ab") as handle:handle.write(b"QUOTETAPE_TAMPER")
    with pytest.raises(ValueError,match="SHA mismatch"):
        source_month_scan(f,"202501",manifest)
