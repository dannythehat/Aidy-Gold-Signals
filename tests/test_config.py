from __future__ import annotations

import pytest

from aidy.config import AidySettings


def test_capture_disabled_needs_no_market_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIDY_CAPTURE_ENABLED", "false")
    monkeypatch.delenv("AIDY_DATABASE_URL", raising=False)
    monkeypatch.delenv("AIDY_METAAPI_TOKEN", raising=False)
    monkeypatch.delenv("AIDY_METAAPI_ACCOUNT_ID", raising=False)

    settings = AidySettings.from_env()

    assert settings.capture_enabled is False
    assert settings.market_data_source == "gold_api"
    assert settings.market_data_ownership == "public_independent"
    assert not hasattr(settings, "metaapi_token")
    assert not hasattr(settings, "metaapi_account_id")


def test_capture_enabled_works_without_api_key_or_broker_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIDY_CAPTURE_ENABLED", "true")
    monkeypatch.setenv("AIDY_MARKET_DATA_SOURCE", "gold_api")
    monkeypatch.setenv("AIDY_MARKET_DATA_OWNERSHIP", "public_independent")
    monkeypatch.delenv("AIDY_DATABASE_URL", raising=False)
    monkeypatch.delenv("AIDY_METAAPI_TOKEN", raising=False)
    monkeypatch.delenv("AIDY_METAAPI_ACCOUNT_ID", raising=False)

    settings = AidySettings.from_env()

    assert settings.capture_enabled is True
    assert settings.market_data_source == "gold_api"
    assert settings.market_data_ownership == "public_independent"
    assert not hasattr(settings, "database_url")


def test_capture_rejects_broker_or_shared_market_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIDY_CAPTURE_ENABLED", "true")
    monkeypatch.setenv("AIDY_MARKET_DATA_SOURCE", "gold_api")
    monkeypatch.setenv("AIDY_MARKET_DATA_OWNERSHIP", "super_signals_shared")

    with pytest.raises(RuntimeError, match="public_independent"):
        AidySettings.from_env()


def test_capture_rejects_source_without_installed_broker_free_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIDY_CAPTURE_ENABLED", "true")
    monkeypatch.setenv("AIDY_MARKET_DATA_SOURCE", "metaapi")
    monkeypatch.setenv("AIDY_MARKET_DATA_OWNERSHIP", "public_independent")

    with pytest.raises(RuntimeError, match="broker-free adapter"):
        AidySettings.from_env()
