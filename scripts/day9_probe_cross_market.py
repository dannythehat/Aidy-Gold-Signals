from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import urlparse

from aidy.cross_market import (
    ENABLED_SERIES,
    CrossMarketGateway,
    CrossMarketObservation,
)


def _validate(observations: list[CrossMarketObservation]) -> dict[str, object]:
    if {item.series_id for item in observations} != set(ENABLED_SERIES):
        raise RuntimeError("Cross-market live probe series mismatch.")
    today = datetime.now(UTC).date()
    output: dict[str, object] = {}
    for item in observations:
        if item.observation_date > today:
            raise RuntimeError(f"Future cross-market observation date: {item.series_id}")
        if urlparse(item.source_url).hostname not in {"fred.stlouisfed.org", "home.treasury.gov"}:
            raise RuntimeError(f"Unexpected cross-market source host: {item.series_id}")
        value = Decimal(item.value)
        if item.unit == "percent" and not Decimal(-20) < value < Decimal(30):
            raise RuntimeError(f"Implausible Treasury yield: {item.series_id}")
        if item.unit == "index_jan_2006_100" and not Decimal(20) < value < Decimal(300):
            raise RuntimeError("Implausible broad-dollar index value.")
        output[item.series_id] = {
            "source": item.source,
            "observation_date": item.observation_date.isoformat(),
            "value": item.value,
            "unit": item.unit,
            "source_host": urlparse(item.source_url).hostname,
            "payload_digest": item.payload_digest,
            "source_document_digest": item.source_document_digest,
        }
    return output


async def _round(gateway: CrossMarketGateway) -> list[CrossMarketObservation]:
    dollar = await gateway.fetch_broad_dollar()
    nominal = await gateway.fetch_treasury_nominal()
    real = await gateway.fetch_treasury_real()
    return [dollar, *nominal, *real]


async def probe() -> dict[str, object]:
    gateway = CrossMarketGateway(timeout_seconds=30)
    first = _validate(await _round(gateway))
    second = _validate(await _round(gateway))
    if set(first) != set(second):
        raise RuntimeError("Repeated cross-market pulls changed series membership.")
    return {
        "status": "PASS",
        "observed_at": datetime.now(UTC).isoformat(),
        "round_1": first,
        "round_2": second,
        "series": list(ENABLED_SERIES),
        "authentication": "none",
        "frequency": "daily_context",
    }


def main() -> int:
    try:
        print(json.dumps(asyncio.run(probe()), sort_keys=True))
        return 0
    except Exception as exc:
        print(f"DAY9_SOURCE_PROBE_ERROR={type(exc).__name__}:{exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
