from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.gc_shadow_spine import (
    DAY41_PROMOTION_POLICY_VERSION,
    DAY41_SHADOW_VERSION,
    GcObservation,
    ShadowSpineError,
    XauObservation,
    day41_architecture_manifest,
    gc_shadow_promotion_policy,
    normalize_databento_api_key,
    pair_shadow_observations,
    parse_databento_ohlcv_jsonl,
    xau_observation_from_gold_api,
)

BASE = datetime(2026, 9, 1, 7, 0, tzinfo=UTC)
FAKE_DATABENTO_KEY = "db-" + ("a" * 29)


def test_databento_jsonl_requires_mapped_contract_identity() -> None:
    payload = "\n".join(
        [
            json.dumps(
                {
                    "stype_in_symbol": "GC.n.0",
                    "stype_out_symbol": "GCZ6",
                    "start_ts": "2026-08-28T00:00:00+00:00",
                }
            ),
            json.dumps(
                {
                    "ts_event": "2026-09-01T07:00:00+00:00",
                    "open": "4520.1",
                    "high": "4522.4",
                    "low": "4518.7",
                    "close": "4521.5",
                    "volume": 1234,
                }
            ),
        ]
    )
    rows = parse_databento_ohlcv_jsonl(payload)
    assert len(rows) == 1
    assert rows[0].contract_symbol == "GCZ6"
    assert rows[0].price == Decimal("4521.5")
    assert rows[0].provider == "Databento"


def test_databento_anonymous_instrument_fails_closed() -> None:
    payload = json.dumps(
        {
            "ts_event": "2026-09-01T07:00:00+00:00",
            "instrument_id": 123,
            "close": "4521.5",
        }
    )
    with pytest.raises(ShadowSpineError, match="contract identity"):
        parse_databento_ohlcv_jsonl(payload)


def test_gold_api_normalizes_independent_xau_reference() -> None:
    result = xau_observation_from_gold_api(
        {
            "symbol": "XAU",
            "price": 4500.25,
            "updatedAt": "2026-09-01T07:00:05Z",
        }
    )
    assert result.symbol == "XAUUSD"
    assert result.source == "gold_api_public"
    assert result.price == Decimal("4500.25")


def test_basis_pair_binds_sources_contract_and_timestamps() -> None:
    gc = GcObservation(BASE, Decimal("4521.50"), "GCZ6", source_digest="a" * 64)
    xau = XauObservation(
        BASE + timedelta(seconds=15),
        Decimal("4500.25"),
        source_digest="b" * 64,
    )
    pair = pair_shadow_observations(gc, xau, max_skew_seconds=60)
    assert pair["shadow_version"] == DAY41_SHADOW_VERSION
    assert pair["paired"] is True
    assert pair["state"] == "paired"
    assert pair["gc"]["contract_symbol"] == "GCZ6"
    assert pair["xau"]["source"] == "gold_api_public"
    assert pair["basis_usd"] == "21.25"
    assert pair["timestamp_skew_seconds"] == 15.0
    assert pair["gc_shadow_only"] is True
    assert pair["xau_reference_retained"] is True
    assert pair["live_gc_promoted"] is False


def test_timestamp_skew_does_not_create_fake_basis() -> None:
    gc = GcObservation(BASE, Decimal("4521.50"), "GCZ6")
    xau = XauObservation(BASE + timedelta(hours=2), Decimal("4500.25"))
    pair = pair_shadow_observations(gc, xau, max_skew_seconds=60)
    assert pair["paired"] is False
    assert pair["basis_usd"] is None
    assert pair["basis_bps"] is None
    assert pair["state"] == "unpaired_timestamp_skew"


def test_source_substitution_is_forbidden() -> None:
    gc = GcObservation(
        BASE,
        Decimal("4521.50"),
        "GCZ6",
        provider="SomeOtherFeed",
    )
    xau = XauObservation(BASE, Decimal("4500.25"))
    with pytest.raises(ShadowSpineError, match="substitution"):
        pair_shadow_observations(gc, xau)


def test_xau_reference_substitution_is_forbidden() -> None:
    gc = GcObservation(BASE, Decimal("4521.50"), "GCZ6")
    xau = XauObservation(BASE, Decimal("4500.25"), source="broker_feed")
    with pytest.raises(ShadowSpineError, match="substitution"):
        pair_shadow_observations(gc, xau)


def test_promotion_policy_is_frozen_before_results_and_never_autonomous() -> None:
    policy = gc_shadow_promotion_policy()
    assert policy["policy_version"] == DAY41_PROMOTION_POLICY_VERSION
    assert policy["frozen_before_shadow_results"] is True
    assert policy["minimum_paired_observations"] == 1000
    assert policy["maximum_p95_timestamp_skew_seconds"] == 120
    assert policy["require_xau_reference_parallel_run"] is True
    assert policy["automatic_promotion_allowed"] is False
    assert policy["performance_improvement_alone_can_promote"] is False


def test_day41_manifest_preserves_shadow_and_broker_free_boundaries() -> None:
    manifest = day41_architecture_manifest()
    assert manifest["provider"] == "Databento"
    assert manifest["dataset"] == "GLBX.MDP3"
    assert manifest["continuous_symbol"] == "GC.n.0"
    assert manifest["vendor_separable_adapter"] is True
    assert manifest["gc_shadow_only"] is True
    assert manifest["xau_reference_retained"] is True
    assert manifest["outage_substitution_allowed"] is False
    assert manifest["broker_market_data_dependency"] is False
    assert manifest["paid_subscription_activated"] is False
    assert manifest["live_gc_promoted"] is False


def test_invalid_gold_api_payload_fails_closed() -> None:
    with pytest.raises(ShadowSpineError):
        xau_observation_from_gold_api(
            {
                "symbol": "BTC",
                "price": 100,
                "updatedAt": "2026-09-01T07:00:05Z",
            }
        )


def test_databento_api_key_raw_format_is_retained() -> None:
    assert normalize_databento_api_key(FAKE_DATABENTO_KEY) == FAKE_DATABENTO_KEY


def test_databento_api_key_common_wrappers_are_safely_removed() -> None:
    assert normalize_databento_api_key(f'"{FAKE_DATABENTO_KEY}"') == FAKE_DATABENTO_KEY
    assert normalize_databento_api_key(f"DATABENTO_API_KEY={FAKE_DATABENTO_KEY}") == FAKE_DATABENTO_KEY
    assert (
        normalize_databento_api_key(f"DATABENTO_API_KEY='{FAKE_DATABENTO_KEY}'")
        == FAKE_DATABENTO_KEY
    )


def test_databento_api_key_invalid_final_value_fails_closed() -> None:
    with pytest.raises(ShadowSpineError, match="32-character"):
        normalize_databento_api_key("not-a-databento-key")
