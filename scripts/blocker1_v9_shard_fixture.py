"""Shard the frozen Blocker-1 v9 fixture into connector-safe, lossless JSON parts."""

from __future__ import annotations

import json
import shutil
from hashlib import sha256
from pathlib import Path

SOURCE = Path("blocker1_t1_v9_fixture.json")
OUT = Path("audit/blocker1-v9/sharded")
PARTS = OUT / "parts"
CHUNK_SIZES = {
    "outcome_history": 1000,
    "commitment_history": 400,
    "trust_history": 300,
    "dependency_history": 60,
}

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def digest(value):
    return sha256(canonical(value).encode()).hexdigest()

def main():
    fixture = json.loads(SOURCE.read_text())
    if OUT.exists():
        shutil.rmtree(OUT)
    PARTS.mkdir(parents=True, exist_ok=True)

    manifest = {
        key: value
        for key, value in fixture.items()
        if key not in CHUNK_SIZES
    }
    sections = {}

    for section, size in CHUNK_SIZES.items():
        rows = fixture[section]
        names = []
        for start in range(0, len(rows), size):
            chunk = rows[start:start + size]
            payload = {
                "fixture_version": fixture["fixture_version"],
                "combined_fixture_digest": fixture["combined_fixture_digest"],
                "section": section,
                "start_index": start,
                "row_count": len(chunk),
                "rows": chunk,
            }
            payload["shard_digest"] = digest(payload)
            name = f"{section}_{start:05d}_{start + len(chunk) - 1:05d}.json"
            (PARTS / name).write_text(
                json.dumps(payload, sort_keys=True, indent=2) + "\n"
            )
            names.append({
                "file": f"parts/{name}",
                "start_index": start,
                "row_count": len(chunk),
                "shard_digest": payload["shard_digest"],
            })
        sections[section] = {
            "row_count": len(rows),
            "chunk_size": size,
            "section_digest": digest(rows),
            "shards": names,
        }
        manifest[section] = {
            "sharded": True,
            "row_count": len(rows),
            "section_digest": digest(rows),
            "manifest_section": section,
        }

    manifest["shard_manifest"] = {
        "format": "blocker1_t1_v9_lossless_shards_v1",
        "full_fixture_reconstruction": (
            "Load this manifest, replace each sharded section with the ordered "
            "concatenation of rows from its listed shards, and remove shard_manifest."
        ),
        "sections": sections,
    }
    (OUT / "blocker1_t1_v9_fixture_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n"
    )
    print("SHARDED_FIXTURE", {
        "combined_fixture_digest": fixture["combined_fixture_digest"],
        "sections": {k: v["row_count"] for k, v in sections.items()},
        "part_files": sum(len(v["shards"]) for v in sections.values()),
    })

if __name__ == "__main__":
    main()
