from __future__ import annotations

import ast
from pathlib import Path

import pytest

from aidy.twelve_data_bootstrap import (
    BOOTSTRAP_MIN_REQUEST_SPACING_SECONDS,
    AidyTwelveDataBootstrapService,
)

ROOT = Path(__file__).resolve().parents[1]


def test_bootstrap_reattestation_admits_existing_immutable_candle_without_timestamp_rewrite() -> None:
    migration = (
        ROOT / "migrations" / "d1" / "0010_twelve_data_bootstrap_reattestation.sql"
    ).read_text(encoding="utf-8")

    assert "DROP VIEW IF EXISTS twelve_data_decision_admitted_m1_v1" in migration
    assert "r.completed_at_utc=c.first_observed_at" in migration
    assert "r.request_kind='scheduled_capture'" in migration
    assert "r.outputsize BETWEEN 1 AND 30" in migration

    bootstrap_clause = migration.split("OR\n    EXISTS (", maxsplit=1)[1]
    assert "r.request_kind='bootstrap'" in bootstrap_clause
    assert "b.state='succeeded'" in bootstrap_clause
    assert "c.open_time_utc>=b.window_start_utc" in bootstrap_clause
    assert "c.open_time_utc<b.window_end_utc" in bootstrap_clause
    assert "c.first_observed_at" not in bootstrap_clause
    assert "manual_probe" not in migration


@pytest.mark.asyncio
async def test_bootstrap_vendor_calls_are_paced_below_short_window_credit_burst() -> None:
    now = [0.0]
    sleeps: list[float] = []

    async def sleeper(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    service = AidyTwelveDataBootstrapService(
        repository=object(),  # type: ignore[arg-type]
        gateway=object(),  # type: ignore[arg-type]
        store=object(),  # type: ignore[arg-type]
        sleeper=sleeper,
        monotonic=lambda: now[0],
    )

    await service._pace_vendor_request()
    assert sleeps == []

    now[0] += 1.0
    await service._pace_vendor_request()

    assert BOOTSTRAP_MIN_REQUEST_SPACING_SECONDS == 9.0
    assert sleeps == [8.0]


def test_recovery_uses_ephemeral_masked_admin_secret_and_restores_bootstrap_off() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "day53-bootstrap-admission-recovery.yml"
    ).read_text(encoding="utf-8")

    mask = workflow.index('echo "::add-mask::$ADMIN_TOKEN"')
    install = workflow.index("secret put AIDY_DAY53_ADMIN_TOKEN")
    delete = workflow.index("secrets/AIDY_DAY53_ADMIN_TOKEN")

    assert mask < install < delete
    assert "AIDY_TWELVE_DATA_BOOTSTRAP_ENABLED']='true'" in workflow
    assert "AIDY_TWELVE_DATA_BOOTSTRAP_ENABLED']='false'" in workflow
    assert "AIDY_CAPTURE_ENABLED']='false'" in workflow
    assert "AIDY_FORMAL_FORWARD_ENABLED']='false'" in workflow
    assert "capture_status='complete'" in workflow
    assert "all_timeframes_ready" in workflow


def test_no_bootstrap_workflow_arms_the_live_forward_gate() -> None:
    """Backfilling market history must never activate live forward trading.

    Each of these workflows used to finish by dispatching
    day53-live-forward-activation.yml as a "production proof", and the hardened one
    asserted its own dispatch was present, so the chain was deliberate rather than a
    slip. On 2026-09-14 a re-dispatch of a bootstrap recovery run followed that chain,
    deployed AIDY_FORMAL_FORWARD_ENABLED=true and activated a live forward cohort that
    nobody had asked for. Repairing market data is not evidence that the system should
    start trading forward, and the two decisions belong to different people.
    """
    for name in (
        "day53-hardened-bootstrap-recovery.yml",
        "day53-bootstrap-admission-recovery.yml",
        "day53-resumable-bootstrap-recovery.yml",
    ):
        workflow = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert "day53-live-forward-activation.yml/dispatches" not in workflow, name
        assert "AIDY_FORMAL_FORWARD_ENABLED']='false'" in workflow, name


def test_resumable_bootstrap_runtime_is_bounded_and_retry_safe() -> None:
    bootstrap = (ROOT / "src" / "aidy" / "twelve_data_bootstrap.py").read_text(encoding="utf-8")
    entry = (ROOT / "src" / "entry.py").read_text(encoding="utf-8")
    assert "MAX_BOOTSTRAP_WINDOW_MINUTES = 30" in bootstrap
    assert '"continue_bootstrap"' in entry
    assert '"remaining_m1_minutes"' in entry
    assert "planned_windows=1" in entry
    assert '"decision_snapshot_created": False' in entry
    assert '"decision_ready": False' in entry


def test_provider_aware_entry_keeps_queue_handler_concrete_after_recovery() -> None:
    """Recovery must restore a Worker that can still consume scheduler messages."""

    source = (ROOT / "src" / "provider_entry.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    default = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Default"
    )
    methods = {node.name for node in default.body if isinstance(node, ast.AsyncFunctionDef)}
    assert "fetch" in methods
    assert "queue" in methods
