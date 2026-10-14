"""Research-only reproducibility gate for immutable GT-BIBLE 2.0 RC1.

Loads a separately checked-out exact GoldThinker commit; checks all manifest hashes
in an independent SHA-256 implementation and verifies 43 pinned golden decision
cases against the reference code. This is NOT an independent port/parity engine
and NOT a historical AIDY strategy backtest.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path

COMMIT = "a15ec4cec1c8c0f06e53befe4b22b55c75da000c"
BUNDLE = "5dd0fdd440d673f358887b490f4b411f059b0fcc0b6955655da7796cc3394c80"


def digest(obj: object) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def main() -> None:
    gt = Path("goldthinker_ref")
    if not gt.is_dir():
        raise SystemExit("GoldThinker pinned checkout missing")
    head = os.popen("git -C goldthinker_ref rev-parse HEAD").read().strip()
    if head != COMMIT:
        raise SystemExit("Wrong GoldThinker commit; frozen RC1 cannot be tested")
    idx = json.loads((gt / "bible/INDEX.json").read_text(encoding="utf-8"))
    if idx["bundle_sha256"] != BUNDLE:
        raise SystemExit("Published bundle hash mismatch")
    mhash = {}
    for item in idx["manifests"]:
        path = gt / item["file"]
        manifest = json.loads(path.read_text(encoding="utf-8"))
        h = digest(manifest)
        if h != item["sha256"]:
            raise SystemExit(f"Manifest SHA mismatch: {item['manifest_id']}")
        mhash[item["manifest_id"]] = h
    if digest(mhash) != BUNDLE:
        raise SystemExit("Recomputed bundle SHA mismatch")
    import sys
    sys.path.insert(0, str((gt / "src").resolve()))
    from goldthinker.bible.decide import decide
    ms = {item["manifest_id"]: json.loads((gt / item["file"]).read_text()) for item in idx["manifests"]}
    common = ms["GT-BIBLE-COMMON"]
    executed = []
    by_manifest = {}
    for f in sorted((gt / "bible/golden").glob("*.json")):
        bundle = json.loads(f.read_text())
        m = ms[bundle["manifest_id"]]
        for v in bundle["vectors"]:
            outcome = decide(m,common,v["snapshot"])
            expected = v["expect"]
            if outcome["decision"] != expected["decision"] or outcome["reasons"] != expected["reasons"]:
                raise SystemExit(f"Golden mismatch {v['id']}: {outcome['decision']}/{outcome['reasons']}")
            for k in ("arm","level_sources","failing_clauses"):
                if k in expected and outcome.get(k) != expected[k]:
                    raise SystemExit(f"Golden mismatch {v['id']}: {k}")
            if "order" in expected:
                for k,val in expected["order"].items():
                    if outcome["order"][k] != val:
                        raise SystemExit(f"Golden mismatch {v['id']}: order.{k}")
            if "valid_bars" in expected and outcome["order"]["valid_bars"] != expected["valid_bars"]:
                raise SystemExit(f"Golden mismatch {v['id']}: valid_bars")
            if "target_source" in expected and outcome["order"]["target_source"] != expected["target_source"]:
                raise SystemExit(f"Golden mismatch {v['id']}: target_source")
            executed.append(v["id"])
            by_manifest[m["manifest_id"]] = by_manifest.get(m["manifest_id"], 0)+1
    if len(executed) != 43 or len(set(executed)) != 43 or len(ms) != 10:
        raise SystemExit(f"Unexpected manifests/vectors {len(ms)}, {len(executed)}, {len(set(executed))}")
    result={"status":"PASS_RC1_GOLDEN_REFERENCE_NOT_INDEPENDENT_IMPLEMENTATION",
            "goldthinker_commit": COMMIT, "rule_bundle_sha256": BUNDLE,
            "manifests":len(ms),"golden_count":len(executed),"golden_ids_sha256":digest(executed),
            "by_manifest":dict(sorted(by_manifest.items())),
            "limitations":["Golden cases are mostly precomputed context snapshots, NOT as-of raw market replay","Reference decision code is used for expected comparison, NOT independently reimplemented","No broker-clock candle aggregation, historical setup census, fill or PnL tests here"]}
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/goldthinker_rc1_golden_gate.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(result,sort_keys=True))

if __name__ == "__main__":
    main()
