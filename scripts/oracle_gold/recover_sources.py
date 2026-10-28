"""Recheck each unresolved ORIGINAL URL; recover only openly exposed source.

No protected/private Pine, authentication, code execution or source rewriting.
Earlier access receipts remain immutable; this is a separate recovery record.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAT = ROOT/"research/strategy_lab/day33_gold_edge_83_snapshot.json"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.tradingview.com/",
           "Origin": "https://www.tradingview.com"}


def get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=25) as response:
        raw = response.read(5_000_001)
        if len(raw) > 5_000_000:
            raise ValueError("Source response over size limit")
        return raw, {"url": url, "final_url": response.url, "http_status": response.status,
            "content_type": response.headers.get("Content-Type"),
            "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def tv_metadata(page):
    # Public SSR metadata supplies the PUBLIC publication ID, not a guessed
    # private USER id. The chart's originalScriptId must not be substituted.
    for match in re.finditer(r'<script[^>]*type="application/prs.init-data\+json"[^>]*>(.*?)</script>', page, re.DOTALL):
        value = json.loads(match[1])
        for section in value.values():
            if isinstance(section, dict) and "ssrIdeaData" in section:
                return section["ssrIdeaData"]
    raise ValueError("Public script metadata absent")


def recover(candidate, out, cached, discovered=None):
    url = candidate["source_url"]
    key = hashlib.sha256(url.encode()).hexdigest()[:16]
    dest = out/key
    dest.mkdir(parents=True, exist_ok=True)
    record = {"source_url": url, "checked_at_utc": datetime.now(UTC).isoformat(),
              "attempts": [], "status": "SOURCE_UNVERIFIED", "source_files": []}
    try:
        if "tradingview.com/" in url:
            old = cached/key/"page.html" if cached else None
            if old and old.exists():
                raw = old.read_bytes()
                receipt = {"url": url, "sha256": hashlib.sha256(raw).hexdigest(),
                           "bytes": len(raw), "status": "PRIOR_PUBLIC_PAGE_REUSED"}
            else:
                raw, receipt = get(url)
            record["attempts"].append(receipt)
            meta = tv_metadata(raw.decode("utf-8"))
            script = meta["script"]
            record["publication"] = {"id": script["id"], "public_id": script["script_id_part"],
                "version": script["version_maj"], "access": script["access"],
                "chart_interval": meta.get("interval"), "author": meta.get("user", {}).get("username")}
            if script["access"] != 1 or not script["script_id_part"].startswith("PUB;"):
                record["status"] = "BLOCKED_PROTECTED_OR_INVITE_ONLY_OR_NOT_PUBLIC"
            else:
                endpoint = "https://pine-facade.tradingview.com/pine-facade/get/"+urllib.parse.quote(script["script_id_part"], safe="")+"/"+str(script["version_maj"])+"?no_4xx=false"
                raw, receipt = get(endpoint)
                record["attempts"].append(receipt)
                source = json.loads(raw)
                if source.get("scriptAccess") != "open_no_auth" or not source.get("source"):
                    raise ValueError("No freely available plaintext original source")
                content = source["source"].encode("utf-8")
                path = dest/"original.pine"
                path.write_bytes(content)
                # Preserve source chart metadata to verify published settings,
                # original instrument, timeframe and tick assumptions later.
                (dest/"publication.json").write_text(json.dumps(meta, sort_keys=True)+"\n")
                record["source_files"] = [{"path": path.name, "sha256": hashlib.sha256(content).hexdigest(),
                    "bytes": len(content), "endpoint": endpoint, "version": source.get("version")}]
                record["status"] = "ORIGINAL_PUBLIC_PINE_RETRIEVED"
        elif "mql5.com/" in url:
            links = list((discovered or {}).get(url, []))
            try:
                raw, receipt = get(url)
                record["attempts"].append(receipt)
                text = raw.decode("utf-8")
                links += re.findall(r'href=[\"\']([^\"\']+(?:\.mq5|\.mq4|\.mqh)(?:\?[^\"\']*)?)[\"\']', text, re.IGNORECASE)
            except Exception as exc:  # noqa: BLE001 - page/download failures are separate evidence
                record["attempts"].append({"url": url, "error_type": type(exc).__name__,
                    "http_status": exc.code if isinstance(exc, urllib.error.HTTPError) else None})
            if not links:
                record["status"] = "BLOCKED_NO_EXECUTABLE_DOWNLOAD_EXPOSED"
            for link in dict.fromkeys(links):
                endpoint = urllib.parse.urljoin(url, link.replace("&amp;", "&"))
                try:
                    payload, item = get(endpoint)
                    record["attempts"].append(item)
                    source = payload.decode("utf-16" if payload[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig")
                    if "<html" in source.lower() or not any(t in source for t in ("OnTick", "OnCalculate", "start()", "OnStart")):
                        raise ValueError("Download is not executable MQL source")
                    name = Path(urllib.parse.urlparse(endpoint).path).name
                    (dest/name).write_bytes(payload)
                    record["source_files"].append({"path": name, "sha256": hashlib.sha256(payload).hexdigest(),
                                                  "bytes": len(payload), "endpoint": endpoint})
                except Exception as exc:  # noqa: BLE001 - retain every source failure
                    record["attempts"].append({"url": endpoint, "error_type": type(exc).__name__,
                        "http_status": exc.code if isinstance(exc, urllib.error.HTTPError) else None})
            if record["source_files"]:
                record["status"] = "ORIGINAL_PUBLIC_MQL_RETRIEVED"
            elif links:
                record["status"] = "BLOCKED_EXECUTABLE_DOWNLOAD"
        else:
            raw, receipt = get(url)
            record["attempts"].append(receipt)
            record["status"] = "BLOCKED_PAPER_PAGE_NO_EXECUTABLE_CODE_VERIFIED"
    except Exception as exc:  # noqa: BLE001 - fail closed, never invent missing source
        record["attempts"].append({"error_type": type(exc).__name__,
            "http_status": exc.code if isinstance(exc, urllib.error.HTTPError) else None})
        record["status"] = "BLOCKED_FETCH_OR_SOURCE_VALIDATION"
    (dest/"receipt.json").write_text(json.dumps(record, indent=2, sort_keys=True)+"\n")
    print(record["status"], candidate["id"], flush=True)
    return record


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--cached-pages", type=Path)
    p.add_argument("--only", choices=("all", "mql", "tv"), default="all")
    p.add_argument("--download-links", type=Path)
    args = p.parse_args()
    candidates = json.loads(CAT.read_text())["candidates"]
    selected = [x for x in candidates if 32 <= int(x["id"][1:]) <= 81]
    if args.only != "all":
        selected = [x for x in selected if ("mql5.com" if args.only == "mql" else "tradingview.com") in x["source_url"]]
    by_url = {x["source_url"]: x for x in selected}
    discovered = {x["url"]: x["downloads"] for x in json.loads(args.download_links.read_text())} if args.download_links else {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(lambda c: recover(c, args.out, args.cached_pages, discovered), by_url.values()))
    packet = {"schema": "oracle.gold.remaining50.source_recovery.v1", "receipts": receipts,
        "ids": [{"id": x["id"], "source_url": x["source_url"]} for x in selected],
        "source_originals_modified": False, "source_execution": False}
    (args.out/"recovery_receipts.json").write_text(json.dumps(packet, indent=2, sort_keys=True)+"\n")


if __name__ == "__main__":
    main()
