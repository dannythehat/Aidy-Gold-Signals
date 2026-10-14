"""Targeted recovery of exactly ten missing historical XAUUSD tick month archives.

Never overwrite a remotely present object. Validate every tick; upload original ZIP
to private R2, then re-download and verify exact original archive SHA256.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from aidy.historical_spread import (
    HistDataTickPeriod, download_histdata_tick_period,
    iter_histdata_ticks, tick_archive_meta,
)

MISSING_PERIODS = frozenset({
    "202010", "202110", "202210", "202310", "202410", "202510",
    "202606", "202607", "202608", "202609",
})
BUCKET = "aidy-memory-test"
PREFIX = "strategy-lab/histdata/xauusd/ticks/"
EST_FIXED = timezone(timedelta(hours=-5))


def remote_metadata(key: str) -> dict | None:
    prefix = urllib.parse.urlencode({"prefix": key, "per_page": 100})
    url = (f"https://api.cloudflare.com/client/v4/accounts/"
           f"{os.environ['CLOUDFLARE_ACCOUNT_ID']}/r2/buckets/{BUCKET}/objects?{prefix}")
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + os.environ["CLOUDFLARE_API_TOKEN"],
        "User-Agent": "AIDY-Strategy-Lab-Archive-Recovery/1.0",
    })
    with urllib.request.urlopen(req, timeout=40) as response:
        result = json.load(response)
    if result.get("success") is not True:
        raise RuntimeError("R2_CATALOG_NOT_AUTHORISED")
    found = [item for item in result.get("result", []) if item.get("key") == key]
    if len(found) > 1:
        raise RuntimeError("DUPLICATE_R2_OBJECT")
    return found[0] if found else None


def run_cmd(*args: str, timeout: int = 240) -> subprocess.CompletedProcess:
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)


def archive_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def acquire(period_str: str, workdir: Path) -> dict:
    year, month = int(period_str[:4]), int(period_str[4:])
    period = HistDataTickPeriod(year, month)
    filename = period.cache_name
    key = f"{PREFIX}{period.key}/{filename}"
    evidence = {"period": period_str, "bucket": BUCKET, "object_key": key,
                "observed_at_utc": datetime.now(UTC).isoformat(), "attempts": []}
    step = "remote_precheck"
    try:
        existing = remote_metadata(key)
        if existing:
            if int(existing.get("size", 0)) < 100:
                raise RuntimeError("REMOTE_OBJECT_UNEXPECTEDLY_SMALL")
            evidence.update({"status":"ALREADY_PRESENT_REMOTE", "remote_bytes":existing["size"],
                             "remote_etag": existing.get("etag")})
            return evidence
        source_path = None
        for attempt in range(1, 4):
            step = "source_download"
            try:
                source_path = download_histdata_tick_period(period, cache_dir=workdir)
                break
            except Exception as exc:  # noqa: BLE001 - classify external provider failures
                diagnostic = {"attempt": attempt, "error_type": type(exc).__name__}
                response = getattr(exc, "response", None)
                if response is not None:
                    diagnostic["http_status"] = getattr(response, "status_code", None)
                evidence["attempts"].append(diagnostic)
                if attempt == 3:
                    evidence["status"] = "SOURCE_DOWNLOAD_FAILED"
                    evidence["last_stage"] = step
                    return evidence
                time.sleep(6 * attempt)
        if source_path is None:
            raise RuntimeError("SOURCE_PATH_MISSING")
        step = "archive_hash"
        meta = tick_archive_meta(source_path)
        step = "tick_parse"
        count = 0
        first = last = None
        for tick in iter_histdata_ticks(source_path):
            count += 1
            first = first or tick.source_tick_time_utc
            last = tick.source_tick_time_utc
            if tick.source_tick_time_utc.astimezone(EST_FIXED).strftime("%Y%m") != period_str:
                raise RuntimeError("WRONG_SOURCE_TICK_MONTH")
        if count < 1000 or first is None or last is None:
            raise RuntimeError("SOURCE_HAS_TOO_FEW_TICKS")
        evidence.update({
            "tick_rows":count, "source_zip_sha256":meta.source_file_sha256,
            "source_payload_sha256":meta.source_payload_sha256,
            "source_zip_bytes":source_path.stat().st_size,
            "first_tick_utc":first.isoformat(), "last_tick_utc":last.isoformat(),
        })
        step = "r2_put"
        result = run_cmd("npx", "--yes", "wrangler@4", "r2", "object", "put",
                         BUCKET + "/" + key, "--remote",
                         "--file", str(source_path), "--content-type", "application/zip")
        if result.returncode:
            raise RuntimeError("R2_UPLOAD_FAILED")
        step = "r2_get_sha_verify"
        reread = workdir / ("remote-" + filename)
        response = run_cmd("npx", "--yes", "wrangler@4", "r2", "object", "get",
                           BUCKET + "/" + key, "--remote", "--file", str(reread))
        if response.returncode:
            raise RuntimeError("R2_READBACK_FAILED")
        if archive_sha(reread) != meta.source_file_sha256:
            raise RuntimeError("R2_READBACK_SHA_MISMATCH")
        reread.unlink()
        step = "r2_final_catalog"
        confirmed = remote_metadata(key)
        if confirmed is None or int(confirmed.get("size", 0)) != source_path.stat().st_size:
            raise RuntimeError("R2_OBJECT_METADATA_MISMATCH")
        evidence.update({"status": "ARCHIVED_AND_SHA_VERIFIED_R2",
                         "remote_bytes":confirmed["size"], "remote_etag":confirmed.get("etag")})
        source_path.unlink()
        return evidence
    except Exception as exc:  # noqa: BLE001 - preserve structured recovery evidence
        evidence.update({"status": "FAILED", "last_stage":step,
                         "error_type":type(exc).__name__})
        # Only print our own known stage and error type; never leak response text/secrets.
        if isinstance(exc, RuntimeError) and str(exc) in {
            "R2_CATALOG_NOT_AUTHORISED", "DUPLICATE_R2_OBJECT",
            "REMOTE_OBJECT_UNEXPECTEDLY_SMALL", "WRONG_SOURCE_TICK_MONTH",
            "SOURCE_HAS_TOO_FEW_TICKS", "R2_UPLOAD_FAILED", "R2_READBACK_FAILED",
            "R2_READBACK_SHA_MISMATCH", "R2_OBJECT_METADATA_MISMATCH",
        }:
            evidence["reason"] = str(exc)
        return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", required=True, choices=sorted(MISSING_PERIODS))
    args = parser.parse_args()
    root = Path("artifacts/retries") / args.period
    root.mkdir(parents=True, exist_ok=True)
    try:
        result = acquire(args.period, root)
    except Exception as exc:  # noqa: BLE001 - preserve blocked account/source state
        result = {"period":args.period, "status":"BLOCKED",
                  "error_type":type(exc).__name__}
    (root / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in (
        "ARCHIVED_AND_SHA_VERIFIED_R2", "ALREADY_PRESENT_REMOTE"
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
