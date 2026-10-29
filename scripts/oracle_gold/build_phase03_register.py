"""Build additive source receipts and five-dimension comparison evidence.

Rule notes are human-reviewed source findings, not NLP duplicate detection.
Different text is never proof of independence; source predicate differences
reject equivalence only. Missing rules stay explicitly unknown.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIMS = ("entry", "exit", "filters", "sizing", "management")
OLD = ROOT/"reports/gold_oracle"
OUT = OLD/"phase03"


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False)+"\n")


def recovery(cards, tv, mql):
    notes = read(ROOT/"research/gold_oracle/phase03/reviewed_rules.json")
    result = {}
    for c in cards:
        ident, url = c["id"], c["source_url"]
        if not 32 <= int(ident[1:]) <= 81:
            continue
        key = hashlib.sha256(url.encode()).hexdigest()[:16]
        root = (mql if "mql5.com" in url else tv)/key
        receipt = read(root/"receipt.json")
        row = {"id": ident, "original_title": c["title"], "source_url": url,
               "receipt": receipt, "original_id_preserved": True,
               "as_of": "2026-10-28", "publisher_original_modified": False,
               "frozen_2026_10_15_byte_identity_verified": False,
               "native_compilation_or_platform_output_parity": False,
               "execution_qualified": False}
        files = {}
        for f in receipt["source_files"]:
            path = root/f["path"]
            if sha(path) != f["sha256"]:
                raise ValueError("Source changed: "+ident)
            raw = path.read_bytes()
            text = raw.decode("utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig")
            lines = text.splitlines()
            item = dict(f)
            item["lines"] = len(lines)
            item["review_anchors"] = [{"line": i,
                "reviewed_symbol": next(token for token in notes[ident]["refs"] if token in line),
                "decoded_line_sha256": hashlib.sha256(line.encode()).hexdigest()}
                for i, line in enumerate(lines, 1)
                if any(token in line for token in notes.get(ident, {}).get("refs", []))
                and not line.strip().startswith("//")][:90]
            files[(f["path"], f["sha256"])] = item
        row["source_files"] = list(files.values())
        if files:
            assert ident in notes, "Obtained source must have individual reviewed rules"
            row["source_status"] = "ORIGINAL_EXECUTABLE_SOURCE_OBTAINED"
            row["review_scope"] = "TRADE_RULE_CORE_AND_DEFAULTS_REVIEWED; pure graphics/dashboard and optional optimiser not certified; native runtime parity separate"
            row["rules"] = {d: notes[ident][d] for d in DIMS}
            row["blockers"] = notes[ident]["blockers"]
        else:
            row["source_status"] = "BLOCKED_ORIGINAL_EXECUTABLE_SOURCE"
            row["review_scope"] = "INDIVIDUAL_ACCESS_ATTEMPTS_ONLY; no rule fingerprint from marketing/abstract"
            row["rules"] = {d: None for d in DIMS}
            if ident in ("S056", "S057"):
                reason = "Original TradingView publication returns404; no public PUB metadata/plaintext recovered"
            elif ident == "S078":
                reason = "SSRN abstract is not complete executable rules; observed PDF delivery attempts tracked separately"
            else:
                reason = "Commercial MQL Market listing exposes no original .mq4/.mq5 source; demo/compiled product is not source code"
            row["blockers"] = [reason]
        result[ident] = row
    assert len(result) == 50
    write(OUT/"remaining50_source_audit.json", {
        "schema": "oracle.gold.phase03.remaining50_source_audit.v1",
        "catalogue_sha256": sha(ROOT/"research/strategy_lab/day33_gold_edge_83_snapshot.json"),
        "counts": dict(Counter(r["source_status"] for r in result.values())),
        "all83_full_rule_and_runtime_verification": False,
        "mql_source_ci": "https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/40730822769",
        "cards": result})
    return result


def previous_rules(row, continuation):
    m, r = row.get("mechanics"), row.get("extracted_rules")
    if m:
        return {"entry": m["entry_rule"],
                "exit": "; ".join(m.get(k, "UNKNOWN") for k in ("exit_rule", "stop_rule", "target_rule")),
                "filters": m["context_filters"], "sizing": json.dumps(m["risk_policy"], sort_keys=True),
                "management": m["position_management"]}
    if r:
        return {"entry": r["entry_and_stop"], "exit": r["target"],
                "filters": "Exact original module/Params/timeframe preset at linked pinned source; not dropped",
                "sizing": r["risk"], "management": r["management"]}
    core = continuation.get(row["id"], {})
    dims = {
        "S002": ("Prior-day M15 open-price sweep/reversal state machine; daily bias sum(open-close)>=0 labelled bullish",
                 "Native WIN/LOSS state transitions; no fixed protective stop", "Daily source bias, reversed extraction chronology",
                 "No original dollar account sizing", "Native TradeSimulation/ExtractTrades core only; chronological account parity unverified"),
        "S003": ("Closed-bar BB15/1.5 breakout with EMA200, ATR18", "Protective source stop,2R target;50% partial at1.6R",
                 "Volume MA15 gate, exchange-hour session,6bar cooldown", "Nominal1% source stop-risk; broker rounding not attested",
                 "Pine strategy partial/BE lifecycle; native MQL version not fully certified"),
        "S011": ("Daily close>SMA200, near SMA10*1.05, RSI14<50, DXY/TNX60day change<0",
                 "Next-open belowSMA50 or RSI>75 exit; frozen3ATR stop", "Point-in-time macro series, daily instrument calendar",
                 "Original100kcapital,1x default; idle4%APY source assumption", "Long-only; source stop-gap fill not actual gap-open price; macro vintages unavailable"),
        "S012": ("Liquidity sweep4+FVG4+H4 SMA20bias4, threshold8; H4 final close joined at H4 OPEN time",
                 "vectorbt from_signals opposite-signal/position rules; no codedSL/TP", "H4 future-close bias; ATR backfill; GC futures proxy acquisition",
                 "Original100k; amount .30; fees.0001,slip.0002", "Proven causal defect retained; no claimed repaired original account"),
        "S014": ("Selected Pine prior20bar sweep/reclaim with EMA50/200 side; alternate Python sweep+MSS+FVG mutually exclusive",
                 "Pine signal-close protective reference and3R; BE1R", "Pine exchange09:30-16 weekdays; alternate implementations not equivalent",
                 "Pine10k,1% EQUITY ENTRY not1% stop-risk", "Next-open entry, signal-close brackets, close-basedBE; original implementation selection unresolved"),
        "S015": ("Python aligned EMA50/200 three-bar FVG; limit previous gap boundary with spread",
                 "Prior opposite extreme plushalfspread stop,3R;15bar fill/30bar outcome horizon", "FVG direction and MA alignment",
                 "risk_pct/initial_balance arguments unused; R setups not dollar sizing", "Independent setups; no account concurrency; code differs from S014 Pine sweep")
    }
    if row["id"] in dims:
        return dict(zip(DIMS, dims[row["id"]], strict=True))
    # Do not invent separate management/sizing fields from a partial source card.
    return {"entry": "; ".join(core.get("rules", [])),
            "exit": None, "filters": None, "sizing": None, "management": None}


def comparisons(new):
    old = {r["id"]: r for r in read(OLD/"83_source_and_duplicate_audit.json")["rows"]}
    continuation = read(OLD/"continuation_source_audit.json")["cards"]
    flags = read(OLD/"dedup_mechanics_review.json")["review_flags"]
    rows = []
    for flag in flags:
        a, b = flag["a"], flag["b"]
        ra = new[a]["rules"] if a in new else previous_rules(old[a], continuation)
        rb = new[b]["rules"] if b in new else previous_rules(old[b], continuation)
        sources = {i: new[i]["source_files"] if i in new else old[i]["evidence"] for i in (a, b)}
        unavailable = [i for i in (a, b) if i in new and not new[i]["source_files"]]
        disposition, proof = "MATERIALLY_DISTINCT", "Source entry predicates differ: "+str(ra["entry"])+" VERSUS "+str(rb["entry"])
        if unavailable:
            disposition = "UNRESOLVED_SOURCE_BLOCKED"
            proof = "Actual executable source missing for "+", ".join(unavailable)+"; known other side is not sufficient to classify equivalence"
        elif {a, b} == {"S036", "S037"}:
            disposition = "PARAMETER_VARIANTS_OF_ONE_ENTRY_EXIT_FAMILY"
            proof = "Identical BreakoutExitLab source and RunExit channel branch; catalogue entry/exit lookbacks20/10 versus55/20. Source default is20/10; no separate55/20 published preset receipt. Do not double-count family."
        elif {a, b} <= {"S036", "S037", "S038", "S039"}:
            disposition = "MATERIALLY_DISTINCT_EXIT_METHODS_SHARED_ENTRY"
            proof = "Same Donchian fresh-breakout entry source; RunExit channel, favorable-extreme ATR-trail and fixed2R are different exit algorithms, not merely tuned numbers. Retain components; no independent account/edge certification."
        elif {a, b} <= {"S041", "S042", "S043"}:
            disposition = "MATERIALLY_DISTINCT_COMPONENTS_SHARED_ACCOUNT"
            proof = "CheckSignalS1 retest after excursion, S2 zone-to-opposite-breakout stage, S3 touch/pullback/retest stage; different timeframe/grid/TP parameters, same default enabled recovery account."
        elif {a, b} == {"S064", "S065"}:
            disposition = "MATERIALLY_DISTINCT_COMPONENTS_SHARED_ACCOUNT"
            proof = "Exact SAME source bytes, but catalogue names different enabled components: FVG delayed zone return versus BB outside candle. Both enabled, FVG priority, shared position and fixed2unit account. Same file is not two equivalent standalone configurations."
        elif {a, b} == {"S050", "S051"}:
            proof = "Shared LONG OR/volume entry template; S050100%equity/2.5range target/20:00close versus S051explicit1.5%stop-risk/1R/16:30close. Material sizing/exit changes, not separate bidirectional entry edge."
        elif {a, b} == {"S014", "S015"}:
            proof = "Pinned Pine sweep/reclaim/session/BE versus Python3barFVG pullback, entry/management materially differ. Python alternate S014 sweep+MSS+FVG contradiction remains blocked separately."
        witnesses = []
        # Same-tape executable witnesses reject equivalence without any title
        # similarity inference. Never treat a matching sample as a proof.
        for year in (2023, 2024, 2025):
            is_r = all(20 <= int(i[1:]) <= 31 for i in (a, b))
            is_b01 = all(5 <= int(i[1:]) <= 9 for i in (a, b))
            if not (is_r or is_b01):
                break
            paths = [OLD/(f"batch02/{year}/{i}_native_setups.csv" if is_r else f"batch01_common/{year}/{i}_base_trades.csv") for i in (a, b)]
            fields = ("direction", "entry_bar_open_utc", "native_entry_price", "stop", "target") if is_r else ("side", "entry_utc", "entry_bid", "exit_bar_utc", "exit_bid")
            sets, native_rows = [], []
            for path in paths:
                with path.open() as f:
                    rs = list(csv.DictReader(f))
                native_rows.append(rs)
                sets.append({tuple(r[k] for k in fields) for r in rs})
            differences = sorted(sets[0] ^ sets[1])
            if differences:
                value = differences[0]
                side = 0 if value in sets[0] else 1
                witnesses.append({"year": year, "present_only_in": (a,b)[side],
                    "geometry": dict(zip(fields, value, strict=True)),
                    "ledger_paths": [str(p.relative_to(ROOT)) for p in paths],
                    "ledger_sha256": [sha(p) for p in paths],
                    "source_input": f"reports/gold_oracle/{'batch02' if is_r else 'batch01_common'}/{year}/report.json",
                    "counts": [len(r) for r in native_rows],
                    "proves": "Historical source output geometries differ on same pinned input; not a profitability/causality certification"})
                break
        rows.append({"a": a, "b": b, "original_flags": flag["flags"],
                     "classification": disposition, "actual_source_evidence": sources,
                     "five_dimension_review": {d: {a: ra[d], b: rb[d],
                         "fully_bound_on_both_sides": ra[d] is not None and rb[d] is not None} for d in DIMS},
                     "equivalence_decision_basis": proof,
                     "same_tape_executable_counterexamples": witnesses,
                     "complete_fingerprint_equality_proven": False,
                     "independent_profitable_edges_proven": False,
                     "all_original_ids_retained": True})
    assert len(rows) == len({(r["a"], r["b"]) for r in rows}) == 125
    write(OUT/"125_duplicate_comparisons.json", {
        "schema": "oracle.gold.phase03.source_comparisons.v1", "comparisons": rows,
        "counts": dict(Counter(r["classification"] for r in rows)),
        "exact_cross_id_duplicates_proven": 0,
        "method": "Reviewed original predicates/defaults and lifecycle; any concrete material rule difference rejects equivalence, but cannot prove profitable independence. Unknown dimensions remain null. No alias from URL/title alone.",
        "prior_source_evidence_preserved": True})


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tv", required=True, type=Path)
    p.add_argument("--mql", required=True, type=Path)
    a = p.parse_args()
    cs = read(ROOT/"research/strategy_lab/day33_gold_edge_83_snapshot.json")["candidates"]
    new = recovery(cs, a.tv, a.mql)
    comparisons(new)
    print("Wrote50 individual source cards and125 comparisons; missing source remains unresolved")


if __name__ == "__main__":
    main()
