from __future__ import annotations

import json

import httpx
import pytest

from aidy.openai_gateway import (
    OPENAI_API_KEY_ENV,
    OPENAI_GATEWAY_VERSION,
    OPENAI_MODEL_ID,
    OPENAI_PROMPT_VERSION,
    OpenAIMasterTraderGateway,
    build_openai_request,
    openai_gateway_manifest,
)


def no_trade_decision() -> dict:
    return {
        "contract_version": "aidy_master_trader_decision_v1",
        "action": "no_trade",
        "symbol": "XAUUSD",
        "evaluated_at_utc": "2026-08-20T12:00:00+00:00",
        "valid_until_utc": "2026-08-20T12:05:00+00:00",
        "confidence": 0.42,
        "setup_taxonomy_version": "aidy_gold_setup_taxonomy_v1",
        "setup_codes": [],
        "reason_codes": ["insufficient_evidence"],
        "decision_summary": "Evidence does not earn a trade.",
        "target_decision_id": None,
        "direction": None,
        "entry_type": None,
        "market_reference_price": None,
        "stop_loss": None,
        "targets": [],
        "management_instruction": None,
        "new_stop_loss": None,
        "new_targets": [],
        "close_scope": None,
    }


def new_trade_decision() -> dict:
    value = no_trade_decision()
    value.update({
        "action": "new_trade",
        "confidence": 0.81,
        "setup_codes": ["trend_pullback_long"],
        "reason_codes": ["setup_present", "evidence_supportive"],
        "decision_summary": "Bullish pullback setup with defined invalidation.",
        "direction": "long",
        "entry_type": "market",
        "market_reference_price": 2500.0,
        "stop_loss": 2490.0,
        "targets": [2510.0, 2520.0],
    })
    return value


def provider_response(decision: dict | None = None, **overrides) -> dict:
    body = {
        "id": "resp_test_123",
        "status": "completed",
        "error": None,
        "model": OPENAI_MODEL_ID,
        "output": [{
            "type": "message",
            "content": [{"type": "output_text", "text": json.dumps(decision or no_trade_decision())}],
        }],
        "usage": {
            "input_tokens": 1000,
            "input_tokens_details": {"cached_tokens": 200},
            "output_tokens": 100,
            "output_tokens_details": {"reasoning_tokens": 40},
            "total_tokens": 1100,
        },
    }
    body.update(overrides)
    return body


def transport_for(responses: list[httpx.Response]):
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        response = responses[min(len(calls) - 1, len(responses) - 1)]
        response.request = request
        return response

    return httpx.MockTransport(handler), calls


async def no_sleep(_: float) -> None:
    return None


def test_manifest_pins_model_prompt_contract_and_fail_closed_boundary():
    manifest = openai_gateway_manifest()
    assert manifest["gateway_version"] == OPENAI_GATEWAY_VERSION
    assert manifest["model_id"] == OPENAI_MODEL_ID
    assert manifest["prompt_version"] == OPENAI_PROMPT_VERSION
    assert manifest["structured_outputs"] is True
    assert manifest["store_provider_response"] is False
    assert manifest["server_side_semantic_validation_required"] is True
    assert manifest["broker_or_telegram_access"] is False


def test_request_uses_responses_structured_outputs_and_store_false():
    request = build_openai_request({"context_hash": "abc", "evidence_grade": "insufficient"})
    assert request["model"] == OPENAI_MODEL_ID
    assert request["store"] is False
    assert request["reasoning"]["effort"] == "medium"
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["text"]["format"]["strict"] is True
    assert request["metadata"]["aidy_prompt_version"] == OPENAI_PROMPT_VERSION


def test_request_contains_no_api_key_field():
    request = build_openai_request({"context_hash": "abc"})
    text = json.dumps(request).lower()
    assert "openai_api_key" not in text
    assert "authorization" not in text


@pytest.mark.parametrize("key", ["api_key", "openai_api_key", "private_key", "authorization"])
def test_secret_bearing_input_keys_are_rejected(key):
    with pytest.raises(ValueError, match="Secret-bearing"):
        build_openai_request({key: "redacted"})


