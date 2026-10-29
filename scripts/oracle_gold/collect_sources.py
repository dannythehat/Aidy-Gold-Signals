"""Fetch original source evidence, never execute it or infer mechanics from titles.

61 exact discovery URLs -> independent access receipts. Git clones are bounded,
read-only and contain upstream immutable commit/blob IDs. HTTP HTML is evidence
of a page read only, NEVER proof that protected Pine/MQL trading rules are known.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "research/strategy_lab/day33_gold_edge_83_snapshot.json"


def collect(url, out):
    key = hashlib.sha256(url.encode()).hexdigest()[:16]
    dest = out / key
    dest.mkdir(parents=True, exist_ok=True)
    receipt = {"source_url": url, "attempted_at_utc": datetime.now(UTC).isoformat(),
               "full_mechanics_audit": False}
    try:
        if urllib.parse.urlparse(url).hostname == "github.com":
            repo = dest / "repo"
            if not repo.exists():
                subprocess.run(["git", "clone", "--quiet", "--depth", "1", url+".git", str(repo)],
                    check=True, timeout=120, capture_output=True)
            commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
            listing = subprocess.check_output(["git", "-C", str(repo), "ls-tree", "-r", "HEAD"], text=True)
            files = []
            for line in listing.splitlines():
                meta, path = line.split("\t", 1)
                if Path(path).suffix.lower() in (".py", ".mq4", ".mq5", ".mqh", ".pine", ".set", ".md", ".txt", ".yaml", ".yml") or "LICENSE" in path.upper():
                    local = repo / path
                    if local.is_file() and not local.is_symlink():
                        data = local.read_bytes()
                        files.append({"path": path, "git_blob": meta.split()[-1],
                                      "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
            receipt.update(access="SOURCE_FILES_RETRIEVED_AUDIT_PENDING", source_commit=commit,
                           source_files=files, local_repo=str(repo))
        else:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (source research)"})
            with urllib.request.urlopen(req, timeout=30) as res:
                payload = res.read(5_000_001)
                if len(payload) > 5_000_000:
                    raise ValueError("Page exceeds evidence limit")
                (dest / "page.html").write_bytes(payload)
                receipt.update(access="PAGE_RETRIEVED_EXECUTABLE_SOURCE_UNVERIFIED",
                    http_status=res.status, content_sha256=hashlib.sha256(payload).hexdigest(),
                    bytes=len(payload), final_url=res.url, local_page=str(dest / "page.html"))
    except Exception as exc:  # noqa: BLE001 - persist every independent source failure
        receipt.update(access="SOURCE_ACCESS_BLOCKED", error_type=type(exc).__name__)
        if isinstance(exc, urllib.error.HTTPError):
            receipt["http_status"] = exc.code
    (dest / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n")
    print(receipt["access"], url, flush=True)
    return receipt


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    candidates = json.loads(CATALOG.read_text())["candidates"]
    urls = sorted({c["source_url"] for c in candidates})
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda u: collect(u, args.out), urls))
    # Persistent evidence contains no copied publisher programs or local paths.
    redacted = [{k: v for k, v in r.items() if not k.startswith("local_")} for r in results]
    output = ROOT / "reports/gold_oracle/source_access_receipts.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(redacted, indent=2, sort_keys=True)+"\n")


if __name__ == "__main__":
    main()
