from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest

from aidy.databento_gc import (
    ALLOWED_RESEARCH_SCHEMAS,
    DATABENTO_DATASET,
    DAY40_CREDIT_RESERVE_USD,
    DAY40_CREDIT_SPEND_CAP_USD,
    DatabentoAuthenticationError,
    DatabentoHistoricalClient,
    DatabentoPolicyError,
    HistoricalRequest,
    day40_free_first_procurement_record,
)
from aidy.day40_gate import (
    ADVERSARIAL_SCENARIOS,
    P0_REQUIREMENTS,
    adversarial_failure_record,
    run_adversarial_matrix,
    validate_formal_paper_metric,
)

FAKE_KEY = "db-" + ("a" * 29)


def _transport(*, cost: str = "0.25") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("authorization", "").startswith("Basic ")
        if request.url.path.endswith("/metadata.list_datasets"):
            return httpx.Response(200, json=[DATABENTO_DATASET, "XNAS.ITCH"])
        if request.url.path.endswith("/metadata.list_schemas"):
            return httpx.Response(200, json=sorted(ALLOWED_RESEARCH_SCHEMAS | {"mbo", "mbp-10"}))
        if request.url.path.endswith("/metadata.get_dataset_range"):
            return httpx.Response(
                200,
                json={
                    "start": "2010-06-06T00:00:00.000000000Z",
                    "end": "2026-09-01T00:00:00.000000000Z",
                    "schema": {
                        "ohlcv-1m": {
                            "start": "2010-06-06T00:00:00.000000000Z",
                            "end": "2026-09-01T00:00:00.000000000Z",
                        }
                    },
                },
            )
        if request.url.path.endswith("/metadata.get_cost"):
            return httpx.Response(200, json=float(cost))
        if request.url.path.endswith("/timeseries.get_range"):
            return httpx.Response(
                200,
                text=(
                    '{"ts_event":"2026-08-31T12:00:00Z","open":"3500.0",'
                    '"high":"3501.0","low":"3499.0","close":"3500.5","volume":100,'
                    '"symbol":"GCZ6"}\n'
                ),
            )
        return httpx.Response(404, json={"error": "unexpected endpoint"})

    return httpx.MockTransport(handler)


def test_documented_databento_key_shape_is_enforced() -> None:
    with pytest.raises(DatabentoAuthenticationError):
        DatabentoHistoricalClient("wrong", transport=_transport())


def test_authenticated_metadata_and_gc_entitlement_contract() -> None:
    with DatabentoHistoricalClient(FAKE_KEY, transport=_transport()) as client:
        result = client.assert_gc_entitlement()
        available = client.dataset_range()
    assert result["authenticated"] is True
    assert result["dataset"] == "GLBX.MDP3"
    assert result["live_subscription_required"] is False
    assert "ohlcv-1m" in available["schema"]


def test_cost_is_quoted_before_bounded_download(tmp_path) -> None:
    request = HistoricalRequest(
        schema="ohlcv-1m",
        start="2026-08-01T00:00:00Z",
        end="2026-08-02T00:00:00Z",
    )
    path = tmp_path / "gc.jsonl"
    with DatabentoHistoricalClient(FAKE_KEY, transport=_transport(cost="0.25")) as client:
        quote = client.estimate_cost(request)
        assert quote.approved is True
        result = client.download_jsonl(request, quote=quote, output_path=path)

    assert result["quoted_cost_usd"] == "0.25"
    assert result["historical_only"] is True
    assert result["paid_subscription_enabled"] is False
    assert path.read_text(encoding="utf-8").endswith("\n")
    assert json.loads(path.read_text(encoding="utf-8"))["symbol"] == "GCZ6"


def test_single_request_cost_cap_fails_closed() -> None:
    request = HistoricalRequest(
        schema="trades",
        start="2026-01-01T00:00:00Z",
        end="2026-09-01T00:00:00Z",
    )
    with DatabentoHistoricalClient(FAKE_KEY, transport=_transport(cost="5.01")) as client:
        quote = client.estimate_cost(request)
    assert quote.approved is False


def test_cumulative_free_credit_cap_preserves_reserve() -> None:
    request = HistoricalRequest(
        schema="tbbo",
        start="2026-08-01T00:00:00Z",
        end="2026-08-02T00:00:00Z",
    )
    with DatabentoHistoricalClient(FAKE_KEY, transport=_transport(cost="2.00")) as client:
        quote = client.estimate_cost(request, prior_committed_usd=Decimal("74.00"))
    assert quote.approved is False
    assert DAY40_CREDIT_SPEND_CAP_USD + DAY40_CREDIT_RESERVE_USD == Decimal("125.00")


def test_l2_l3_expensive_schemas_are_deliberately_rejected() -> None:
    for schema in ("mbo", "mbp-10"):
        request = HistoricalRequest(
            schema=schema,
            start="2026-08-01T00:00:00Z",
            end="2026-08-02T00:00:00Z",
        )
        with pytest.raises(DatabentoPolicyError):
            request.validate()


def test_definition_requests_use_parent_symbology_for_roll_provenance() -> None:
    with pytest.raises(DatabentoPolicyError):
        HistoricalRequest(
            schema="definition",
            start="2026-08-01T00:00:00Z",
            end="2026-08-02T00:00:00Z",
        ).validate()

    HistoricalRequest(
        schema="definition",
        start="2026-08-01T00:00:00Z",
        end="2026-08-02T00:00:00Z",
        symbols="GC.FUT",
        stype_in="parent",
    ).validate()


def test_procurement_record_is_free_first_and_non_live() -> None:
    record = day40_free_first_procurement_record()
    assert record["decision"] == "go_gc_research_no_go_paid_live"
    assert record["preferred_historical_provider"] == "Databento"
    assert record["free_credit_usd"] == "125.00"
    assert record["paid_subscription_enabled"] is False
    assert record["owner_approval_required_before_paid_activation"] is True


def test_day40_has_exactly_18_machine_checklist_items() -> None:
    assert len(P0_REQUIREMENTS) == 18
    assert [item.requirement_id for item in P0_REQUIREMENTS] == [
        f"P0-{index:02d}" for index in range(1, 19)
    ]


def test_all_adversarial_scenarios_default_to_fail_closed() -> None:
    result = run_adversarial_matrix()
    assert result["scenario_count"] == len(ADVERSARIAL_SCENARIOS)
    assert result["all_failed_closed"] is True
    assert result["publication_mutation_observed"] is False
    assert result["broker_mutation_observed"] is False
    assert result["super_signals_mutation_observed"] is False


def test_adversarial_mutation_is_not_mislabelled_fail_closed() -> None:
    result = adversarial_failure_record("provider_outage", broker_mutated=True)
    assert result["fail_closed"] is False


def test_pre_gate_formal_paper_metrics_are_rejected() -> None:
    assert validate_formal_paper_metric(generated_after_day40_gate=False) == {
        "accepted": False,
        "reason": "pre_day40_formal_paper_metrics_are_non_authoritative",
    }
    assert validate_formal_paper_metric(generated_after_day40_gate=True)["accepted"] is True
