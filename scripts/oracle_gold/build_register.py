"""83 retained identities; audited mechanics separated from unresolved source leads."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.gold_hunter_oracle_dedup_audit import audit
from scripts.oracle_gold.batch01 import APEX_COMMIT, CASES, S010_COMMIT
from scripts.oracle_gold.history import digest

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/gold_oracle"
APEX = "https://github.com/sbrakni/MQL5-trading-bot-claude-experiment"
SWEEP = "https://github.com/baturdenada/gold-sweep-backtester"
SWEEP_COMMIT = "39dbb6ec67ad772f778bf30f4a0ada741e08bef4"
EXTRACTED = {
    "S020": ("liquidity_imbalance", "Confirmed swing -> wick sweep/reclaim -> prefer nearby opposite-colour OB else aligned FVG; first pullback fill; stop beyond sweep/zone plus buffer", "Zone impulse confirmation time can postdate zone.end_index; full causal gate required"),
    "S021": ("prev_day_breakout", "First close beyond prior-day high/low; entry recorded at broken level; stop beyond signal candle extreme; one attempt each side/day", "NONCAUSAL_FILL: close confirmation then retroactive intrabar level entry"),
    "S022": ("orb", "Fixed 14:30 UTC opening range; count 3 M5 or 1 M15/M30/H1/H4; first close beyond range; level entry; opposing range edge stop; one each side/day", "NONCAUSAL_FILL: close confirmation then retroactive level fill; fixed EST differs from DST NY"),
    "S023": ("rsi_reversal", "RSI14 crosses above30 after oversold -> long; crosses below70 after overbought -> short; signal close entry; signal extreme plus buffer stop", "Close-price fill after close confirmation is conditional; bid/ask/account sizing absent"),
    "S024": ("support_resistance", "Cluster all swing prices within max(2*min_fvg,2*buffer), >=2 touches; zone ready after last member pivot+strength+1; first close rejection; zone edge stop", "Full-series clustering changes prior zones with appended future swings; prefix stability unproven"),
    "S025": ("momentum_breakout", "Prior max(5,ema_fast) high/low close break and candle range >= prior average; signal-close entry; candle opposite edge stop; lookback-bar cooldown", "Conditional close fill; no authenticated account/quote replay"),
    "S026": ("momentum_pullback", "EMA50 trend; two opposite-colour candles then directional candle closes past prior high/low; entry close; stop beyond two-bar pullback", "Conditional close fill; account/risk sizing unspecified"),
    "S027": ("ict_fvg", "Three-bar gap strictly > min_fvg; first proximal-edge touch strictly after third bar within pullback_window; opposite gap edge buffered stop", "first_touch lacks both-sided limit reach/gap-price checks; quote chronology required"),
    "S028": ("ict_ifvg", "FVG close-through flips polarity; first subsequent retest within window, long at top/short at bottom; opposite buffered edge stop", "first_touch quote/gap conditions and chronological protective exits unverified"),
    "S029": ("ict_order_block", "Confirmed structure break BOS/CHoCH; last opposite candle among event and five prior; next-window first touch of OB high/low; buffered opposite edge stop", "Source outputs independent overlapping setups; no account-level risk semantics"),
    "S030": ("smart_money", "Sweep then first CHoCH in reversal direction within pullback_window; last opposite candle in six-bar search; retrace; stop beyond OB and sweep", "Shared zone/limit/gap chronology unverified; full account model absent"),
    "S031": ("supply_demand", "Departure range >=1.5 prior average and body >=60% range; prior base edge first retest within window; stop beyond base plus buffer", "Source code does NOT require base itself quiet despite docstring; no account or broker semantics"),
}


def apex_card(ident):
    _method, params, ep = CASES[ident]
    common = {"instrument": "XAUUSD research target; author gold input GC=F proxy",
        "timeframe": "H1", "direction": "LONG_AND_SHORT", "entry_order": "NEXT_AVAILABLE_H1_OPEN_MARKET_BID_PROXY",
        "signal_clock": "Completed H1; UTC session clock", "position_management":
        "One position; source stop-first OHLC, gap stops; close-bar exit; EOD force close; source c[i] sizing defect",
        "target_rule": "NONE", "parameters": params,
        "risk_policy": {"risk_pct": 1., "start_equity": 10000., "max_leverage": 20.,
                        "lot_quantization": "NONE_FLOAT_OUNCES", "engine_overrides": ep}}
    lines = {"S005": 73, "S006": 56, "S007": 93, "S008": 107, "S009": 119}
    rules = {
        "S005": ("Close exceeds previous24 high/low", "EMA200 side agreement", "Close breaks opposite previous12 channel", "Wilder ATR14 x2.5 entry frozen"),
        "S006": ("EMA9 crosses EMA120; ADX14>=20", "ADX evaluated on crossover bar", "Opposite filtered cross reversal; trail", "Wilder ATR14 x2 initial; close-bar3.5ATR trail"),
        "S007": ("Close < BB lower and RSI2<15 long; upper and RSI2>85 short", "BB20 population SD multiplier2", "Long close>=BB mid; short close<=mid", "Wilder ATR14 x2 entry frozen"),
        "S008": ("Close>EMA100 and RSI2<10 long; close<EMA100 and RSI2>90 short", "EMA100 side agreement", "Long RSI2>55; short RSI2<45", "Wilder ATR14 x1.5 entry frozen"),
        "S009": ("First close beyond built 00<=UTC hour<06 range; entry06<=hour<12", "Once per side/day; original Python accepts observed incomplete range", "Close bar hour>=21, original Python timing differs MQL", "Wilder ATR14 x3 entry frozen"),
    }
    entry, context, exit_rule, stop = rules[ident]
    m = {**common, "entry_rule": entry, "context_filters": context, "exit_rule": exit_rule, "stop_rule": stop}
    return {"source_commit_sha": APEX_COMMIT, "mechanics": m,
        "evidence_uri": f"{APEX}/blob/{APEX_COMMIT}/research/strategies.py#L{lines[ident]}",
        "source_refs": [f"{APEX}/blob/{APEX_COMMIT}/research/engine.py#L160",
                        f"{APEX}/blob/{APEX_COMMIT}/research/optimize.py#L39"],
        "licence": "NO_LICENCE_FILE_AT_PIN; redistribution/commercial use UNQUALIFIED",
        "source_audit_scope": "FULL_SELECTED_PY_RULES_REVIEWED; NOT_NATIVE_MQL_PARITY",
        "selection": "FIRST_SOURCE_GRID_COMBINATION_NOT_UNIQUE_GOLD_PRESET" if ident in ("S007", "S008") else "EXISTING_FROZEN_SOURCE_PRESET",
        "blocker": "GAP-APEX-ENTRY-SIZING-LOOKAHEAD"}


def cards():
    result = {i: apex_card(i) for i in CASES}
    url = f"https://github.com/AluminumShark/Tick-Backtest/blob/{S010_COMMIT}"
    result["S010"] = {"source_commit_sha": S010_COMMIT,
        "evidence_uri": url+"/src/strategy.py#L13", "source_refs": [url+"/main.py#L22", url+"/src/backtest_engine.py#L116"],
        "licence": "MIT source LICENSE inspected; historical data rights separately unqualified",
        "source_audit_scope": "ORIGINAL_SIGNAL_PARITY; ACCOUNTING_MODELS_DIFFER",
        "selection": "MAIN_PY_PUBLISHED_CONFIG_NOT_CLASS_DEFAULT20_50",
        "blocker": "GAP-NATIVE-ENGINE-ACCOUNTING-AND-BROKER-PARITY",
        "mechanics": {"instrument": "XAUUSD", "timeframe": "H1", "direction": "LONG_ONLY",
            "entry_rule": "SMA12>SMA34 after previous<= and RSI14<70", "entry_order": "Publisher close reference; AIDY separately modelled next H1 open",
            "context_filters": "RSI14 adjusted pandas EWM com13,min_periods14", "exit_rule": "SMA12<SMA34 after previous>= and RSI14>30; flat otherwise maintain state",
            "stop_rule": "NONE_IN_SOURCE", "target_rule": "NONE_IN_SOURCE",
            "position_management": "Long/flat, no protective stop; publisher bar-return leverage accounting differs AIDY fixed units",
            "signal_clock": "Completed H1", "parameters": {"sma_fast": 12, "sma_slow": 34, "rsi": 14, "buy_rsi_below": 70, "sell_rsi_above": 30},
            "risk_policy": {"leverage": 3.28, "initial_usd": 10000., "financing_margin": "UNSPECIFIED"}}}
    return result


def main():
    cat = json.loads((ROOT/"research/strategy_lab/day33_gold_edge_83_snapshot.json").read_text())
    access = json.loads((OUT/"source_access_receipts.json").read_text())
    by_url = {r["source_url"]: r for r in access}
    reviewed = cards()
    signatures = {i: {k: c[k] for k in ("source_commit_sha", "mechanics", "evidence_uri")} for i, c in reviewed.items()}
    dedup = audit(cat, signatures)
    rows = []
    for candidate in cat["candidates"]:
        ident = candidate["id"]
        receipt = by_url[candidate["source_url"]]
        card = reviewed.get(ident)
        row = {"id": ident, "original_title": candidate["title"], "source_url": candidate["source_url"],
            "source_access": receipt["access"], "source_commit_sha": receipt.get("source_commit"),
            "source_audit_status": "SOURCE_CODE_RETRIEVED_REVIEW_PENDING" if receipt.get("source_commit") else "SOURCE_UNVERIFIABLE",
            "disposition": "DISCOVERED", "family": None, "canonical_id": ident,
            "duplicate_classification": "UNKNOWN", "independence": "NOT_PROVEN",
            "complete_mechanics_sha256": None, "mechanics": None,
            "licence": "UNVERIFIED", "evidence": [], "blockers": [],
            "batch": None, "historical_reports": [], "score": None, "orders": 0}
        if card:
            row.update(source_audit_status=card["source_audit_scope"], disposition="SOURCE_AUDITED",
                       family=f"REVIEWED_METHOD_{ident}", source_commit_sha=card["source_commit_sha"],
                       complete_mechanics_sha256=digest(card["mechanics"]), mechanics=card["mechanics"],
                       licence=card["licence"], evidence=[card["evidence_uri"], *card["source_refs"]],
                       blockers=[card["blocker"], "NATIVE_BROKER_AND_SEALED_OOS_UNQUALIFIED"],
                       batch="B01", selection=card["selection"])
        elif ident in EXTRACTED:
            method, rule, blocker = EXTRACTED[ident]
            row.update(source_audit_status="RULE_MODULE_AND_DEPENDENCIES_REVIEWED_INCOMPLETE_ACCOUNT_SPEC",
                source_commit_sha=SWEEP_COMMIT, disposition="UNTESTABLE", family=f"REVIEWED_METHOD_{ident}",
                evidence=[f"{SWEEP}/blob/{SWEEP_COMMIT}/src/sweepbt/strategies/{method}.py#L1",
                          f"{SWEEP}/blob/{SWEEP_COMMIT}/src/sweepbt/params.py#L13",
                          f"{SWEEP}/blob/{SWEEP_COMMIT}/src/sweepbt/simulate.py#L75"],
                extracted_rules={"module": method, "entry_and_stop": rule,
                    "target": "entry +/- abs(entry-stop)*Params.rr, default2",
                    "management": "Each setup independent; stop-first samebar; no account/netting/margin model",
                    "timeframe": "MULTI_TIMEFRAME_PRESETS; no uniquely selected catalogue timeframe",
                    "parameters": "Exact Params dataclass and timeframe preset at linked commit",
                    "risk": "STOP_DISTANCE_AND_R_MULTIPLE_ONLY; no equity sizing/fees"},
                blockers=[blocker, "NO_UNIQUE_TIMEFRAME_OR_ACCOUNT_SIZING; complete fingerprint withheld"])
        else:
            row["blockers"] = ["Full source semantics not yet audited" if receipt.get("source_commit") else
                               "Executable source not retrieved; page text/403 cannot substitute for code"]
        if ident in ("S001", "S002", "S003", "S004", "S005", "S006", "S010"):
            row["historical_reports"] = sorted(str(p.relative_to(ROOT)) for p in (ROOT/"research/strategy_lab").glob(ident+"*.md"))
            row["prior_evidence_preserved"] = True
        rows.append(row)
    packet = {"schema": "oracle.gold.original83.source_register.v1", "status": "PARTIAL_AUDIT_EXPLICIT_GAPS",
        "original_catalogue_sha256": dedup["catalogue_sha256"], "rows": rows,
        "coverage": {"ids_retained": 83, "upstream_urls_attempted": len(access),
            "selected_rule_cards": len(reviewed), "additional_rule_modules_reviewed": len(EXTRACTED),
            "proven_exact_duplicates": 0, "proven_parameter_variant_pairs": 0,
            "independent_edges_certified": 0, "all83_fully_audited": False},
        "qualification": "NO_STRATEGY_ADMITTED; UNKNOWN IS NOT NEGATIVE_PERFORMANCE"}
    packet["sha256"] = digest(packet)
    (OUT/"83_source_and_duplicate_audit.json").write_text(json.dumps(packet, sort_keys=True, indent=2)+"\n")
    with (OUT/"83_source_and_duplicate_audit.csv").open("w", newline="") as f:
        fields = ["id", "original_title", "source_url", "source_access", "source_commit_sha", "source_audit_status", "disposition", "family", "canonical_id", "duplicate_classification", "independence", "complete_mechanics_sha256", "licence", "batch", "evidence", "blockers", "historical_reports"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows({k: json.dumps(r.get(k), ensure_ascii=False) if isinstance(r.get(k), (dict, list)) else r.get(k) for k in fields} for r in rows)
    graph = {"nodes": [{"id": r["id"], "family": r["family"], "canonical_id": r["canonical_id"]} for r in rows],
             "edges": [{"a": r["a"], "b": r["b"], "type": "REVIEW_ONLY", "flags": r["flags"]} for r in dedup["review_flags"]],
             "frozen_duplicate_families": [], "independence_proven": False}
    (OUT/"family_graph.json").write_text(json.dumps(graph, sort_keys=True, indent=2)+"\n")
    (OUT/"dedup_mechanics_review.json").write_text(json.dumps(dedup, sort_keys=True, indent=2)+"\n")
    print(json.dumps(packet["coverage"], sort_keys=True))


if __name__ == "__main__":
    main()
