"""Reconcile immutable CI ledgers; retain losses and every original ID."""
import csv
import hashlib
import io
import json
import zipfile
from itertools import combinations

import pandas as pd

from scripts.oracle_gold.build_phase03_register import OLD, OUT, ROOT, read, sha, write

CI = "https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/40735495376"
CODE = "e33700c454560cc504f00f3cd8174e4495a8701f"
ZIP_SHA = "73909232d1839e63a6226193448cb875a0c021b6b3b0641f53c06259bf7d8c09"


def main():
    bundle = OUT/"accounts/ci_account_ledgers.zip"
    if sha(bundle) != ZIP_SHA:
        raise ValueError("Original successful CI ZIP changed")
    monthly_series, model_summaries, members = {}, {}, {}
    with zipfile.ZipFile(bundle) as z:
        members = {n: hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist()}
        report_name = next(n for n in z.namelist() if n.endswith("report.json"))
        report = json.loads(z.read(report_name))
        for key, model in report["models"].items():
            ident, scenario = key.split("/")
            trades_name = next(n for n in z.namelist() if n.endswith(f"{ident}_{scenario}_trades.csv"))
            trades = list(csv.DictReader(io.StringIO(z.read(trades_name).decode())))
            assert len(trades) == model["closed_trades"]
            assert abs(sum(float(t["net_excluding_unverified_funding_usd"]) for t in trades)-model["net_closed_excluding_unverified_funding_usd"]) < 1e-6
            summary = {k: v for k, v in model.items() if k != "monthly"}
            summary.update(ci_url=CI, code_commit=CODE, source_sha256=report["source_pins"][ident]["source"]["sha256"],
                           evidence_zip_member=trades_name)
            years = []
            for year in (2023, 2024, 2025):
                ms = [m for m in model["monthly"] if m["month"].startswith(str(year))]
                years.append({"year": year, "start_equity": ms[0]["start_equity"],
                    "end_equity": ms[-1]["end_equity"],
                    "net_marked_excluding_funding_usd": ms[-1]["end_equity"]-ms[0]["start_equity"],
                    "return_pct": (ms[-1]["end_equity"]/ms[0]["start_equity"]-1)*100,
                    "months": len(ms), "negative_months": sum(m["return_pct"] < 0 for m in ms),
                    "closed_trades": sum(t["exit_bar_utc"].startswith(str(year)) for t in trades),
                    "note": "Continuous account, NOT reset/re-sized annually; S081 date gate ends2024 but existing position carries2025"})
            summary["years"] = years
            summary["negative_months"] = [m for m in model["monthly"] if m["return_pct"] < 0]
            summary["net_sign"] = "NEGATIVE" if model["net_marked_excluding_unverified_funding_usd"] < 0 else "NONNEGATIVE"
            model_summaries[key] = summary
            if scenario in ("common_base", "common_stress"):
                monthly_series[key] = pd.Series({m["month"]: m["return_pct"] for m in model["monthly"]})
    write(OUT/"account_results_register.json", {
        "schema": "oracle.gold.phase03.account_results.v1", "ci_url": CI, "code_commit": CODE,
        "artifact_id": 12838106556, "artifact_zip_sha256": ZIP_SHA,
        "committed_artifact": str(bundle.relative_to(ROOT)), "member_sha256": members,
        "models": model_summaries, "negative_cases": sum(m["net_sign"] == "NEGATIVE" for m in model_summaries.values()),
        "negative_case_years": sum(y["net_marked_excluding_funding_usd"] < 0 for m in model_summaries.values() for y in m["years"]),
        "qualified_profitable_strategies": 0, "all83_backtested": False,
        "scope": "4 source-default fixedONE-unit accounts,3 continuous source periods,3 friction cases; funding unknown, no native platform/broker parity or sealed OOS; full calendars/ASK not certified"})

    for ident in ("S005", "S006", "S007", "S008", "S009", "S010"):
        for cost in ("base", "stress"):
            values = {}
            for year in (2023, 2024, 2025):
                with (OLD/f"batch01_common/{year}/{ident}_{cost}_monthly.csv").open() as f:
                    values.update({m["month"]: float(m["return_pct"]) for m in csv.DictReader(f)})
            monthly_series[f"{ident}/common_{cost}"] = pd.Series(values)
    dependence = []
    for cost in ("base", "stress"):
        selected = {k: v for k, v in monthly_series.items() if k.endswith("common_"+cost)}
        for (a, sa), (b, sb) in combinations(selected.items(), 2):
            joined = pd.concat([sa, sb], axis=1).dropna()
            corr = joined.iloc[:, 0].corr(joined.iloc[:, 1])
            both = (joined.iloc[:, 0] < 0)&(joined.iloc[:, 1] < 0)
            dependence.append({"a": a, "b": b, "cost": cost, "months": len(joined),
                "pearson_monthly_return": float(corr) if pd.notna(corr) else None,
                "both_negative_months": list(joined.index[both]),
                "neither_positive_months": int(((joined <= 0).all(axis=1)).sum())})
    write(OUT/"dependence.json", {"schema": "oracle.gold.phase03.dependence.v1", "pairs": dependence,
        "normalisation": "Per-account monthly marked equity returns; no capital rescaling or combined portfolio",
        "limits": ["Earlier B01 resets annually; phase03 accounts continuous, different original capitals/units and timeframes",
                   "Same archive identities, but M1 aggregation and complete-H1 views differ; not perfectly identical price tapes",
                   "36 observed months, source periods incomplete, no sealed OOS, missing funding and broker fills",
                   "S081 no new entries2025; carry P/L not new2025 edge", "Correlation cannot certify independent profitable strategies"]})
    new = read(OUT/"remaining50_source_audit.json")["cards"]
    old = {r["id"]: r for r in read(OLD/"83_source_and_duplicate_audit.json")["rows"]}
    flags = read(OUT/"125_duplicate_comparisons.json")["comparisons"]
    register = []
    for c in read(ROOT/"research/strategy_lab/day33_gold_edge_83_snapshot.json")["candidates"]:
        ident = c["id"]
        src = new.get(ident)
        results = [m for k, m in model_summaries.items() if k.startswith(ident+"/")]
        existing = old[ident]
        blockers = src["blockers"] if src else existing["blockers"]
        status = "SOURCE_ACCESS_BLOCKED" if src and not src["source_files"] else "EXECUTION_OR_RULE_GATES_REMAIN"
        if results:
            status = "REJECTED_UNDER_STRESS_COST_MODEL; NOT_BROKER_QUALIFIED"
        elif existing["batch02_results"]:
            status = "NATIVE_R_SETUP_TESTS_ONLY; NO_SOURCE_DEFINED_ACCOUNT"
        elif existing["batch01_common_results"]:
            status = "EXISTING_ACCOUNT_DIAGNOSTICS_PRESERVED; QUALIFICATION_GATES_REMAIN"
        group = "ORIGINAL_ID_"+ident
        group_note = "No cross-ID alias proven; retained original identifier is not an independence certificate"
        if ident in ("S036", "S037", "S038", "S039"):
            group = "BREAKOUT_EXIT_LAB_SHARED_ENTRY"
            group_note = "S036/S037 channel lookback parameter family; S038/S039 different exit algorithms; no account allocation defined"
        elif ident in ("S041", "S042", "S043"):
            group = "DAILY_ZONE_RECOVERY_COMPOSITE"
            group_note = "Three distinct entry state machines enabled in one default recovery account"
        elif ident in ("S064", "S065"):
            group = "FVG_BB_SHARED_COMPOSITE"
            group_note = "Two different components enabled in one default account; same source bytes, not two standalone duplicates"
        register.append({"id": ident, "title": c["title"], "source_url": c["source_url"],
            "source_status": src["source_status"] if src else "PREVIOUSLY_OBTAINED_ORIGINAL_SOURCE",
            "source_audit_scope": src["review_scope"] if src else existing["source_audit_status"],
            "source_evidence": f"remaining50_source_audit.json#/cards/{ident}" if src else f"../83_source_and_duplicate_audit.json#/rows/id={ident}",
            "source_files": src["source_files"] if src else existing["evidence"],
            "canonical_original_id": ident, "research_family": group, "family_note": group_note,
            "pair_decisions": [{k: r[k] for k in ("a", "b", "classification")} for r in flags if ident in (r["a"], r["b"])],
            "disposition": status, "blockers": blockers,
            "phase03_account_cases": results,
            "existing_b01_cases": len(existing["batch01_results"]),
            "existing_b01_common_cases": len(existing["batch01_common_results"]),
            "existing_b02_R_cases": len(existing["batch02_results"]),
            "prior_evidence_register": "../83_source_and_duplicate_audit.json",
            "native_broker_qualified": False, "independent_profitable_edge_certified": False,
            "score": None, "live_activation": False})
    write(OUT/"independent_strategy_register.json", {
        "schema": "oracle.gold.phase03.independent_strategy_register.v1", "original_ids": 83,
        "source_obtained_ids": 74, "source_blocked_ids": 9, "new_source_obtained_ids": 41,
        "source_availability_is_not_complete_native_audit": True, "all83_backtested": False,
        "new_account_ids": 4, "new_account_cases": 12, "profitable_independent_strategies_certified": 0,
        "research_status": "OPEN; native/source/data gates retained per ID", "rows": register})
    with (OUT/"independent_strategy_register.csv").open("w", newline="") as f:
        fields = ("id", "title", "source_status", "research_family", "disposition", "existing_b01_cases", "existing_b02_R_cases", "new_account_cases", "blockers")
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in register:
            values = {k: r[k] for k in fields if k not in ("new_account_cases", "blockers")}
            values.update(new_account_cases=len(r["phase03_account_cases"]), blockers="; ".join(r["blockers"]))
            writer.writerow(values)
    lines = ["# Original83 phase03 research register", "", "Research remains OPEN. Source availability is not native execution verification; catalogue registration is not a backtest. Earlier225 evidence files are unchanged.", "",
        "41 of remaining50 now have original source:21 TradingView IDs and20 MQL IDs. Overall74 source-obtained IDs,9 access blockers. Every obtained source has five trade-rule dimensions and individual execution gates; native MQL compilation/platform parity remain unverified.", "",
        "125 flagged comparisons:108 material rule differences,4 distinct component pairs sharing accounts,5 different exit methods sharing an entry,1 parameter-family pair,7 unresolved source-blocked pairs. Zero cross-ID exact duplicates proved.76 pairs also have a same-tape executable output counterexample. S016 earlier within-ID parameter family evidence remains unchanged.", "",
        "## New actual historical account batch", "", f"[Successful CI]({CI}), code `{CODE}`. [Immutable original CI ZIP](accounts/ci_account_ledgers.zip), SHA256 `"+ZIP_SHA+"`. Includes every trade/monthly ledger and original report; retained in git beyond90day Actions artifact expiry.", "",
        "One authenticated minute cache:2023 308753 rows;2024 355592;2025 353951.12 R2 originals and all monthly BQ identities verified. Full calendar/ASK/funding/broker/platform parity not certified. Base/stress friction .47/1.44USD per ounce roundtrip replaces native declared costs in separate cases. No optimisation or invented end liquidation.", "",
        "| Original ID | Source capital | Closed trades | Native net USD | Base net USD | Stress net USD | Stress model-path DD |", "|---|---:|---:|---:|---:|---:|---:|"]
    for ident in ("S058", "S060", "S061", "S081"):
        native, base, stress = (model_summaries[ident+"/"+k] for k in ("native", "common_base", "common_stress"))
        lines.append(f"|{ident}|{base['initial_capital']:,.0f}|{base['closed_trades']}|{native['net_marked_excluding_unverified_funding_usd']:.2f}|{base['net_marked_excluding_unverified_funding_usd']:.2f}|{stress['net_marked_excluding_unverified_funding_usd']:.2f}|{stress['max_modelled_pine_path_drawdown_pct']:.3f}%|")
    lines += ["", "All4 lose under stress. Native positive S060/S081 become negative with base costs. S061 base positive is cost-sensitive and not qualified. Different original capitals remain unchanged; do not sum these accounts into a portfolio. S081 carries its final position through2025 after its entry date gate ends2024. Published S058 example is BTC, S061 silver: neither publisher example is imported as gold performance.", "",
        "[Every model/year/loss/worst month/largest-winner sensitivity](account_results_register.json), [90 monthly dependence pairs](dependence.json), [all83 IDs and gates](independent_strategy_register.json), [CSV](independent_strategy_register.csv), [50 source cards](remaining50_source_audit.json), [125 five-dimension decisions](125_duplicate_comparisons.json). Correlations compare marked returns across36 observed months and have aggregation/account-reset differences; they are diagnostics, not independence proof.", "",
        "## Individual access blockers", ""]
    for r in new.values():
        if not r["source_files"]:
            lines.append(f"- {r['id']}: {r['blockers'][0]}. [Original URL]({r['source_url']}).")
    lines += ["", "S078 observed SSRN PDF deliveries both returned403 on isolated runner [CI](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/40737173797). Abstract prose was not promoted into executable rules. Six commercial products require actual original source; compiled/demo products are not source access. No source/broker/data blocker is assigned a fabricated economic grade.", "",
        "Remaining work is explicit in the register: source access, native dependencies/parity, actual broker clock/lot/margin/funding/quotes, source-compatible volume, realtime/random state, complete data calendars and independent validation. No qualified profitable strategy, sealed OOS or simultaneous shared-margin portfolio is claimed. No production/broker activation."]
    (OUT/"REVIEW.md").write_text("\n".join(lines)+"\n")
    print("83 IDs,12 new account cases,90 dependence pairs; open research gates retained")


if __name__ == "__main__":
    main()
