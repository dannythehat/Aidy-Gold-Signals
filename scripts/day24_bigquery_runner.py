from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from google.cloud import bigquery


def _load_json_rows(
    self: bigquery.Client,
    table: Any,
    json_rows: Iterable[Mapping[str, Any]],
    **_: Any,
) -> list[Any]:
    """Use the load-job path that already persisted Day 23 BigQuery JSON evidence."""
    rows = [dict(row) for row in json_rows]
    if not rows:
        return []
    job = self.load_table_from_json(rows, table)
    job.result()
    if job.errors:
        return list(job.errors)
    return []


def main() -> int:
    # google-cloud-bigquery's streaming insert path rejects native objects for
    # this environment's JSON columns. Day 23 already proved load_table_from_json
    # works for the same BigQuery JSON type. This adapter changes persistence
    # transport only; it never sees or mutates retrieval queries, gates or scores.
    bigquery.Client.insert_rows_json = _load_json_rows  # type: ignore[method-assign]

    from day24_independent_episode_acceptance import main as acceptance_main

    return acceptance_main()


if __name__ == "__main__":
    raise SystemExit(main())
