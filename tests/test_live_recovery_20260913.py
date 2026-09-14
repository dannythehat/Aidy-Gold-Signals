from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_provider_m1_recovery_keeps_pit_admission_without_forced_plan() -> None:
    sql = (ROOT / "migrations" / "d1" / "0016_provider_market_view_recovery.sql").read_text(
        encoding="utf-8"
    )
    assert "DROP VIEW IF EXISTS twelve_data_decision_admitted_m1_v1" in sql
    assert "CREATE VIEW twelve_data_decision_admitted_m1_v1" in sql
    assert "c.source='twelve_data_vendor_m1_v1'" in sql
    assert "c.symbol='XAUUSD'" in sql
    assert "c.timeframe='1m'" in sql
    assert "r.status='succeeded'" in sql
    assert "r.request_kind='scheduled_capture'" in sql
    assert "r.outputsize BETWEEN 1 AND 30" in sql
    assert "r.request_kind='bootstrap'" in sql
    assert "b.state='succeeded'" in sql
    view_sql = sql.split("CREATE VIEW twelve_data_decision_admitted_m1_v1 AS", 1)[1]
    assert "INDEXED BY" not in view_sql


def test_provider_market_endpoint_converts_store_failures_to_fail_closed_response() -> None:
    source = (ROOT / "src" / "aidy" / "provider_market_api.py").read_text(encoding="utf-8")
    assert '"market_evidence_store_unavailable"' in source
    assert "exception_type" in source
    assert "status=503" in source
    # Revision validation must also be inside the protected evidence-validation path.
    assert source.index("try:\n        selected = _latest_revisions(rows)") < source.index(
        '"market_evidence_invalid"'
    )


def test_direct_cron_template_cannot_regress_to_queue_or_no_schedule() -> None:
    cfg = json.loads((ROOT / "wrangler.test.example.jsonc").read_text(encoding="utf-8"))
    assert cfg["main"] == "src/provider_entry.py"
    # Per-minute Cron is required by the M1 publication-lag offset: market capture is
    # due two minutes past each five-minute boundary, and the former boundary-aligned
    # schedule had no tick in half of those windows. Capture cadence is unchanged.
    assert cfg["triggers"]["crons"] == ["* * * * *"]
    assert cfg["queues"]["consumers"] == []


def test_recovery_workflow_preserves_direct_cron_when_deploying() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "ops-aidy-live-recovery-20260913.yml"
    ).read_text(encoding="utf-8")
    assert "cfg['triggers']['crons'] == expected_crons" in workflow
    assert "cfg['queues']['consumers'] == []" in workflow
    assert "cfg['triggers']['crons']=[]" not in workflow
    assert "d1 migrations apply AIDY_OPS --remote" in workflow
    assert "twelve_data_decision_admitted_m1_v1" in workflow
