"""Retrospective M1 history for provider research, structurally barred from decisions.

Shadow research needs to know whether a provider's past trades made money. That question
is about objective price history, so it can be answered from bars fetched long after the
fact. Live decisions are a different question entirely: AIDY must never reason from a bar
it could not have seen at the time, which is why scheduled capture and bootstrap are
bounded to the minutes that prove the latest six timeframes.

Those two needs collided. ``bootstrap_required_m1_open_times`` returns only the minutes
behind the latest 5m/15m/1h/4h/1d buckets, so the bootstrap path can never reach a gap
several days old -- on 2026-09-15 it could repair Monday's daily bar but not the 998
shadow trades sitting on 09-01, 09-04, 09-09 and 09-10, where capture was down.

The separation here is structural rather than procedural. Retrospective bars are written
under their own source, and ``twelve_data_decision_admitted_m1_v1`` selects
``source='twelve_data_vendor_m1_v1'``, so a retrospective bar cannot enter the
decision-admitted view, cannot reach ``/market/ohlc``, and cannot become evidence for a
forward decision. No flag governs that and no caller can opt out of it; the bars are
simply not in the set the PIT view is built from.

A retrospective bar is also never a substitute for a missing live one. Where capture
genuinely did not observe a minute, that minute stays unobserved for PIT purposes
forever. This store answers "what did the market actually do", not "what did we see".
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta

from .storage_contracts import AidyMarketRepository
from .twelve_data_market import AIDY_SYMBOL, TwelveDataOhlcGateway
from .twelve_data_storage import D1TwelveDataMarketStore

# Deliberately not RAW_M1_SOURCE. The decision-admitted view filters on that value, so
# this tag is what keeps retrospective history out of every PIT read path.
RETROSPECTIVE_M1_SOURCE = "twelve_data_retrospective_m1_v1"

# One vendor request per call, paced like the bootstrap path so a long backfill cannot
# exhaust the per-minute credit allowance shared with live capture.
MAX_RETROSPECTIVE_WINDOW_MINUTES = 240
RETROSPECTIVE_MIN_REQUEST_SPACING_SECONDS = 9.0


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Retrospective timestamps must be timezone-aware.")
    return value.astimezone(UTC)


def validate_window(start_utc: datetime, end_utc: datetime) -> tuple[datetime, datetime]:
    """Bound a retrospective request to one paced vendor call over closed history."""
    start = _utc(start_utc)
    end = _utc(end_utc)
    if start.second or start.microsecond or end.second or end.microsecond:
        raise ValueError("retrospective_window_not_minute_aligned")
    if start >= end:
        raise ValueError("retrospective_window_invalid")
    if end - start > timedelta(minutes=MAX_RETROSPECTIVE_WINDOW_MINUTES):
        raise ValueError("retrospective_window_too_large")
    # Only settled history. Anything still forming belongs to scheduled capture, and
    # fetching it here would put a bar in the store under the wrong provenance.
    if end > datetime.now(UTC) - timedelta(minutes=2):
        raise ValueError("retrospective_window_not_settled")
    return start, end


class AidyRetrospectiveBackfillService:
    """Ingest one bounded window of settled M1 history for research only."""

    def __init__(
        self,
        *,
        repository: AidyMarketRepository,
        gateway: TwelveDataOhlcGateway,
        store: D1TwelveDataMarketStore,
        sleep=asyncio.sleep,
        monotonic=time.monotonic,
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._store = store
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: float | None = None

    async def _pace_vendor_request(self) -> None:
        if self._last_request_at is not None:
            elapsed = self._monotonic() - self._last_request_at
            remaining = RETROSPECTIVE_MIN_REQUEST_SPACING_SECONDS - elapsed
            if remaining > 0:
                await self._sleep(remaining)
        self._last_request_at = self._monotonic()

    async def ingest_window(
        self, *, start_utc: datetime, end_utc: datetime
    ) -> dict[str, object]:
        start, end = validate_window(start_utc, end_utc)
        requested_at = datetime.now(UTC)
        request_id = await self._store.reserve_request(
            requested_at=requested_at,
            request_kind="retrospective_research",
            outputsize=None,
        )
        try:
            await self._pace_vendor_request()
            fetch = await self._gateway.fetch_1m(start_date=start, end_date=end)
        except Exception as exc:
            await self._store.finish_request(
                request_id=request_id,
                completed_at=datetime.now(UTC),
                status="failed",
                error_code=type(exc).__name__,
            )
            raise

        await self._store.finish_request(
            request_id=request_id,
            completed_at=fetch.fetched_at_utc,
            status="succeeded",
            fetch=fetch,
        )

        persisted = 0
        seen = 0
        for bar in sorted(fetch.closed_bars, key=lambda item: item.open_time_utc):
            if not (start <= bar.open_time_utc < end):
                continue
            seen += 1
            _, _, created = await self._repository.store_candle(
                {
                    "symbol": AIDY_SYMBOL,
                    "timeframe": "1m",
                    "open_time_utc": bar.open_time_utc,
                    "broker_open_time": None,
                    "open": str(bar.open),
                    "high": str(bar.high),
                    "low": str(bar.low),
                    "close": str(bar.close),
                    "tick_volume": None,
                    "spread": None,
                    "volume": None,
                    "source": RETROSPECTIVE_M1_SOURCE,
                    "first_observed_at": fetch.fetched_at_utc,
                    "payload_digest": bar.payload_digest,
                }
            )
            persisted += int(created)

        return {
            "ok": True,
            "window_start_utc": start.isoformat(),
            "window_end_utc": end.isoformat(),
            "vendor_minutes_returned": seen,
            "persisted_new_minutes": persisted,
            "source": RETROSPECTIVE_M1_SOURCE,
            "pit_eligible": False,
            "decision_admitted": False,
            "response_digest": fetch.response_digest,
        }


__all__ = [
    "MAX_RETROSPECTIVE_WINDOW_MINUTES",
    "RETROSPECTIVE_M1_SOURCE",
    "AidyRetrospectiveBackfillService",
    "validate_window",
]
