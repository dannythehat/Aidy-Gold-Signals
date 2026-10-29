"""Read-only extra-financing sensitivity on two immutable original AIDY account archives.

This is NOT a strategy rerun, forward test, funding estimate, executable trading
account, nor broker order. Apply separately labelled hypothetical USD per physical
ounce per elapsed UTC day to existing 2023-25 stressed marked-equity models.
Position sizing is NOT recomputed after financing; this is linear first-order
post-hoc analysis. No broker quote, swap rollover or margin rule is invented.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = {
    "S016": {
        "path": "reports/gold_oracle/phase04/native_accounts/ci_evidence.zip",
        "sha256": "d71b5f6ae6cf1beef0acbdb461c843f31d0593cc31004ab0108dc9617eee2324",
        "key": "S016_entry20_risk1_STANDARDISED_CAPITAL_COMPARISON_common_stress",
    },
    "S083": {
        "path": "reports/gold_oracle/phase05/S083_costs/ci_evidence.zip",
        "sha256": "acab30523d3edc3c18718ed5d573dd97ff94b04fe81f94a43ba9a01ddb75b562",
        "key": "common_stress",
    },
}
RATES = (0.0, 0.10, 0.25, 0.50, 1.0, 1.5, 2.0)


def utc(value):
    out = datetime.fromisoformat(value)
    if out.tzinfo is None or out.utcoffset().total_seconds() != 0:
        raise ValueError("Explicit UTC dates required")
    return out


def exposure_years(start, end, ounces):
    if end < start or ounces < 0:
        raise ValueError("Reverse dates or negative ounces")
    out = {}
    while start < end:
        boundary = datetime(start.year + 1, 1, 1, tzinfo=UTC)
        stop = min(end, boundary)
        year = str(start.year)
        out[year] = out.get(year, 0.0) + ounces * (stop-start).total_seconds()/86400
        start = stop
    return out


def csv_rows(archive, name):
    return list(csv.DictReader(StringIO(archive.read(name).decode("utf-8-sig"))))


def audit_one(root, ident):
    meta = SOURCE[ident]
    original = (root / meta["path"]).read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    if digest != meta["sha256"]:
        raise ValueError("Original AIDY artifact hash mismatch for " + ident)
    with ZipFile(root/meta["path"]) as z:
        report = json.loads(z.read("results/report.json"))
        model = report["models"][meta["key"]]
        positions = []
        if ident == "S016":
            rows = csv_rows(z, "results/"+meta["key"]+"_trades.csv")
            for r in rows:
                ounces = float(r["commission_usd"]) / 1.44
                if abs(ounces-round(ounces)) > 1e-7:
                    raise ValueError("S016 native 1.44 USD/oz cost and inferred ounces disagree")
                positions.append((utc(r["entry_utc"]), utc(r["exit_utc"]), ounces))
            if abs(sum(float(r["net_usd"]) for r in rows) - model["net_closed_usd"]) > 1e-6:
                raise ValueError("S016 closed cash P&L does not reconcile")
            details = model["details"]
            open_ounces = float(details["native_open_units"])
            if open_ounces:
                last_fill = details["order_fills"][-1]
                if float(last_fill["quantity_delta"]) != open_ounces:
                    raise ValueError("Unverified native open position; reject funding test")
                positions.append((utc(last_fill["utc"]),
                                  utc(report["input_manifests"][-1]["last_utc"]),
                                  abs(open_ounces)))
            open_count = int(bool(open_ounces))
            years = model["years"]
        else:
            rows = csv_rows(z, "results/S083_common_stress_exact_trades.csv")
            for r in rows:
                ounces = float(r["units_exact"])
                if abs(ounces*1.44 - float(r["cash_cost_exact_usd"])) > 1e-6:
                    raise ValueError("S083 actual ounces and cash stress do not reconcile")
                positions.append((utc(r["entry_ts"]), utc(r["exit_ts"]), ounces))
            if abs(sum(float(r["pnl"]) for r in rows) -
                   float(model["net_marked_usd"])) > 1e-6:
                raise ValueError("S083 closed net and marked net do not reconcile")
            years = model["yearly"]
            open_count = 0
        if len(rows) != model["closed_trades"]:
            raise ValueError("Trade count does not reconcile")

        exposures = {}
        for first, last, ounces in positions:
            for year, amount in exposure_years(first, last, ounces).items():
                exposures[year] = exposures.get(year, 0.0) + amount
        total = sum(exposures.values())
        marked = float(model["net_marked_usd"])
        reported = {
            str(year.get("year", str(year.get("period"))[:4])): float(year["net_usd"])
            for year in years
        }
        if abs(sum(reported.values()) - marked) > 0.01:
            raise ValueError("Yearly marked results do not reconcile")

        scenarios = []
        for rate in RATES:
            per_year = {
                y: {
                    "baseline_marked_usd": round(reported[y], 2),
                    "extra_cost_usd": round(rate*exposures.get(y, 0.0), 2),
                    "sensitivity_marked_usd": round(reported[y] - rate*exposures.get(y, 0.0), 2),
                } for y in sorted(reported)
            }
            scenarios.append({
                "hypothetical_usd_per_oz_per_elapsed_utc_day": rate,
                "marked_net_after_extra_cost_usd": round(marked-rate*total, 2),
                "positive_in_every_historical_year": all(
                    reported[y] - rate*exposures.get(y, 0.0) > 0 for y in reported
                ),
                "years": per_year,
            })
        return {
            "id": ident,
            "original_artifact_sha256": digest,
            "closed_trades": len(rows),
            "unclosed_positions_included": open_count,
            "cash_account_start_usd": 10000,
            "baseline_stressed_marked_usd": round(marked, 2),
            "actual_elapsed_ounce_days": round(total, 6),
            "ounce_days_by_year": {y: round(v, 6) for y, v in sorted(exposures.items())},
            "hypothetical_rate_until_zero_total_usd_per_oz_per_day": round(marked/total, 6),
            "scenarios": scenarios,
        }


def run(root=ROOT):
    return {
        "schema": "oracle.gold.gpt6.posthoc_financing_test.v1",
        "sources_verified": True,
        "broker_orders": 0,
        "systems_newly_qualified": 0,
        "method": "Additional USD/oz per elapsed UTC day against pinned observed trade holding intervals, split across UTC year boundaries",
        "limitations": [
            "Not real broker funding, margin, triple-swap calendar, broker lot sizing or risk-resized execution",
            "S016 source model is fully paid stocklike; hypothetical CFD financing need not apply to that particular account",
            "Close/open ledger geometries assumed; exact broker partial fills or mid-trade resizing not verified",
            "Previously researched 2023-2025 periods are not a sealed out-of-sample test",
            "No real account activation, no new signal, no executable portfolio, no paper promotion",
        ],
        "cases": {ident: audit_one(root, ident) for ident in SOURCE},
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = run(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2)+"\n")
    for ident, data in result["cases"].items():
        print("INDEPENDENT_FINANCING", ident,
              "stressed_net", data["baseline_stressed_marked_usd"],
              "observed_ounce_days", data["actual_elapsed_ounce_days"],
              "hypothetical_breakeven_rate", data["hypothetical_rate_until_zero_total_usd_per_oz_per_day"])


if __name__ == "__main__":
    main()
