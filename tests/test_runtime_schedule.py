from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from aidy.config import AidySettings
from aidy.runtime import interval_due, run_worker_scheduled_cycle
from aidy.storage_contracts import ArchiveFlushResult


def test_worker_env_loader_is_disabled_without_secrets() -> None:
    env = SimpleNamespace(AIDY_CAPTURE_ENABLED="false", AIDY_ARCHIVE_FLUSH_LIMIT="25")
    settings = AidySettings.from_worker_env(env)
    assert settings.capture_enabled is False
    assert settings.metaapi_token == ""
    assert settings.metaapi_account_id == ""
    assert settings.market_data_ownership == ""
    assert settings.archive_flush_limit == 25


def test_worker_env_loader_fails_closed_when_capture_enabled_without_secrets() -> None:
    env = SimpleNamespace(AIDY_CAPTURE_ENABLED="true")
    with pytest.raises(RuntimeError, match="capture is enabled"):
        AidySettings.from_worker_env(env)


def test_interval_due_is_restart_independent() -> None:
    assert interval_due(datetime(2026, 8, 16, 9, 10, tzinfo=UTC), 300) is True
    assert interval_due(datetime(2026, 8, 16, 9, 11, tzinfo=UTC), 300) is False
    assert interval_due(datetime(2026, 8, 16, 9, 12, tzinfo=UTC), 120) is True


class ArchiveOnlyRepository:
    def __init__(self) -> None:
        self.flush_limits: list[int] = []

    async def flush_archive_outbox(self, *, limit: int):
        self.flush_limits.append(limit)
        return ArchiveFlushResult(attempted=0, archived=0, failed=0)


@pytest.mark.asyncio
async def test_disabled_worker_cycle_still_retries_archive_outbox() -> None:
    settings = AidySettings(metaapi_token="", metaapi_account_id="", archive_flush_limit=17)
    repository = ArchiveOnlyRepository()
    result = await run_worker_scheduled_cycle(
        settings,
        repository=repository,  # type: ignore[arg-type]
        scheduled_at=datetime(2026, 8, 16, 9, 12, tzinfo=UTC),
    )
    assert result.market is None
    assert result.fed is None
    assert result.archive == ArchiveFlushResult(attempted=0, archived=0, failed=0)
    assert repository.flush_limits == [17]
