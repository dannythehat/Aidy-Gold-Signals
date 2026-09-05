from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
import pytest

from aidy.argentapi_gateway import ArgentApiGateway, ArgentApiReadError
from aidy.config import AidySettings
from aidy.forward_live_observer import _blocked_reason
from aidy.live_gold_recorder import (
    CANDLE_SOURCE,
    AidyLiveGoldRecorderService,
    day53_genuine_live_gold_feed_manifest,
)
from aidy.live_gold_storage import D1LiveGoldQuoteHistory

ROOT = Path(__file__).resolve().parents[1]
CAPTURED = datetime(2026, 9, 2, 12, 0, 10, tzinfo=UTC)
QUOTE_TIME = datetime(2026, 9, 2, 12, 0, 0, tzinfo=UTC)
API_KEY = "ag_live_test_secret_value"


def _payload(*, stale: bool = False, bid: float = 3499.5, ask: float = 3500.5) -> dict:
    fetched_ms = int((QUOTE_TIME + timedelta(milliseconds=250)).timestamp() * 1000)
    return {
        "metal": "gold",
        "symbol": "AU",
        "currency": "USD",
        "unit": "OUNCE",
        "bid": bid,
        "ask": ask,
        "mid": (bid + ask) / 2,
        "high": 3512.0,
        "low": 3479.0,
        "change": 10.0,
        "changePercent": 0.3,
        "sourceTimestamp": "Sep 02, 2026 12:00",
        "fetchedAt": fetched_ms,
        "ageMs": 250,
        "stale": stale,
    }


@pytest.mark.asyncio
async def test_argent_gateway_normalizes_genuine_bid_ask_and_keeps_key_out_of_payload() -> None:
    seen_header = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_header
        seen_header = request.headers.get("X-API-Key")
        assert API_KEY not in str(request.url)
        return httpx.Response(200, json=_payload())

    quote = await ArgentApiGateway(
        api_key=API_KEY,
        transport=httpx.MockTransport(handler),
    ).read_xau_usd()

    assert seen_header == API_KEY
    assert quote["bid"] == Decimal("3499.5")
    assert quote["ask"] == Decimal("3500.5")
    assert quote["mid"] == Decimal("3500.0")
    assert quote["spread"] == Decimal("1.0")
    assert quote["observed_at"] == QUOTE_TIME
    assert quote["source"] == "argentapi"
    assert API_KEY not in json.dumps(quote, default=str)


@pytest.mark.asyncio
async def test_argent_gateway_rejects_stale_crossed_and_auth_without_secret_leak() -> None:
    async def read(payload: dict, status: int = 200):
        gateway = ArgentApiGateway(
            api_key=API_KEY,
            transport=httpx.MockTransport(lambda request: httpx.Response(status, json=payload)),
        )
        return await gateway.read_xau_usd()

    with pytest.raises(ArgentApiReadError, match="argentapi_stale_or_unknown_quote"):
        await read(_payload(stale=True))
    with pytest.raises(ArgentApiReadError, match="argentapi_crossed_quote"):
        await read(_payload(bid=3501.0, ask=3500.0))
    with pytest.raises(ArgentApiReadError) as exc_info:
        await read({}, status=401)
    assert exc_info.value.code == "argentapi_authorization_rejected"
    assert API_KEY not in str(exc_info.value)


