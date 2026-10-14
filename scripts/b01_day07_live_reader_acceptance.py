"""Day 07 acceptance: verify live BigQuery historical reader, no warehouse writes."""
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from google.cloud import bigquery
from google.oauth2 import service_account

from aidy.strategy_lab_history_reader import Window, read_bigquery_window


def main() -> int:
    out = Path("artifacts/b01_day07_live_reader.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        info = json.loads(os.environ["AIDY_GCP_SERVICE_ACCOUNT_JSON"])
        client = bigquery.Client(
            project=info["project_id"], location="EU",
            credentials=service_account.Credentials.from_service_account_info(info),
        )
        # Entirely past sample: London / New York active overlapping source day.
        start = datetime(2025, 1, 6, 13, tzinfo=UTC)
        result = {"source": "histdata", "symbol": "XAUUSD", "clock": "EST_FIXED_UTC_MINUS_05",
                  "sample_start_utc": start.isoformat(), "read_only": True, "checks": []}
        # Actual complete 240-minute M1 input, derived locally into five timeframes.
        for minutes in (1, 5, 15, 60, 240):
            end = start + timedelta(minutes=240)
            window = Window(start, end, end, minutes)
            output, job_id = read_bigquery_window(client, window)
            check = {"timeframe_minutes": minutes,
                     "bigquery_job_id": job_id,
                     "native_m1_count": output.native_m1_rows,
                     "emitted_bars": len(output.bars),
                     "first_open_utc": output.bars[0].open_time_utc.isoformat(),
                     "last_closed_utc": output.bars[-1].available_at_utc.isoformat(),
                     "input_digest": output.input_digest,
                     "source_archive_hashes": list(output.source_archive_hashes),
                     "price_basis": output.bars[0].price_basis}
            if output.native_m1_rows != 240 or len(output.bars) != 240 // minutes:
                raise RuntimeError("real M1 or derived candle count mismatch")
            result["checks"].append(check)
        if len({x["input_digest"] for x in result["checks"]}) != 1:
            raise RuntimeError("timeframe-specific input digest drift on identical M1 source")
        # Prove a second independent SELECT cannot silently change frozen source.
        verify_window = Window(start, start + timedelta(minutes=240),
                               start + timedelta(minutes=240), 15,
                               expected_digest=result["checks"][0]["input_digest"])
        repeat, repeat_job = read_bigquery_window(client, verify_window)
        if len(repeat.bars) != 16:
            raise RuntimeError("pinned replay output mismatch")
        result["replay_bigquery_job_id"] = repeat_job
        result["status"] = "PASS"
        result["scope"] = "Live 2025-01-06 M1 / M5 / M15 / H1 / H4 validated replay, not full session/holiday calendar"
    except Exception as exc:  # noqa: BLE001 - retain explicit blocked evidence
        result = {"status": "BLOCKED", "error_type": type(exc).__name__,
                  "message": str(exc)[:400]}
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