@pytest.mark.parametrize("value", ["sk-test-secret", "Bearer secret", "-----BEGIN PRIVATE KEY-----"])
def test_secret_like_values_are_rejected(value):
    with pytest.raises(ValueError, match="Secret-like"):
        build_openai_request({"note": value})


@pytest.mark.parametrize("key", ["broker", "mt5", "metaapi", "telegram", "super_signals", "follower"])
def test_external_execution_or_follower_keys_are_rejected(key):
    with pytest.raises(ValueError, match="External execution"):
        build_openai_request({key: {"state": "x"}})


def test_repr_redacts_key():
    gateway = OpenAIMasterTraderGateway("sk-test-do-not-show")
    assert "sk-test" not in repr(gateway)
    assert "<redacted>" in repr(gateway)


def test_from_env_requires_key(monkeypatch):
    monkeypatch.delenv(OPENAI_API_KEY_ENV, raising=False)
    with pytest.raises(RuntimeError, match=OPENAI_API_KEY_ENV):
        OpenAIMasterTraderGateway.from_env()


@pytest.mark.asyncio
async def test_schema_valid_no_trade_round_trips_and_is_publication_allowed():
    transport, calls = transport_for([httpx.Response(200, json=provider_response())])
    result = await OpenAIMasterTraderGateway("secret", transport=transport, sleep=no_sleep).evaluate({"context_hash": "abc"})
    assert result["status"] == "accepted"
    assert result["publication_allowed"] is True
    assert result["structured_decision"]["action"] == "no_trade"
    assert result["decision_digest"]
    assert result["attempts"] == 1
    assert len(calls) == 1
    assert calls[0].headers["authorization"] == "Bearer secret"


@pytest.mark.asyncio
async def test_schema_valid_new_trade_round_trips():
    transport, _ = transport_for([httpx.Response(200, json=provider_response(new_trade_decision()))])
    result = await OpenAIMasterTraderGateway("secret", transport=transport, sleep=no_sleep).evaluate({"context_hash": "abc"})
    assert result["status"] == "accepted"
    assert result["structured_decision"]["action"] == "new_trade"


@pytest.mark.asyncio
async def test_refusal_fails_closed():
    body = provider_response()
    body["output"][0]["content"] = [{"type": "refusal", "refusal": "No"}]
    transport, _ = transport_for([httpx.Response(200, json=body)])
    result = await OpenAIMasterTraderGateway("secret", transport=transport, sleep=no_sleep).evaluate({"context_hash": "abc"})
    assert result["status"] == "failed_closed"
    assert result["publication_allowed"] is False
    assert result["failure_reason"] == "model_refusal"


@pytest.mark.asyncio
async def test_incomplete_response_fails_closed():
    transport, _ = transport_for([httpx.Response(200, json=provider_response(status="incomplete"))])
    result = await OpenAIMasterTraderGateway("secret", transport=transport, sleep=no_sleep).evaluate({"context_hash": "abc"})
    assert result["failure_reason"] == "provider_incomplete_or_failed"
    assert result["publication_allowed"] is False


@pytest.mark.asyncio
async def test_provider_error_fails_closed():
    transport, _ = transport_for([httpx.Response(200, json=provider_response(error={"code": "x"}))])
    result = await OpenAIMasterTraderGateway("secret", transport=transport, sleep=no_sleep).evaluate({"context_hash": "abc"})
    assert result["failure_reason"] == "provider_incomplete_or_failed"


@pytest.mark.asyncio
async def test_missing_output_text_fails_closed():
    transport, _ = transport_for([httpx.Response(200, json=provider_response(output=[]))])
    result = await OpenAIMasterTraderGateway("secret", transport=transport, sleep=no_sleep).evaluate({"context_hash": "abc"})
    assert result["failure_reason"] == "missing_or_ambiguous_output_text"


@pytest.mark.asyncio
async def test_multiple_output_text_items_fail_closed():
    body = provider_response()
    body["output"][0]["content"].append({"type": "output_text", "text": json.dumps(no_trade_decision())})
    transport, _ = transport_for([httpx.Response(200, json=body)])
    result = await OpenAIMasterTraderGateway("secret", transport=transport, sleep=no_sleep).evaluate({"context_hash": "abc"})
    assert result["failure_reason"] == "missing_or_ambiguous_output_text"


