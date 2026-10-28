"""Attach bounded code-reading receipts without discarding earlier experiments."""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import subprocess
from pathlib import Path

from scripts.oracle_gold.batch01 import blob
from scripts.oracle_gold.build_register import write_register_csv
from scripts.oracle_gold.history import digest

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/"reports/gold_oracle"


def strategy_class_without_params(text):
    tree = ast.parse(text)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    params = next(n for n in cls.body if isinstance(n, ast.Assign)
                  and any(isinstance(x, ast.Name) and x.id == "params" for x in n.targets))
    values = dict(ast.literal_eval(params.value))
    cls = copy.deepcopy(cls)
    cls.body = [n for n in cls.body if not (isinstance(n, ast.Assign)
                and any(isinstance(x, ast.Name) and x.id == "params" for x in n.targets))]
    return values, ast.dump(cls, include_attributes=False)


def compare_s016(root):
    paths = ("strategies/gold_donchian_channel_strategy.py", "src/gold_donchian_channel_strategy.py")
    a, b = [strategy_class_without_params((root/p).read_text()) for p in paths]
    if a[1] != b[1]:
        raise ValueError("S016 class mechanics changed beyond parameters")
    changes = {k: [a[0][k], b[0][k]] for k in a[0] if a[0][k] != b[0][k]}
    if changes != {"entry_period": [20, 95], "risk_percent": [1., 2.]}:
        raise ValueError("S016 parameter variants changed")
    return {"original_id": "S016", "source_paths": paths, "scope": "STRATEGY_CLASS_ONLY",
            "classification": "PROVEN_WITHIN_ID_PARAMETER_VARIANTS", "parameter_changes": changes,
            "class_ast_excluding_params_sha256": hashlib.sha256(a[1].encode()).hexdigest(),
            "full_program_identity_claimed": False, "additional_independent_original_ids": 0}


def record(source_root):
    cards = json.loads((ROOT/"research/gold_oracle/continuation_rule_cards.json").read_text())
    register_path = OUT/"83_source_and_duplicate_audit.json"
    register = json.loads(register_path.read_text())
    expected = register.pop("sha256")
    if digest(register) != expected:
        raise ValueError("Original 83 register tampered")
    by_id = {r["id"]: r for r in register["rows"]}
    for ident, card in cards.items():
        row = by_id[ident]
        url, commit = row["source_url"], row["source_commit_sha"]
        repo = source_root/hashlib.sha256(url.encode()).hexdigest()[:16]/"repo"
        actual = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        if actual != commit:
            raise ValueError("Publisher commit changed: "+ident)
        refs = []
        for path in card["source_files"]:
            content = (repo/path).read_bytes()
            expected_blob = subprocess.check_output(["git", "-C", str(repo), "rev-parse", f"{commit}:{path}"], text=True).strip()
            if blob(content) != expected_blob:
                raise ValueError("Dirty publisher source: "+path)
            refs.append({"path": path, "git_blob": expected_blob,
                         "sha256": hashlib.sha256(content).hexdigest(),
                         "url": url+f"/blob/{commit}/"+path.replace(" ", "%20")})
        row["continuation_audit"] = {**card, "source_commit": commit, "source_refs": refs,
            "full_mechanics_audit": False, "execution_qualified": False,
            "source_original_modified": False, "score": None}
    row16 = by_id["S016"]
    repo16 = source_root/hashlib.sha256(row16["source_url"].encode()).hexdigest()[:16]/"repo"
    variants = compare_s016(repo16)
    packet = {"schema": "oracle.gold.continuation.source_read.v1", "cards": {
        ident: by_id[ident]["continuation_audit"] for ident in cards},
        "within_id_parameter_variant_evidence": [variants],
        "cross_id_comparisons": [
            {"a": "S014", "b": "S015", "classification": "RELATED_DISTINCT_ENTRY_AND_MANAGEMENT",
             "evidence": "Pine sweep/reclaim with session and BE versus Python three-bar FVG pullback; shared repo does not make parameter variants",
             "complete_fingerprints_available": False},
            {"a": "S005", "b": "S016", "classification": "MATERIAL_RULE_DIFFERENCES_RETAIN_BOTH",
             "evidence": "S005 H1 high/low channels, EMA200, two-sided and ATR protective stop; S016 daily close channels, long-only, no protective stop",
             "complete_fingerprints_available": False}],
        "all83_fully_audited": False, "independent_edges_certified": 0,
        "note": "File hashes prove inspected source identity, not completeness of this explicitly bounded semantic review"}
    packet["sha256"] = digest(packet)
    (OUT/"continuation_source_audit.json").write_text(json.dumps(packet, indent=2, sort_keys=True)+"\n")
    register["coverage"]["continuation_bounded_source_cards"] = len(cards)
    register["coverage"]["proven_within_id_variant_families"] = 1
    register["sha256"] = digest(register)
    register_path.write_text(json.dumps(register, indent=2, sort_keys=True)+"\n")
    write_register_csv(register["rows"])
    print("CONTINUATION_AUDIT", len(cards), "bounded cards; S016 class variant proven; no new IDs")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source-root", required=True, type=Path)
    record(p.parse_args().source_root)


if __name__ == "__main__":
    main()
