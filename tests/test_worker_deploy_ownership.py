from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_day11_backfill_cannot_deploy_or_disable_canonical_worker_cron() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "day11-calibration-backfill.yml"
    ).read_text(encoding="utf-8")
    assert "pywrangler deploy" not in workflow
    assert "cfg['triggers']['crons']=[]" not in workflow
    assert "cfg['triggers']['crons']=['* * * * *']" in workflow

    push_section = workflow.split("  push:", 1)[1].split("\nconcurrency:", 1)[0]
    assert '"src/provider_entry.py"' not in push_section
    assert '"src/aidy/provider_calibration_api.py"' not in push_section


def test_canonical_deploy_owns_calibration_route_and_preserves_minute_cron() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "aidy-provider-research-read-deploy.yml"
    ).read_text(encoding="utf-8")
    assert '"src/aidy/provider_calibration_api.py"' in workflow
    assert "src/aidy/provider_calibration_api.py" in workflow
    assert "tests/test_day11_calibration_backfill.py" in workflow
    assert "assert cfg['triggers']['crons'] == ['* * * * *']" in workflow
    assert "pywrangler deploy" in workflow
