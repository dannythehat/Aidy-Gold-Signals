"""Day39 executed local encrypted store restoration, never a remote disaster claim."""
import hashlib
import json
from pathlib import Path

import pytest

from aidy.strategy_lab_operational_controls import REQUIRED_EXTERNAL_GATES


def main() -> None:
    code = pytest.main(["-q", "tests/test_strategy_lab_operational_controls.py"])
    if int(code) != 0:
        raise RuntimeError("Local recovery tests failed")
    packet = {
        "day": 39,
        "status": "PARTIAL_EXTERNAL_OPERATIONS_BLOCKED",
        "local_sqlite_copy_restored_and_decrypted": True,
        "incident_safe_halt_tested": True,
        "remote_recovery_tested": False,
        "vendor_data_licence_verified": False,
        "real_cloud_budget_alerts_verified": False,
        "legal_and_customer_rights_approved": False,
        "owner_public_launch_approved": False,
        "external_blockers": list(REQUIRED_EXTERNAL_GATES),
    }
    packet["sha256"] = hashlib.sha256(
        json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    dest = Path("artifacts/strategy_lab/day39/ops_readiness.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(packet, sort_keys=True, indent=2) + "\n")
    print("Day39 local restore verified; remote/legal/production evidence BLOCKED")


if __name__ == "__main__":
    main()