class FakeHistory:
    def __init__(self, *, dense: bool) -> None:
        self.dense = dense

    async def latest_candle_ids(self, *, symbol: str, source: str) -> dict[str, UUID]:
        assert symbol == "XAUUSD"
        assert source == CANDLE_SOURCE
        return {}

    async def candle_id_for_bucket(
        self, *, symbol: str, source: str, timeframe: str, open_time_utc
    ) -> UUID | None:
        assert symbol == "XAUUSD"
        assert source == CANDLE_SOURCE
        return None

    async def quote_observations(self, *, symbol: str, source: str, start_utc, end_utc):
        assert symbol == "XAUUSD"
        assert source == "argentapi"
        minutes = int((end_utc - start_utc).total_seconds() // 60)
        count = minutes if self.dense else max(1, minutes // 2)
        rows = []
        for index in range(count):
            quote_time = start_utc + timedelta(minutes=index)
            price = Decimal(3400) + Decimal(index) / Decimal(100)
            rows.append(
                {
                    "id": str(uuid5(NAMESPACE_URL, f"quote-{start_utc}-{index}")),
                    "quote_time": quote_time.isoformat(),
                    "mid": str(price),
                    "spread": "0.80",
                    "snapshot_digest": f"digest-{index:04d}",
                }
            )
        return rows


class FakeRepository:
    def __init__(self) -> None:
        self.candles = []
        self.snapshots = []

    async def store_candle(self, candle):
        self.candles.append(dict(candle))
        candle_id = uuid5(NAMESPACE_URL, str(candle["payload_digest"]))
        return candle_id, 1, True

    async def event_observation_ids_known_at(self, *, captured_at, lookback_hours=24):
        return []

    async def store_snapshot(self, snapshot):
        self.snapshots.append(dict(snapshot))
        return uuid5(NAMESPACE_URL, str(snapshot["snapshot_digest"]))


class FakeGateway:
    async def read_xau_usd(self):
        return {
            "symbol": "XAUUSD",
            "bid": Decimal("3499.50"),
            "ask": Decimal("3500.50"),
            "mid": Decimal("3500.00"),
            "spread": Decimal("1.00"),
            "observed_at": QUOTE_TIME,
            "source": "argentapi",
            "ownership": "public_independent",
        }


@pytest.mark.asyncio
async def test_dense_genuine_quote_history_materializes_all_six_closed_timeframes() -> None:
    repository = FakeRepository()
    result = await AidyLiveGoldRecorderService(
        repository=repository,
        gateway=FakeGateway(),
        quote_history=FakeHistory(dense=True),
        clock=lambda: CAPTURED,
    ).capture_once(now=CAPTURED)

    assert result.status == "complete"
    assert result.stored_candles == 6
    assert len(repository.candles) == 6
    assert {candle["timeframe"] for candle in repository.candles} == {
        "1m",
        "5m",
        "15m",
        "1h",
        "4h",
        "1d",
    }
    assert all(candle["source"] == CANDLE_SOURCE for candle in repository.candles)
    snapshot = repository.snapshots[-1]
    assert snapshot["bid"] == Decimal("3499.50")
    assert snapshot["ask"] == Decimal("3500.50")
    assert snapshot["spread"] == Decimal("1.00")
    candle_fields = (
        "latest_m1_id",
        "latest_m5_id",
        "latest_m15_id",
        "latest_h1_id",
        "latest_h4_id",
        "latest_d1_id",
    )
    assert all(snapshot[key] is not None for key in candle_fields)
    assert _blocked_reason(snapshot) is None
    availability = json.loads(snapshot["data_availability_json"])
    assert availability["market_data_source"] == "argentapi"
    assert availability["candle_source"] == CANDLE_SOURCE
    assert availability["candles"]["1d"]["state"] == "closed_bucket_materialized"


@pytest.mark.asyncio
async def test_sparse_quote_history_never_fabricates_higher_timeframe_ohlc() -> None:
    repository = FakeRepository()
    await AidyLiveGoldRecorderService(
        repository=repository,
        gateway=FakeGateway(),
        quote_history=FakeHistory(dense=False),
        clock=lambda: CAPTURED,
    ).capture_once(now=CAPTURED)

    snapshot = repository.snapshots[-1]
    availability = json.loads(snapshot["data_availability_json"])
    assert availability["candles"]["1m"]["state"] == "closed_bucket_materialized"
    for timeframe in ("5m", "15m", "1h", "4h", "1d"):
        assert availability["candles"][timeframe]["state"] == "insufficient_live_coverage"
    assert snapshot["latest_m5_id"] is None
    assert _blocked_reason(snapshot) == "missing_genuine_live_ohlc"


class Prepared:
    def __init__(self, connection: sqlite3.Connection, sql: str, params=()) -> None:
        self.connection = connection
        self.sql = sql
        self.params = params

    def bind(self, *params):
        return Prepared(self.connection, self.sql, params)

    async def all(self):
        rows = self.connection.execute(self.sql, self.params).fetchall()
        return {"results": [dict(row) for row in rows]}


class LocalD1:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE market_candles (
                id TEXT PRIMARY KEY, symbol TEXT, timeframe TEXT, open_time_utc TEXT,
                source TEXT, revision_index INTEGER
            );
            CREATE TABLE market_snapshots (
                id TEXT PRIMARY KEY, captured_at TEXT, symbol TEXT, capture_status TEXT,
                market_data_source TEXT, bid TEXT, ask TEXT, mid TEXT, spread TEXT, quote_time TEXT,
                quote_age_seconds REAL, data_availability_json TEXT, snapshot_digest TEXT
            );
            CREATE INDEX ix_market_snapshots_quote_history
                ON market_snapshots(symbol,market_data_source,capture_status,quote_time,captured_at,id);
            CREATE INDEX ix_market_candles_source_symbol_timeframe_latest
                ON market_candles(source,symbol,timeframe,open_time_utc DESC,revision_index DESC,id);
            """
        )

    def prepare(self, sql: str):
        return Prepared(self.connection, sql)


@pytest.mark.asyncio
async def test_source_aware_history_never_selects_legacy_metaapi_candle() -> None:
    d1 = LocalD1()
    meta_id = str(uuid5(NAMESPACE_URL, "meta"))
    argent_id = str(uuid5(NAMESPACE_URL, "argent"))
    d1.connection.executemany(
        "INSERT INTO market_candles VALUES (?,?,?,?,?,?)",
        [
            (meta_id, "XAUUSD", "1m", "2026-09-02T11:58:00+00:00", "metaapi", 1),
            (argent_id, "XAUUSD", "1m", "2026-09-02T11:59:00+00:00", CANDLE_SOURCE, 1),
        ],
    )
    d1.connection.commit()
    history = D1LiveGoldQuoteHistory(d1)
    latest = await history.latest_candle_ids(symbol="XAUUSD", source=CANDLE_SOURCE)
    assert latest["1m"] == UUID(argent_id)
    assert latest["1m"] != UUID(meta_id)


@pytest.mark.asyncio
async def test_quote_history_filters_to_exact_public_source() -> None:
    d1 = LocalD1()
    for source, suffix in (("argentapi", "a"), ("gold_api", "g")):
        availability = json.dumps({"market_data_source": source})
        d1.connection.execute(
            "INSERT INTO market_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"snap-{suffix}",
                "2026-09-02T11:59:10+00:00",
                "XAUUSD",
                "complete",
                source,
                "3499",
                "3501",
                "3500",
                "2",
                "2026-09-02T11:59:00+00:00",
                10.0,
                availability,
                f"digest-{suffix}",
            ),
        )
    d1.connection.commit()
    rows = await D1LiveGoldQuoteHistory(d1).quote_observations(
        symbol="XAUUSD",
        source="argentapi",
        start_utc=datetime(2026, 9, 2, 11, 58, tzinfo=UTC),
        end_utc=datetime(2026, 9, 2, 12, 0, tzinfo=UTC),
    )
    assert [row["id"] for row in rows] == ["snap-a"]


def test_config_allows_argentapi_only_inside_public_independent_boundary() -> None:
    values = {
        "AIDY_CAPTURE_ENABLED": "true",
        "AIDY_MARKET_DATA_SOURCE": "argentapi",
        "AIDY_MARKET_DATA_OWNERSHIP": "public_independent",
    }
    settings = AidySettings._from_getter(lambda name, default: values.get(name, default))
    assert settings.market_data_source == "argentapi"
    values["AIDY_MARKET_DATA_OWNERSHIP"] = "broker_owned"
    with pytest.raises(RuntimeError, match="public_independent"):
        AidySettings._from_getter(lambda name, default: values.get(name, default))


def test_manifest_preserves_fail_closed_and_no_execution_boundaries() -> None:
    manifest = day53_genuine_live_gold_feed_manifest()
    assert manifest["quote_source"] == "argentapi"
    assert manifest["minimum_coverage_ratio"] == "0.90"
    assert manifest["missing_or_sparse_data_fails_closed"] is True
    assert manifest["api_key_header_only"] is True
    assert manifest["api_key_persisted"] is False
    assert manifest["decision_adapter_enabled_by_this_change"] is False
    assert manifest["super_signals_dependency_allowed"] is False
    assert manifest["live_money_execution_allowed"] is False
    assert manifest["freeze_break_reason"] == "material_safety_or_data_integrity_defect"


def test_worker_secret_is_header_boundary_only_and_smoke_never_returns_secret() -> None:
    source = (ROOT / "src" / "entry.py").read_text(encoding="utf-8")
    assert "AIDY_ARGENT_API_KEY" in source
    assert 'url.path == "/day53/live-gold-smoke"' in source
    assert '"AIDY_ARGENT_API_KEY":' not in source
    assert "MetaApi" not in source
    assert "Vantage" not in source
    assert "Super Signals" not in source
