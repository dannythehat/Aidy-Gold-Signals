#!/usr/bin/env python3
"""Fetch only the frozen Day 11 reconciliation windows from Twelve Data.

The output SQL writes exclusively to calibration-only D1 tables created by migration 0015.
It never writes market_candles or any decision-admitted view. Missing Twelve bars remain
missing and are recorded as INCOMPLETE; no bar is synthesized or interpolated.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aidy.twelve_data_market import TwelveDataOhlcGateway, expected_market_minute_opens

SOURCE_KIND = "calibration_backfill"
SOURCE_PROVIDER = "twelve_data"
EXPECTED_WINDOWS = 56
REQUEST_PACING_SECONDS = 8.0


def _dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("calibration window timestamp must be timezone-aware")
    parsed = parsed.astimezone(UTC)
    if parsed.second or parsed.microsecond:
        raise ValueError("calibration window timestamp must be minute-aligned")
    return parsed


def _q(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _load_manifest(path: Path) -> list[dict[str, str]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or len(raw) != EXPECTED_WINDOWS:
        raise ValueError(f"expected exactly {EXPECTED_WINDOWS} calibration windows")
    ids: set[str] = set()
    windows: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise TypeError("calibration manifest row must be an object")
        window_id = str(item.get("window_id") or "").strip()
        start = str(item.get("from") or "").strip()
        end = str(item.get("to") or "").strip()
        if not window_id or window_id in ids:
            raise ValueError("calibration window id missing or duplicated")
        start_dt = _dt(start)
        end_dt = _dt(end)
        if start_dt >= end_dt or (end_dt - start_dt).total_seconds() > 48 * 3600:
            raise ValueError(f"invalid calibration window {window_id}")
        ids.add(window_id)
        windows.append(
            {"window_id": window_id, "from": start_dt.isoformat(), "to": end_dt.isoformat()}
        )
    return windows


async def _run(manifest: Path, sql_out: Path, summary_out: Path) -> None:
    api_key = os.getenv("AIDY_TWELVE_DATA_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("AIDY_TWELVE_DATA_API_KEY is required")
    windows = _load_manifest(manifest)
    gateway = TwelveDataOhlcGateway(api_key=api_key)

    unique_bars: dict[str, dict[str, str]] = {}
    window_results: list[dict[str, Any]] = []
    for index, window in enumerate(windows, start=1):
        start = _dt(window["from"])
        end = _dt(window["to"])
        fetched = await gateway.fetch_1m(start_date=start, end_date=end)
        expected = tuple(expected_market_minute_opens(start, end))
        expected_set = set(expected)
        actual = {
            bar.open_time_utc
            for bar in fetched.closed_bars
            if bar.open_time_utc in expected_set
        }
        missing = tuple(value for value in expected if value not in actual)

        for bar in fetched.closed_bars:
            if bar.open_time_utc not in expected_set:
                continue
            opened = bar.open_time_utc.isoformat()
            row = {
                "open_time_utc": opened,
                "open": str(bar.open),
                "high": str(bar.high),
                "low": str(bar.low),
                "close": str(bar.close),
                "first_observed_at": fetched.fetched_at_utc.isoformat(),
                "payload_digest": bar.payload_digest,
            }
            prior = unique_bars.get(opened)
            if prior is not None and any(
                prior[key] != row[key]
                for key in ("open", "high", "low", "close", "payload_digest")
            ):
                raise RuntimeError(
                    f"Twelve historical revision conflict within calibration run: {opened}"
                )
            if prior is None or row["first_observed_at"] < prior["first_observed_at"]:
                unique_bars[opened] = row

        result = {
            "window_id": window["window_id"],
            "from": start.isoformat(),
            "to": end.isoformat(),
            "expected_row_count": len(expected),
            "observed_row_count": len(actual),
            "missing_row_count": len(missing),
            "status": "COMPLETE" if not missing else "INCOMPLETE",
            "fetched_at_utc": fetched.fetched_at_utc.isoformat(),
            "response_digest": fetched.response_digest,
            "first_missing_open_time": missing[0].isoformat() if missing else None,
        }
        window_results.append(result)
        print(
            f"calibration_window={index}/{len(windows)} id={window['window_id']} "
            f"expected={len(expected)} observed={len(actual)} missing={len(missing)} "
            f"status={result['status']}",
            flush=True,
        )
        if index < len(windows):
            await asyncio.sleep(REQUEST_PACING_SECONDS)

    lines = [
        "BEGIN TRANSACTION;",
        "DELETE FROM provider_calibration_backfill_windows;",
        "DELETE FROM provider_calibration_m1_backfill;",
    ]
    for row in sorted(unique_bars.values(), key=lambda item: item["open_time_utc"]):
        lines.append(
            "INSERT INTO provider_calibration_m1_backfill("
            "open_time_utc,symbol,timeframe,open,high,low,close,source_kind,source_provider,"
            "pit_eligible,research_only,live_money_execution_allowed,first_observed_at,"
            "payload_digest) VALUES ("
            + ",".join(
                [
                    _q(row["open_time_utc"]),
                    "'XAUUSD'",
                    "'1m'",
                    _q(row["open"]),
                    _q(row["high"]),
                    _q(row["low"]),
                    _q(row["close"]),
                    _q(SOURCE_KIND),
                    _q(SOURCE_PROVIDER),
                    "0",
                    "1",
                    "0",
                    _q(row["first_observed_at"]),
                    _q(row["payload_digest"]),
                ]
            )
            + ");"
        )
    for row in window_results:
        lines.append(
            "INSERT INTO provider_calibration_backfill_windows("
            "window_id,symbol,timeframe,window_from,window_to,source_kind,source_provider,"
            "pit_eligible,research_only,live_money_execution_allowed,expected_row_count,"
            "observed_row_count,missing_row_count,status,fetched_at_utc,response_digest"
            ") VALUES ("
            + ",".join(
                [
                    _q(row["window_id"]),
                    "'XAUUSD'",
                    "'1m'",
                    _q(row["from"]),
                    _q(row["to"]),
                    _q(SOURCE_KIND),
                    _q(SOURCE_PROVIDER),
                    "0",
                    "1",
                    "0",
                    str(row["expected_row_count"]),
                    str(row["observed_row_count"]),
                    str(row["missing_row_count"]),
                    _q(row["status"]),
                    _q(row["fetched_at_utc"]),
                    _q(row["response_digest"]),
                ]
            )
            + ");"
        )
    lines.append("COMMIT;")
    sql_out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = {
        "source_kind": SOURCE_KIND,
        "source_provider": SOURCE_PROVIDER,
        "pit_eligible": False,
        "research_only": True,
        "live_money_execution_allowed": False,
        "window_count": len(window_results),
        "complete_windows": sum(row["status"] == "COMPLETE" for row in window_results),
        "incomplete_windows": sum(row["status"] == "INCOMPLETE" for row in window_results),
        "unique_bar_count": len(unique_bars),
        "windows": window_results,
    }
    summary_out.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    keys = (
        "source_kind",
        "source_provider",
        "pit_eligible",
        "research_only",
        "live_money_execution_allowed",
        "window_count",
        "complete_windows",
        "incomplete_windows",
        "unique_bar_count",
    )
    print(
        "DAY11_CALIBRATION_BACKFILL="
        + json.dumps({key: summary[key] for key in keys}, sort_keys=True),
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--sql-out", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(_run(args.manifest, args.sql_out, args.summary_out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
