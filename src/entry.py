from __future__ import annotations

import json
import traceback
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from workers import Response, WorkerEntrypoint

from aidy.argentapi_gateway import ArgentApiGateway
from aidy.cloudflare_storage import R2ArchiveStore
from aidy.config import AidySettings
from aidy.continuity_auditor import audit_window
from aidy.cross_market import CrossMarketGateway
from aidy.cross_market_recorder import AidyCrossMarketRecorderService
from aidy.cross_market_storage import D1CrossMarketOperationalEvidenceStore
from aidy.forward_live_observer import live_forward_status, observe_private_forward_snapshot
from aidy.live_gold_storage import D1LiveGoldQuoteHistory
from aidy.openai_gateway_v2 import OpenAIMasterTraderGatewayV2
from aidy.reference_continuity import D1R2ReferenceContinuityReader, ReferenceContinuityPolicy
from aidy.runtime import run_capture_cycle, run_worker_scheduled_cycle
from aidy.storage_contracts import AidyMarketRepository
from aidy.twelve_data_bootstrap import AidyTwelveDataBootstrapService, plan_bootstrap_windows
from aidy.twelve_data_market import TwelveDataOhlcGateway, latest_completed_bucket
from aidy.twelve_data_storage import D1TwelveDataMarketStore


def _repository(env):
    operational = D1CrossMarketOperationalEvidenceStore(env.AIDY_OPS)
    return operational, AidyMarketRepository(operational, R2ArchiveStore(env.AIDY_MEMORY))


def _market_runtime_dependencies(env, settings: AidySettings):
    if settings.market_data_source == "argentapi":
        api_key = str(getattr(env, "AIDY_ARGENT_API_KEY", ""))
        return ArgentApiGateway(api_key=api_key), D1LiveGoldQuoteHistory(env.AIDY_OPS)
    if settings.market_data_source == "twelve_data":
        api_key = str(getattr(env, "AIDY_TWELVE_DATA_API_KEY", ""))
        return TwelveDataOhlcGateway(api_key=api_key), D1TwelveDataMarketStore(env.AIDY_OPS)
    return None, None


def _private_forward_gateway(env):
    api_key = str(getattr(env, "OPENAI_API_KEY", "")).strip()
    if not api_key:
        return None
    return OpenAIMasterTraderGatewayV2(api_key)


