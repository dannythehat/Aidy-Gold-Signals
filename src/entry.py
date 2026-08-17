from __future__ import annotations

import json
import traceback
from datetime import UTC, datetime
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint

from aidy.cloudflare_storage import D1OperationalEvidenceStore, R2ArchiveStore
from aidy.config import AidySettings
from aidy.runtime import run_worker_scheduled_cycle
from aidy.storage_contracts import AidyMarketRepository


def _repository(env):
    operational = D1OperationalEvidenceStore(env.AIDY_OPS)
    return operational, AidyMarketRepository(operational, R2ArchiveStore(env.AIDY_MEMORY))


def _scheduled_at_from_queue_body(body: object) -> datetime:
    if not isinstance(body, dict):
        raise ValueError("AIDY queue message body must be an object.")
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
    if str(getattr(env, "AIDY_ENV", "")).lower() != "test":
        return
    token = (settings.metaapi_token if settings is not None else None) or ""
    message = str(exc)
    trace = traceback.format_exc()
    if token:
        message = message.replace(token, "[redacted]")
        trace = trace.replace(token, "[redacted]")
    payload = {
        "observed_at": datetime.now(UTC).isoformat(),
        "exception_type": type(exc).__name__,
        "message": message[:1000],
        "traceback": trace[-6000:],
    }
    await env.AIDY_MEMORY.put(
        "diagnostics/day2-queue-consumer-error.json",
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
                    "scheduler": "queue-consumer",
                }
            )

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

        return Response("Not found", status=404)

    async def queue(self, batch, env, ctx):
        """Consume one scheduled-capture message using Cloudflare's Python queue ABI."""
        del ctx  # Context is not required by the deterministic capture cycle.
        settings: AidySettings | None = None
        for message in batch.messages:
            try:
                settings = AidySettings.from_worker_env(env)
                _, repository = _repository(env)
                scheduled_at = _scheduled_at_from_queue_body(message.body)
                await run_worker_scheduled_cycle(
                    settings,
                    repository=repository,
                    scheduled_at=scheduled_at,
                )
            except Exception as exc:
                await _write_test_queue_error(env, settings, exc)
                message.retry(delaySeconds=30)
            else:
                message.ack()
