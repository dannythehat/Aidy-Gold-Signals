"""Read-only, fail-closed cross-period audit of pinned PR370/PR371 AIDY CI evidence.

No data downloads, broker API, new strategy signals, orders, or account executions.
2025 BID+modelled ASK and 2026 genuine ASK-at-open+hourly maximum spread are
NOT execution-equivalent; neither period is untouched OOS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from pathlib import Path
from zipfile import ZipFile

PINNED = {
    (370, 2025): ("22e55b4b045592600ca90af8672e683ba76597dac1a35a918db0cfb3ccae8c4d", "af8f38a2dfe89eebffb64843c80ea9ef3cc7c1007e5bda0551d4f34c15a877bd", 11, "64fceb92cb49e807ff0e53c53d6f8cebe81c06e927e6859092addba0d3edf448", 5866, 12),
    (370, 2026): ("7d05d29152fe93bc0bc74ff5c274f575e6308f315d56baf18a8931ad442b3cb9", "1f3eb99f50e55449eb410299ff93272daed2aa2c741ea0627f147631c8808701", 11, "fffff26b3560ac0cf9d41bd1f4139f782e9482fe3f8105a7db7d4559e3aed265", 4382, 10),
    (371, 2025): ("f70a27b588b70d00932f56a04e67db3755991a1fdb31a46968bfe2bc0099cb89", "434a59926b87238395eab23ae352180a389f83438263312652f20a023c0c1919", 16, "64fceb92cb49e807ff0e53c53d6f8cebe81c06e927e6859092addba0d3edf448", 5866, 12),
    (371, 2026): ("d1c471b4e195934b0a33e0f613b920a31c609e32db87f2abfd5928fdbbd80ddd", "dfbdfb8708d325c1906751a4e5fc01302fe42e19b52d5a91cefd1f2cec16ff11", 16, "fffff26b3560ac0cf9d41bd1f4139f782e9482fe3f8105a7db7d4559e3aed265", 4382, 10),
}
CORE_FIVE = ("DONCHIAN_TREND", "EMA_RSI_CROSS", "BOLLINGER_REENTRY", "ASIA_RANGE_BREAK", "ASIA_LIQUIDITY_SWEEP")
NEW_FIVE = ("PREV_DAY_BREAKOUT", "ADX_DI_POWER", "EMA_PULLBACK", "RSI_RECLAIM", "VOL_COMPRESSION_BREAK")
COMPOSITES = ("ALL_FIVE", "ALL_TEN", "FIVE_NEW", "SESSION_PAIR", "TREND_PAIR", "DONCHIAN_ASIA_BREAK", "DONCHIAN_PLUS_SESSIONS")
DEPENDENCE_PAIRS = (("DONCHIAN_TREND", "PREV_DAY_BREAKOUT"), ("DONCHIAN_TREND", "ADX_DI_POWER"), ("PREV_DAY_BREAKOUT", "ASIA_RANGE_BREAK"), ("DONCHIAN_TREND", "ASIA_RANGE_BREAK"))


def read_member(path: Path, name: str) -> bytes:
    if path.is_dir():
        target = path / name
        return target.read_bytes()
    with ZipFile(path) as z:
        return z.read(name)


def read_pinned(path: Path, pr: int, year: int) -> dict:
    report_sha, models_sha, expected_n, csv_sha, rows, months = PINNED[(pr, year)]
    prefix = f"gold_hunter/open_lab_{year}/"
    report_bytes = read_member(path, prefix + "report.json")
    if hashlib.sha256(report_bytes).hexdigest() != report_sha:
        raise ValueError(f"Pinned report hash mismatch PR{pr} {year}")
    report = json.loads(report_bytes)
    trace = report["trace"]
    if (trace["input_csv_sha256"], trace["source_rows"], trace["month_receipts"]) != (csv_sha, rows, months):
        raise ValueError(f"Original source receipt mismatch PR{pr} {year}")
    if report["no_untouched_holdout_claim"] is not True or report["research_not_broker_order"] is not True:
        raise ValueError("Unsafe live or false holdout claim")
    names = sorted(f"{prefix}stress_{key}.json" for key in report["result"]["stress"])
    if len(names) != expected_n:
        raise ValueError("Missing stress case(s)")
    digest = hashlib.sha256()
    models = {}
    for name in names:
        raw = read_member(path, name)
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(raw)
        model = json.loads(raw)
        key = name.split("stress_", 1)[1].removesuffix(".json")
        summary = report["result"]["stress"][key]
        if any(model.get(k) != v for k, v in summary.items()):
            raise ValueError(f"Trade/summary mismatch PR{pr} {year} {key}")
        if len(model["trades"]) != model["closed_trades"]:
            raise ValueError(f"Trade count mismatch PR{pr} {year} {key}")
        if abs(sum(t["pnl_usd"] for t in model["trades"]) - model["realized_net_usd"]) > .02:
            raise ValueError(f"Trade cash mismatch PR{pr} {year} {key}")
        if abs(sum(m["realized_net_usd"] for m in model["monthly"]) - model["realized_net_usd"]) > .05:
            raise ValueError(f"Monthly cash mismatch PR{pr} {year} {key}")
        if len(model["monthly"]) != (12 if year == 2025 else 9):
            raise ValueError("Incomplete or unexpected monthly results")
        models[key] = model
    if digest.hexdigest() != models_sha:
        raise ValueError(f"Original full stress ledger hash mismatch PR{pr} {year}")
    return {"report": report, "models": models, "ledger_sha256": models_sha, "report_sha256": report_sha}


def summary(model: dict) -> dict:
    monthly = model["monthly"]
    return {
        "stress_net_usd": model["net_marked_usd"],
        "closed_trades": model["closed_trades"],
        "profit_factor": model["profit_factor"],
        "max_marked_drawdown_pct": model["max_marked_drawdown_pct"],
        "positive_months": sum(m["realized_net_usd"] > 0 for m in monthly),
        "months_observed": len(monthly),
        "worst_month_realized_usd": min(m["realized_net_usd"] for m in monthly),
        "months_over_10pct": model["months_above_10_pct"],
        "net_without_largest_winner_usd": model["net_ex_largest_winner_usd"],
    }


def dependence(a: dict, b: dict) -> dict:
    at = {(t["signal_utc"], t["side"]) for t in a["trades"]}
    bt = {(t["signal_utc"], t["side"]) for t in b["trades"]}
    am = {m["month"]: m["realized_net_usd"] for m in a["monthly"]}
    bm = {m["month"]: m["realized_net_usd"] for m in b["monthly"]}
    months = sorted(set(am) & set(bm))
    x, y = [am[m] for m in months], [bm[m] for m in months]
    correlation = statistics.correlation(x, y) if len(months) > 2 and len(set(x)) > 1 and len(set(y)) > 1 else None
    return {
        "same_hour_same_side_signal_count": len(at & bt),
        "signals_a": len(at), "signals_b": len(bt),
        "monthly_realized_pnl_correlation": round(correlation, 4) if correlation is not None else None,
        "joint_losing_months": sum(am[m] < 0 and bm[m] < 0 for m in months),
        "compared_months": len(months),
    }


def audit(paths: dict[tuple[int, int], Path]) -> dict:
    if set(paths) != set(PINNED):
        raise ValueError("All four original PR370/PR371 2025/2026 archives are required")
    src = {key: read_pinned(path, *key) for key, path in paths.items()}
    parity = {}
    for year in (2025, 2026):
        left = src[(370, year)]["models"]
        right = src[(371, year)]["models"]
        common = sorted(set(left) & set(right))
        if len(common) != 9 or any(left[k] != right[k] for k in common):
            raise ValueError(f"Original five model paths were altered between PR370/PR371 in {year}")
        parity[str(year)] = {"matching_stress_case_ledgers": len(common), "exact_match": True}
    aliases = {}
    for year in (2025, 2026):
        for pr in (370, 371):
            m = src[(pr, year)]["models"]
            if m["MEAN_REVERSION"] != m["BOLLINGER_REENTRY"] or m["MEAN_REVERSION"]["systems"] != ["BOLLINGER_REENTRY"]:
                raise ValueError("MEAN_REVERSION must not be counted as a separate system")
            aliases[f"PR{pr}_{year}"] = "MEAN_REVERSION is exactly the BOLLINGER_REENTRY single-arm replay, NOT an independent system"
    if set(CORE_FIVE + NEW_FIVE) != set(src[(371, 2026)]["models"]) - set(COMPOSITES) - {"MEAN_REVERSION"}:
        raise ValueError("Unexpected independent hypothesis count or composite aliases")
    candidates = {}
    for key in CORE_FIVE + NEW_FIVE + COMPOSITES:
        cases = {}
        for year in (2025, 2026):
            model = src[(371 if key not in ("DONCHIAN_ASIA_BREAK", "DONCHIAN_PLUS_SESSIONS") else 370, year)]["models"][key]
            cases[str(year)] = summary(model)
        candidates[key] = {
            "identity": "RESEARCH_COMPOSITE_NOT_INDEPENDENT" if key in COMPOSITES else "UNIQUE_RESEARCH_HYPOTHESIS_NOT_UPSTREAM_SOURCE_PARITY_CERTIFIED",
            "stress": cases,
            "both_observed_periods_positive": all(c["stress_net_usd"] > 0 for c in cases.values()),
            "historically_qualified": False,
        }
    dependencies = {}
    for year in (2025, 2026):
        m = src[(371, year)]["models"]
        dependencies[str(year)] = {f"{a}__{b}": dependence(m[a], m[b]) for a, b in DEPENDENCE_PAIRS}
    return {
        "schema": "aidy.gold_hunter.gpt6_independent_cross_period.v1",
        "source_runs": {"PR370_2025": 40665596315, "PR370_2026": 40665596333, "PR371_2025": 40671701827, "PR371_2026": 40671702112},
        "source_integrity": {f"PR{pr}_{year}": {"report_sha256": v["report_sha256"], "stress_ledgers_sha256": v["ledger_sha256"], "original_csv_sha256": v["report"]["trace"]["input_csv_sha256"]} for (pr, year), v in src.items()},
        "frozen_original_five_parity": parity,
        "verified_duplicate_aliases": aliases,
        "unique_hypothesis_ids": list(CORE_FIVE + NEW_FIVE),
        "composites_are_not_independent_bots": list(COMPOSITES),
        "candidate_results": candidates,
        "dependence": dependencies,
        "conclusions": {
            "unique_research_hypotheses": 10,
            "independently_source_certified_upstream_bots": 0,
            "positive_stress_both_observed_periods_individual_ids": [k for k in CORE_FIVE + NEW_FIVE if candidates[k]["both_observed_periods_positive"]],
            "positive_stress_both_observed_periods_composite_ids": [k for k in COMPOSITES if candidates[k]["both_observed_periods_positive"]],
            "historically_qualified": 0,
            "2025_complete_months": 12,
            "2026_complete_months": 9,
            "new_order_count": 0,
            "note": "2025 and Jan-Sep 2026 are examined DEVELOPMENT periods; 2025 BID+synthetic ASK versus 2026 observed ASK-at-open with pessimistic hourly maximum spread, not identical execution fidelity; original publisher source parity, real funding, lot/margin, and native broker execution unverified.",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    for pr in (370, 371):
        for year in (2025, 2026):
            parser.add_argument(f"--pr{pr}-{year}", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    paths = {(pr, year): getattr(args, f"pr{pr}_{year}") for pr in (370, 371) for year in (2025, 2026)}
    result = audit(paths)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("SOURCE VERIFIED: 4 CI artifacts, 2025+2026, 2025 12 months / 2026 9 months")
    print("ORIGINAL FIVE PARITY:", result["frozen_original_five_parity"])
    print("EXACT ALIAS: MEAN_REVERSION = BOLLINGER_REENTRY (not 11th method)")
    print("TWO-PERIOD POSITIVE INDIVIDUALS:", result["conclusions"]["positive_stress_both_observed_periods_individual_ids"])
    print("ALL_TEN 2025/2026:", result["candidate_results"]["ALL_TEN"]["stress"])
    print("HISTORICALLY QUALIFIED:", result["conclusions"]["historically_qualified"])


if __name__ == "__main__":
    main()
