from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse

from workers import Response

from aidy.config import AidySettings
from aidy.data_health import collect_and_record_data_health, collect_data_health
from aidy.episode_memory_runtime import sync_aidy_episode_memory_runtime
from aidy.gold_cycle_environment import GOLD_CYCLE_ENVIRONMENT_VERSION
from aidy.gold_cycle_memory import GOLD_CYCLE_MEMORY_VERSION, sync_gold_cycle_memory
from aidy.gold_marker_brain import GOLD_MARKER_BRAIN_VERSION
from aidy.gold_scorecard_api import GOLD_SCORECARD_API_VERSION, gold_scorecard_response
from aidy.gold_movement_investigator import GOLD_MOVEMENT_INVESTIGATOR_VERSION
from aidy.gold_movement_memory import (
    GOLD_MOVEMENT_MEMORY_VERSION,
    sync_gold_movement_memory,
)
from aidy.gold_state_engine import GOLD_STATE_ENGINE_VERSION, PROVIDER_GOLD_STATE_VERSION
from aidy.gold_toolbox_registry import GOLD_TOOLBOX_MANIFEST_VERSION
from aidy.provider_calibration_api import calibration_market_ohlc_response
from aidy.provider_context_api import PROVIDER_CONTEXT_API_VERSION, provider_context_response
from aidy.provider_data_health_api import provider_data_health_response
from aidy.provider_decision_memory_api import provider_decision_memory_response
from aidy.provider_market_api import market_ohlc_response, research_market_ohlc_response
from entry import Default as CoreDefault


class _DirectCronMessage:
    """Adapt a Cron Trigger into the existing single-message capture contract."""

    def __init__(self, *, scheduled_time: object, cron: object) -> None:
        self.body = {"scheduledTime": scheduled_time, "cron": cron}
        self.acked = False

    def ack(self) -> None:
        self.acked = True

    def retry(self, *, delaySeconds: int | None = None) -> None:
        del delaySeconds
        # Queue retries do not exist on a direct Cron Trigger. Surface the capture
        # failure so Cloudflare records the scheduled event as failed; the next
        # deterministic Cron tick is the safe retry boundary.
        raise RuntimeError("aidy_direct_cron_capture_retry_requested")


class _DirectCronBatch:
    def __init__(self, message: _DirectCronMessage) -> None:
        self.messages = [message]


def _bool_env(env: object, name: str, default: str = "false") -> bool:
    return str(getattr(env, name, default)).strip().lower() in {"1", "true", "yes", "on"}


async def _public_health_response(env: object):
    """Production health must describe the brain, not merely the Worker process."""

    settings = AidySettings.from_worker_env(env)
    try:
        data_health = await collect_data_health(
            env.AIDY_OPS,
            now=datetime.now(UTC),
            capture_enabled=settings.capture_enabled,
            market_data_source=settings.market_data_source,
            scheduler="direct-cron",
        )
        health_summary = {
            "status": data_health.status,
            "alert": data_health.alert,
            "reason": data_health.reason,
            "session_open": data_health.session_open,
            "latest_scheduled_success_utc": data_health.latest_scheduled_success_utc,
            "latest_provider_context_snapshot_utc": (
                data_health.latest_provider_context_snapshot_utc
            ),
            "success_lag_seconds": data_health.success_lag_seconds,
            "provider_context_snapshot_lag_seconds": (
                data_health.provider_context_snapshot_lag_seconds
            ),
            "health_version": data_health.health_version,
        }
        overall_status = "degraded" if data_health.alert else "ok"
    except Exception as exc:  # noqa: BLE001 - public health must fail visibly, not crash
        health_summary = {
            "status": "monitor_error",
            "alert": True,
            "reason": "AIDY data-health evidence could not be read",
            "exception_type": type(exc).__name__,
            "message": str(exc)[:300],
        }
        overall_status = "degraded"

    return Response.json(
        {
            "service": "aidy-signals",
            "status": overall_status,
            "runtime": "cloudflare-workers",
            "environment": str(getattr(env, "AIDY_ENV", "unknown")),
            "capture_enabled": settings.capture_enabled,
            "formal_forward_enabled": _bool_env(env, "AIDY_FORMAL_FORWARD_ENABLED"),
            "private_forward_model_gateway_configured": bool(
                str(getattr(env, "OPENAI_API_KEY", "")).strip()
            ),
            "market_data_source": settings.market_data_source,
            "market_data_ownership": settings.market_data_ownership,
            "cross_market_source": "public_official_daily",
            "scheduler": "direct-cron",
            "provider_context_api_version": PROVIDER_CONTEXT_API_VERSION,
            "gold_state_engine_version": GOLD_STATE_ENGINE_VERSION,
            "provider_gold_state_version": PROVIDER_GOLD_STATE_VERSION,
            "gold_movement_investigator_version": GOLD_MOVEMENT_INVESTIGATOR_VERSION,
            "gold_movement_memory_version": GOLD_MOVEMENT_MEMORY_VERSION,
            "gold_cycle_memory_version": GOLD_CYCLE_MEMORY_VERSION,
            "gold_cycle_environment_version": GOLD_CYCLE_ENVIRONMENT_VERSION,
            "gold_marker_brain_version": GOLD_MARKER_BRAIN_VERSION,
            "gold_scorecard_api_version": GOLD_SCORECARD_API_VERSION,
            "gold_toolbox_manifest_version": GOLD_TOOLBOX_MANIFEST_VERSION,
            "data_health": health_summary,
        }
    )


