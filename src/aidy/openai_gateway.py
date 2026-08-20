from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Awaitable, Callable, Mapping
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256
from typing import Any

import httpx

from aidy.master_trader_contract import (
    MASTER_TRADER_CONTRACT_VERSION,
    MASTER_TRADER_SCHEMA_VERSION,
    master_trader_contract_manifest,
    master_trader_decision_digest,
    master_trader_response_format,
    validate_master_trader_decision,
)

OPENAI_GATEWAY_VERSION = "aidy_openai_reasoning_gateway_v1"
OPENAI_PROMPT_VERSION = "aidy_master_trader_prompt_v1"
OPENAI_MODEL_ID = "gpt-5.6-sol"
OPENAI_REASONING_EFFORT = "medium"
OPENAI_API_URL = "https://api.openai.com/v1/responses"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
OPENAI_MAX_OUTPUT_TOKENS = 1800
OPENAI_TIMEOUT_SECONDS = 90.0
OPENAI_MAX_ATTEMPTS = 2
OPENAI_RETRY_BACKOFF_SECONDS = 0.5
OPENAI_PRICING_VERSION = "openai_gpt_5_6_sol_pricing_2026_08_20"
OPENAI_INPUT_PER_MILLION_USD = Decimal("5.00")
OPENAI_CACHED_INPUT_PER_MILLION_USD = Decimal("0.50")
OPENAI_OUTPUT_PER_MILLION_USD = Decimal("30.00")

MASTER_TRADER_INSTRUCTIONS = """You are AIDY Master Trader V1, the sole model-based trading judgement layer for a standalone XAUUSD signal provider.
Use only the evidence in the supplied input. Unknown stays unknown. Never invent market facts, setup evidence, historical probabilities, broker state, follower state, account state, Telegram state, or execution state.
Return exactly one decision conforming to the supplied Day 20 schema: new_trade, manage_trade, close_trade, or no_trade.
new_trade is XAUUSD market-entry only and requires a real Day 15 setup code, mandatory stop loss, and one to three ordered targets. manage_trade and close_trade may act only on an exact AIDY target_decision_id supplied in the evidence. If evidence is insufficient, contradictory, stale, unsafe, or does not earn a trade, choose no_trade.
Confidence is an informational judgement from 0 to 1 only. It never controls lot size, account risk, or position size. Do not provide hidden chain-of-thought, scratchpad, or analysis trace. decision_summary must contain only a concise final rationale grounded in supplied evidence."""

_FORBIDDEN_SECRET_KEYS = frozenset({
    "api_key", "openai_api_key", "cloudflare_api_token", "telegram_bot_token",
    "metaapi_token", "password", "secret", "client_secret", "service_account_json",
    "private_key", "authorization",
})
_FORBIDDEN_RUNTIME_KEYS = frozenset({
    "broker", "broker_account", "mt5", "metaapi", "vantage", "telegram",
    "super_signals", "follower", "follower_position", "account_balance", "account_equity",
})
_SECRET_VALUE_MARKERS = ("sk-", "bearer ", "-----begin private key-----")
_RETRY_STATUS_CODES = frozenset({408, 409, 429})


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _prompt_digest() -> str:
    return sha256(MASTER_TRADER_INSTRUCTIONS.encode()).hexdigest()


