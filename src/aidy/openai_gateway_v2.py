from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Awaitable, Callable, Mapping
from hashlib import sha256
from typing import Any

import httpx

from aidy.master_trader_contract_v2 import (
    MASTER_TRADER_CONTRACT_VERSION_V2,
    MASTER_TRADER_SCHEMA_VERSION_V2,
    master_trader_contract_manifest_v2,
    master_trader_decision_digest_versioned,
    master_trader_response_format_v2,
    validate_master_trader_decision_v2,
)
from aidy.openai_gateway import (
    _RETRY_STATUS_CODES,
    OPENAI_API_KEY_ENV,
    OPENAI_API_URL,
    OPENAI_CACHED_INPUT_PER_MILLION_USD,
    OPENAI_INPUT_PER_MILLION_USD,
    OPENAI_MAX_ATTEMPTS,
    OPENAI_MAX_OUTPUT_TOKENS,
    OPENAI_OUTPUT_PER_MILLION_USD,
    OPENAI_PRICING_VERSION,
    OPENAI_REASONING_EFFORT,
    OPENAI_RETRY_BACKOFF_SECONDS,
    OPENAI_TIMEOUT_SECONDS,
    _assert_safe_prompt_input,
    _canonical_json,
    _digest,
    _estimated_cost_usd,
    _extract_structured_text,
    _usage,
)

OPENAI_GATEWAY_VERSION_V2 = "aidy_openai_reasoning_gateway_v2_falsifiable"
OPENAI_PROMPT_VERSION_V2 = "aidy_master_trader_prompt_v2_falsifiable"
OPENAI_MODEL_ID_V2 = "gpt-5.6-sol"

MASTER_TRADER_INSTRUCTIONS_V2 = """You are AIDY Master Trader V2, the sole model-based trading judgement layer for a standalone XAUUSD signal provider.
Use only the supplied point-in-time evidence. Unknown stays unknown. Never invent market facts, probabilities, setup evidence, historical evidence, broker state, follower state, account state, Telegram state, execution state, or hidden reasoning.
Return exactly one strict Master Trader V2 decision: new_trade, manage_trade, close_trade, or no_trade.
For every actionable decision, preserve Day-20 XAUUSD geometry rules and also provide a concise falsifiable thesis, expected horizon, explicit counter-argument, and one machine-evaluable invalidation condition using only fields available in the supplied current context.
For no_trade, provide a concise abstention basis plus an auditable shadow thesis, shadow direction, horizon, and machine-evaluable shadow evaluation condition. no_trade is a valid outcome and must never be converted into an external action.
For manage_trade or close_trade, target only the exact originating AIDY decision ID supplied in the evidence. Never invent a target ID. Do not rewrite the original thesis or invalidation logic when the evidence bundle requires them to remain fixed.
Confidence is informational only. It never controls position size, account risk, gates, publication, or execution. Do not provide chain-of-thought, scratchpad, hidden analysis, lot size, leverage, account sizing, or follower instructions. Return only the strict JSON object requested."""


def _prompt_digest_v2() -> str:
    return sha256(MASTER_TRADER_INSTRUCTIONS_V2.encode()).hexdigest()


def openai_gateway_manifest_v2() -> dict[str, Any]:
    contract = master_trader_contract_manifest_v2()
    manifest: dict[str, Any] = {
        "gateway_version": OPENAI_GATEWAY_VERSION_V2,
        "prompt_version": OPENAI_PROMPT_VERSION_V2,
        "prompt_digest": _prompt_digest_v2(),
        "model_id": OPENAI_MODEL_ID_V2,
        "reasoning_effort": OPENAI_REASONING_EFFORT,
        "api_endpoint": "/v1/responses",
        "structured_outputs": True,
        "master_trader_contract_version": MASTER_TRADER_CONTRACT_VERSION_V2,
        "master_trader_schema_version": MASTER_TRADER_SCHEMA_VERSION_V2,
        "master_trader_manifest_digest": contract["manifest_digest"],
        "max_output_tokens": OPENAI_MAX_OUTPUT_TOKENS,
        "timeout_seconds": OPENAI_TIMEOUT_SECONDS,
        "max_attempts": OPENAI_MAX_ATTEMPTS,
        "pricing_version": OPENAI_PRICING_VERSION,
        "store_provider_response": False,
        "raw_provider_body_persisted": False,
        "secrets_allowed_in_prompt_or_metadata": False,
        "server_side_semantic_validation_required": True,
        "falsifiable_v2_required": True,
        "publication_implemented": False,
        "broker_or_telegram_access": False,
    }
    manifest["manifest_digest"] = _digest(manifest)
    return manifest


