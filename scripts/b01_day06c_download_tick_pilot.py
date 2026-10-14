"""Download and validate one previously missing XAUUSD bid/ask tick month.

Real archive retained in Actions artifact. Does not alter BigQuery, R2 or production.
"""
import json
from datetime import UTC, datetime
from pathlib import Path
from aidy.historical_spread import HistDataTickPeriod, download_histdata_tick_period, iter_histdata_ticks, tick_archive_meta

period=HistDataTickPeriod(2024, 1)
root=Path("artifacts/bidask_download")
zip_path=download_histdata_tick_period(period,cache_dir=root)
meta=tick_archive_meta(zip_path)
count=0
first=None
last=None
for tick in iter_histdata_ticks(zip_path):
    count+=1
    if first is None: first=tick.source_tick_time_utc
    last=tick.source_tick_time_utc
if count==0:raise RuntimeError("Downloaded tick archive is empty")
result={"period":period.key,"tick_rows":count,"first_utc":first.isoformat(),"last_utc":last.isoformat(),
        "source_zip_sha256":meta.source_file_sha256,"payload_sha256":meta.source_payload_sha256,
        "archive_filename":zip_path.name,"archive_bytes":zip_path.stat().st_size,
        "checked_at_utc":datetime.now(UTC).isoformat(),"status":"PASS"}
(root/"manifest.json").write_text(json.dumps(result,indent=2)+"\n")
print(json.dumps(result))
