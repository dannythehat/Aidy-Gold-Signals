"""Portable AIDY recorder orchestration.

Cloudflare Workers own production scheduling. Live market capture is broker-free:
AIDY reads public-independent XAU/USD evidence and never reads account state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .argentapi_gateway import ArgentApiGateway
from .config import AidySettings
from .cross_market import CrossMarketGateway
from .cross_market_recorder import AidyCrossMarketRecorderService, CrossMarketCaptureResult
from .fed_recorder import AidyFedRssRecorderService
from .fed_rss import FedRssCaptureResult, FedRssGateway
from .gold_api_gateway import GoldApiGateway
from .live_gold_recorder import AidyLiveGoldRecorderService, LiveGoldQuoteHistory
from .official_macro import OfficialMacroCaptureResult, OfficialMacroGateway
from .official_macro_recorder import AidyOfficialMacroRecorderService
from .reference_price_recorder import AidyReferencePriceRecorderService, ReferenceCaptureResult
from .storage_contracts import AidyMarketRepository, ArchiveFlushResult
from .twelve_data_intraday_repair import repair_intraday_provider_context_gap
from .twelve_data_market import TwelveDataOhlcGateway
from .twelve_data_recorder import AidyTwelveDataRecorderService
from .twelve_data_storage import D1TwelveDataMarketStore


@dataclass(frozen=True, slots=True)
class RecorderCycleResult:
    market: ReferenceCaptureResult | None
    fed: FedRssCaptureResult | None
    macro: OfficialMacroCaptureResult | None
    cross_market: CrossMarketCaptureResult | None
    archive: ArchiveFlushResult


# Twelve Data publishes each closed M1 bar roughly 64 seconds after the bar closes
# (observed 63.8-64.0s across every production capture on 2026-09-14). Sampling a
# just-closed aggregate bucket at the boundary therefore always misses that bucket's
# final minute, which pins 5m coverage at 0.800 and keeps all_timeframes_ready false
# forever. Market capture is offset past the boundary so the vendor has published the
# final bar before the bucket is evaluated. This changes only WHEN the decision surface
# is sampled; bucket boundaries, coverage thresholds and PIT semantics are untouched.
MARKET_PUBLICATION_LAG_OFFSET_SECONDS = 120


def interval_due(
    now: datetime,
    interval_seconds: float,
    *,
    tick_seconds: int = 60,
    offset_seconds: int = 0,
) -> bool:
    """Return whether a periodic task is due on this scheduler tick.

    ``offset_seconds`` shifts the due window later within each interval without
    changing the interval itself. The scheduler must provide a tick inside the shifted
    window; a non-zero offset with a boundary-aligned Cron would silently halve the
    capture rate.
    """

    if now.tzinfo is None:
        raise ValueError("AIDY scheduler requires a timezone-aware datetime.")
    interval = max(int(interval_seconds), tick_seconds)
    offset = int(offset_seconds) % interval
    return (int(now.astimezone(UTC).timestamp()) - offset) % interval < tick_seconds


MarketGateway = GoldApiGateway | ArgentApiGateway | TwelveDataOhlcGateway
MarketHistory = LiveGoldQuoteHistory | D1TwelveDataMarketStore


async def run_capture_cycle(
    settings: AidySettings,
    *,
    repository: AidyMarketRepository,
    now: datetime | None = None,
    include_market: bool = True,
    include_fed: bool = True,
    include_macro: bool = True,
    include_cross_market: bool = True,
    market_gateway: MarketGateway | None = None,
    live_gold_history: MarketHistory | None = None,
    fed_gateway: FedRssGateway | None = None,
    macro_gateway: OfficialMacroGateway | None = None,
    cross_market_gateway: CrossMarketGateway | None = None,
) -> RecorderCycleResult | None:
    """Run one broker-free recorder cycle.

    `now` represents only the scheduler/event evaluation time. First-observed
    timestamps are deliberately stamped by each recorder after its upstream HTTP
    response arrives, not with this nominal tick.
    """

    if not settings.capture_enabled:
        return None
    _ = (now or datetime.now(UTC)).astimezone(UTC)
    market: ReferenceCaptureResult | None = None
    fed: FedRssCaptureResult | None = None
    macro: OfficialMacroCaptureResult | None = None
    cross_market: CrossMarketCaptureResult | None = None

    if include_market:
        if settings.market_data_source == "gold_api":
            gateway = market_gateway or GoldApiGateway()
            market = await AidyReferencePriceRecorderService(
                repository=repository,
                gateway=gateway,  # type: ignore[arg-type]
                stale_seconds=settings.market_stale_seconds,
            ).capture_once()
        elif settings.market_data_source == "argentapi":
            if live_gold_history is None:
                raise RuntimeError("ArgentAPI live capture requires source-aware D1 quote history.")
            gateway = market_gateway or ArgentApiGateway(api_key="")
            market = await AidyLiveGoldRecorderService(
                repository=repository,
                gateway=gateway,  # type: ignore[arg-type]
                quote_history=live_gold_history,  # type: ignore[arg-type]
                stale_seconds=settings.market_stale_seconds,
            ).capture_once()
        elif settings.market_data_source == "twelve_data":
            if market_gateway is None or not isinstance(live_gold_history, D1TwelveDataMarketStore):
                raise RuntimeError(
                    "Twelve Data capture requires an authenticated gateway and D1 market store."
                )
            recorder = AidyTwelveDataRecorderService(
                repository=repository,
                gateway=market_gateway,  # type: ignore[arg-type]
                market_store=live_gold_history,
            )
            market = await recorder.capture_once()
            if market.status == "partial" and isinstance(market_gateway, TwelveDataOhlcGateway):
                try:
                    repair = await repair_intraday_provider_context_gap(
                        repository=repository,
                        gateway=market_gateway,
                        store=live_gold_history,
                        as_of=datetime.now(UTC),
                    )
                except Exception as exc:  # noqa: BLE001 - repair must never undo capture
                    print(
                        "AIDY intraday Provider Context self-heal failed: "
                        f"{type(exc).__name__}: {str(exc)[:500]}"
                    )
                else:
                    if repair.get("repaired") is True:
                        # Re-run the normal scheduled-capture path so the repaired,
                        # first-observed M1 evidence is aggregated into a fresh
                        # canonical snapshot. This is still fail-closed: if any
                        # required intraday minute remains missing, status stays partial.
                        market = await recorder.capture_once()
        else:
            raise RuntimeError("Unsupported AIDY market-data source.")

    if include_fed:
        fed = await AidyFedRssRecorderService(
            repository=repository,
            gateway=fed_gateway or FedRssGateway(),
        ).capture_once()

    if include_macro:
        macro = await AidyOfficialMacroRecorderService(
            repository=repository,
            gateway=macro_gateway or OfficialMacroGateway(),
        ).capture_once()

    if include_cross_market:
        cross_market = await AidyCrossMarketRecorderService(
            repository=repository,
            gateway=cross_market_gateway or CrossMarketGateway(),
        ).capture_once()

    archive = await repository.flush_archive_outbox(limit=settings.archive_flush_limit)
    return RecorderCycleResult(
        market=market,
        fed=fed,
        macro=macro,
        cross_market=cross_market,
        archive=archive,
    )


async def run_worker_scheduled_cycle(
    settings: AidySettings,
    *,
    repository: AidyMarketRepository,
    scheduled_at: datetime,
    market_gateway: MarketGateway | None = None,
    live_gold_history: MarketHistory | None = None,
) -> RecorderCycleResult:
    """Run the Cloudflare one-minute plan while always allowing archive retries."""

    scheduled_at = scheduled_at.astimezone(UTC)
    if not settings.capture_enabled:
        archive = await repository.flush_archive_outbox(limit=settings.archive_flush_limit)
        return RecorderCycleResult(
            market=None,
            fed=None,
            macro=None,
            cross_market=None,
            archive=archive,
        )

    market_due = interval_due(
        scheduled_at,
        settings.market_poll_seconds,
        offset_seconds=MARKET_PUBLICATION_LAG_OFFSET_SECONDS,
    )
    fed_due = interval_due(scheduled_at, settings.fed_rss_poll_seconds)
    macro_due = interval_due(scheduled_at, settings.macro_poll_seconds)
    cross_market_due = interval_due(scheduled_at, settings.cross_market_poll_seconds)

    if not market_due and not fed_due and not macro_due and not cross_market_due:
        archive = await repository.flush_archive_outbox(limit=settings.archive_flush_limit)
        return RecorderCycleResult(
            market=None,
            fed=None,
            macro=None,
            cross_market=None,
            archive=archive,
        )

    result = await run_capture_cycle(
        settings,
        repository=repository,
        now=scheduled_at,
        include_market=market_due,
        include_fed=fed_due,
        include_macro=macro_due,
        include_cross_market=cross_market_due,
        market_gateway=market_gateway,
        live_gold_history=live_gold_history,
    )
    assert result is not None
    return result
