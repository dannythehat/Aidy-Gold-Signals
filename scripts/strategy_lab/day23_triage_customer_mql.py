"""Read-only customer MQL source triage CLI. No MetaTrader account or terminal."""
from __future__ import annotations

import argparse
from pathlib import Path

from aidy.strategy_lab_customer_mql_intake import inspect_customer_mql


def main() -> int:
    parser = argparse.ArgumentParser(description="AIDY customer MQL4/MQL5 source triage")
    parser.add_argument("source", type=Path, help="Original customer's .mq4/.mq5 source")
    args = parser.parse_args()
    print(inspect_customer_mql(args.source.read_bytes(), filename=args.source.name).to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
