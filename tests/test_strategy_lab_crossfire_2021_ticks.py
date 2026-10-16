"""Crossfire original tick archival integrity and non-monotonic source tests."""
from __future__ import annotations

import csv
import io
import zipfile
from datetime import UTC, datetime, timedelta

import pytest

from aidy.strategy_lab_crossfire_tick_2021 import (
    derive_month_zip,
    parse_tick,
)


def test_source_fixed_est_to_utc_with_fraction_and_seconds_only():
    cache = {}
    ts, micros, bid, ask = parse_tick(
        ["20210105 194500123","1949.50","1949.80"],month="202101",
        day_cache=cache,
    )
    assert datetime.fromtimestamp(ts, UTC).isoformat()=="2021-01-06T00:45:00+00:00"
    assert micros==123000
    assert ask-bid==pytest.approx(.30)
    s, frac, *_ = parse_tick(
        ["20210105 194500","1949.50","1949.80"],month="202101",day_cache=cache,
    )
    assert (s,frac)==(ts,0)
    with pytest.raises(ValueError):
        parse_tick(["20210105 194500123","1949.90","1949.80"],
                   month="202101",day_cache=cache)


def _archive(path, *, inverted=False, bad_ask=False):
    output=io.StringIO()
    writer=csv.writer(output,lineterminator="\n")
    start=datetime(2021,1,3,0,0)
    # 200 full source EST hours -> 200*60 complete UTC hours.
    for i in range(200*60):
        d=start+timedelta(minutes=i)
        base=1900+i*.001
        rows=[
            [d.strftime("%Y%m%d %H%M%S")+"100",f"{base:.3f}",f"{base+.3:.3f}"],
            [d.strftime("%Y%m%d %H%M%S")+"900",f"{base+.02:.3f}",f"{base+.32:.3f}"],
        ]
        if inverted and i==400:
            rows.reverse()
        if bad_ask and i==10:
            rows[0][2]="1.00"
        writer.writerows(rows)
    with zipfile.ZipFile(path,"w",compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("HISTDATA_COM_ASCII_XAUUSD_T_202101.csv",output.getvalue())


def test_realistic_month_derivation_is_source_sha_fingerprinted(tmp_path):
    path=tmp_path/"source.zip"
    _archive(path,inverted=True)
    rows,receipt=derive_month_zip(path,"202101")
    assert len(rows)==200
    assert receipt["source_order_inversions"]==1
    assert receipt["source_tick_rows"]==24000
    assert receipt["occupied_source_minutes"]==12000
    assert receipt["excluded_incomplete_h1"]==0
    assert receipt["raw_source_modified"] is False
    assert rows[0]["m1_count"]==60
    assert rows[0]["observed_open_spread"]==pytest.approx(.3)
    assert len(receipt["input_zip_sha256"])==64
    again, second=derive_month_zip(path,"202101")
    assert (rows,receipt)==(again,second)


def test_fail_closed_wrong_archive_month_and_invalid_price(tmp_path):
    file=tmp_path/"wrong.zip"
    _archive(file,bad_ask=True)
    with pytest.raises(ValueError,match="BID/ASK"):
        derive_month_zip(file,"202101")
    _archive(file)
    with pytest.raises(ValueError,match="outside fixed-EST"):
        derive_month_zip(file,"202102")
