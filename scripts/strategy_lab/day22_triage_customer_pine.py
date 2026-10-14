"""Inspect a customer-supplied Pine file without a TradingView account.

Read-only receipt only; does not execute user source, place trades, assume
unsupported entry rules, authenticate a provider export or upload source data.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from aidy.strategy_lab_customer_pine_intake import inspect_customer_pine


def main() -> int:
    parser=argparse.ArgumentParser(description="AIDY read-only customer Pine strategy intake")
    parser.add_argument("source",type=Path,help="The customer's original Pine source file")
    parser.add_argument("--pasted-text",action="store_true",
                        help="This file contains customer pasted text rather than a Pine upload")
    args=parser.parse_args()
    raw=args.source.read_bytes()
    submission="source_text_paste" if args.pasted_text else "pine_source_upload"
    result=inspect_customer_pine(raw,submission_type=submission,
                                filename=args.source.name)
    print(json.dumps(result.to_wire(),sort_keys=True,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
