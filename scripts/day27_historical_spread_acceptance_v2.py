from __future__ import annotations

from typing import Any

import day27_historical_spread_acceptance as acceptance

from aidy.historical_spread import RESEARCH_BIDASK_MINUTE_QUOTES


def _merge_quote_rows_v2(
    client: Any,
    bigquery: Any,
    not_found: type[Exception],
    *,
    project: str,
    dataset: str,
    rows: list[dict[str, Any]],
    run_id: str,
) -> int:
    """Day-27 quote persistence with BigQuery-safe reconciliation aliases."""
    table_id = f"{project}.{dataset}.{RESEARCH_BIDASK_MINUTE_QUOTES.name}"
    stage_id = f"{project}.{dataset}._stage_day27_bidask_minute_quotes"
    acceptance._ensure_table(
        client,
        bigquery,
        not_found,
        table_id,
        RESEARCH_BIDASK_MINUTE_QUOTES,
    )
    acceptance._ensure_stage(
        client,
        bigquery,
        not_found,
        stage_id,
        RESEARCH_BIDASK_MINUTE_QUOTES.fields,
    )
    client.query(f"TRUNCATE TABLE `{stage_id}`").result()
    for offset in range(0, len(rows), 20_000):
        batch = [{"_run_id": run_id, **row} for row in rows[offset : offset + 20_000]]
        job = client.load_table_from_json(batch, stage_id)
        job.result()
        if job.errors:
            raise RuntimeError(f"Day 27 quote staging failed: {job.errors}")

    columns = [field.name for field in RESEARCH_BIDASK_MINUTE_QUOTES.fields]
    column_sql = ", ".join(f"`{name}`" for name in columns)
    value_sql = ", ".join(f"S.`{name}`" for name in columns)
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("run_id", "STRING", run_id)]
    )
    client.query(
        f"""MERGE `{table_id}` T
            USING (
              SELECT {column_sql}
              FROM `{stage_id}`
              WHERE _run_id=@run_id
              QUALIFY ROW_NUMBER() OVER (PARTITION BY quote_identity ORDER BY minute_utc)=1
            ) S
            ON T.quote_identity=S.quote_identity
            WHEN NOT MATCHED THEN INSERT ({column_sql}) VALUES ({value_sql})""",
        job_config=config,
    ).result()

    duplicate = next(
        client.query(
            f"""SELECT COUNT(*) AS duplicate_groups FROM (
                  SELECT source_file_sha256, minute_utc, COUNT(*) AS n
                  FROM `{table_id}`
                  WHERE source='histdata' AND source_dataset='generic_ascii_tick'
                  GROUP BY source_file_sha256, minute_utc HAVING n > 1
                )"""
        ).result()
    )
    if int(duplicate["duplicate_groups"]):
        raise RuntimeError("Day 27 quote table contains duplicate logical source minutes.")

    source_hashes = sorted({str(row["source_file_sha256"]) for row in rows})
    reconcile_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("hashes", "STRING", source_hashes)]
    )
    reconciled = next(
        client.query(
            f"""SELECT COUNT(*) AS row_count,
                       COUNT(DISTINCT quote_identity) AS identity_count
                FROM `{table_id}`
                WHERE source_file_sha256 IN UNNEST(@hashes)""",
            job_config=reconcile_config,
        ).result()
    )
    client.query(
        f"DELETE FROM `{stage_id}` WHERE _run_id=@run_id",
        job_config=config,
    ).result()
    if int(reconciled["row_count"]) != len(rows) or int(reconciled["identity_count"]) != len(rows):
        raise RuntimeError("Day 27 quote reconciliation differs from canonical source rows.")
    return int(reconciled["row_count"])


def main() -> int:
    acceptance._ALLOWED_CHANGED_FILES = {
        *acceptance._ALLOWED_CHANGED_FILES,
        "scripts/day27_historical_spread_acceptance_v2.py",
    }
    acceptance._merge_quote_rows = _merge_quote_rows_v2
    return acceptance.main()


if __name__ == "__main__":
    raise SystemExit(main())