def _assert_safe_prompt_input(value: Any, *, path: str = "evidence") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_SECRET_KEYS:
                raise ValueError(f"Secret-bearing field is forbidden at {path}.{key}.")
            if normalized in _FORBIDDEN_RUNTIME_KEYS:
                raise ValueError(f"External execution/follower field is forbidden at {path}.{key}.")
            _assert_safe_prompt_input(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_safe_prompt_input(item, path=f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.strip().lower()
        if any(marker in lowered for marker in _SECRET_VALUE_MARKERS):
            raise ValueError(f"Secret-like value is forbidden at {path}.")


def openai_gateway_manifest() -> dict[str, Any]:
    contract = master_trader_contract_manifest()
    manifest = {
        "gateway_version": OPENAI_GATEWAY_VERSION,
        "prompt_version": OPENAI_PROMPT_VERSION,
        "prompt_digest": _prompt_digest(),
        "model_id": OPENAI_MODEL_ID,
        "reasoning_effort": OPENAI_REASONING_EFFORT,
        "api_endpoint": "/v1/responses",
        "structured_outputs": True,
        "day20_contract_version": MASTER_TRADER_CONTRACT_VERSION,
        "day20_schema_version": MASTER_TRADER_SCHEMA_VERSION,
        "day20_manifest_digest": contract["manifest_digest"],
        "max_output_tokens": OPENAI_MAX_OUTPUT_TOKENS,
        "timeout_seconds": OPENAI_TIMEOUT_SECONDS,
        "max_attempts": OPENAI_MAX_ATTEMPTS,
        "pricing_version": OPENAI_PRICING_VERSION,
        "store_provider_response": False,
        "raw_provider_body_persisted": False,
        "secrets_allowed_in_prompt_or_metadata": False,
        "server_side_semantic_validation_required": True,
        "publication_implemented": False,
        "broker_or_telegram_access": False,
    }
    manifest["manifest_digest"] = _digest(manifest)
    return manifest


def build_openai_request(evidence_bundle: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(evidence_bundle, Mapping):
        raise TypeError("evidence_bundle must be a mapping.")
    _assert_safe_prompt_input(evidence_bundle)
    evidence = json.loads(_canonical_json(evidence_bundle))
    return {
        "model": OPENAI_MODEL_ID,
        "instructions": MASTER_TRADER_INSTRUCTIONS,
        "input": [{
            "role": "user",
            "content": [{
                "type": "input_text",
                "text": _canonical_json({
                    "task": "Return exactly one AIDY Master Trader V1 decision.",
                    "evidence_bundle": evidence,
                }),
            }],
        }],
        "reasoning": {"effort": OPENAI_REASONING_EFFORT},
        "text": {"format": master_trader_response_format(), "verbosity": "low"},
        "max_output_tokens": OPENAI_MAX_OUTPUT_TOKENS,
        "store": False,
        "metadata": {
            "aidy_gateway_version": OPENAI_GATEWAY_VERSION,
            "aidy_prompt_version": OPENAI_PROMPT_VERSION,
            "aidy_contract_version": MASTER_TRADER_CONTRACT_VERSION,
        },
    }


def _usage(response: Mapping[str, Any]) -> dict[str, int]:
    usage = response.get("usage")
    if not isinstance(usage, Mapping):
        return {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0,
                "reasoning_tokens": 0, "total_tokens": 0}
    input_details = usage.get("input_tokens_details")
    output_details = usage.get("output_tokens_details")
    cached = int(input_details.get("cached_tokens", 0)) if isinstance(input_details, Mapping) else 0
    reasoning = int(output_details.get("reasoning_tokens", 0)) if isinstance(output_details, Mapping) else 0
    return {
        "input_tokens": int(usage.get("input_tokens", 0)),
        "cached_input_tokens": cached,
        "output_tokens": int(usage.get("output_tokens", 0)),
        "reasoning_tokens": reasoning,
        "total_tokens": int(usage.get("total_tokens", 0)),
    }


def _estimated_cost_usd(usage: Mapping[str, int]) -> str:
    input_tokens = max(int(usage["input_tokens"]), 0)
    cached = min(max(int(usage["cached_input_tokens"]), 0), input_tokens)
    uncached = input_tokens - cached
    output = max(int(usage["output_tokens"]), 0)
    million = Decimal(1_000_000)
    cost = (
        Decimal(uncached) * OPENAI_INPUT_PER_MILLION_USD
        + Decimal(cached) * OPENAI_CACHED_INPUT_PER_MILLION_USD
        + Decimal(output) * OPENAI_OUTPUT_PER_MILLION_USD
    ) / million
    return str(cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def _extract_structured_text(response: Mapping[str, Any]) -> tuple[str | None, str | None]:
    texts: list[str] = []
    refusals: list[str] = []
    output = response.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, Mapping) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, Mapping):
                    continue
                if part.get("type") == "refusal":
                    refusal = part.get("refusal") or part.get("text")
                    if isinstance(refusal, str) and refusal:
                        refusals.append(refusal)
                elif part.get("type") == "output_text":
                    text = part.get("text")
                    if isinstance(text, str) and text:
                        texts.append(text)
    if refusals:
        return None, "model_refusal"
    if len(texts) != 1:
        return None, "missing_or_ambiguous_output_text"
    return texts[0], None


def _safe_failure(
    *, reason: str, attempts: int, latency_ms: int, request_digest: str,
    response: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    provider_usage = _usage(response or {})
    return {
        "gateway_version": OPENAI_GATEWAY_VERSION,
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
        "prompt_version": OPENAI_PROMPT_VERSION,
        "prompt_digest": _prompt_digest(),
        "model_id": OPENAI_MODEL_ID,
        "reasoning_effort": OPENAI_REASONING_EFFORT,
    }


class OpenAIMasterTraderGateway:
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
    def from_env(cls, **kwargs: Any) -> OpenAIMasterTraderGateway:
        key = os.environ.get(OPENAI_API_KEY_ENV, "")
        if not key:
            raise RuntimeError(f"{OPENAI_API_KEY_ENV} is not configured.")
        return cls(key, **kwargs)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(api_key=<redacted>, model={OPENAI_MODEL_ID!r})"

    async def evaluate(self, evidence_bundle: Mapping[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            payload = build_openai_request(evidence_bundle)
        except (TypeError, ValueError):
            latency = int((time.perf_counter() - started) * 1000)
            return _safe_failure(
                reason="unsafe_or_invalid_input",
                attempts=0,
                latency_ms=latency,
                request_digest="",
            )

        request_digest = _digest(payload)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(OPENAI_TIMEOUT_SECONDS)
        attempts = 0

        async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
            while attempts < OPENAI_MAX_ATTEMPTS:
                attempts += 1
                try:
                    http_response = await client.post(OPENAI_API_URL, headers=headers, json=payload)
                except httpx.RequestError:
                    if attempts < OPENAI_MAX_ATTEMPTS:
                        await self._sleep(OPENAI_RETRY_BACKOFF_SECONDS)
                        continue
                    latency = int((time.perf_counter() - started) * 1000)
                    return _safe_failure(
                        reason="api_transport_error",
                        attempts=attempts,
                        latency_ms=latency,
                        request_digest=request_digest,
                    )

                status_code = http_response.status_code
                if status_code >= 500 or status_code in _RETRY_STATUS_CODES:
                    if attempts < OPENAI_MAX_ATTEMPTS:
                        await self._sleep(OPENAI_RETRY_BACKOFF_SECONDS)
                        continue
                    latency = int((time.perf_counter() - started) * 1000)
                    return _safe_failure(
                        reason="api_retryable_error",
                        attempts=attempts,
                        latency_ms=latency,
                        request_digest=request_digest,
                    )
                if status_code < 200 or status_code >= 300:
                    latency = int((time.perf_counter() - started) * 1000)
                    return _safe_failure(
                        reason="api_nonretryable_error",
                        attempts=attempts,
                        latency_ms=latency,
                        request_digest=request_digest,
                    )
                try:
                    response = http_response.json()
                except ValueError:
                    latency = int((time.perf_counter() - started) * 1000)
                    return _safe_failure(
                        reason="invalid_provider_json",
                        attempts=attempts,
                        latency_ms=latency,
                        request_digest=request_digest,
                    )
                break
            else:
                raise AssertionError("Unreachable retry state.")

        latency = int((time.perf_counter() - started) * 1000)
        if not isinstance(response, Mapping):
            return _safe_failure(
                reason="invalid_provider_json",
                attempts=attempts,
                latency_ms=latency,
                request_digest=request_digest,
            )
        if response.get("status") != "completed" or response.get("error") is not None:
            return _safe_failure(
                reason="provider_incomplete_or_failed",
                attempts=attempts,
                latency_ms=latency,
                request_digest=request_digest,
                response=response,
            )

        output_text, output_error = _extract_structured_text(response)
        if output_error is not None or output_text is None:
            return _safe_failure(
                reason=output_error or "missing_output_text",
                attempts=attempts,
                latency_ms=latency,
                request_digest=request_digest,
                response=response,
            )
        try:
            parsed = json.loads(output_text)
        except json.JSONDecodeError:
            return _safe_failure(
                reason="malformed_structured_output",
                attempts=attempts,
                latency_ms=latency,
                request_digest=request_digest,
                response=response,
            )
        try:
            decision = validate_master_trader_decision(parsed)
        except (TypeError, ValueError):
            return _safe_failure(
                reason="semantic_validator_rejection",
                attempts=attempts,
                latency_ms=latency,
                request_digest=request_digest,
                response=response,
            )

        provider_usage = _usage(response)
        return {
            "gateway_version": OPENAI_GATEWAY_VERSION,
            "status": "accepted",
            "publication_allowed": True,
            "failure_reason": None,
            "structured_decision": decision,
            "decision_digest": master_trader_decision_digest(decision),
            "request_digest": request_digest,
            "attempts": attempts,
            "latency_ms": latency,
            "response_id": str(response.get("id") or "") or None,
            "provider_status": str(response.get("status") or "") or None,
            "provider_model": str(response.get("model") or "") or None,
            "usage": provider_usage,
            "estimated_cost_usd": _estimated_cost_usd(provider_usage),
            "pricing_version": OPENAI_PRICING_VERSION,
            "prompt_version": OPENAI_PROMPT_VERSION,
            "prompt_digest": _prompt_digest(),
            "model_id": OPENAI_MODEL_ID,
            "reasoning_effort": OPENAI_REASONING_EFFORT,
        }
