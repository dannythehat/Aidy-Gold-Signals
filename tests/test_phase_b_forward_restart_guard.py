from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_restart_registry_is_one_shot_and_research_only() -> None:
    sql = (ROOT / "migrations" / "d1" / "0020_phase_b_forward_restart_guard.sql").read_text(
        encoding="utf-8"
    )
    assert "CREATE UNIQUE INDEX IF NOT EXISTS ux_aidy_forward_cohorts_one_active_version" in sql
    assert "WHERE state='active'" in sql
    assert "campaign_id TEXT PRIMARY KEY" in sql
    assert "acceptance_state IN ('activated','model_resolved')" in sql
    assert "consecutive_capture_successes >= 3" in sql
    assert "recent_complete_snapshots >= 2" in sql
    assert "model_gateway_configured = 1" in sql
    assert "broker_or_account_state_allowed = 0" in sql
    assert "follower_state_allowed = 0" in sql
    assert "super_signals_dependency_allowed = 0" in sql
    assert "live_money_execution_allowed = 0" in sql


def test_restart_workflow_requires_open_fresh_market_before_mutation() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "phase-b-forward-restart.yml"
    ).read_text(encoding="utf-8")
    required = (
        "gold_session_is_open",
        "data_health_status",
        "consecutive_capture_successes",
        "recent_complete_snapshots",
        "private_forward_model_gateway_configured",
        "stale_archive_rows",
        "steps.gate.outputs.ready == 'true'",
        "material_safety_or_data_integrity_defect",
        "performance_information_used':False",
        "AIDY_FORMAL_FORWARD_ENABLED']='true'",
        "scheduler')=='direct-cron'",
        "live_money_execution_allowed",
        "super_signals_dependency_allowed",
    )
    for token in required:
        assert token in workflow, token


def test_restart_workflow_never_adds_queue_or_live_execution_dependency() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "phase-b-forward-restart.yml"
    ).read_text(encoding="utf-8")
    assert "assert cfg['queues']['consumers']==[]" in workflow
    assert "assert cfg['triggers']['crons']==['*/2 * * * *','5,15,25,35,45,55 * * * *']" in workflow
    assert "telegram_publication_enabled':False" in workflow
    assert "live_money_execution_enabled':False" in workflow
    assert "performance_information_used':False" in workflow
    assert "MetaAPI" not in workflow
    assert "Vantage" not in workflow
    assert "MT5" not in workflow
