from __future__ import annotations

import importlib

support = importlib.import_module("day26_acceptance_support")
WINDOW_LIMIT = 2048


def _deduplicated_research_windows(
    client: object,
    project: str,
    dataset: str,
) -> dict[str, list[dict[str, object]]]:
    """Reconstruct the exact frozen per-anchor windows from one deduplicated transfer.

    The original acceptance query joined every historical candle to every later
    anchor, so the same candle crossed the network many times. This query first
    computes the exact last-2048 membership for every frozen anchor/timeframe,
    then returns the DISTINCT union of those candle rows. Local reconstruction
    filters that union back to each anchor and takes the same last-2048 ordering.
    No scientific definition, anchor, cutoff, feature or evidence gate changes.
    """

    case_table = f"{project}.{dataset}.research_gold_cases"
    candle_table = f"{project}.{dataset}.research_candles"

    anchors = support._query_rows(
        client,
        f"""SELECT case_id, as_of_utc
            FROM `{case_table}`
            WHERE symbol='XAUUSD'
            ORDER BY as_of_utc, case_id""",
        label="research-anchor-index",
    )
    if len(anchors) != support.CANDIDATE_COUNT:
        raise RuntimeError(
            f"Expected {support.CANDIDATE_COUNT} frozen anchors, found {len(anchors)}"
        )

    sql = f"""
WITH anchors AS (
  SELECT case_id, as_of_utc
  FROM `{case_table}`
  WHERE symbol='XAUUSD'
), ranked AS (
  SELECT
    a.case_id AS anchor_case_id,
    c.symbol,
    c.timeframe,
    c.open_time_utc,
    c.open,
    c.high,
    c.low,
    c.close,
    c.research_identity,
    c.provenance_class,
    c.pit_eligible,
    c.source,
    c.source_file_sha256,
    c.source_payload_sha256,
    c.derivation_version,
    ROW_NUMBER() OVER (
      PARTITION BY a.case_id, c.timeframe
      ORDER BY c.open_time_utc DESC, c.research_identity DESC
    ) AS timeframe_rank
  FROM anchors a
  JOIN `{candle_table}` c
    ON c.symbol='XAUUSD'
   AND c.open_time_utc <= a.as_of_utc
  WHERE c.provenance_class='retrospective_history'
    AND c.pit_eligible=FALSE
), exact_union AS (
  SELECT DISTINCT
    symbol,
    timeframe,
    open_time_utc,
    open,
    high,
    low,
    close,
    research_identity,
    provenance_class,
    pit_eligible,
    source,
    source_file_sha256,
    source_payload_sha256,
    derivation_version
  FROM ranked
  WHERE timeframe_rank <= {WINDOW_LIMIT}
)
SELECT *
FROM exact_union
ORDER BY timeframe, open_time_utc, research_identity
""".strip()

    unique_rows = support._query_rows(client, sql, label="research-window-union")
    by_timeframe: dict[str, list[dict[str, object]]] = {}
    for payload in unique_rows:
        by_timeframe.setdefault(str(payload["timeframe"]), []).append(payload)

    grouped: dict[str, list[dict[str, object]]] = {}
    reconstructed_total = 0
    for anchor in anchors:
        case_id = str(anchor["case_id"])
        as_of = support.utc(anchor["as_of_utc"])
        selected: list[dict[str, object]] = []
        for timeframe in sorted(by_timeframe):
            eligible = [
                payload
                for payload in by_timeframe[timeframe]
                if support.utc(payload["open_time_utc"]) <= as_of
            ]
            eligible.sort(
                key=lambda payload: (
                    support.utc(payload["open_time_utc"]),
                    str(payload["research_identity"]),
                )
            )
            selected.extend(dict(payload) for payload in eligible[-WINDOW_LIMIT:])
        grouped[case_id] = selected
        reconstructed_total += len(selected)

    print(
        "WAREHOUSE research-windows: "
        f"unique_transfer_rows={len(unique_rows)} "
        f"reconstructed_anchor_rows={reconstructed_total} "
        f"anchors={len(grouped)}",
        flush=True,
    )
    return grouped


def main() -> int:
    support.load_research_windows = _deduplicated_research_windows
    acceptance = importlib.import_module("day26_price_structure_acceptance")
    return acceptance.main()


if __name__ == "__main__":
    raise SystemExit(main())
