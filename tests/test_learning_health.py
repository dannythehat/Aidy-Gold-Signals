"""Fresh successful syncs cannot conceal frozen learning progress."""

from datetime import UTC, datetime, timedelta

import pytest

from aidy.data_health import collect_learning_health

NOW = datetime(2026, 11, 6, 4, tzinfo=UTC)


class D1:
    def __init__(self, **changes):
        self.row = dict(  # noqa: C408
            last_cycle=(NOW - timedelta(minutes=10)).isoformat(),
            last_sync=NOW.isoformat(),
            sync_status="ok",
            creation_reason="view_already_frozen",
            last_data=NOW.isoformat(),
            error_type=None,
        )
        self.row.update(changes)

    def prepare(self, sql):
        assert "INSERT" not in sql and "UPDATE" not in sql
        return self

    async def first(self):
        return self.row


@pytest.mark.asyncio
async def test_successful_sync_cannot_mask_stalled_cycle():
    report = await collect_learning_health(
        D1(last_cycle="2026-09-24T03:40:47Z"), now=NOW, session_open=True
    )
    assert report["status"] == "degraded"
    assert report["blocked_reason"] == "learning_not_progressing"
    assert report["cycle_elapsed_seconds"] > 86400
    assert report["last_sync_utc"] == NOW.isoformat()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"last_data": None}, "market_data_unavailable_or_stale"),
        ({"last_sync": None}, "sync_unavailable_or_stale"),
        ({"sync_status": "error"}, "sync_error"),
        ({"last_cycle": None}, "learning_not_progressing"),
    ],
)
async def test_missing_or_failed_components(changes, reason):
    r = await collect_learning_health(D1(**changes), now=NOW, session_open=True)
    assert r["status"] == "degraded" and r["blocked_reason"] == reason


@pytest.mark.asyncio
async def test_closed_market_retains_last_cycle_age():
    r = await collect_learning_health(
        D1(last_cycle="2026-09-24T03:40:47Z"), now=NOW, session_open=False
    )
    assert r["status"] == "market_closed" and r["cycle_elapsed_seconds"] > 86400


@pytest.mark.asyncio
async def test_available_progress_and_database_failure():
    r = await collect_learning_health(D1(), now=NOW, session_open=True)
    assert r["status"] == "fresh"

    class Broken(D1):
        async def first(self):
            raise RuntimeError("fixture")

    r = await collect_learning_health(Broken(), now=NOW, session_open=True)
    assert r["status"] == "unavailable" and r["blocked_reason"] == "learning_health_read_failed"


@pytest.mark.asyncio
async def test_public_health_degrades_when_request_and_data_are_healthy():
    # Execute the actual endpoint without importing Cloudflare-only runtime modules.
    import ast
    from pathlib import Path
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    module = ast.parse(Path("src/provider_entry.py").read_text())
    function = next(
        n
        for n in module.body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_public_health_response"
    )
    scope = {
        name.id: "fixture-version"
        for name in ast.walk(function)
        if isinstance(name, ast.Name) and name.id.isupper()
    }
    scope.update(
        dict(
            datetime=datetime,
            UTC=UTC,
            _bool_env=lambda *a: False,
            AidySettings=SimpleNamespace(
                from_worker_env=lambda env: SimpleNamespace(
                    capture_enabled=True,
                    market_data_source="twelve_data",
                    market_data_ownership="fixture",
                )
            ),
            Response=SimpleNamespace(json=lambda value: value),
            collect_data_health=AsyncMock(
                return_value=SimpleNamespace(
                    status="fresh",
                    alert=False,
                    reason=None,
                    session_open=True,
                    latest_scheduled_success_utc=NOW.isoformat(),
                    latest_provider_context_snapshot_utc=NOW.isoformat(),
                    success_lag_seconds=0,
                    provider_context_snapshot_lag_seconds=0,
                    health_version="fixture",
                )
            ),
            collect_learning_health=AsyncMock(
                return_value={"status": "degraded", "blocked_reason": "learning_not_progressing"}
            ),
        )
    )
    exec(compile(ast.Module(body=[function], type_ignores=[]), "public-health", "exec"), scope)
    result = await scope["_public_health_response"](SimpleNamespace(AIDY_OPS=object()))
    assert result["status"] == "degraded"
    assert result["data_health"]["status"] == "fresh"
    assert result["learning_health"]["blocked_reason"] == "learning_not_progressing"