async def _sync_gold_cycle_memory_best_effort(env: object) -> None:
    """Freeze/resolve 15-minute Gold cycle views without risking market capture."""

    now = datetime.now(UTC)
    try:
        result = await sync_gold_cycle_memory(
            env.AIDY_OPS,
            now_utc=now,
        )
        creation = result.get("creation") or {}
        resolution = result.get("resolution") or {}
        backfill = result.get("backfill") or {}
        try:
            await env.AIDY_OPS.prepare(
                """
                INSERT INTO aidy_gold_cycle_sync_health (
                    singleton_id,observed_at_utc,status,creation_created,
                    creation_reason,view_direction,resolution_resolved,
                    backfill_views,backfill_markers_scored,error_type,error_message
                ) VALUES (1,?,'ok',?,?,?,?,?,?,NULL,NULL)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    observed_at_utc=excluded.observed_at_utc,
                    status='ok',
                    creation_created=excluded.creation_created,
                    creation_reason=excluded.creation_reason,
                    view_direction=excluded.view_direction,
                    resolution_resolved=excluded.resolution_resolved,
                    backfill_views=excluded.backfill_views,
                    backfill_markers_scored=excluded.backfill_markers_scored,
                    error_type=NULL,
                    error_message=NULL
                """
            ).bind(
                now.isoformat(),
                int(bool(creation.get("created"))),
                str(creation.get("reason") or ""),
                (
                    None
                    if creation.get("view_direction") is None
                    else str(creation.get("view_direction"))
                ),
                int(resolution.get("resolved") or 0),
                int(backfill.get("views_backfilled") or 0),
                int(backfill.get("markers_scored") or 0),
            ).run()
        except Exception as health_exc:  # noqa: BLE001 - diagnostics cannot risk capture
            print(
                "AIDY Gold-cycle sync health write failed: "
                f"{type(health_exc).__name__}: {str(health_exc)[:300]}"
            )
        if creation.get("created") or int(resolution.get("resolved") or 0):
            print(
                "AIDY Gold-cycle memory sync: "
                f"created={creation.get('created')} "
                f"direction={creation.get('view_direction')} "
                f"resolved={resolution.get('resolved')}"
            )
    except Exception as exc:  # noqa: BLE001 - learning cannot undo successful capture
        try:
            await env.AIDY_OPS.prepare(
                """
                INSERT INTO aidy_gold_cycle_sync_health (
                    singleton_id,observed_at_utc,status,creation_created,
                    creation_reason,view_direction,resolution_resolved,
                    backfill_views,backfill_markers_scored,error_type,error_message
                ) VALUES (1,?,'error',NULL,NULL,NULL,NULL,NULL,NULL,?,?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    observed_at_utc=excluded.observed_at_utc,
                    status='error',
                    creation_created=NULL,
                    creation_reason=NULL,
                    view_direction=NULL,
                    resolution_resolved=NULL,
                    backfill_views=NULL,
                    backfill_markers_scored=NULL,
                    error_type=excluded.error_type,
                    error_message=excluded.error_message
                """
            ).bind(
                now.isoformat(),
                type(exc).__name__,
                str(exc)[:1000],
            ).run()
        except Exception as health_exc:  # noqa: BLE001 - diagnostics cannot risk capture
            print(
                "AIDY Gold-cycle sync error health write failed: "
                f"{type(health_exc).__name__}: {str(health_exc)[:300]}"
            )
        print(
            "AIDY Gold-cycle memory sync failed: "
            f"{type(exc).__name__}: {str(exc)[:500]}"
        )


