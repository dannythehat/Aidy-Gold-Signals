"""Day40 checks actual unresolved external prerequisites and records NO_GO."""
import json
from pathlib import Path

from aidy.strategy_lab_launch_gate import GATES, evaluate_launch

evidence = dict.fromkeys(GATES, False)
verdict = evaluate_launch(evidence)
assert verdict["status"] == "NO_GO"
assert verdict["automated_trade_or_public_launch_authority"] is False
payload = {"day": 40, "verdict": verdict,
           "actual_consenting_customer_pilot_completed": False,
           "real_provider_test_payment_completed": False,
           "strategy_profitability_tested": False,
           "original_gold_edge_83_candidates": "UNTESTED",
           "original_day40_acceptance": "BLOCKED"}
p = Path("artifacts/strategy_lab/day40/go_no_go.json")
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
print("Day40 evidence NO_GO: controlled pilot not authorised")
