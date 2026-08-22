from __future__ import annotations

from typing import Any

import day26_acceptance_support as support


QUERY_TIMEOUT_SECONDS = 180


def _fast_query_rows(
    client: Any,
    sql: str,
    *,
    label: str,
    job_config: Any | None = None,
) -> list[dict[str, Any]]:
    """Fetch a completed BigQuery result through the Storage API.

    The Day-26 acceptance query can return hundreds of thousands of duplicated
    anchor/candle rows. The normal REST RowIterator is correct but painfully
    slow in Cloud Shell. BigQuery Storage preserves the same query result while
    using the bulk read path. Scientific logic and frozen evidence are unchanged.
    """

    print(f"WAREHOUSE {label}: query start", flush=True)
    job = client.query(sql, job_config=job_config)
    iterator = job.result(timeout=QUERY_TIMEOUT_SECONDS)
    print(f"WAREHOUSE {label}: query complete; bulk retrieval start", flush=True)
    table = iterator.to_arrow(create_bqstorage_client=True)
    rows = table.to_pylist()
    print(f"WAREHOUSE {label}: bulk retrieval complete rows={len(rows)}", flush=True)
    return rows


def main() -> int:
    # Existing support functions resolve _query_rows from their module globals at
    # call time, so this transport-only replacement applies to candidate,
    # retrospective-window and PIT reads without changing any acceptance logic.
    support._query_rows = _fast_query_rows

    import day26_price_structure_acceptance as acceptance

    return acceptance.main()


if __name__ == "__main__":
    raise SystemExit(main())