async def _record_health_best_effort(env: object, *, scheduler: str) -> None:
    """Observability may report a failure but must never undo a successful capture."""

    try:
        settings = AidySettings.from_worker_env(env)
        await collect_and_record_data_health(
            env.AIDY_OPS,
            now=datetime.now(UTC),
            capture_enabled=settings.capture_enabled,
            market_data_source=settings.market_data_source,
            scheduler=scheduler,
        )
    except Exception as exc:  # noqa: BLE001 - capture is more important than telemetry
        print(f"AIDY data-health telemetry failed: {type(exc).__name__}: {str(exc)[:500]}")


async def _sync_episode_memory_best_effort(env: object) -> None:
    """Close the decision->outcome->learning loop without risking market capture."""

    try:
        result = await sync_aidy_episode_memory_runtime(
            env.AIDY_OPS,
            now_utc=datetime.now(UTC),
        )
        changed = (
            int(result.get("episodes_materialized") or 0)
            + int((result.get("forward_outcomes") or {}).get("resolved") or 0)
            + int(result.get("outcomes_materialized") or 0)
            + int(result.get("learning_cards_materialized") or 0)
        )
        if changed:
            print(
                "AIDY episode-memory sync: "
                f"episodes={result.get('episodes_materialized')} "
                f"outcomes={result.get('outcomes_materialized')} "
                f"cards={result.get('learning_cards_materialized')}"
            )
    except Exception as exc:  # noqa: BLE001 - memory cannot undo successful capture
        print(f"AIDY episode-memory sync failed: {type(exc).__name__}: {str(exc)[:500]}")


async def _sync_gold_movement_memory_best_effort(env: object) -> None:
    """Detect, diagnose and learn from abnormal Gold moves without risking capture."""

    try:
        result = await sync_gold_movement_memory(
            env.AIDY_OPS,
            now_utc=datetime.now(UTC),
        )
        detection = result.get("detection") or {}
        resolution = result.get("resolution") or {}
        changed = (
            int(detection.get("episodes_stored") or 0)
            + int(resolution.get("cards_stored") or 0)
        )
        if changed:
            print(
                "AIDY Gold-movement memory sync: "
                f"episodes={detection.get('episodes_stored')} "
                f"cards={resolution.get('cards_stored')}"
            )
    except Exception as exc:  # noqa: BLE001 - learning cannot undo successful capture
        print(
            "AIDY Gold-movement memory sync failed: "
            f"{type(exc).__name__}: {str(exc)[:500]}"
        )


class Default(CoreDefault):
    async def fetch(self, request):
        path = urlparse(request.url).path
        if request.method == "GET" and path == "/health":
            return await _public_health_response(self.env)
        if path == "/market/ohlc":
            return await market_ohlc_response(request, self.env)
        if path == "/calibration/market/ohlc":
            return await calibration_market_ohlc_response(request, self.env)
        if path == "/research/market/ohlc":
            return await research_market_ohlc_response(request, self.env)
        if path == "/provider/context":
            return await provider_context_response(request, self.env)
        if path == "/provider/gold-scorecard":
            return await gold_scorecard_response(request, self.env)
        if path == "/provider/data-health":
            return await provider_data_health_response(request, self.env)
        if path == "/provider/decision-memory":
            return await provider_decision_memory_response(request, self.env)
        return await super().fetch(request)

    async def scheduled(self, controller, env, ctx):
        """Run capture directly from Cloudflare Cron without Queue operations.

        Cloudflare's Python scheduled ABI can pass ``env`` as None; bindings live on
        ``self.env`` just as the core queue consumer already expects. Always use
        the bound Worker environment for health and memory so a successful capture
        leaves both point-in-time health evidence and permanent decision memory.
        """
        message = _DirectCronMessage(
            scheduled_time=controller.scheduledTime,
            cron=controller.cron,
        )
        try:
            await super().queue(_DirectCronBatch(message), env, ctx)
        finally:
            await _sync_episode_memory_best_effort(self.env)
            await _sync_gold_movement_memory_best_effort(self.env)
            await _sync_gold_cycle_memory_best_effort(self.env)
            await _record_health_best_effort(self.env, scheduler="direct-cron")
        if not message.acked:
            raise RuntimeError("aidy_direct_cron_capture_not_acknowledged")

    async def queue(self, batch, env, ctx):
        """Retain the Queue ABI for safe rollback; production has no Queue consumer."""
        try:
            return await super().queue(batch, env, ctx)
        finally:
            await _sync_episode_memory_best_effort(self.env)
            await _sync_gold_movement_memory_best_effort(self.env)
            await _sync_gold_cycle_memory_best_effort(self.env)
            await _record_health_best_effort(self.env, scheduler="queue-consumer")
