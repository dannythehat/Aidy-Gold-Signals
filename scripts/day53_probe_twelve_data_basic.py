from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from aidy.twelve_data_probe import (
    TWELVE_DATA_PROBE_VERSION,
    TwelveDataProbeError,
    probe_twelve_data_basic,
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe Twelve Data Basic entitlement and real XAU/USD 1-minute OHLC"
    )
    parser.add_argument("--output", default="day53_twelve_data_basic_probe.json")
    parser.add_argument("--outputsize", type=int, default=30)
    return parser.parse_args()


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


async def _main_async(args: argparse.Namespace) -> int:
    output = Path(args.output)
    api_key = os.getenv("AIDY_TWELVE_DATA_API_KEY", "").strip()
    try:
        result = await probe_twelve_data_basic(api_key=api_key, outputsize=args.outputsize)
        exit_code = 0
    except TwelveDataProbeError as exc:
        result = {
            "probe_version": TWELVE_DATA_PROBE_VERSION,
            "ready_for_adapter_build": False,
            "error_code": exc.code,
        }
        exit_code = 2
    output.write_text(_canonical(result) + "\n", encoding="utf-8")
    print(_canonical(result))
    return exit_code


def main() -> int:
    return asyncio.run(_main_async(_args()))


if __name__ == "__main__":
    raise SystemExit(main())
