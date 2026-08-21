from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from aidy.day23_research import digest

BASE_SHA = "262bf436dcd948d0dabe554f93d64edb82726121"
CANDIDATE_DIGEST = "bd3c81b54ec05b2150e6e6ecbdffbc3c1e4f943c6a23c9a8ee4977c1dc1c3a88"
CANDIDATE_COUNT = 36
RESULT_TABLE = "research_day26_price_structure_results"
SUMMARY_TABLE = "research_day26_summary"
PIT_CANDLE_SOURCE = "gold_api"


def utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Day 26 warehouse timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def row(value: Any) -> dict[str, Any]:
    return dict(value.items())


def query_config(bigquery: Any, pairs: list[tuple[str, str, Any]]) -> Any:
    return bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(name, kind, value) for name, kind, value in pairs
        ]
    )


def load_candidate_snapshot(client: Any, project: str, dataset: str) -> list[dict[str, Any]]:
    table = f"{project}.{dataset}.research_gold_cases"
    rows = [
        row(item)
        for item in client.query(
            f"""SELECT case_id, case_digest, input_digest, as_of_utc,
                       future_available_after_utc, provenance_class, data_quality_grade
                FROM `{table}`
                WHERE symbol='XAUUSD'
                ORDER BY as_of_utc, case_id"""
        ).result()
    ]
    snapshot = [
        {
            "case_id": str(item["case_id"]),
            "case_digest": str(item["case_digest"]),
            "input_digest": str(item["input_digest"]),
            "as_of_utc": utc(item["as_of_utc"]).isoformat(),
            "future_available_after_utc": (
                None
                if item.get("future_available_after_utc") is None
                else utc(item["future_available_after_utc"]).isoformat()
            ),
            "provenance_class": str(item["provenance_class"]),
            "data_quality_grade": str(item["data_quality_grade"]),
        }
        for item in rows
    ]
    if len(snapshot) != CANDIDATE_COUNT:
        raise RuntimeError(f"Expected {CANDIDATE_COUNT} frozen cases, found {len(snapshot)}")
    if digest(snapshot) != CANDIDATE_DIGEST:
        raise RuntimeError("Day 26 candidate store differs from frozen Day 23-25 snapshot.")
    return snapshot


def load_research_windows(client: Any, project: str, dataset: str) -> dict[str, list[dict[str, Any]]]:
    case_table = f"{project}.{dataset}.research_gold_cases"
    candle_table = f"{project}.{dataset}.research_candles"
    sql = f"""
WITH anchors AS (
  SELECT case_id, as_of_utc
  FROM `{case_table}`
  WHERE symbol='XAUUSD'
), ranked AS (
  SELECT
    a.case_id AS anchor_case_id,
    a.as_of_utc AS anchor_as_of_utc,
    c.*,
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
)
SELECT * EXCEPT(timeframe_rank)
FROM ranked
WHERE timeframe_rank <= 2048
ORDER BY anchor_as_of_utc, anchor_case_id, timeframe, open_time_utc
""".strip()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in client.query(sql).result():
        payload = row(item)
        anchor = str(payload.pop("anchor_case_id"))
        payload.pop("anchor_as_of_utc", None)
        grouped[anchor].append(payload)
    return dict(grouped)


def load_pit_probe(
    client: Any,
    bigquery: Any,
    project: str,
    dataset: str,
    cutoff: datetime,
) -> tuple[datetime, dict[str, Any], list[dict[str, Any]]]:
    snapshot_table = f"{project}.{dataset}.market_snapshots"
    config = query_config(
        bigquery,
        [("symbol", "STRING", "XAUUSD"), ("cutoff", "TIMESTAMP", cutoff)],
    )
    snapshot_rows = list(
        client.query(
            f"""SELECT * FROM `{snapshot_table}`
                WHERE symbol=@symbol AND captured_at <= @cutoff
                ORDER BY captured_at DESC, load_identity DESC
                LIMIT 1""",
            job_config=config,
        ).result()
    )
    if not snapshot_rows:
        raise RuntimeError("Day 26 requires one real PIT snapshot at/before the frozen cutoff.")
    snapshot = row(snapshot_rows[0])
    as_of = utc(snapshot["captured_at"])

    candle_table = f"{project}.{dataset}.market_candles"
    candle_config = query_config(
        bigquery,
        [
            ("symbol", "STRING", "XAUUSD"),
            ("source", "STRING", PIT_CANDLE_SOURCE),
            ("as_of", "TIMESTAMP", as_of),
        ],
    )
    rows = [
        row(item)
        for item in client.query(
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
            job_config=candle_config,
        ).result()
    ]
    if not rows:
        raise RuntimeError("Day 26 PIT probe found no canonical Gold candles.")
    return as_of, snapshot, rows