def _formal_forward_enabled(env) -> bool:
    return str(getattr(env, "AIDY_FORMAL_FORWARD_ENABLED", "false")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _twelve_data_bootstrap_enabled(env) -> bool:
    return str(getattr(env, "AIDY_TWELVE_DATA_BOOTSTRAP_ENABLED", "false")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _admin_authorized(request, env) -> bool:
    expected = str(getattr(env, "AIDY_DAY53_ADMIN_TOKEN", "")).strip()
    if not expected:
        return False
    supplied = str(request.headers.get("X-AIDY-Admin-Token") or "").strip()
    return supplied == expected


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
                    "private_forward_model_gateway_configured": (
                        bool(str(getattr(self.env, "OPENAI_API_KEY", "")).strip())
                    ),
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
            status["model_gateway_configured"] = bool(
                str(getattr(self.env, "OPENAI_API_KEY", "")).strip()
            )
            return Response.json({"ok": True, "forward": status})

        if request.method == "POST" and url.path == "/day53/twelve-data-smoke":
            if str(self.env.AIDY_ENV).lower() != "test":
                return Response("Not found", status=404)
            if not _admin_authorized(request, self.env):
                return Response("Forbidden", status=403)
            settings = AidySettings.from_worker_env(self.env)
            if settings.market_data_source != "twelve_data":
                return Response.json(
                    {"ok": False, "error": "twelve_data_not_configured"}, status=409
                )
            if parse_qs(url.query).get("bootstrap", ["0"])[0] == "1":
                return Response.json(
                    {
                        "ok": False,
                        "error": "legacy_smoke_bootstrap_disabled",
                        "bootstrap_endpoint": "/day53/twelve-data-bootstrap",
                    },
                    status=409,
                )
            market_gateway, market_store = _market_runtime_dependencies(self.env, settings)
            request_id = None
            try:
                assert isinstance(market_gateway, TwelveDataOhlcGateway)
                assert isinstance(market_store, D1TwelveDataMarketStore)
                request_id = await market_store.reserve_request(
                    requested_at=datetime.now(UTC),
                    request_kind="manual_probe",
                    outputsize=30,
                )
                fetch = await market_gateway.fetch_1m(outputsize=30)
                await market_store.finish_request(
                    request_id=request_id,
                    completed_at=fetch.fetched_at_utc,
                    status="succeeded",
                    fetch=fetch,
                )
                await market_store.record_feed_observation(fetch)
                return Response.json(
                    {
                        "ok": True,
                        "probe_only": True,
                        "decision_input_allowed": False,
                        "canonical_candles_written": 0,
                        "decision_snapshot_created": False,
                        "request_ledger_id": str(request_id),
                        "fetched_at_utc": fetch.fetched_at_utc.isoformat(),
                        "raw_bar_count": fetch.raw_bar_count,
                        "closed_bar_count": len(fetch.closed_bars),
                        "forming_bar_count": fetch.forming_bar_count,
                        "off_session_bar_count": fetch.off_session_bar_count,
                        "freshness_state": fetch.freshness_state,
                        "credit_headers": fetch.credit_headers,
                        "provider_meta": fetch.meta,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - protected test-only probe diagnosis
                if request_id is not None and isinstance(market_store, D1TwelveDataMarketStore):
                    try:
                        await market_store.finish_request(
                            request_id=request_id,
                            completed_at=datetime.now(UTC),
                            status="failed",
                            error_code=type(exc).__name__,
                        )
                    except Exception:
                        pass
                return Response.json(
                    {"ok": False, "error": type(exc).__name__, "message": str(exc)[:1000]},
                    status=500,
                )

        if request.method == "POST" and url.path == "/day53/twelve-data-bootstrap":
            if str(self.env.AIDY_ENV).lower() != "test":
                return Response("Not found", status=404)
            if not _admin_authorized(request, self.env):
                return Response("Forbidden", status=403)
            if not _twelve_data_bootstrap_enabled(self.env):
                return Response.json(
                    {"ok": False, "error": "twelve_data_bootstrap_disabled"}, status=409
                )
            settings = AidySettings.from_worker_env(self.env)
            if settings.market_data_source != "twelve_data":
                return Response.json(
                    {"ok": False, "error": "twelve_data_not_configured"}, status=409
                )
            _, repository = _repository(self.env)
            market_gateway, market_store = _market_runtime_dependencies(self.env, settings)
            bootstrap_id = None
            try:
                assert isinstance(market_gateway, TwelveDataOhlcGateway)
                assert isinstance(market_store, D1TwelveDataMarketStore)
                as_of = datetime.now(UTC)
                latest_m1_open, _ = latest_completed_bucket(as_of, "1m")
                windows = plan_bootstrap_windows(as_of, latest_m1_open_utc=latest_m1_open)
                if not windows:
                    return Response.json({"ok": False, "error": "bootstrap_plan_empty"}, status=503)
                all_required = frozenset().union(*(window.required_opens for window in windows))
                admitted_rows = await market_store.latest_m1_bars(
                    start_utc=windows[0].start_utc,
                    end_utc=windows[-1].end_utc,
                )
                admitted_opens = set()
                for row in admitted_rows:
                    raw_open = row.get("open_time_utc")
                    parsed_open = raw_open if isinstance(raw_open, datetime) else datetime.fromisoformat(str(raw_open))
                    if parsed_open.tzinfo is None:
                        raise ValueError("Admitted Twelve M1 timestamp must be timezone-aware.")
                    admitted_opens.add(parsed_open.astimezone(UTC))
                missing_required = all_required - admitted_opens
                if not missing_required:
                    return Response.json(
                        {
                            "ok": True,
                            "bootstrap_id": None,
                            "state": "complete",
                            "planned_windows": 0,
                            "required_m1_minutes": len(all_required),
                            "remaining_m1_minutes": 0,
                            "window_results": [],
                            "decision_snapshot_created": False,
                            "decision_ready": False,
                            "next_step": "wait_for_fresh_scheduled_capture",
                        }
                    )
                target = next(window for window in windows if window.required_opens & missing_required)
                bootstrap_id = await market_store.start_bootstrap(
                    started_at=as_of,
                    as_of=as_of,
                    planned_windows=1,
                    required_m1_minutes=len(target.required_opens),
                )
                service = AidyTwelveDataBootstrapService(
                    repository=repository,
                    gateway=market_gateway,
                    store=market_store,
                )
                result = await service.ingest_window(bootstrap_id=bootstrap_id, window=target)
                complete = await market_store.finalize_bootstrap(
                    bootstrap_id=bootstrap_id,
                    completed_at=datetime.now(UTC),
                )
                if not complete or result.get("state") != "succeeded":
                    return Response.json(
                        {
                            "ok": False,
                            "bootstrap_id": str(bootstrap_id),
                            "state": "failed",
                            "window_results": [result],
                            "decision_snapshot_created": False,
                            "decision_ready": False,
                        },
                        status=503,
                    )
                remaining = missing_required - target.required_opens
                state = "complete" if not remaining else "in_progress"
                return Response.json(
                    {
                        "ok": True,
                        "bootstrap_id": str(bootstrap_id),
                        "state": state,
                        "planned_windows": 1,
                        "processed_window_index": target.index,
                        "processed_window_start_utc": target.start_utc.isoformat(),
                        "processed_window_end_utc": target.end_utc.isoformat(),
                        "required_m1_minutes": len(all_required),
                        "remaining_m1_minutes": len(remaining),
                        "window_results": [result],
                        "decision_snapshot_created": False,
                        "decision_ready": False,
                        "next_step": "wait_for_fresh_scheduled_capture" if state == "complete" else "continue_bootstrap",
                    }
                )
            except Exception as exc:  # noqa: BLE001 - protected administrative bootstrap diagnosis
                if bootstrap_id is not None and isinstance(market_store, D1TwelveDataMarketStore):
                    try:
                        await market_store.finalize_bootstrap(
                            bootstrap_id=bootstrap_id,
                            completed_at=datetime.now(UTC),
                        )
                    except Exception:
                        pass
                return Response.json(
                    {"ok": False, "error": type(exc).__name__, "message": str(exc)[:1000]},
                    status=500,
                )

        if request.method == "POST" and url.path == "/day53/live-gold-smoke":
            if str(self.env.AIDY_ENV).lower() != "test":
                return Response("Not found", status=404)
            settings = AidySettings.from_worker_env(self.env)
            if settings.market_data_source != "argentapi":
                return Response.json(
                    {"ok": False, "error": "argentapi_not_configured"}, status=409
                )
            _, repository = _repository(self.env)
            market_gateway, live_gold_history = _market_runtime_dependencies(self.env, settings)
            try:
                result = await run_capture_cycle(
                    settings,
                    repository=repository,
                    include_market=True,
                    include_fed=False,
                    include_macro=False,
                    include_cross_market=False,
                    market_gateway=market_gateway,
                    live_gold_history=live_gold_history,
                )
                if result is None or result.market is None or result.market.snapshot_id is None:
                    return Response.json({"ok": False, "error": "no_market_snapshot"}, status=503)
                row = await self.env.AIDY_OPS.prepare(
                    """
                    SELECT id,captured_at,capture_status,bid,ask,mid,spread,quote_time,
                           quote_age_seconds,data_availability_json,latest_m1_id,latest_m5_id,
                           latest_m15_id,latest_h1_id,latest_h4_id,latest_d1_id
                    FROM market_snapshots WHERE id=? LIMIT 1
                    """
                ).bind(str(result.market.snapshot_id)).first()
                snapshot = {} if row is None else dict(row)
                availability = json.loads(str(snapshot.get("data_availability_json") or "{}"))
                candle_fields = (
                    "latest_m1_id",
                    "latest_m5_id",
                    "latest_m15_id",
                    "latest_h1_id",
                    "latest_h4_id",
                    "latest_d1_id",
                )
                quote_ready = all(
                    snapshot.get(key) not in {None, ""} for key in ("bid", "ask", "spread")
                )
                candles_ready = all(
                    snapshot.get(key) not in {None, ""} for key in candle_fields
                )
                ok = snapshot.get("capture_status") == "complete" and quote_ready
                return Response.json(
                    {
                        "ok": ok,
                        "snapshot": {
                            "id": snapshot.get("id"),
                            "captured_at": snapshot.get("captured_at"),
                            "capture_status": snapshot.get("capture_status"),
                            "bid": snapshot.get("bid"),
                            "ask": snapshot.get("ask"),
                            "mid": snapshot.get("mid"),
                            "spread": snapshot.get("spread"),
                            "quote_time": snapshot.get("quote_time"),
                            "quote_age_seconds": snapshot.get("quote_age_seconds"),
                            "candles_ready": candles_ready,
                            "candle_ids": {key: snapshot.get(key) for key in candle_fields},
                            "market_data_source": availability.get("market_data_source"),
                            "candle_source": availability.get("candle_source"),
                        },
                        "stored_candles": result.market.stored_candles,
                    },
                    status=200 if ok else 503,
                )
            except Exception as exc:  # noqa: BLE001 - test-only smoke exposes safe diagnosis
                return Response.json(
                    {"ok": False, "error": type(exc).__name__, "message": str(exc)[:1000]},
                    status=500,
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
                market_gateway, live_gold_history = _market_runtime_dependencies(
                    worker_env, settings
                )
                result = await run_worker_scheduled_cycle(
                    settings,
                    repository=repository,
                    scheduled_at=scheduled_at,
                    market_gateway=market_gateway,
                    live_gold_history=live_gold_history,
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
                        gateway=_private_forward_gateway(worker_env),
                    )
                except Exception as exc:  # noqa: BLE001 - do not duplicate successful capture
                    await _write_test_forward_error(worker_env, exc, scheduled_at=scheduled_at)

            message.ack()
