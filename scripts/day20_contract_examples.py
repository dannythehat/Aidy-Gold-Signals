from __future__ import annotations

import json

from aidy.master_trader_contract import (
    MASTER_TRADER_CONTRACT_VERSION,
    master_trader_contract_manifest,
    master_trader_decision_digest,
    validate_master_trader_decision,
)
from aidy.setup_detector import SETUP_TAXONOMY_VERSION


def _base(action: str) -> dict[str, object]:
    return {
        "contract_version": MASTER_TRADER_CONTRACT_VERSION,
        "action": action,
        "symbol": "XAUUSD",
        "evaluated_at_utc": "2026-08-20T12:00:00+00:00",
        "valid_until_utc": "2026-08-20T12:15:00+00:00",
        "confidence": 0.75,
        "setup_taxonomy_version": SETUP_TAXONOMY_VERSION,
        "setup_codes": [],
        "reason_codes": ["evidence_supportive"],
        "decision_summary": "Accepted evidence supports this bounded decision.",
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


def examples() -> list[dict[str, object]]:
    new_trade = _base("new_trade")
    new_trade.update(
        {
            "setup_codes": ["trend_pullback_long"],
            "direction": "long",
            "entry_type": "market",
            "market_reference_price": 2500.0,
            "stop_loss": 2480.0,
            "targets": [2520.0, 2540.0],
        }
    )

    manage_trade = _base("manage_trade")
    manage_trade.update(
        {
            "target_decision_id": "aidy_dec_12345678",
            "management_instruction": "move_stop",
            "new_stop_loss": 2505.0,
            "reason_codes": ["thesis_intact"],
        }
    )

    close_trade = _base("close_trade")
    close_trade.update(
        {
            "target_decision_id": "aidy_dec_12345678",
            "close_scope": "full",
            "reason_codes": ["thesis_invalidated"],
        }
    )

    no_trade = _base("no_trade")
    no_trade.update(
        {
            "confidence": 0.82,
            "reason_codes": ["evidence_insufficient"],
            "decision_summary": "No trade is earned by the currently accepted evidence.",
        }
    )

    return [new_trade, manage_trade, close_trade, no_trade]


def main() -> int:
    validated = []
    for raw in examples():
        decision = validate_master_trader_decision(raw)
        validated.append(
            {
                "action": decision["action"],
                "decision_digest": master_trader_decision_digest(decision),
                "target_decision_id": decision["target_decision_id"],
                "setup_codes": decision["setup_codes"],
            }
        )

    assert [item["action"] for item in validated] == [
        "new_trade",
        "manage_trade",
        "close_trade",
        "no_trade",
    ]
    assert validated[0]["target_decision_id"] is None
    assert validated[1]["target_decision_id"] == "aidy_dec_12345678"
    assert validated[2]["target_decision_id"] == "aidy_dec_12345678"
    assert validated[3]["target_decision_id"] is None

    output = {
        "ok": True,
        "manifest": master_trader_contract_manifest(),
        "validated_examples": validated,
    }
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
