"""Seed AIDY's retrospective 15-minute Gold cycle analogue memory from BigQuery.

Historical rows are explicitly retrospective research. They are never marked PIT eligible
and never rewrite a live cycle view. The output is deterministic SQL for Cloudflare D1 so
the live Worker can retrieve prior cycle-path analogues without depending on BigQuery.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from typing import Any

from aidy.gold_cycle_memory import CYCLE_NEUTRAL_BAND_BPS
from aidy.market_sessions import new_york_utc_offset_hours, session_code_at

DEFAULT_DATASET = "aidy_analytics_test"
DEFAULT_LOCATION = "EU"
DEFAULT_START = "2024-01-01T00:00:00+00:00"
DEFAULT_END = "2026-01-01T00:00:00+00:00"
SOURCE_PROVENANCE = "retrospective_history"


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Historical cycle timestamp must be timezone-aware.")
    return parsed.astimezone(UTC)


def _decimal(value: Any) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid historical decimal: {value!r}") from exc
    if not parsed.is_finite():
        raise ValueError(f"Non-finite historical decimal: {value!r}")
    return parsed


def _fmt(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN), "f")


def _state(open_value: Decimal, close_value: Decimal) -> tuple[str, Decimal]:
    if open_value <= 0:
        raise ValueError("Historical cycle open must be positive.")
    return_bps = ((close_value - open_value) / open_value) * Decimal(10000)
    if return_bps > CYCLE_NEUTRAL_BAND_BPS:
        state = "bullish"
    elif return_bps < -CYCLE_NEUTRAL_BAND_BPS:
        state = "bearish"
    else:
        state = "neutral"
    return state, return_bps


def _trading_day(value: datetime) -> date:
    """Group the continuous Gold session by the New York 17:00/18:00 daily boundary."""

    stamp = _utc(value)
    local = stamp + timedelta(hours=new_york_utc_offset_hours(stamp))
    if local.hour >= 18:
        return local.date() + timedelta(days=1)
    return local.date()


def _identity(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "aidy_hist_cycle_" + sha256(raw.encode()).hexdigest()[:32]


def build_historical_cycle_rows(
    rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in rows:
        opened = _utc(raw["open_time_utc"])
        open_value = _decimal(raw["open"])
        close_value = _decimal(raw["close"])
        state, return_bps = _state(open_value, close_value)
        normalized.append(
            {
                "open_time_utc": opened,
                "open": open_value,
                "close": close_value,
                "state": state,
                "return_bps": return_bps,
                "session_code": session_code_at(opened),
                "trading_day": _trading_day(opened),
            }
        )
    normalized.sort(key=lambda item: item["open_time_utc"])

    by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for item in normalized:
        if item["session_code"] == "weekend":
            continue
        by_day[item["trading_day"]].append(item)

    output: list[dict[str, Any]] = []
    for trading_day, day_rows in sorted(by_day.items()):
        states = [str(item["state"]) for item in day_rows]
        for index, item in enumerate(day_rows[:-1]):
            next_item = day_rows[index + 1]
            if next_item["open_time_utc"] - item["open_time_utc"] > timedelta(minutes=30):
                continue

            sequence_start = max(0, index - 3)
            sequence = states[sequence_start : index + 1]
            signature = ">".join(sequence)

            run_length = 1
            cursor = index + 1
            while cursor < len(day_rows) and day_rows[cursor]["state"] == item["state"]:
                if (
                    day_rows[cursor]["open_time_utc"]
                    - day_rows[cursor - 1]["open_time_utc"]
                    > timedelta(minutes=30)
                ):
                    break
                run_length += 1
                cursor += 1

            identity_payload = {
                "window_start_utc": item["open_time_utc"].isoformat(),
                "session_code": item["session_code"],
                "prior_sequence_signature": signature,
                "next_state": next_item["state"],
                "source_provenance": SOURCE_PROVENANCE,
            }
            output.append(
                {
                    "historical_cycle_id": _identity(identity_payload),
                    "window_start_utc": item["open_time_utc"].isoformat(),
                    "session_code": item["session_code"],
                    "time_slot_utc": item["open_time_utc"].strftime("%H:%M"),
                    "observed_state": item["state"],
                    "prior_sequence_signature": signature,
                    "next_state": next_item["state"],
                    "next_return_bps": _fmt(next_item["return_bps"]),
                    "state_run_length_windows": run_length,
                    "source_provenance": SOURCE_PROVENANCE,
                    "pit_eligible": 0,
                    "research_only": 1,
                    "live_money_execution_allowed": 0,
                    "trading_day": trading_day.isoformat(),
                }
            )
    return output


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def write_d1_sql(rows: list[Mapping[str, Any]], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "-- Generated retrospective Gold cycle seed. Never PIT/live authority.",
        "BEGIN TRANSACTION;",
    ]
    batch_size = 200
    columns = (
        "historical_cycle_id",
        "window_start_utc",
        "session_code",
        "time_slot_utc",
        "observed_state",
        "prior_sequence_signature",
        "next_state",
        "next_return_bps",
        "state_run_length_windows",
        "source_provenance",
        "pit_eligible",
        "research_only",
        "live_money_execution_allowed",
    )
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        lines.append(
            "INSERT OR IGNORE INTO aidy_gold_cycle_historical ("
            + ",".join(columns)
            + ") VALUES"
        )
        values: list[str] = []
        for row in batch:
            values.append(
                "("
                + ",".join(
                    (
                        _sql_quote(str(row["historical_cycle_id"])),
                        _sql_quote(str(row["window_start_utc"])),
                        _sql_quote(str(row["session_code"])),
                        _sql_quote(str(row["time_slot_utc"])),
                        _sql_quote(str(row["observed_state"])),
                        _sql_quote(str(row["prior_sequence_signature"])),
                        _sql_quote(str(row["next_state"])),
                        _sql_quote(str(row["next_return_bps"])),
                        str(int(row["state_run_length_windows"])),
                        _sql_quote(str(row["source_provenance"])),
                        "0",
                        "1",
                        "0",
                    )
                )
                + ")"
            )
        lines.append(",\n".join(values) + ";")
    lines.append("COMMIT;")
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.environ.get("AIDY_GCP_PROJECT_ID"))
    parser.add_argument("--dataset", default=os.environ.get("AIDY_BIGQUERY_DATASET", DEFAULT_DATASET))
    parser.add_argument("--location", default=os.environ.get("AIDY_BIGQUERY_LOCATION", DEFAULT_LOCATION))
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not args.project:
        raise SystemExit("AIDY_GCP_PROJECT_ID or --project is required.")
    start = _utc(args.start)
    end = _utc(args.end)
    if end <= start:
        raise SystemExit("--end must be after --start")

    raw_credentials = os.environ.get("AIDY_GCP_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw_credentials:
        raise SystemExit("AIDY_GCP_SERVICE_ACCOUNT_JSON is required.")

    from google.cloud import bigquery
    from google.oauth2 import service_account

    info = json.loads(raw_credentials)
    credentials = service_account.Credentials.from_service_account_info(info)
    client = bigquery.Client(project=args.project, credentials=credentials, location=args.location)
    table = f"{args.project}.{args.dataset}.research_candles"
    sql = f"""
        SELECT open_time_utc,open,close
        FROM `{table}`
        WHERE symbol='XAUUSD'
          AND timeframe='M15'
          AND source='histdata'
          AND provenance_class='retrospective_history'
          AND pit_eligible=FALSE
          AND open_time_utc>=@start
          AND open_time_utc<@end
        ORDER BY open_time_utc
    """
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start", "TIMESTAMP", start),
            bigquery.ScalarQueryParameter("end", "TIMESTAMP", end),
        ]
    )
    job = client.query(sql, job_config=config)
    source_rows = [dict(row.items()) for row in job.result()]
    cycle_rows = build_historical_cycle_rows(source_rows)
    if not cycle_rows:
        raise SystemExit("No historical cycle rows were produced.")

    write_d1_sql(cycle_rows, args.output)
    result = {
        "ok": True,
        "source_table": "research_candles",
        "source_provenance": SOURCE_PROVENANCE,
        "source_rows": len(source_rows),
        "cycle_rows": len(cycle_rows),
        "first_window_utc": cycle_rows[0]["window_start_utc"],
        "last_window_utc": cycle_rows[-1]["window_start_utc"],
        "neutral_band_bps": str(CYCLE_NEUTRAL_BAND_BPS),
        "pit_eligible": False,
        "research_only": True,
        "live_money_execution_allowed": False,
        "query_total_bytes_processed": int(job.total_bytes_processed or 0),
        "output": str(args.output),
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
