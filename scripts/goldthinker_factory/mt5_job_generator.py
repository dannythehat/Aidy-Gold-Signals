"""Generate six isolated MT5 Strategy Tester INI configs (DOES NOT launch MT5).

Official syntax: https://www.metatrader5.com/en/terminal/help/start_advanced/start
Native terminal needs a separate, configured non-funded demo/testing account. The
2021-2026 jobs do NOT imply ticks, contracts or actual MT5 executions are available.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path

SUPPORTED_PERIODS = {"M1", "M5", "M15", "H1", "H4", "D1"}
CLEAN = re.compile(r"^[A-Za-z0-9_.\\ -]{1,120}$")
ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{2,79}$")


def _safe(value: str, label: str) -> str:
    if not CLEAN.fullmatch(value) or ".." in value or value.startswith(("\\", ".", " ")):
        raise ValueError(f"unsafe {label}")
    return value


def _as_of(raw: str) -> date:
    try:
        result = date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("as-of must be an ISO date") from exc
    if result.year != 2026:
        raise ValueError("factory pilot requires an as-of date within 2026")
    if result <= date(2026, 1, 1):
        raise ValueError("the partial 2026 period must have at least one completed date")
    return result


def build_configs(
    *, system_id: str, expert: str, symbol: str, period: str, as_of: str,
    output_dir: Path, deposit: str, leverage: int, preset: str | None = None
) -> dict:
    if not ID.fullmatch(system_id):
        raise ValueError("invalid system_id")
    expert = _safe(expert, "relative EA path")
    symbol = _safe(symbol, "broker symbol")
    if period not in SUPPORTED_PERIODS:
        raise ValueError("unsupported timeframe")
    if preset is not None:
        preset = _safe(preset, "preset filename")
        if not preset.endswith(".set") or "\\" in preset:
            raise ValueError("preset must be filename ending in .set")
    if type(leverage) is not int or not 1 <= leverage <= 1000:
        raise ValueError("leverage must be in range 1-1000")
    try:
        money = Decimal(deposit)
    except (ValueError, InvalidOperation, TypeError) as exc:
        raise ValueError("deposit must be decimal text") from exc
    if type(deposit) is not str or not re.fullmatch(r"\d+(?:\.\d{1,2})?", deposit):
        raise ValueError("deposit must use exact positive decimal text")
    if not money.is_finite() or money <= 0:
        raise ValueError("deposit must be positive")
    cutoff = _as_of(as_of)
    jobs: list[dict] = []
    # Pre-generate only nonexecuting text. No broker or trade interactions.
    output_dir.mkdir(parents=True, exist_ok=True)
    for year in range(2021, 2027):
        end = date(year + 1, 1, 1) if year < 2026 else cutoff
        name = f"{system_id}_{year}_real_ticks.ini"
        report = f"{system_id}_{year}_real_ticks.htm"
        lines = [
            "[Experts]",
            "Enabled=0",
            "AllowLiveTrading=0",
            "AllowDllImport=0",
            "",
            "[Tester]",
            f"Expert={expert}",
            f"Symbol={symbol}",
            f"Period={period}",
            "Model=4",  # every tick based on real ticks (not proof ticks exist)
            "ExecutionMode=0",
            "Optimization=0",
            "ForwardMode=0",
            f"FromDate={year}.01.01",
            f"ToDate={end:%Y.%m.%d}",
            f"Deposit={deposit}",
            "Currency=USD",
            f"Leverage=1:{leverage}",
            "UseLocal=1",
            "UseRemote=0",
            "UseCloud=0",
            "Visual=0",
            f"Report={report}",
            "ReplaceReport=0",
            "ShutdownTerminal=1",
        ]
        if preset is not None:
            lines.insert(8, f"ExpertParameters={preset}")
        data = ("\n".join(lines) + "\n").encode("ascii")
        dest = output_dir / name
        if dest.exists():
            raise ValueError(f"refusing overwrite of existing test config: {dest}")
        dest.write_bytes(data)
        jobs.append({
            "year": year,
            "period_label": "COMPLETE_CALENDAR_YEAR" if year < 2026 else "PARTIAL_2026_YTD",
            "from_date": f"{year}-01-01", "to_date_exclusive": end.isoformat(),
            "ini": name, "report_expected": report,
            "ini_sha256": sha256(data).hexdigest(),
            "job_status": "NOT_EXECUTED",
            "tick_coverage_verified": False,
            "tester_account_verified": False,
        })
    manifest = {
        "schema": "goldthinker.factory.mt5_jobs.v1",
        "system_id": system_id, "as_of": cutoff.isoformat(),
        "test_model": "REAL_TICKS_REQUESTED_NOT_VERIFIED",
        "terminal_configured": False, "run_status": "CONFIGS_ONLY",
        "broker_account_credentials_in_manifest": False,
        "jobs": jobs,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--system", required=True)
    p.add_argument("--expert", required=True, help="EA path relative to MQL5/Experts")
    p.add_argument("--symbol", required=True, help="actual broker symbol")
    p.add_argument("--period", required=True)
    p.add_argument("--as-of", required=True, help="YYYY-MM-DD UTC")
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--deposit", default="10000.00")
    p.add_argument("--leverage", default=100, type=int)
    p.add_argument("--preset", default=None)
    args = p.parse_args()
    try:
        result = build_configs(
            system_id=args.system, expert=args.expert, symbol=args.symbol,
            period=args.period, as_of=args.as_of, output_dir=args.out_dir,
            deposit=args.deposit, leverage=args.leverage, preset=args.preset,
        )
    except (OSError, ValueError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(f"CREATED_ONLY: {len(result['jobs'])} annual tester configs, no MT5 process started")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