def build_openai_request_v2(evidence_bundle: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(evidence_bundle, Mapping):
        raise TypeError("evidence_bundle must be a mapping.")
    _assert_safe_prompt_input(evidence_bundle)
    evidence = json.loads(_canonical_json(evidence_bundle))
    return {
        "model": OPENAI_MODEL_ID_V2,
        "instructions": MASTER_TRADER_INSTRUCTIONS_V2,
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": _canonical_json(
                            {
                                "task": "Return exactly one AIDY Master Trader V2 decision.",
                                "evidence_bundle": evidence,
                            }
                        ),
                    }
                ],
            }
        ],
        "reasoning": {"effort": OPENAI_REASONING_EFFORT},
        "text": {"format": master_trader_response_format_v2(), "verbosity": "low"},
        "max_output_tokens": OPENAI_MAX_OUTPUT_TOKENS,
        "store": False,
        "metadata": {
            "aidy_gateway_version": OPENAI_GATEWAY_VERSION_V2,
            "aidy_prompt_version": OPENAI_PROMPT_VERSION_V2,
            "aidy_contract_version": MASTER_TRADER_CONTRACT_VERSION_V2,
        },
    }


def _safe_failure_v2(
    *,
    reason: str,
    attempts: int,
    latency_ms: int,
    request_digest: str,
    response: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    provider_usage = _usage(response or {})
    return {
        "gateway_version": OPENAI_GATEWAY_VERSION_V2,
        "status": "failed_closed",
        "publication_allowed": False,
        "failure_reason": reason,
        "structured_decision": None,
        "decision_digest": None,
        "request_digest": request_digest,
        "attempts": attempts,
        "latency_ms": latency_ms,
        "response_id": str((response or {}).get("id") or "") or None,
        "provider_status": str((response or {}).get("status") or "") or None,
        "provider_model": str((response or {}).get("model") or "") or None,
        "usage": provider_usage,
        "estimated_cost_usd": _estimated_cost_usd(provider_usage),
        "pricing_version": OPENAI_PRICING_VERSION,
        "prompt_version": OPENAI_PROMPT_VERSION_V2,
        "prompt_digest": _prompt_digest_v2(),
        "model_id": OPENAI_MODEL_ID_V2,
        "reasoning_effort": OPENAI_REASONING_EFFORT,
    }


class OpenAIMasterTraderGatewayV2:
    """Strict Responses-API gateway for falsifiable Master Trader V2."""

    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("OpenAI API key is required.")
        self._api_key = api_key.strip()
        self._transport = transport
        self._sleep = sleep

    @classmethod
    def from_env(cls, **kwargs: Any) -> OpenAIMasterTraderGatewayV2:
        key = os.environ.get(OPENAI_API_KEY_ENV, "")
        if not key:
            raise RuntimeError(f"{OPENAI_API_KEY_ENV} is not configured.")
        return cls(key, **kwargs)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(api_key=<redacted>, model={OPENAI_MODEL_ID_V2!r})"

    async def evaluate(self, evidence_bundle: Mapping[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            payload = build_openai_request_v2(evidence_bundle)
        except (TypeError, ValueError):
            return _safe_failure_v2(
                reason="unsafe_or_invalid_input",
                attempts=0,
                latency_ms=int((time.perf_counter() - started) * 1000),
                request_digest="",
            )

        request_digest = _digest(payload)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(OPENAI_TIMEOUT_SECONDS)
        attempts = 0
        response: Mapping[str, Any] | None = None

        async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
            while attempts < OPENAI_MAX_ATTEMPTS:
                attempts += 1
                try:
                    http_response = await client.post(
                        OPENAI_API_URL,
                        headers=headers,
                        json=payload,
                    )
                except httpx.RequestError:
                    if attempts < OPENAI_MAX_ATTEMPTS:
                        await self._sleep(OPENAI_RETRY_BACKOFF_SECONDS)
                        continue
                    return _safe_failure_v2(
                        reason="api_transport_error",
                        attempts=attempts,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        request_digest=request_digest,
                    )

                status_code = http_response.status_code
                if status_code >= 500 or status_code in _RETRY_STATUS_CODES:
                    if attempts < OPENAI_MAX_ATTEMPTS:
                        await self._sleep(OPENAI_RETRY_BACKOFF_SECONDS)
                        continue
                    return _safe_failure_v2(
                        reason="api_retryable_error",
                        attempts=attempts,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        request_digest=request_digest,
                    )
                if status_code < 200 or status_code >= 300:
                    return _safe_failure_v2(
                        reason="api_nonretryable_error",
                        attempts=attempts,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        request_digest=request_digest,
                    )
                try:
                    parsed_response = http_response.json()
                except ValueError:
                    return _safe_failure_v2(
                        reason="invalid_provider_json",
                        attempts=attempts,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        request_digest=request_digest,
                    )
                if not isinstance(parsed_response, Mapping):
                    return _safe_failure_v2(
                        reason="invalid_provider_json",
                        attempts=attempts,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        request_digest=request_digest,
                    )
                response = parsed_response
                break

        latency_ms = int((time.perf_counter() - started) * 1000)
        if response is None:
            return _safe_failure_v2(
                reason="api_transport_error",
                attempts=attempts,
                latency_ms=latency_ms,
                request_digest=request_digest,
            )
        if response.get("status") != "completed" or response.get("error") is not None:
            return _safe_failure_v2(
                reason="provider_incomplete_or_failed",
                attempts=attempts,
                latency_ms=latency_ms,
                request_digest=request_digest,
                response=response,
            )

        output_text, output_error = _extract_structured_text(response)
        if output_error is not None or output_text is None:
            return _safe_failure_v2(
                reason=output_error or "missing_output_text",
                attempts=attempts,
                latency_ms=latency_ms,
                request_digest=request_digest,
                response=response,
            )
        try:
            parsed = json.loads(output_text)
        except json.JSONDecodeError:
            return _safe_failure_v2(
                reason="malformed_structured_output",
                attempts=attempts,
                latency_ms=latency_ms,
                request_digest=request_digest,
                response=response,
            )
        try:
            decision = validate_master_trader_decision_v2(parsed)
        except (TypeError, ValueError):
            return _safe_failure_v2(
                reason="semantic_validator_rejection",
                attempts=attempts,
                latency_ms=latency_ms,
                request_digest=request_digest,
                response=response,
            )

        provider_usage = _usage(response)
        return {
            "gateway_version": OPENAI_GATEWAY_VERSION_V2,
            "status": "accepted",
            "publication_allowed": True,
            "failure_reason": None,
            "structured_decision": decision,
            "decision_digest": master_trader_decision_digest_versioned(decision),
            "request_digest": request_digest,
            "attempts": attempts,
            "latency_ms": latency_ms,
            "response_id": str(response.get("id") or "") or None,
            "provider_status": str(response.get("status") or "") or None,
            "provider_model": str(response.get("model") or "") or None,
            "usage": provider_usage,
            "estimated_cost_usd": _estimated_cost_usd(provider_usage),
            "pricing_version": OPENAI_PRICING_VERSION,
            "prompt_version": OPENAI_PROMPT_VERSION_V2,
            "prompt_digest": _prompt_digest_v2(),
            "model_id": OPENAI_MODEL_ID_V2,
            "reasoning_effort": OPENAI_REASONING_EFFORT,
        }


# Re-export pricing constants for immutable Day-34 reproducibility manifests.
DAY52_PRICING = {
    "input_per_million_usd": str(OPENAI_INPUT_PER_MILLION_USD),
    "cached_input_per_million_usd": str(OPENAI_CACHED_INPUT_PER_MILLION_USD),
    "output_per_million_usd": str(OPENAI_OUTPUT_PER_MILLION_USD),
    "pricing_version": OPENAI_PRICING_VERSION,
}