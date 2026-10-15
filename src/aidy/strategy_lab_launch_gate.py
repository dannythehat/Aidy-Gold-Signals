"""Day40: advisory checklist is never proof of consent, a sandbox charge or launch."""
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
    # Raw booleans are assertions, NOT authenticated evidence receipts. Even every
    # value=True is untrusted and cannot promote a research build to GO.
    blockers = sorted(name for name in GATES if evidence[name] is False)
    unverified = sorted(name for name in GATES if evidence[name] is True)
    report = {
        "status": "NO_GO",
        "original_40_day_program_complete": False,
        "unverified_assertions": unverified,
        "verified_external_evidence_count": 0,
        "evidence_origin": "UNTRUSTED_BOOLEAN_CHECKLIST",
        "missing_gates": blockers,
        "automated_trade_or_public_launch_authority": False,
        "owner_explicit_deployment_approval_separate": True,
        "trusted_external_receipt_verifier_implemented": False,
    }
    report["sha256"] = hashlib.sha256(json.dumps(
        report, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    return report
