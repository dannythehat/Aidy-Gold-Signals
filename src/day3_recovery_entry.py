from __future__ import annotations

import json
import traceback
from datetime import UTC, datetime

from entry import (
    Default as BaseDefault,
    _formal_forward_enabled,
    _market_runtime_dependencies,
    _private_forward_gateway,
    _repository,
    _scheduled_at_from_queue_body,
)
from aidy.config import AidySettings
from aidy.forward_live_observer import observe_private_forward_snapshot
from aidy.runtime import run_worker_scheduled_cycle


def _safe_payload(*, stage: str, exc: Exception, scheduled_at: datetime | None) -> dict[str, object]:
    return {
        "observed_at": datetime.now(UTC).isoformat(),
        "stage": stage,
        "scheduled_at": None if scheduled_at is None else scheduled_at.astimezone(UTC).isoformat(),
        "exception_type": type(exc).__name__,
        "message": str(exc)[:2000],
        "traceback": traceback.format_exc()[-10000:],
    }


async def _record_queue_failure(env, payload: dict[str, object]) -> None:
    # Console output is the primary diagnostic. R2 diagnostics are best-effort only so
    # a broken R2 binding/write path cannot mask the original queue exception.
    print("AIDY_QUEUE_EXCEPTION " + json.dumps(payload, sort_keys=True))
    try:
        await env.AIDY_MEMORY.put(
            "diagnostics/day3-queue-consumer-error.json",
            json.dumps(payload, sort_keys=True),
        )
    except Exception as diagnostic_exc:  # noqa: BLE001 - diagnostics must never mask root cause
        print(
            "AIDY_QUEUE_DIAGNOSTIC_WRITE_FAILED "
            + json.dumps(
                {
                    "exception_type": type(diagnostic_exc).__name__,
                    "message": str(diagnostic_exc)[:2000],
                },
                sort_keys=True,
            )
        )


class Default(BaseDefault):
    """Temporary Day-3 recovery entrypoint with stage-level queue diagnostics.

    Fetch routes are inherited unchanged from the production entrypoint. Only the
    queue handler is overridden so the true consumer exception is emitted before
    any best-effort diagnostic persistence is attempted.
    """

    async def queue(self, batch, env=None, ctx=None):
        del env, ctx
        worker_env = self.env
        for message in batch.messages:
            settings: AidySettings | None = None
            scheduled_at: datetime | None = None
            stage = "settings"
            try:
                settings = AidySettings.from_worker_env(worker_env)
                stage = "repository"
                operational, repository = _repository(worker_env)
                stage = "scheduled_at"
                scheduled_at = _scheduled_at_from_queue_body(message.body)
                if scheduled_at.minute == 0:
                    stage = "hot_prune"
                    await operational.prune_archived_hot_data(now=scheduled_at)
                stage = "market_dependencies"
                market_gateway, live_gold_history = _market_runtime_dependencies(
                    worker_env, settings
                )
                stage = "scheduled_cycle"
                result = await run_worker_scheduled_cycle(
                    settings,
                    repository=repository,
                    scheduled_at=scheduled_at,
                    market_gateway=market_gateway,
                    live_gold_history=live_gold_history,
                )
            except Exception as exc:  # noqa: BLE001 - exact queue diagnosis + retry
                payload = _safe_payload(stage=stage, exc=exc, scheduled_at=scheduled_at)
                await _record_queue_failure(worker_env, payload)
                try:
                    message.retry(delaySeconds=30)
                except Exception as retry_exc:  # noqa: BLE001 - do not hide retry ABI failures
                    print(
                        "AIDY_QUEUE_RETRY_FAILED "
                        + json.dumps(
                            {
                                "exception_type": type(retry_exc).__name__,
                                "message": str(retry_exc)[:2000],
                            },
                            sort_keys=True,
                        )
                    )
                    raise
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
                except Exception as exc:  # noqa: BLE001 - forward remains isolated from capture
                    print(
                        "AIDY_FORWARD_OBSERVER_EXCEPTION "
                        + json.dumps(
                            {
                                "scheduled_at": scheduled_at.astimezone(UTC).isoformat(),
                                "exception_type": type(exc).__name__,
                                "message": str(exc)[:2000],
                            },
                            sort_keys=True,
                        )
                    )

            message.ack()
