from __future__ import annotations

import asyncio
import json

from aidy.openai_gateway import OpenAIMasterTraderGateway


async def main() -> None:
    gateway = OpenAIMasterTraderGateway.from_env()
    result = await gateway.evaluate({
        "context_hash": "day21_live_probe_synthetic_context",
        "as_of_utc": "2026-08-20T12:00:00+00:00",
        "symbol": "XAUUSD",
        "evidence_grade": "insufficient",
        "data_quality": {"state": "synthetic_probe_only"},
        "candidate_setups": [],
        "historical_analogues": [],
        "required_decision_timing": {
            "evaluated_at_utc": "2026-08-20T12:00:00+00:00",
            "valid_until_utc": "2026-08-20T12:05:00+00:00",
        },
        "instruction_context": (
            "Synthetic contract probe only; no real trade may be inferred. "
            "Return the required_decision_timing values exactly."
        ),
    })
    safe = {
        "status": result["status"],
        "publication_allowed": result["publication_allowed"],
        "failure_reason": result["failure_reason"],
        "response_id": result["response_id"],
        "provider_model": result["provider_model"],
        "usage": result["usage"],
        "estimated_cost_usd": result["estimated_cost_usd"],
        "pricing_version": result["pricing_version"],
        "latency_ms": result["latency_ms"],
        "attempts": result["attempts"],
        "decision_action": (result["structured_decision"] or {}).get("action"),
        "decision_digest": result["decision_digest"],
    }
    print(json.dumps(safe, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
