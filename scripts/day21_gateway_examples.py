from __future__ import annotations

import asyncio
import json

import httpx

from aidy.openai_gateway import OpenAIMasterTraderGateway, openai_gateway_manifest


def decision() -> dict:
    return {
        "contract_version": "aidy_master_trader_decision_v1",
        "action": "no_trade",
        "symbol": "XAUUSD",
        "evaluated_at_utc": "2026-08-20T12:00:00+00:00",
        "valid_until_utc": "2026-08-20T12:05:00+00:00",
        "confidence": 0.41,
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


def response() -> dict:
    return {
        "id": "resp_day21_example",
        "status": "completed",
        "error": None,
        "model": "gpt-5.6-sol",
        "output": [{
            "type": "message",
            "content": [{"type": "output_text", "text": json.dumps(decision())}],
        }],
        "usage": {
            "input_tokens": 1000,
            "input_tokens_details": {"cached_tokens": 200},
            "output_tokens": 100,
            "output_tokens_details": {"reasoning_tokens": 40},
            "total_tokens": 1100,
        },
    }


async def main() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response(), request=request)

    gateway = OpenAIMasterTraderGateway(
        "example-not-a-real-key",
        transport=httpx.MockTransport(handler),
    )
    result = await gateway.evaluate({
        "context_hash": "example_context_hash",
        "evidence_grade": "insufficient",
        "candidate_setups": [],
    })
    print(json.dumps({
        "ok": result["status"] == "accepted",
        "manifest": openai_gateway_manifest(),
        "result": result,
    }, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
