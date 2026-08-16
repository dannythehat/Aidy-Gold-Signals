from __future__ import annotations

import pytest

from aidy.config import AidySettings


_REQUIRED = ("AIDY_METAAPI_TOKEN", "AIDY_METAAPI_ACCOUNT_ID")


def test_capture_disabled_does_not_require_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIDY_CAPTURE_ENABLED", "false")
    monkeypatch.delenv("AIDY_DATABASE_URL", raising=False)
    for name in _REQUIRED:
        monkeypatch.delenv(name, raising=False)

    settings = AidySettings.from_env()

    assert settings.capture_enabled is False
    assert settings.metaapi_token == ""
    assert settings.metaapi_account_id == ""


def test_capture_enabled_fails_closed_when_required_values_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIDY_CAPTURE_ENABLED", "true")
    for name in _REQUIRED:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError, match="capture is enabled"):
        AidySettings.from_env()


def test_capture_enabled_no_longer_requires_postgresql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIDY_CAPTURE_ENABLED", "true")
    monkeypatch.delenv("AIDY_DATABASE_URL", raising=False)
    monkeypatch.setenv("AIDY_METAAPI_TOKEN", "test-token")
    monkeypatch.setenv("AIDY_METAAPI_ACCOUNT_ID", "test-account")

    settings = AidySettings.from_env()

    assert settings.capture_enabled is True
    assert settings.metaapi_token == "test-token"
    assert settings.metaapi_account_id == "test-account"
    assert not hasattr(settings, "database_url")
