"""S001 GoldEA read-only AIDY data/source preflight, NOT a trading backtest."""
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/strategy_lab/s001_goldea"
START = datetime(2025, 1, 1, tzinfo=UTC)
END = datetime(2025, 2, 1, tzinfo=UTC)
BYTE_CAP = 1_500_000_000
TABLE = "aidy-signals.aidy_analytics_test.research_candles"
ORIGINAL = "https://github.com/eamonnkennedy93-blip/GoldEA"
SOURCE_BLOBS = {
    "strategy_edge.py": "d763084900c02986d8691aad26b71cf87caa3af8",
    "session_levels.py": "4b0302001b849a5f3c2291f4fa9ca80f4a904558",
    "swing_structure.py": "19f14e8fa9b9fd6ad53ce8bc70e87b6f7e559686",
    "backtester.py": "eca177393950575015609002bc2fe06447e317ee",
    "walk_forward.py": "ae01ffd6bd1312535f59353f5de5ae0b78bdcdfa",
}
BLOCKERS = [
    "MT5-native M15 tick volume required for anchored VWAP is not qualified by original AIDY BID-only M1 OHLC.",
    "Publisher's backtester unconditionally imports absent entry_refinement.py.",
    "Publisher's live MQL5 EA is unpublished, so original execution parity cannot be certified.",
    "Author's 183 OOS trades, PF 1.30 and control PF 1.09 are NOT independent AIDY results.",
    "Original public repository lacks LICENSE; reuse/publication rights need separate verification.",
]

