from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import Request, urlopen

_SENTINEL = Path(".aidy_cf_recovery_started")


def _run(*args: str) -> None:
    subprocess.run(args, check=True)


def _json_get(url: str, token: str) -> dict:
    req = Request(url, headers={"Authorization": f"Bearer {token}"})
    with urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _health() -> dict:
    req = Request(
        "https://aidy-signals-test.dannythehat2.workers.dev/health?render_recovery=1",
        headers={"Cache-Control": "no-cache"},
    )
    with urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _recover() -> None:
    if os.environ.get("AIDY_EMERGENCY_CF_DEPLOY") != "1" or _SENTINEL.exists():
        return
    _SENTINEL.write_text("started\n", encoding="utf-8")

    if sys.version_info[:2] != (3, 13):
        raise RuntimeError(f"recovery runner must use Python 3.13, got {sys.version}")
    python313 = shutil.which("python3.13") or sys.executable
    if not python313:
        raise RuntimeError("Python 3.13 executable is not available")

    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("missing Cloudflare credential")

    print("AIDY_CF_RECOVERY_START=1", flush=True)
    print(f"AIDY_RECOVERY_PYTHON={sys.version.split()[0]}", flush=True)

    if not Path("src/aidy/provider_context_api.py").exists():
        raise RuntimeError("provider context source missing from recovery artifact")

    _run(sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--quiet", "uv")
    _run("uv", "sync", "--python", sys.executable)

    accounts = _json_get("https://api.cloudflare.com/client/v4/accounts", token)
    rows = accounts.get("result") or []
    if len(rows) != 1:
        raise RuntimeError(f"expected one accessible Cloudflare account, found {len(rows)}")
    account_id = rows[0]["id"]
    os.environ["CLOUDFLARE_ACCOUNT_ID"] = account_id

    _run(
        "uv", "run", "--python", sys.executable, "ruff", "check",
        "src/aidy/provider_market_api.py",
        "src/aidy/provider_context_api.py",
        "src/provider_entry.py",
    )
    _run("uv", "run", "--python", sys.executable, "python", "-m", "compileall", "-q", "src", "tests")
    _run(
        "uv", "run", "--python", sys.executable, "pytest", "-q",
        "tests/test_provider_market_api.py",
        "tests/test_provider_context_api.py",
        "tests/test_twelve_data_retrospective.py",
    )

    cfg = json.loads(Path("wrangler.test.example.jsonc").read_text(encoding="utf-8"))
    cfg["d1_databases"][0]["database_name"] = "aidy-ops-test"
    cfg["d1_databases"][0]["database_id"] = "3588d82a-d686-4430-872d-d4c0e62c3d5d"
    cfg["r2_buckets"][0]["bucket_name"] = "aidy-memory-test"
    cfg["vars"]["AIDY_CAPTURE_ENABLED"] = "true"
    cfg["vars"]["AIDY_MARKET_DATA_SOURCE"] = "twelve_data"
    cfg["vars"]["AIDY_MARKET_DATA_OWNERSHIP"] = "public_independent"
    cfg["vars"]["AIDY_MARKET_POLL_SECONDS"] = "300"
    cfg["vars"]["AIDY_FORMAL_FORWARD_ENABLED"] = "false"
    if cfg["triggers"]["crons"] != ["* * * * *"]:
        raise RuntimeError(f"unsafe cron config {cfg['triggers']}")
    Path("wrangler.jsonc").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print("AIDY_CONFIG_SAFE=PASS", flush=True)

    _run(python313, "--version")
    for key in (
        "UV_NO_MANAGED_PYTHON",
        "UV_SYSTEM_PYTHON",
        "UV_PROJECT_ENVIRONMENT",
        "UV_PYTHON",
    ):
        os.environ.pop(key, None)
    os.environ["UV_PYTHON_DOWNLOADS"] = "automatic"
    os.environ["UV_PYTHON_PREFERENCE"] = "managed"
    _run("uv", "run", "--python", sys.executable, "pywrangler", "deploy")

    schedules = _json_get(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/workers/scripts/aidy-signals-test/schedules",
        token,
    )
    result = schedules.get("result") or {}
    items = result.get("schedules", []) if isinstance(result, dict) else result
    crons = {row.get("cron") for row in items}
    if "* * * * *" not in crons:
        raise RuntimeError(f"minute cron missing after deploy: {crons}")
    print("AIDY_CRON_PRESENT=PASS", flush=True)

    for _ in range(18):
        try:
            health = _health()
        except Exception as exc:
            print(f"AIDY_HEALTH_FETCH_NONFATAL={type(exc).__name__}:{exc}", flush=True)
            return
        if (
            health.get("capture_enabled") is True
            and health.get("formal_forward_enabled") is False
            and health.get("market_data_source") == "twelve_data"
            and health.get("market_data_ownership") == "public_independent"
        ):
            print("AIDY_HEALTH_BOUNDARY=PASS", flush=True)
            print("AIDY_MANUAL_CF_DEPLOY=PASS", flush=True)
            return
        time.sleep(10)
    raise RuntimeError("post-deploy health boundary did not settle")


_recover()
