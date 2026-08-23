from __future__ import annotations

import importlib
from datetime import datetime
from typing import Any

fast = importlib.import_module("day26_fast_warehouse_acceptance")
support = importlib.import_module("day26_acceptance_support")


def _load_pit_probe_at_frozen_t(
    client: Any,
    bigquery: Any,
    project: str,
    dataset: str,
    cutoff: datetime,
) -> tuple[datetime, dict[str, Any], list[dict[str, Any]]]:
    """Build the real PIT probe at the frozen evaluation time T.

    A snapshot is valid quote evidence when captured_at <= T. Candle evidence is
    independently valid when first_observed_at <= T. The earlier harness
    incorrectly replaced T with the snapshot's own captured_at, which could
    discard candles that were genuinely known by the frozen cutoff.

    Missing PIT candle history is preserved as unknown. This matches the frozen
    Day-26 contract and the accepted Day-7 warehouse behavior; it must never be
    fabricated merely to make a real PIT probe non-empty.
    """
    snapshot_table = f"{project}.{dataset}.market_snapshots"
    snapshot_config = support.query_config(
        bigquery,
        [("symbol", "STRING", "XAUUSD"), ("cutoff", "TIMESTAMP", cutoff)],
    )
    snapshot_rows = support._query_rows(
        client,
        f"""SELECT * FROM `{snapshot_table}`
            WHERE symbol=@symbol AND captured_at <= @cutoff
            ORDER BY captured_at DESC, load_identity DESC
            LIMIT 1""",
        label="pit-snapshot",
        job_config=snapshot_config,
    )
    if not snapshot_rows:
        raise RuntimeError("Day 26 requires one real PIT snapshot at/before the frozen cutoff.")
    snapshot = snapshot_rows[0]

    candle_table = f"{project}.{dataset}.market_candles"
    candle_config = support.query_config(
        bigquery,
        [
            ("symbol", "STRING", "XAUUSD"),
            ("source", "STRING", support.PIT_CANDLE_SOURCE),
            ("as_of", "TIMESTAMP", cutoff),
        ],
    )
    rows = support._query_rows(
        client,
        f"""WITH eligible AS (
              SELECT *, ROW_NUMBER() OVER (
                PARTITION BY source, symbol, timeframe, open_time_utc
                ORDER BY first_observed_at DESC, revision_index DESC, load_identity DESC
              ) AS revision_rank
              FROM `{candle_table}`
              WHERE symbol=@symbol
                AND source=@source
                AND open_time_utc <= @as_of
                AND first_observed_at <= @as_of
            ), canonical AS (
              SELECT * EXCEPT(revision_rank), ROW_NUMBER() OVER (
                PARTITION BY timeframe
                ORDER BY open_time_utc DESC, first_observed_at DESC,
                         revision_index DESC, load_identity DESC
              ) AS timeframe_rank
              FROM eligible
              WHERE revision_rank=1
            )
            SELECT * EXCEPT(timeframe_rank)
            FROM canonical
            WHERE timeframe_rank <= 2048
            ORDER BY timeframe, open_time_utc""",
        label="pit-candles",
        job_config=candle_config,
    )
    print(
        "WAREHOUSE pit-probe: "
        f"evaluation_t={cutoff.isoformat()} "
        f"snapshot_captured_at={support.utc(snapshot['captured_at']).isoformat()} "
        f"candle_rows={len(rows)} "
        f"candle_state={'observed' if rows else 'unknown'}",
        flush=True,
    )
    return support.utc(cutoff), snapshot, rows


def main() -> int:
    support.load_research_windows = fast._deduplicated_research_windows
    support.load_pit_probe = _load_pit_probe_at_frozen_t
    acceptance = importlib.import_module("day26_price_structure_acceptance")
    return acceptance.main()


if __name__ == "__main__":
    raise SystemExit(main())
