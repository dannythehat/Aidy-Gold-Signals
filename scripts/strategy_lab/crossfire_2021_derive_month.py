"""CLI for independently validating archived original, read-only 2021 tick ZIP."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from aidy.strategy_lab_crossfire_tick_2021 import write_period


def main() -> None:
    p=argparse.ArgumentParser()
    p.add_argument("--period",required=True)
    p.add_argument("--archive",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args()
    receipt=write_period(Path(args.archive),args.period,Path(args.output))
    print("CROSSFIRE_REAL_SOURCE_MONTH",json.dumps(receipt,sort_keys=True),flush=True)


if __name__=="__main__":
    main()
