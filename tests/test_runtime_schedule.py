from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from aidy.config import AidySettings
from aidy.runtime import interval_due, run_worker_scheduled_cycle
from aidy.storage_contracts import ArchiveFlushResult


def test_worker_env_loader_is_keyless_when_capture_disabled() -> None:
    env = SimpleNamespace(AIDY_CAPTURE_ENABLED="false", AIDY_ARCHIVE_FLUSH_LIMIT="25")
    settings = AidySettings.from_worker_env(env)
    assert settings.capture_enabled is False
    assert settings.market_data_source == "gold_api"
    assert settings.market_data_ownership == "public_independent"
    assert settings.archive_flush_limit == 25


def test_twelve_intraday_self_heal_requires_explicit_flag() -> None:
    disabled = AidySettings.from_worker_env(
        SimpleNamespace(
            AIDY_CAPTURE_ENABLED="true",
            AIDY_MARKET_DATA_SOURCE="twelve_data",
            AIDY_MARKET_DATA_OWNERSHIP="public_independent",
            AIDY_MARKET_POLL_SECONDS="300",
        )
    )
    enabled = AidySettings.from_worker_env(
        SimpleNamespace(
            AIDY_CAPTURE_ENABLED="true",
            AIDY_MARKET_DATA_SOURCE="twelve_data",
            AIDY_MARKET_DATA_OWNERSHIP="public_independent",
            AIDY_MARKET_POLL_SECONDS="300",
            AIDY_TWELVE_INTRADAY_SELF_HEAL_ENABLED="true",
        )
    )
    assert disabled.twelve_intraday_self_heal_enabled is False
    assert enabled.twelve_intraday_self_heal_enabled is True


def test_worker_env_loader_allows_keyless_public_capture() -> None:
    env = SimpleNamespace(
        AIDY_CAPTURE_ENABLED="true",
        AIDY_MARKET_DATA_SOURCE="gold_api",
        AIDY_MARKET_DATA_OWNERSHIP="public_independent",
    )
    settings = AidySettings.from_worker_env(env)
    assert settings.capture_enabled is True


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


async def test_disabled_worker_cycle_still_retries_archive_outbox() -> None:
    settings = AidySettings(capture_enabled=False, archive_flush_limit=17)
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
