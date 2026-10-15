"""Day40 immutable readiness decision: no synthetic pilot can be promoted."""
from __future__ import annotations

import hashlib
import json

GATES = (
    "day03_owner_approval", "day06_owner_approval",
    "b00_b11_owner_signoff", "day38_actual_payment_sandbox",
    "day39_production_operational_clearance",
    "independent_customer_security_audit",
    "consenting_real_two_user_pilot", "qualified_data_licences",
    "contract_and_regulatory_legal_review",
    "verified_original_broker_parity",
)

def evaluate_launch(evidence: dict) -> dict:
    if not isinstance(evidence, dict) or set(evidence) != set(GATES):
        raise ValueError("Missing or extra hard launch gates")
    if any(type(value) is not bool for value in evidence.values()):
        raise ValueError("Hard gates require independently evidenced booleans")
    # No incoming 'test fixture passed' may turn into trusted real-world proof.
    blockers = sorted(name for name in GATES if evidence[name] is False)
    report = {
        "status": "GO" if not blockers else "NO_GO",
        "original_40_day_program_complete": not blockers,
        "missing_gates": blockers,
        "automated_trade_or_public_launch_authority": False,
        "owner_explicit_deployment_approval_separate": True,
    }
    report["sha256"] = hashlib.sha256(json.dumps(
        report, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    return report
