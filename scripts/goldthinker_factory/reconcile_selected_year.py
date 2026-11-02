"""Reconcile AIDY trades to the single year named by a selection receipt.

Does not search other years and does not start a strategy replay by itself.
Omit --aidy-trades to record that the offline AIDY strategy hook is absent.
Exit 0 only for MATCH. Exit 3 blocks packaging. Exit 2 is a bad invocation.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aidy.goldthinker_factory_contract import FactoryContractError, canonical_json
from aidy.goldthinker_factory_metrics import load_thresholds
from aidy.goldthinker_factory_mt5_extract import atomic_write
from aidy.goldthinker_factory_reconcile import (
    ExplicitTradeListReplay,
    UnavailableAidyStrategyReplay,
    load_trade_document,
    reconcile_selected_year,
)


def run(
    *,
    selection_path: Path,
    ledger_dir: Path,
    manifest_path: Path,
    thresholds_path: Path,
    output_path: Path,
    aidy_trades_path: Path | None,
) -> dict:
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    thresholds = load_thresholds(thresholds_path.read_text(encoding="utf-8"))
    if aidy_trades_path is None:
        replay = UnavailableAidyStrategyReplay()
    else:
        replay = ExplicitTradeListReplay(load_trade_document(aidy_trades_path.read_text(encoding="utf-8")))
    receipt = reconcile_selected_year(
        selection=selection,
        ledger_dir=ledger_dir,
        data_manifest=manifest,
        replay=replay,
        thresholds=thresholds,
    )
    atomic_write(output_path, canonical_json(receipt) + "\n")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--ledger-dir", required=True, type=Path)
    parser.add_argument("--data-manifest", required=True, type=Path)
    parser.add_argument("--thresholds", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--aidy-trades", type=Path, default=None)
    args = parser.parse_args()
    try:
        receipt = run(
            selection_path=args.selection,
            ledger_dir=args.ledger_dir,
            manifest_path=args.data_manifest,
            thresholds_path=args.thresholds,
            output_path=args.output,
            aidy_trades_path=args.aidy_trades,
        )
    except (OSError, FactoryContractError, json.JSONDecodeError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(
        f"{receipt['status']}: packaging_allowed={str(receipt['research_packaging_allowed']).lower()} "
        f"year={receipt['aidy_year']}"
    )
    return 0 if receipt["status"] == "MATCH" else 3


if __name__ == "__main__":
    raise SystemExit(main())