def ensure_table(
    client: Any,
    bigquery: Any,
    not_found: type[Exception],
    table_id: str,
    schema: list[Any],
) -> None:
    try:
        table = client.get_table(table_id)
    except not_found:
        client.create_table(bigquery.Table(table_id, schema=schema))
        return
    actual = [(field.name, field.field_type, field.mode) for field in table.schema]
    expected = [(field.name, field.field_type, field.mode) for field in schema]
    if actual != expected:
        raise RuntimeError(f"BigQuery schema drift for {table_id}")


def persist_results(
    client: Any,
    bigquery: Any,
    not_found: type[Exception],
    table_id: str,
    experiment: str,
    rows: list[dict[str, Any]],
) -> None:
    schema = [
        bigquery.SchemaField("experiment_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("base_sha", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("head_sha", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("anchor_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("mode", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("as_of_utc", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("payload_digest", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("semantic_digest", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("payload_json", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("recorded_at_utc", "TIMESTAMP", mode="REQUIRED"),
    ]
    ensure_table(client, bigquery, not_found, table_id, schema)
    config = query_config(bigquery, [("experiment", "STRING", experiment)])
    existing = {
        str(item["anchor_id"]): str(item["payload_digest"])
        for item in client.query(
            f"SELECT anchor_id,payload_digest FROM `{table_id}` WHERE experiment_id=@experiment",
            job_config=config,
        ).result()
    }
    missing: list[dict[str, Any]] = []
    for payload in rows:
        anchor = str(payload["anchor_id"])
        if anchor in existing and existing[anchor] != payload["payload_digest"]:
            raise RuntimeError("Immutable Day 26 result conflict.")
        if anchor not in existing:
            missing.append(payload)
    if missing:
        job = client.load_table_from_json(
            missing,
            table_id,
            job_config=bigquery.LoadJobConfig(schema=schema, write_disposition="WRITE_APPEND"),
        )
        job.result()
    check = next(
        client.query(
            f"SELECT COUNT(*) n,COUNT(DISTINCT anchor_id) ids FROM `{table_id}` WHERE experiment_id=@experiment",
            job_config=config,
        ).result()
    )
    if int(check["n"]) != len(rows) or int(check["ids"]) != len(rows):
        raise RuntimeError("Day 26 result reconciliation failed.")


def persist_summary(
    client: Any,
    bigquery: Any,
    not_found: type[Exception],
    table_id: str,
    experiment: str,
    summary: dict[str, Any],
    recorded_at: str,
    canonical_json: Any,
) -> None:
    schema = [
        bigquery.SchemaField("experiment_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("base_sha", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("head_sha", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("payload_digest", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("summary_payload_json", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("recorded_at_utc", "TIMESTAMP", mode="REQUIRED"),
    ]
    ensure_table(client, bigquery, not_found, table_id, schema)
    config = query_config(bigquery, [("experiment", "STRING", experiment)])
    existing = [
        str(item["payload_digest"])
        for item in client.query(
            f"SELECT payload_digest FROM `{table_id}` WHERE experiment_id=@experiment",
            job_config=config,
        ).result()
    ]
    if existing and existing != [summary["summary_digest"]]:
        raise RuntimeError("Immutable Day 26 summary conflict.")
    if not existing:
        payload = {
            "experiment_id": experiment,
            "base_sha": BASE_SHA,
            "head_sha": summary["head_sha"],
            "payload_digest": summary["summary_digest"],
            "summary_payload_json": canonical_json(summary),
            "recorded_at_utc": recorded_at,
        }
        job = client.load_table_from_json(
            [payload],
            table_id,
            job_config=bigquery.LoadJobConfig(schema=schema, write_disposition="WRITE_APPEND"),
        )
        job.result()
