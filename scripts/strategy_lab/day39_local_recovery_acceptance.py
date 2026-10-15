"""Day39 scoped local recovery evidence; no public launch clearance."""
import json
import tempfile
from pathlib import Path
from aidy.strategy_lab_tenant_vault import TenantVault
from aidy.strategy_lab_operational_controls import OperationalControls

with tempfile.TemporaryDirectory() as d:
    v=TenantVault(Path(d)/"db.sqlite",encryption_key=b"K"*32,token_pepper=b"P"*32,provision_key=b"U"*32)
    ops=OperationalControls(v,operations_key=b"O"*32)
    receipt=ops.local_sqlite_backup(operator_key=b"O"*32,backup_path=Path(d)/"recovered.sqlite")
    assert receipt["quick_check"]=="ok"
    assert not receipt["remote_backup_restored"]
    out={"day":39,"status":"PARTIAL_EXTERNAL_READINESS_BLOCKED","local_restore":"PASS","real_remote_restore":False,"owner_launch_approved":False,"external_missing":ops.launch_blockers(operator_key=b"O"*32)["documented_external_gates_missing"]}
    path=Path("artifacts/strategy_lab/day39/local_recovery.json")
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(out,indent=2,sort_keys=True))
    print("Day39 LOCAL recovery PASS; external operations and legal gate BLOCKED")
