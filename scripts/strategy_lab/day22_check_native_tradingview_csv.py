"""Run strict Day22 source-bound TradingView CSV parity, read-only.

This CLI checks values, NOT that an untrusted CSV was genuinely exported by
TradingView. Save input evidence/metadata separately and independently verify
origin before allowing Day22 full acceptance.
"""
from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

from aidy.strategy_lab_pine_adapter import admit_pine_subset
from aidy.strategy_lab_tv_chart_csv import verify_tv_chart_csv

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "research/strategy_lab/fixtures/day22_tradingview_exportable_v6.pine.txt"
TEMPLATE = ROOT / "research/strategy_lab/fixtures/strategy_spec_v1_sample.json"
SOURCE_REF = "research/strategy_lab/fixtures/day22_tradingview_exportable_v6.pine.txt"


def inspect_csv(csv_path: Path) -> dict:
    script = SOURCE.read_bytes()
    source_sha = sha256(script).hexdigest()
    spec = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    spec["origin"]["source_language"] = "pine"
    spec["origin"]["source_sha256"] = source_sha
    spec["origin"]["source_snapshot_ref"] = SOURCE_REF
    spec["origin"]["interpretation_notes"] = [
        "DAY22 technical reviewer: instrumented signal subset only; "
        "not a broker trade-system licence/owner approval."
    ]
    parsed = admit_pine_subset(
        script, source_sha256=source_sha, source_ref=SOURCE_REF,
        spec_json=json.dumps(spec, sort_keys=True),
    )
    original_csv = csv_path.read_bytes()
    report = verify_tv_chart_csv(
        parsed, original_csv,
        expected_csv_sha256=sha256(original_csv).hexdigest(),
        chart_symbol="OANDA:XAUUSD", chart_interval="5",
    )
    return json.loads(report.to_json())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify TradingView chart CSV crossover values; origin remains unverified.",
    )
    parser.add_argument("csv", type=Path, help="Unmodified native TradingView chart CSV")
    parser.add_argument(
        "--receipt", type=Path, help="Optional path to save source-bound JSON receipt",
    )
    args = parser.parse_args()
    record = inspect_csv(args.csv)
    output = json.dumps(record, sort_keys=True, indent=2)
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(output+"\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
