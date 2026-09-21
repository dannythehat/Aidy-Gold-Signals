from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aidy.databento_gc import DatabentoHistoricalClient, HistoricalRequest

WINDOW_COUNT = 40
WINDOW_MINUTES = 15
START = datetime(2025, 1, 7, 15, 0, tzinfo=UTC)


def main() -> int:
    requests: list[HistoricalRequest] = []
    for index in range(WINDOW_COUNT):
        start = START + timedelta(weeks=index)
        end = start + timedelta(minutes=WINDOW_MINUTES)
        requests.append(
            HistoricalRequest(
                schema="tbbo",
                start=start.isoformat(),
                end=end.isoformat(),
            )
        )

    quoted: list[dict[str, str]] = []
    total = Decimal(0)
    with DatabentoHistoricalClient.from_env() as client:
        entitlement = client.assert_gc_entitlement()
        for request in requests:
            quote = client.estimate_cost(request, prior_committed_usd=Decimal(0))
            total += quote.quoted_cost_usd
            quoted.append(
                {
                    "start": request.start,
                    "end": request.end,
                    "request_digest": request.request_digest,
                    "quoted_cost_usd": str(quote.quoted_cost_usd),
                }
            )

    result = {
        "ok": True,
        "mode": "quote_only_no_download",
        "provider": "Databento",
        "dataset": "GLBX.MDP3",
        "schema": "tbbo",
        "window_count": WINDOW_COUNT,
        "window_minutes": WINDOW_MINUTES,
        "independent_weekly_windows": True,
        "first_window_start_utc": requests[0].start,
        "last_window_end_utc": requests[-1].end,
        "quoted_total_usd": str(total),
        "max_window_quote_usd": str(max(Decimal(row["quoted_cost_usd"]) for row in quoted)),
        "min_window_quote_usd": str(min(Decimal(row["quoted_cost_usd"]) for row in quoted)),
        "entitlement": entitlement,
        "download_performed": False,
        "paid_activation_performed": False,
        "recurring_subscription_enabled": False,
        "owner_approval_required_before_download": True,
        "requests": quoted,
    }
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
