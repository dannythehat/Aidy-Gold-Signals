"""Read-only cross-check of 81 historical tick months against genuine R2 object listing
and seven saved GitHub Actions manifests. No production or warehouse writes.
"""
from __future__ import annotations

import io
import json
import os
import urllib.parse
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

RUN_ID = 38522925686
REPOSITORY = "dannythehat/Aidy-Gold-Signals"
BUCKET = "aidy-memory-test"
PREFIX = "strategy-lab/histdata/xauusd/ticks/"
OUTPUT = Path("artifacts/gold_tick_reconciliation_before.json")


def request_json(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "AIDY-Strategy-Lab-ReadOnly-Inventorier/1.0",
    })
    with urllib.request.urlopen(req, timeout=45) as result:
        return json.load(result)


def previous_manifests(github_token: str) -> dict[str, dict]:
    url = f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{RUN_ID}/artifacts?per_page=100"
    doc = request_json(url, github_token)
    expected = {f"gold-tick-manifest-{year}" for year in range(2020, 2027)}
    actual = {item["name"]: item for item in doc["artifacts"] if item["name"] in expected}
    if set(actual) != expected:
        raise RuntimeError(f"original 7 GitHub manifests not all accessible: {sorted(expected-set(actual))}")
    out = {}
    for name, item in sorted(actual.items()):
        req = urllib.request.Request(item["archive_download_url"], headers={
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "AIDY-Strategy-Lab-ReadOnly-Inventorier/1.0",
        })
        with urllib.request.urlopen(req, timeout=45) as f:
            raw = f.read()
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names = [n for n in z.namelist() if n.endswith("manifest.json")]
            if len(names) != 1:
                raise RuntimeError(f"invalid original archive manifest: {name}")
            payload = json.loads(z.read(names[0]))
        for month in payload["months"]:
            key = month["period"]
            if key in out:
                raise RuntimeError("duplicate month across original job manifests")
            out[key] = month
    if len(out) != 81:
        raise RuntimeError(f"original run only contains {len(out)} months, expected 81")
    return out


def r2_catalog(account_id: str, api_token: str) -> dict[str, dict]:
    result = {}
    cursor = None
    for _ in range(15):
        args = {"prefix": PREFIX, "per_page": 1000}
        if cursor:
            args["cursor"] = cursor
        url = ("https://api.cloudflare.com/client/v4/accounts/"
               + urllib.parse.quote(account_id, safe="")
               + "/r2/buckets/" + BUCKET + "/objects?"
               + urllib.parse.urlencode(args))
        response = request_json(url, api_token)
        if response.get("success") is not True:
            codes = [e.get("code") for e in response.get("errors", [])]
            raise RuntimeError(f"R2 remote object listing denied: {codes}")
        for entry in response.get("result", []):
            key = entry.get("key", "")
            if key in result:
                raise RuntimeError(f"duplicated R2 key in pagination: {key}")
            result[key] = entry
        page = response.get("result_info") or {}
        if not page.get("is_truncated"):
            return result
        cursor = page.get("cursor")
        if not cursor:
            raise RuntimeError("truncated R2 listing missing cursor")
    raise RuntimeError("R2 catalog exceeded safe pagination cap")


def audit() -> dict:
    manifest_read_error = None
    try:
        archive = previous_manifests(os.environ["GITHUB_TOKEN"])
    except (OSError, RuntimeError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        archive = {}
        manifest_read_error = f"GITHUB_MANIFEST_ACCESS_{type(exc).__name__}"
    try:
        remotely_listed = r2_catalog(os.environ["CLOUDFLARE_ACCOUNT_ID"],
                                     os.environ["CLOUDFLARE_API_TOKEN"])
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        raise RuntimeError(f"R2_CATALOG_ACCESS_{type(exc).__name__}") from exc
    months = []
    for year in range(2020, 2027):
        for mon in range(1, 10 if year == 2026 else 13):
            period = f"{year:04d}{mon:02d}"
            name = f"HISTDATA_COM_ASCII_XAUUSD_T_{period}.zip"
            key = f"{PREFIX}{period}/{name}"
            reported = archive.get(period) or {}
            obj = remotely_listed.get(key)
            verified = bool(
                obj and reported.get("status") == "ARCHIVED_R2"
                and int(obj.get("size", 0)) == reported.get("zip_bytes")
                and bool(reported.get("source_zip_sha256"))
                and bool(reported.get("source_payload_sha256"))
                and int(reported.get("tick_rows", 0)) > 0
            )
            months.append({
                "period": period, "bucket": BUCKET, "object_key": key,
                "old_job_status": reported.get("status"),
                "old_failure_type": reported.get("error_type"),
                "remote_exists": obj is not None,
                "remote_bytes": obj.get("size") if obj else None,
                "expected_bytes": reported.get("zip_bytes"),
                "remote_last_modified": obj.get("last_modified") if obj else None,
                "remote_etag": obj.get("etag") if obj else None,
                "manifest_sha256": reported.get("source_zip_sha256"),
                "manifest_payload_sha256": reported.get("source_payload_sha256"),
                "manifest_tick_count": reported.get("tick_rows"),
                "metadata_matches_manifest": verified,
                "remote_nonempty_object": bool(obj and int(obj.get("size",0)) > 500),
            })
    return {
        "observed_at": datetime.now(UTC).isoformat(),
        "source_run": f"https://github.com/{REPOSITORY}/actions/runs/{RUN_ID}",
        "bucket": BUCKET, "prefix": PREFIX, "scope": "2020-01 through 2026-09",
        "total_expected_months": len(months),
        "r2_objects_in_prefix": len(remotely_listed),
        "verified_metadata_and_manifest": sum(m["metadata_matches_manifest"] for m in months),
        "remote_present": sum(m["remote_exists"] for m in months),
        "pending_periods": [m["period"] for m in months if not m["metadata_matches_manifest"]],
        "github_manifest_access": "PASS" if not manifest_read_error else manifest_read_error,
        "remote_nonempty_objects": sum(m["remote_nonempty_object"] for m in months),
        "verification_level": "Cloudflare remote object list; source manifest hash/size comparison ONLY when GH manifests accessible. Full object bytes not rehashed",
        "months": months,
    }


def main() -> int:
    OUTPUT.parent.mkdir(exist_ok=True, parents=True)
    try:
        result = audit()
        result["status"] = "PASS" if result["verified_metadata_and_manifest"] >= 71 else "REMOTE_LISTED"
        print(json.dumps({k:v for k,v in result.items() if k != "months"}, sort_keys=True))
    except Exception as e:
        result = {"status":"BLOCKED", "error_class": type(e).__name__,
                  "message": str(e)[:260]}
        print(json.dumps(result), flush=True)
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n")
    return 0 if result["status"] != "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
