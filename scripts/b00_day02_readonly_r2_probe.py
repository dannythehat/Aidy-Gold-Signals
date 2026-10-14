#!/usr/bin/env python3
"""Day 02 read-only evidence: D1 archived key -> verify its R2 object via Wrangler GET.

Never creates a smoke object, modifies D1/outbox or prints confidential payload.
"""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
import tempfile
import urllib.request
from datetime import datetime, UTC
from pathlib import Path

def main() -> int:
    result = {"probe":"b00_day02_r2_read_only_v1","observed_at_utc":datetime.now(UTC).isoformat(),"status":"BLOCKED"}
    path=Path("artifacts/b00_day02_r2.json")
    path.parent.mkdir(parents=True,exist_ok=True)
    try:
        account=os.environ["CLOUDFLARE_ACCOUNT_ID"]
        db=os.environ["AIDY_D1_DATABASE_ID"]
        token=os.environ["CLOUDFLARE_API_TOKEN"]
        endpoint=f"https://api.cloudflare.com/client/v4/accounts/{account}/d1/database/{db}/query"
        sql=("SELECT archive_key FROM archive_outbox WHERE status='archived' "
             "AND archive_key LIKE 'gold/%' AND archive_key IS NOT NULL "
             "ORDER BY created_at DESC LIMIT 1")
        req=urllib.request.Request(endpoint,data=json.dumps({"sql":sql,"params":[]}).encode(),
                headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"},method="POST")
        with urllib.request.urlopen(req,timeout=40) as resp:
            data=json.load(resp)
        if not data.get("success"): raise RuntimeError("D1 query failed")
        rows=data["result"][0].get("results",[])
        if len(rows)!=1: raise RuntimeError("No eligible archived gold key")
        key=rows[0]["archive_key"]
        if not key.startswith("gold/") or ".." in key or any(c in key for c in "\\ \t\r\n"):
            raise ValueError("Unexpected archive key")
        with tempfile.TemporaryDirectory() as tmp:
            out=str(Path(tmp)/"archive.bin")
            command=["npx","--yes","wrangler@4","r2","object","get",
                     f"aidy-memory-test/{key}","--remote","--file",out]
            proc=subprocess.run(command,capture_output=True,text=True,timeout=150)
            if proc.returncode: raise RuntimeError("R2 object read returned non-zero exit")
            raw=Path(out).read_bytes()
        if not raw: raise ValueError("R2 archive object empty")
        result.update({"status":"PASS","archive_key":key,
            "bucket":"aidy-memory-test","object_bytes":len(raw),
            "object_sha256":hashlib.sha256(raw).hexdigest(),
            "read_only":True,"notes":"D1 outbox archive key and remote R2 object retrieved; no object contents published."})
    except Exception as exc:
        result.update({"status":"BLOCKED","error_type":type(exc).__name__,
                       "notes":"No archive access claim; investigate credentials or archive availability."})
    path.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result))
    return 0 if result["status"]=="PASS" else 1

if __name__=="__main__":
    raise SystemExit(main())
