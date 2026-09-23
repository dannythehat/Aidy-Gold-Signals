"""No workflow may redeploy the live AIDY Worker with its schedule emptied.

The live Worker is `aidy-signals-test`. Its `* * * * *` cron is what captures market data,
runs the shadow loop and scores cycles. A deploy that ships `crons=[]` does not fail - it
succeeds, and AIDY silently stops collecting.

On 2026-09-21 the Day 11 calibration backfill did exactly that, triggered by an unrelated
edit to `src/provider_entry.py`. A fix (PR #181) was written and never merged, and on
2026-09-23 three workflows could still do it: Day 11 (fired by `provider_entry.py`), Day 6
(fired by `cross_market_storage.py`) and a dated 09-08 ops repair. All three were
completed one-off jobs and were deleted.

The two workflows allowed below set an empty cron only on a *different* Worker, so they
cannot touch capture. Anything else that deploys and empties the cron fails here.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

EMPTY_CRON = "cfg['triggers']['crons']=[]"
DEPLOY_MARKERS = ("pywrangler deploy", "wrangler deploy", "wrangler@4 deploy")

#: Deploy a separate Worker, never `aidy-signals-test`. Adding to this list is a claim
#: that the workflow cannot reach the live Worker - verify the name before adding.
NON_CANONICAL_WORKER_WORKFLOWS = {
    "day53-twelve-data-package-proof.yml": "renames the Worker to aidy-day53-twelve-package-test",
    "ops-provider-market-rollout-20260905.yml": "deploys aidy-signals-scheduler-test",
}

REMOVED_LANDMINES = (
    "day11-calibration-backfill.yml",
    "day6-archive-dead-letter-rollout.yml",
    "ops-provider-entry-queue-repair-20260908.yml",
)


def _deploys(text: str) -> bool:
    return any(marker in text for marker in DEPLOY_MARKERS)


def test_no_workflow_can_redeploy_the_live_worker_with_an_empty_cron() -> None:
    offenders = sorted(
        path.name
        for path in WORKFLOWS.glob("*.yml")
        if _deploys(text := path.read_text(encoding="utf-8"))
        and EMPTY_CRON in text
        and path.name not in NON_CANONICAL_WORKER_WORKFLOWS
    )
    assert offenders == [], (
        "these workflows deploy a Worker with an empty cron and are not proven to target "
        f"a non-live Worker - they would silently stop AIDY capture: {offenders}"
    )


def test_the_allowed_exceptions_really_target_other_workers() -> None:
    """The allowlist is only safe while each entry still points somewhere else."""
    day53 = (WORKFLOWS / "day53-twelve-data-package-proof.yml").read_text(encoding="utf-8")
    assert "cfg['name']='aidy-day53-twelve-package-test'" in day53

    rollout = (WORKFLOWS / "ops-provider-market-rollout-20260905.yml").read_text(
        encoding="utf-8"
    )
    assert "wrangler.scheduler.test.jsonc" in rollout
    scheduler = (ROOT / "wrangler.scheduler.test.jsonc").read_text(encoding="utf-8")
    assert '"name": "aidy-signals-scheduler-test"' in scheduler


def test_the_removed_landmines_stay_removed() -> None:
    for name in REMOVED_LANDMINES:
        assert not (WORKFLOWS / name).exists(), f"{name} was deleted on purpose - see module docstring"


def test_the_canonical_deploy_still_asserts_the_minute_cron() -> None:
    canonical = (WORKFLOWS / "aidy-provider-research-read-deploy.yml").read_text(
        encoding="utf-8"
    )
    assert "'* * * * *' in crons" in canonical