def summarise(rows, job_id, estimated_bytes):
    if not job_id or not 0 <= estimated_bytes <= BYTE_CAP or not rows:
        raise ValueError("Missing bounded real-source receipt")
    prev = None
    m1 = complete = partial = 0
    archives = set()
    for r in rows:
        ts = r["period_utc"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        if (ts.tzinfo is None or ts.utcoffset().total_seconds() != 0
                or not START <= ts < END or ts.minute % 15 or ts.second
                or (prev is not None and ts <= prev)):
            raise ValueError("Original UTC candle order/clock invalid")
        prev = ts
        count, unique = int(r["m1_count"]), int(r["unique_m1"])
        if not 1 <= count <= 15 or unique != count or int(r["invalid_original_rows"]):
            raise ValueError("M1 duplicate, wrong source or original provenance")
        for h in r["archive_shas"]:
            if len(h) != 64 or any(c not in "0123456789abcdef" for c in h):
                raise ValueError("Invalid market source hash")
            archives.add(h)
        if not (0 < float(r["low"]) <= float(r["open"]) <= float(r["high"])
                and float(r["low"]) <= float(r["close"]) <= float(r["high"])):
            raise ValueError("Bad gold OHLC")
        m1 += count
        complete += count == 15
        partial += count != 15
    if not archives or complete < 100:
        raise ValueError("Insufficient original M15 market bars")
    return {"period": "2025-01", "original_bid_m1": m1,
            "complete_m15": complete, "excluded_partial_m15": partial,
            "source_archive_shas": sorted(archives), "bigquery_job_id": job_id,
            "estimated_bytes": estimated_bytes, "basis": "ORIGINAL_HISTDATA_M1_BID"}


def read_market():
    from google.cloud import bigquery
    from google.oauth2 import service_account
    info = json.loads(os.environ["AIDY_GCP_SERVICE_ACCOUNT_JSON"])
    client = bigquery.Client(
        project=info["project_id"], location="EU",
        credentials=service_account.Credentials.from_service_account_info(info))
    sql = f"""
      SELECT TIMESTAMP_SECONDS(DIV(UNIX_SECONDS(open_time_utc),900)*900) period_utc,
        ARRAY_AGG(open ORDER BY open_time_utc ASC LIMIT 1)[OFFSET(0)] open,
        MAX(high) high, MIN(low) low,
        ARRAY_AGG(close ORDER BY open_time_utc DESC LIMIT 1)[OFFSET(0)] close,
        COUNT(*) m1_count, COUNT(DISTINCT open_time_utc) unique_m1,
        COUNTIF(NOT (
          source='histdata' AND symbol='XAUUSD' AND timeframe='M1'
          AND price_basis='bid' AND source_dataset='generic_ascii_m1'
          AND source_timezone='EST_FIXED_UTC_MINUS_05'
          AND derivation_version='aidy_histdata_source_aligned_v1'
          AND provenance_class='retrospective_history'
          AND pit_eligible=FALSE AND derived_from_timeframe IS NULL
          AND input_rows=1 AND LENGTH(source_file_sha256)=64
          AND LENGTH(source_payload_sha256)=64
        )) invalid_original_rows,
        ARRAY_AGG(DISTINCT source_file_sha256 IGNORE NULLS) archive_shas
      FROM {chr(96)}{TABLE}{chr(96)}
      WHERE symbol='XAUUSD' AND timeframe='M1'
        AND open_time_utc>=@start AND open_time_utc<@end
      GROUP BY 1 ORDER BY 1
    """
    params = [bigquery.ScalarQueryParameter("start", "TIMESTAMP", START),
              bigquery.ScalarQueryParameter("end", "TIMESTAMP", END)]
    dry = client.query(sql, job_config=bigquery.QueryJobConfig(
        query_parameters=params, dry_run=True, use_query_cache=False))
    estimated = int(dry.total_bytes_processed or 0)
    if estimated > BYTE_CAP:
        raise ValueError("BigQuery dry-run scan over 1.5GB")
    job = client.query(sql, job_config=bigquery.QueryJobConfig(
        query_parameters=params, maximum_bytes_billed=BYTE_CAP,
        use_query_cache=False))
    return summarise([dict(r) for r in job.result(timeout=240)], job.job_id, estimated)


def make_packet(market):
    result = {
        "schema": "aidy.strategy_lab.s001.source_preflight.v1",
        "strategy_id": "S001", "source": ORIGINAL, "source_blob_shas": SOURCE_BLOBS,
        "historical_market": market,
        "status": "ORIGINAL_HISTORY_READ__STRATEGY_BACKTEST_BLOCKED",
        "author_claims_unverified": {"oos_trades": 183, "pf": 1.30, "naive_pf": 1.09},
        "blocking_gates": BLOCKERS, "reference_account_usd": 10000,
        "aidy_trades": None, "aidy_profit_factor": None,
        "aidy_net_pnl_usd": None, "aidy_drawdown_pct": None,
        "broker_orders": 0, "independent_alpha_qualified": False,
    }
    result["sha256"] = hashlib.sha256(json.dumps(
        result, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        packet = make_packet(read_market())
        exit_code = 0
    except (ValueError, KeyError, RuntimeError, OSError) as exc:
        packet = {"strategy_id": "S001", "status": "REAL_DATA_READ_BLOCKED",
                  "reason": str(exc), "aidy_net_pnl_usd": None, "broker_orders": 0}
        exit_code = 2
    (OUT / "s001_aidy_report.json").write_text(
        json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = ["# S001 GoldEA | AIDY first research report",
             "", "**Status:** " + packet["status"],
             "", "This is a REAL-DATA source gate, NOT a strategy P&L report.",
             "The original publisher's PF 1.30 is NOT AIDY verified."]
    if "historical_market" in packet:
        r = packet["historical_market"]
        lines += ["", "## Genuine 2025-01 XAUUSD archive",
                  "- Native BID M1 rows: " + str(r["original_bid_m1"]),
                  "- Complete M15 candles: " + str(r["complete_m15"]),
                  "- Excluded incomplete M15: " + str(r["excluded_partial_m15"]),
                  "- Original BigQuery job ID: " + r["bigquery_job_id"],
                  "", "## Missing source and execution proof",
                  *["- " + item for item in BLOCKERS]]
    else:
        lines += ["", "**Source error:** " + packet["reason"]]
    (OUT / "s001_aidy_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    print("S001_AIDY", packet["status"], flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
