from __future__ import annotations

import json
import traceback
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from workers import Response, WorkerEntrypoint

from aidy.cloudflare_storage import R2ArchiveStore
from aidy.config import AidySettings
from aidy.continuity_auditor import audit_window
from aidy.cross_market import CrossMarketGateway
from aidy.cross_market_recorder import AidyCrossMarketRecorderService
from aidy.cross_market_storage import D1CrossMarketOperationalEvidenceStore
from aidy.forward_live_observer import live_forward_status, observe_private_forward_snapshot
from aidy.reference_continuity import D1R2ReferenceContinuityReader, ReferenceContinuityPolicy
from aidy.runtime import run_worker_scheduled_cycle
from aidy.storage_contracts import AidyMarketRepository


def _repository(env):
    operational = D1CrossMarketOperationalEvidenceStore(env.AIDY_OPS)
    return operational, AidyMarketRepository(operational, R2ArchiveStore(env.AIDY_MEMORY))


def _formal_forward_enabled(env) -> bool:
    return str(getattr(env, "AIDY_FORMAL_FORWARD_ENABLED", "false")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _scheduled_at_from_queue_body(body: object) -> datetime:
    if not isinstance(body, dict):
        raise TypeError("AIDY queue message body must be an object.")
    raw = body.get("scheduledTime")
    if isinstance(raw, bool) or raw is None:
        raise ValueError("AIDY queue message is missing scheduledTime.")
    try:
        milliseconds = float(raw)
        scheduled_at = datetime.fromtimestamp(milliseconds / 1000.0, tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError) as exc:
        raise ValueError("AIDY queue scheduledTime is invalid.") from exc
    return scheduled_at


async def _write_test_queue_error(env, settings: AidySettings | None, exc: Exception) -> None:
    del settings
    if str(getattr(env, "AIDY_ENV", "")).lower() != "test":
        return
    payload = {
        "observed_at": datetime.now(UTC).isoformat(),
        "exception_type": type(exc).__name__,
        "message": str(exc)[:1000],
        "traceback": traceback.format_exc()[-6000:],
    }
    await env.AIDY_MEMORY.put(
        "diagnostics/day2-queue-consumer-error.json",
        json.dumps(payload, sort_keys=True),
    )


async def _write_test_forward_error(env, exc: Exception, *, scheduled_at: datetime) -> None:
    if str(getattr(env, "AIDY_ENV", "")).lower() != "test":
        return
    payload = {
        "observed_at": datetime.now(UTC).isoformat(),
        "scheduled_at": scheduled_at.astimezone(UTC).isoformat(),
        "exception_type": type(exc).__name__,
        "message": str(exc)[:1000],
        "traceback": traceback.format_exc()[-6000:],
        "capture_retry_requested": False,
        "reason": "forward_observer_failure_must_not_duplicate_market_capture",
    }
    await env.AIDY_MEMORY.put(
        "diagnostics/day53-forward-observer-error.json",
        json.dumps(payload, sort_keys=True),
    )


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        url = urlparse(request.url)
        if request.method == "GET" and url.path == "/health":
            settings = AidySettings.from_worker_env(self.env)
            return Response.json(
                {
                    "service": "aidy-signals",
                    "status": "ok",
                    "runtime": "cloudflare-workers",
                    "environment": str(getattr(self.env, "AIDY_ENV", "unknown")),
                    "capture_enabled": settings.capture_enabled,
                    "formal_forward_enabled": _formal_forward_enabled(self.env),
                    "market_data_source": settings.market_data_source,
                    "market_data_ownership": settings.market_data_ownership,
                    "cross_market_source": "public_official_daily",
                    "scheduler": "queue-consumer",
                }
            )

        if request.method == "GET" and url.path == "/day53/forward-status":
            if str(self.env.AIDY_ENV).lower() != "test":
                return Response("Not found", status=404)
            try:
                status = await live_forward_status(self.env.AIDY_OPS)
            except (TypeError, ValueError, RuntimeError) as exc:
                return Response.json(
                    {"ok": False, "error": type(exc).__name__, "message": str(exc)},
                    status=500,
                )
            status["deployment_enabled"] = _formal_forward_enabled(self.env)
            return Response.json({"ok": True, "forward": status})

        if request.method == "POST" and url.path == "/day1/storage-smoke":
            if str(self.env.AIDY_ENV).lower() != "test":
                return Response("Not found", status=404)
            operational, repository = _repository(self.env)
            probe = await operational.create_storage_smoke_probe(now=datetime.now(UTC))
            flushed = await repository.flush_archive_outbox(limit=100)
            if probe.outbox_id is None or probe.archive_key is None:
                return Response.json({"ok": False, "error": "probe_commit_invalid"}, status=500)
            status = await operational.archive_status(outbox_id=probe.outbox_id)
            archived_object = await self.env.AIDY_MEMORY.head(probe.archive_key)
            ok = status == "archived" and archived_object is not None
            return Response.json(
                {
                    "ok": ok,
                    "probe_id": str(probe.evidence_id),
                    "archive_key": probe.archive_key,
                    "outbox_status": status,
                    "flush": {
                        "attempted": flushed.attempted,
                        "archived": flushed.archived,
                        "failed": flushed.failed,
                    },
                },
                status=200 if ok else 503,
            )

        if request.method == "POST" and url.path == "/day9/cross-market-smoke":
            if str(self.env.AIDY_ENV).lower() != "test":
                return Response("Not found", status=404)
            try:
                operational, repository = _repository(self.env)
                capture = await AidyCrossMarketRecorderService(
                    repository=repository,
                    gateway=CrossMarketGateway(),
                ).capture_once()
                flushed = await repository.flush_archive_outbox(limit=100)
                rows_result = await self.env.AIDY_OPS.prepare(
                    """
                    SELECT id,source,series_id,observation_date,value,unit,first_observed_at,
                           revision_index,payload_digest,archive_key
                    FROM cross_market_observations c
                    WHERE NOT EXISTS (
                        SELECT 1 FROM cross_market_observations newer
                        WHERE newer.source=c.source AND newer.series_id=c.series_id
                          AND newer.observation_date=c.observation_date
                          AND newer.revision_index > c.revision_index
                    )
                    ORDER BY series_id,observation_date DESC
                    """
                ).all()
                rows = rows_result.results if hasattr(rows_result, "results") else []
                latest: dict[str, object] = {}
                for row in rows or []:
                    series_id = str(row["series_id"])
                    if series_id not in latest:
                        latest[series_id] = dict(row)
                pending_row = await self.env.AIDY_OPS.prepare(
                    "SELECT COUNT(*) AS n FROM cross_market_archive_outbox WHERE status='pending'"
                ).first()
                pending = 0 if pending_row is None else int(pending_row["n"])
                ok = capture.sources_failed == 0 and len(latest) == 4 and pending == 0
                return Response.json(
                    {
                        "ok": ok,
                        "capture": {
                            "sources_checked": capture.sources_checked,
                            "sources_failed": capture.sources_failed,
                            "observations_seen": capture.observations_seen,
                            "observations_added": capture.observations_added,
                        },
                        "archive": {
                            "attempted": flushed.attempted,
                            "archived": flushed.archived,
                            "failed": flushed.failed,
                            "pending": pending,
                        },
                        "latest": latest,
                    },
                    status=200 if ok else 503,
                )
            except Exception as exc:  # noqa: BLE001 - test-only endpoint must expose diagnosis
                return Response.json(
                    {
                        "ok": False,
                        "error": type(exc).__name__,
                        "message": str(exc)[:1000],
                    },
                    status=500,
                )

        if request.method == "GET" and url.path == "/day3/continuity":
            if str(self.env.AIDY_ENV).lower() != "test":
                return Response("Not found", status=404)
            try:
                query = parse_qs(url.query)
                minutes = int(query.get("minutes", ["10"])[0])
                archive_limit = int(query.get("archive_limit", ["40"])[0])
                start, end = audit_window(end=datetime.now(UTC), minutes=minutes)
                settings = AidySettings.from_worker_env(self.env)
                report = await D1R2ReferenceContinuityReader(
                    self.env.AIDY_OPS,
                    self.env.AIDY_MEMORY,
                ).load_and_audit(
                    start=start,
                    end=end,
                    archive_limit=archive_limit,
                    policy=ReferenceContinuityPolicy(
                        expected_source=settings.market_data_source,
                        capture_enabled=settings.capture_enabled,
                        ownership_confirmed=(
                            settings.market_data_ownership == "public_independent"
                        ),
                        stale_quote_seconds=settings.market_stale_seconds,
                    ),
                )
            except (TypeError, ValueError, RuntimeError) as exc:
                return Response.json(
                    {"ok": False, "error": type(exc).__name__, "message": str(exc)},
                    status=400,
                )
            return Response.json(
                {"ok": report.passed, "report": report.as_dict()},
                status=200 if report.passed else 503,
            )

        return Response("Not found", status=404)

    async def queue(self, batch, env, ctx):
        """Consume one scheduled-capture message using Cloudflare's Python queue ABI."""
        del env, ctx
        worker_env = self.env
        settings: AidySettings | None = None
        for message in batch.messages:
            try:
                settings = AidySettings.from_worker_env(worker_env)
                _, repository = _repository(worker_env)
                scheduled_at = _scheduled_at_from_queue_body(message.body)
                result = await run_worker_scheduled_cycle(
                    settings,
                    repository=repository,
                    scheduled_at=scheduled_at,
                )
            except Exception as exc:  # noqa: BLE001 - capture failures must retry safely
                await _write_test_queue_error(worker_env, settings, exc)
                message.retry(delaySeconds=30)
                continue

            if _formal_forward_enabled(worker_env):
                snapshot_id = None if result.market is None else result.market.snapshot_id
                try:
                    await observe_private_forward_snapshot(
                        d1=worker_env.AIDY_OPS,
                        scheduled_at=scheduled_at,
                        snapshot_id=snapshot_id,
                    )
                except Exception as exc:  # noqa: BLE001 - do not duplicate successful capture
                    await _write_test_forward_error(worker_env, exc, scheduled_at=scheduled_at)

            message.ack()
