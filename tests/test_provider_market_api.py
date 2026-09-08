from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import aidy.provider_market_api as api
from aidy.twelve_data_market import expected_market_minute_opens

ROOT = Path(__file__).resolve().parents[1]


def _request(auth: str | None) -> SimpleNamespace:
    headers = {} if auth is None else {"Authorization": auth}
    return SimpleNamespace(
        method="GET",
        url="https://aidy.test/market/ohlc?symbol=XAUUSD",
        headers=headers,
    )


def _env(token: str | None) -> SimpleNamespace:
    values = {} if token is None else {"AIDY_PROVIDER_MARKET_TOKEN": token}
    return SimpleNamespace(**values)


def test_provider_bearer_auth_accepts_valid_token() -> None:
    assert api._authorized(_request("Bearer shared-secret"), _env("shared-secret")) is True


def test_provider_bearer_auth_rejects_missing_token() -> None:
    assert api._authorized(_request(None), _env("shared-secret")) is False


def test_provider_bearer_auth_rejects_wrong_token() -> None:
    assert api._authorized(_request("Bearer wrong"), _env("shared-secret")) is False


def test_provider_bearer_auth_fails_closed_when_worker_secret_missing() -> None:
    assert api._authorized(_request("Bearer shared-secret"), _env(None)) is False


def test_latest_revision_is_selected_for_each_minute() -> None:
    rows = [
        {
            "open_time_utc": "2026-09-05T06:00:00+00:00",
            "open": "3500",
            "high": "3502",
            "low": "3499",
            "close": "3501",
            "revision_index": 1,
            "first_observed_at": "2026-09-05T06:01:10+00:00",
        },
        {
            "open_time_utc": "2026-09-05T06:00:00+00:00",
            "open": "3500",
            "high": "3503",
            "low": "3499",
            "close": "3502",
            "revision_index": 2,
            "first_observed_at": "2026-09-05T06:02:10+00:00",
        },
    ]
    selected = api._latest_revisions(rows)
    assert len(selected) == 1
    assert selected[0]["revision_index"] == 2


def test_expected_minutes_distinguish_gold_maintenance_gap() -> None:
    start = datetime(2026, 9, 3, 21, 58, tzinfo=UTC)
    end = datetime(2026, 9, 3, 22, 2, tzinfo=UTC)
    expected = expected_market_minute_opens(start, end)
    assert datetime(2026, 9, 3, 21, 58, tzinfo=UTC) not in expected
    assert datetime(2026, 9, 3, 22, 0, tzinfo=UTC) in expected


def test_provider_query_contract_is_bounded_pit_safe_read_only_and_continuity_aware() -> None:
    source = (ROOT / "src" / "aidy" / "provider_market_api.py").read_text(encoding="utf-8")
    assert "FROM twelve_data_decision_admitted_m1_v1" in source
    assert "open_time_utc>=? AND open_time_utc<? AND first_observed_at<=?" in source
    assert "payload_digest" in source
    assert "expected_market_minute_opens" in source
    assert '"expected_open_times"' in source
    assert '"missing_open_times"' in source
    assert "LIMIT ?" in source
    assert "MAX_M1_ROWS + 1" in source
    assert "MAX_WINDOW = timedelta(hours=48)" in source
    assert "INSERT " not in source
    assert "UPDATE " not in source
    assert "DELETE " not in source
    assert "broker" not in source.lower()


def test_provider_auth_path_is_worker_safe_and_constant_time() -> None:
    source = (ROOT / "src" / "aidy" / "provider_market_api.py").read_text(encoding="utf-8")
    assert "hmac.compare_digest" in source
    assert "AIDY_PROVIDER_MARKET_TOKEN" in source
    assert "cryptography" not in source
    assert "Ed25519" not in source


def test_worker_routes_provider_endpoint_without_replacing_core_runtime() -> None:
    wrapper = (ROOT / "src" / "provider_entry.py").read_text(encoding="utf-8")
    config = (ROOT / "wrangler.test.example.jsonc").read_text(encoding="utf-8")
    assert 'path == "/market/ohlc"' in wrapper
    assert 'path == "/provider/context"' in wrapper
    assert "return await super().fetch(request)" in wrapper
    assert '"main": "src/provider_entry.py"' in config


def test_provider_rollout_guard_checks_real_formal_forward_env_var() -> None:
    rollout = (
        ROOT / ".github" / "workflows" / "ops-provider-market-rollout-20260905.yml"
    ).read_text(encoding="utf-8")
    assert "settings.formal_forward_enabled" not in rollout
    assert "cfg['vars']['AIDY_FORMAL_FORWARD_ENABLED']='false'" in rollout
    assert (
        "str(cfg['vars'].get('AIDY_FORMAL_FORWARD_ENABLED', '')).strip().lower() == 'false'"
        in rollout
    )


# Provider-context D1 read-budget fix protection-check trigger; no runtime semantic change.
