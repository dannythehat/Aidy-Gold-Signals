from __future__ import annotations

from datetime import UTC, datetime

from workers import Response, WorkerEntrypoint

from aidy.twelve_data_market import latest_completed_d1_bucket


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        del request
        summer_start, summer_close = latest_completed_d1_bucket(
            datetime(2026, 7, 2, 22, 0, tzinfo=UTC)
        )
        winter_start, winter_close = latest_completed_d1_bucket(
            datetime(2026, 1, 2, 23, 0, tzinfo=UTC)
        )
        expected = {
            "summer_start_utc": "2026-07-01T22:00:00+00:00",
            "summer_close_utc": "2026-07-02T21:00:00+00:00",
            "winter_start_utc": "2026-01-01T23:00:00+00:00",
            "winter_close_utc": "2026-01-02T22:00:00+00:00",
        }
        observed = {
            "summer_start_utc": summer_start.isoformat(),
            "summer_close_utc": summer_close.isoformat(),
            "winter_start_utc": winter_start.isoformat(),
            "winter_close_utc": winter_close.isoformat(),
        }
        ok = observed == expected
        return Response.json(
            {
                "ok": ok,
                "zone": "America/New_York",
                "fallback_fixed_offset_allowed": False,
                "expected": expected,
                "observed": observed,
            },
            status=200 if ok else 503,
        )