@pytest.mark.asyncio
async def test_malformed_output_json_fails_closed():
    body = provider_response()
    body["output"][0]["content"][0]["text"] = "not-json"
    transport, _ = transport_for([httpx.Response(200, json=body)])
    result = await OpenAIMasterTraderGateway("secret", transport=transport, sleep=no_sleep).evaluate({"context_hash": "abc"})
    assert result["failure_reason"] == "malformed_structured_output"


@pytest.mark.asyncio
async def test_day20_semantic_validator_rejection_fails_closed():
    invalid = no_trade_decision()
    invalid["valid_until_utc"] = invalid["evaluated_at_utc"]
    transport, _ = transport_for([httpx.Response(200, json=provider_response(invalid))])
    result = await OpenAIMasterTraderGateway("secret", transport=transport, sleep=no_sleep).evaluate({"context_hash": "abc"})
    assert result["failure_reason"] == "semantic_validator_rejection"
    assert result["publication_allowed"] is False


@pytest.mark.asyncio
async def test_nonretryable_400_does_not_retry_or_store_body():
    transport, calls = transport_for([httpx.Response(400, json={"error": {"message": "sensitive provider body"}})])
    result = await OpenAIMasterTraderGateway("secret", transport=transport, sleep=no_sleep).evaluate({"context_hash": "abc"})
    assert result["failure_reason"] == "api_nonretryable_error"
    assert result["attempts"] == 1
    assert len(calls) == 1
    assert "sensitive provider body" not in json.dumps(result)


@pytest.mark.asyncio
async def test_429_retries_once_then_accepts():
    transport, calls = transport_for([
        httpx.Response(429, json={"error": {"message": "rate"}}),
        httpx.Response(200, json=provider_response()),
    ])
    result = await OpenAIMasterTraderGateway("secret", transport=transport, sleep=no_sleep).evaluate({"context_hash": "abc"})
    assert result["status"] == "accepted"
    assert result["attempts"] == 2
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_500_retries_once_then_fails_closed():
    transport, calls = transport_for([httpx.Response(500), httpx.Response(503)])
    result = await OpenAIMasterTraderGateway("secret", transport=transport, sleep=no_sleep).evaluate({"context_hash": "abc"})
    assert result["failure_reason"] == "api_retryable_error"
    assert result["attempts"] == 2
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_invalid_provider_json_fails_closed():
    transport, _ = transport_for([httpx.Response(200, text="not-json")])
    result = await OpenAIMasterTraderGateway("secret", transport=transport, sleep=no_sleep).evaluate({"context_hash": "abc"})
    assert result["failure_reason"] == "invalid_provider_json"


@pytest.mark.asyncio
async def test_unsafe_prompt_input_fails_before_network():
    transport, calls = transport_for([httpx.Response(200, json=provider_response())])
    result = await OpenAIMasterTraderGateway("secret", transport=transport, sleep=no_sleep).evaluate({"telegram": "x"})
    assert result["failure_reason"] == "unsafe_or_invalid_input"
    assert result["attempts"] == 0
    assert calls == []


@pytest.mark.asyncio
async def test_usage_cost_and_reproducibility_metadata_are_recorded():
    transport, _ = transport_for([httpx.Response(200, json=provider_response())])
    result = await OpenAIMasterTraderGateway("secret", transport=transport, sleep=no_sleep).evaluate({"context_hash": "abc"})
    assert result["usage"] == {
        "input_tokens": 1000,
        "cached_input_tokens": 200,
        "output_tokens": 100,
        "reasoning_tokens": 40,
        "total_tokens": 1100,
    }
    assert result["estimated_cost_usd"] == "0.007100"
    assert result["prompt_version"] == OPENAI_PROMPT_VERSION
    assert result["model_id"] == OPENAI_MODEL_ID
    assert result["response_id"] == "resp_test_123"


@pytest.mark.asyncio
async def test_api_key_never_appears_in_result():
    key = "sk-test-never-return"
    transport, _ = transport_for([httpx.Response(200, json=provider_response())])
    result = await OpenAIMasterTraderGateway(key, transport=transport, sleep=no_sleep).evaluate({"context_hash": "abc"})
    assert key not in json.dumps(result)
