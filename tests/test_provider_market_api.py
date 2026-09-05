from __future__ import annotations

import base64
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import aidy.provider_market_api as api

ROOT = Path(__file__).resolve().parents[1]


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def test_provider_auth_is_signed_and_replay_bounded(monkeypatch) -> None:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    monkeypatch.setattr(api, "PROVIDER_PUBLIC_KEY_B64URL", _b64url(public))
    now = datetime(2026, 9, 5, 6, 40, tzinfo=UTC)
    timestamp = str(int(now.timestamp()))
    query = urlencode(
        {
            "symbol": "XAUUSD",
            "from": "2026-09-04T06:40:00+00:00",
            "to": "2026-09-05T06:40:00+00:00",
            "timeframe": "1m",
        }
    )
    payload = api._signing_payload(
        path="/market/ohlc",
        raw_query=query,
        timestamp=timestamp,
        client=api.PROVIDER_CLIENT,
    )
    request = SimpleNamespace(
        url=f"https://aidy.test/market/ohlc?{query}",
        headers={
            "X-AIDY-Client": api.PROVIDER_CLIENT,
            "X-AIDY-Timestamp": timestamp,
            "X-AIDY-Signature": _b64url(private.sign(payload)),
        },
    )
    assert api._authorized(request, now=now) is True
    stale = datetime(2026, 9, 5, 6, 46, tzinfo=UTC)
    assert api._authorized(request, now=stale) is False


def test_latest_revision_is_selected_without_leaking_internal_identity() -> None:
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


def test_provider_query_contract_is_bounded_pit_safe_and_read_only() -> None:
    source = (ROOT / "src" / "aidy" / "provider_market_api.py").read_text(encoding="utf-8")
    assert "FROM twelve_data_decision_admitted_m1_v1" in source
    assert "open_time_utc>=? AND open_time_utc<? AND first_observed_at<=?" in source
    assert "LIMIT ?" in source
    assert "MAX_M1_ROWS + 1" in source
    assert "MAX_WINDOW = timedelta(hours=48)" in source
    assert "INSERT " not in source
    assert "UPDATE " not in source
    assert "DELETE " not in source
    assert "broker" not in source.lower()


def test_worker_routes_provider_endpoint_without_replacing_core_runtime() -> None:
    wrapper = (ROOT / "src" / "provider_entry.py").read_text(encoding="utf-8")
    config = (ROOT / "wrangler.test.example.jsonc").read_text(encoding="utf-8")
    assert 'urlparse(request.url).path == "/market/ohlc"' in wrapper
    assert "return await super().fetch(request)" in wrapper
    assert '"main": "src/provider_entry.py"' in config
