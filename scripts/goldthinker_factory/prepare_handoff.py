"""CLI: validate a recorded MT5 annual bundle and prepare AIDY's single-year receipt.

Usage: PYTHONPATH=src python -m scripts.goldthinker_factory.prepare_handoff \
  --input path/to/mt5_results.json --output path/to/selection.json

This is research PRE-FLIGHT, not a source-authenticity or broker parity check.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from aidy.goldthinker_factory_contract import (
    FactoryContractError,
    canonical_json,
    select_best_completed_year,
)


def run(input_path: Path, output_path: Path) -> dict:
    if input_path.resolve() == output_path.resolve():
        raise FactoryContractError("input and output files must be different")
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FactoryContractError("cannot read a valid MT5 input JSON bundle") from exc
    outcome = select_best_completed_year(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replacement keeps the previous receipt if writing a new one fails.
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=output_path.parent,
            prefix=".factory-", suffix=".json", delete=False
        ) as file:
            tmp_path = Path(file.name)
            file.write(canonical_json(outcome) + "\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp_path, output_path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()
    return outcome


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = run(args.input, args.output)
    except FactoryContractError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(
        f"{result['selection_status']}: year={result['aidy_year']} "
        f"receipt={result['selection_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
