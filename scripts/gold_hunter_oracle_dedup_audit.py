"""Conservative preflight for the 83 AIDY GoldThinker strategy leads.

Discovery text and common source URLs are NEVER sufficient to declare that
two trading systems have identical code, entry rules or backtest outcomes.
This tool produces REVIEW flags, with optional source-audited rule signatures
that can establish exact/parameter-variant relationships. It places no orders.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from difflib import SequenceMatcher
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "research/strategy_lab/day33_gold_edge_83_snapshot.json"
OUTPUT = ROOT / "artifacts/gold_hunter/oracle_dedup_review.json"

STOPWORDS = frozenset({
    "gold", "xauusd", "ea", "bot", "strategy", "system", "research", "lab",
    "trader", "trading", "v", "tv", "mt4", "mt5", "mql5", "break", "with",
    "and", "plus", "the", "in", "after", "first", "multi", "phase",
    "apex", "test", "follow", "mode", "of", "for", "at",
})
METHOD_WORDS = frozenset({
    "ema", "sma", "rsi", "adx", "dmi", "bollinger", "vwap", "fvg",
    "breakout", "orb", "asian", "london", "ny", "liquidity", "sweep",
    "reversal", "donchian", "channel", "turtle", "trend", "pullback",
    "momentum", "range", "retest", "order", "block", "support", "resistance",
    "supply", "demand", "supertrend", "mean", "keltner", "ict", "smc",
    "false", "gap", "ma", "grid", "volatility",
})
# Exact/variant signatures MUST be independently audited from actual rules,
# not inferred from names. Required fields deliberately include execution.
CORE_FIELDS = (
    "instrument", "timeframe", "direction", "entry_rule",
    "entry_order", "context_filters", "exit_rule", "stop_rule",
    "target_rule", "position_management", "signal_clock",
)
SIG_FIELDS = (*CORE_FIELDS, "parameters", "risk_policy")


def canonical_source(value: str) -> str:
    s = str(value or "").strip()
    return s.lower().rstrip("/").removesuffix(".git")


def words(title: str) -> set[str]:
    normalized = re.sub(r"[^a-z0-9]+", " ", title.lower())
    return {v for v in normalized.split() if len(v) > 1 and v not in STOPWORDS}


def identity(item: dict) -> tuple:
    return (item["id"], item["title"], canonical_source(item["source_url"]))


def digest(data: object) -> str:
    return sha256(json.dumps(
        data, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def validated_signatures(raw: dict, known_ids: set[str]) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("Audited signature data must be keyed by S###")
    result = {}
    for ident, entry in raw.items():
        if ident not in known_ids or not isinstance(entry, dict):
            raise ValueError(f"Unknown/malformed audited system: {ident}")
        if set(entry) != {"source_commit_sha", "mechanics", "evidence_uri"}:
            raise ValueError(f"Malformed audited evidence: {ident}")
        if not re.fullmatch(r"[a-f0-9]{40}", entry["source_commit_sha"]):
            raise ValueError("Only source-pinned audited code is admissible")
        if not str(entry["evidence_uri"]).startswith("https://"):
            raise ValueError("Independent source audit evidence URI missing")
        m = entry["mechanics"]
        if not isinstance(m, dict) or set(m) != set(SIG_FIELDS):
            raise ValueError(f"Incomplete rule specification: {ident}")
        for key in SIG_FIELDS:
            if m[key] is None or m[key] == "" or m[key] == [] or m[key] == {}:
                raise ValueError(f"Missing original rule mechanic {ident}.{key}")
        # AIDY native source, original rule and code audit remain separate
        # evidence gates. No fuzzy title match can manufacture this signature.
        result[ident] = entry
    return result


def audit(catalog: dict, signatures: dict | None = None) -> dict:
    candidates = catalog.get("candidates")
    if (catalog.get("schema") != "aidy.strategy_lab.gold_edge_frozen_catalogue.v1"
            or not isinstance(candidates, list)
            or len(candidates) != 83
            or {x["id"] for x in candidates}
            != {f"S{i:03d}" for i in range(1, 84)}):
        raise ValueError("Original AIDY 83-source catalogue is not intact")
    by_id = {x["id"]: x for x in candidates}
    sigs = validated_signatures(signatures or {}, set(by_id))

    by_url = defaultdict(list)
    for x in candidates:
        by_url[canonical_source(x["source_url"])].append(x["id"])
    shared_sources = [{
        "source_url": src,
        "ids": sorted(ids),
        "candidate_count": len(ids),
        "classification": "SHARED_SOURCE_NOT_PROOF_OF_DUPLICATE",
    } for src, ids in sorted(by_url.items()) if len(ids) > 1]

    review_pairs = []
    confirmed_pairs = []
    for a, b in combinations(sorted(by_id), 2):
        x, y = by_id[a], by_id[b]
        same_url = canonical_source(x["source_url"]) == canonical_source(y["source_url"])
        wx, wy = words(x["title"]), words(y["title"])
        joint = wx | wy
        jaccard = len(wx & wy) / len(joint) if joint else 0
        methods = sorted(wx & wy & METHOD_WORDS)
        ratio = SequenceMatcher(None, " ".join(sorted(wx)), " ".join(sorted(wy))).ratio()

        evidence = []
        if a in sigs and b in sigs:
            core_x = {k:sigs[a]["mechanics"][k] for k in CORE_FIELDS}
            core_y = {k:sigs[b]["mechanics"][k] for k in CORE_FIELDS}
            full_x, full_y = sigs[a]["mechanics"], sigs[b]["mechanics"]
            if full_x == full_y:
                evidence.append("AUDITED_FULL_MECHANICS_EQUAL")
                confirmed_pairs.append({
                    "a": a, "b": b, "classification": "AUDITED_EXACT_MECHANICS",
                    "mechanics_sha256": digest(full_x),
                    "audit_urls": [sigs[a]["evidence_uri"], sigs[b]["evidence_uri"]],
                    "action": "REVIEW_FOR_ONE_CANONICAL_STRATEGY",
                })
            elif core_x == core_y:
                evidence.append("AUDITED_ENTRY_EXIT_CORE_EQUAL")
                confirmed_pairs.append({
                    "a": a, "b": b, "classification": "AUDITED_PARAMETER_OR_RISK_VARIANT",
                    "mechanics_core_sha256": digest(core_x),
                    "audit_urls": [sigs[a]["evidence_uri"], sigs[b]["evidence_uri"]],
                    "action": "GROUP_AS_VERSION_FAMILY_NOT_TWO_INDEPENDENT_EDGES",
                })
            elif same_url or jaccard >= .65:
                evidence.append("AUDITED_MECHANICS_DIFFER")
        if same_url:
            evidence.append("SAME_UPSTREAM_URL_ONLY")
        if jaccard >= .65:
            evidence.append("SIMILAR_DESCRIPTION_ONLY")
        if len(methods) >= 2:
            evidence.append("SHARED_METHOD_WORDS_ONLY")
        if evidence:
            review_pairs.append({
                "a": a, "b": b, "flags": evidence,
                "same_source_url": same_url, "title_jaccard": round(jaccard, 4),
                "description_similarity": round(ratio, 4),
                "shared_method_words": methods,
                "cannot_assert_duplicate_without_source_audit": not any(
                    flag.startswith("AUDITED_FULL_") or
                    flag.startswith("AUDITED_ENTRY_EXIT_") for flag in evidence),
            })
    review_pairs.sort(key=lambda p: (
        not bool(set(p["flags"]) & {
            "AUDITED_FULL_MECHANICS_EQUAL",
            "AUDITED_ENTRY_EXIT_CORE_EQUAL",
        }),
        not p["same_source_url"], -p["title_jaccard"], p["a"], p["b"],
    ))
    return {
        "schema": "oracle.gold.83.conservative_dedup.v1",
        "source_catalog_date_utc": catalog.get("frozen_date_utc"),
        "catalogue_sha256": digest(catalog),
        "candidates": len(candidates),
        "distinct_upstream_urls": len(by_url),
        "source_reuse_excess_references": len(candidates) - len(by_url),
        "shared_source_groups": shared_sources,
        "shared_source_groups_count": len(shared_sources),
        "source_audited_rule_signatures_count": len(sigs),
        "audited_equivalence_pairs": confirmed_pairs,
        "review_flags_count": len(review_pairs),
        "review_flags": review_pairs,
        "status": "DISCOVERY_PRECHECK_NEEDS_SOURCE_PARITY_AND_TRADE_OVERLAP",
        "automatic_deletion_or_promotion": False,
        "live_trading_changes": 0,
        "instructions": [
            "Same GitHub URL does NOT imply same strategy",
            "Title tokens do NOT prove executable rule equivalence",
            "Same audited full mechanics = review canonical duplicate",
            "Same audited core, changed parameters/risk = parameter variant",
            "Different rules can still be portfolio-correlated: compare signal event "
            "timings and returns across the identical original AIDY archives",
            "Retain all original IDs, losing outcomes and links; never delete evidence",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--audited-signatures", type=Path)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    source = json.loads(args.catalog.read_text(encoding="utf-8"))
    audits = json.loads(args.audited_signatures.read_text(encoding="utf-8")) if args.audited_signatures else None
    report = audit(source, audits)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("ORACLE_GOLD_DEDUP_PRECHECK", json.dumps({
        "candidates": report["candidates"],
        "unique_upstream_urls": report["distinct_upstream_urls"],
        "source_url_reuse": report["source_reuse_excess_references"],
        "source_review_groups": report["shared_source_groups_count"],
        "audited_mechanics": report["source_audited_rule_signatures_count"],
        "possible_review_pairs": report["review_flags_count"],
        "confirmed_rule_pairs": len(report["audited_equivalence_pairs"]),
        "status": report["status"],
        "no_broker_orders": True,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
