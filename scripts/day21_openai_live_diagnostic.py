from __future__ import annotations

import asyncio
import json
import os

import httpx

from aidy.master_trader_contract import validate_master_trader_decision
from aidy.openai_gateway import OPENAI_API_KEY_ENV, OPENAI_API_URL, build_openai_request


def extract_output_text(response: dict) -> str:
    texts: list[str] = []
    for item in response.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content", []):
            if isinstance(part, dict) and part.get("type") == "output_text":
                text = part.get("text")
                if isinstance(text, str) and text:
                    texts.append(text)
    if len(texts) != 1:
        raise RuntimeError(f"Expected one output_text item, found {len(texts)}.")
    return texts[0]


async def main() -> None:
    api_key = os.environ.get(OPENAI_API_KEY_ENV, "")
    if not api_key:
        raise RuntimeError(f"{OPENAI_API_KEY_ENV} is not configured.")

    evidence = {
        "context_hash": "day21_live_probe_synthetic_context",
        "as_of_utc": "2026-08-20T12:00:00+00:00",
        "symbol": "XAUUSD",
        "evidence_grade": "insufficient",
        "data_quality": {"state": "synthetic_probe_only"},
        "candidate_setups": [],
        "historical_analogues": [],
        "instruction_context": "Synthetic contract probe only; no real trade may be inferred.",
    }
    payload = build_openai_request(evidence)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(OPENAI_API_URL, headers=headers, json=payload)
    response.raise_for_status()
    body = response.json()
    output_text = extract_output_text(body)
    decision = json.loads(output_text)

    validation_error = None
    try:
        validate_master_trader_decision(decision)
    except (TypeError, ValueError) as exc:
        validation_error = f"{type(exc).__name__}: {exc}"

    safe = {
        "response_id": body.get("id"),
        "provider_model": body.get("model"),
        "provider_status": body.get("status"),
        "decision": decision,
        "validation_error": validation_error,
    }
    print(json.dumps(safe, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
