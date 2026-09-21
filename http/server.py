from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request

WORKER_URL = "https://aidy-signals-test.dannythehat2.workers.dev/health"
D1_ID = "3588d82a-d686-4430-872d-d4c0e62c3d5d"


def _serve_stdlib() -> None:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    os.chdir("/tmp")
    os.execve(
        sys.executable,
        [sys.executable, "-m", "http.server", os.environ.get("PORT", "10000")],
        env,
    )


def _health() -> dict:
    with urllib.request.urlopen(
        f"{WORKER_URL}?runner={int(time.time())}",
        timeout=20,
    ) as response:
        return json.load(response)


def _target_live() -> bool:
    try:
        h = _health()
    except Exception:
        return False
    return (
        h.get("capture_enabled") is True
        and h.get("formal_forward_enabled") is False
        and h.get("market_data_source") == "twelve_data"
        and h.get("market_data_ownership") == "public_independent"
        and h.get("provider_context_api_version") == "aidy_provider_context_api_v5"
        and h.get("gold_state_engine_version") == "aidy_gold_state_engine_v1"
        and h.get("gold_movement_investigator_version") == "aidy_gold_movement_investigator_v1"
        and h.get("gold_movement_memory_version") == "aidy_gold_movement_memory_v1"
    )


def _cf_json(url: str, *, token: str, data: dict | None = None) -> dict:
    body = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method="POST" if data is not None else "GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def main() -> None:
    if os.environ.get("AIDY_GOLD_DEPLOY_RUNNER") != "1":
        _serve_stdlib()

    if _target_live():
        print("gold_movement_worker_already_live=true", flush=True)
        _serve_stdlib()

    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if not token:
        raise SystemExit("missing CLOUDFLARE_API_TOKEN")

    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--quiet", "uv"],
        check=True,
    )
    subprocess.run(["uv", "sync"], check=True)
    subprocess.run(
        [
            "uv", "run", "ruff", "check",
            "src/aidy/provider_market_api.py",
            "src/aidy/provider_context_api.py",
            "src/aidy/gold_state_engine.py",
            "src/aidy/gold_movement_investigator.py",
            "src/aidy/gold_movement_memory.py",
            "src/aidy/private_forward_context.py",
            "src/provider_entry.py",
        ],
        check=True,
    )
    subprocess.run(
        [
            "uv", "run", "pytest", "-q",
            "tests/test_provider_context_api.py",
            "tests/test_gold_state_engine.py",
            "tests/test_gold_movement_investigator.py",
            "tests/test_gold_movement_memory.py",
        ],
        check=True,
    )

    accounts = _cf_json("https://api.cloudflare.com/client/v4/accounts", token=token)
    assert accounts.get("success") is True, accounts
    result = accounts.get("result") or []
    assert len(result) == 1, {"account_count": len(result)}
    account_id = result[0]["id"]

    cfg = json.load(open("wrangler.test.example.jsonc", encoding="utf-8"))
    cfg["d1_databases"][0]["database_name"] = "aidy-ops-test"
    cfg["d1_databases"][0]["database_id"] = D1_ID
    cfg["r2_buckets"][0]["bucket_name"] = "aidy-memory-test"
    cfg["vars"]["AIDY_CAPTURE_ENABLED"] = "true"
    cfg["vars"]["AIDY_MARKET_DATA_SOURCE"] = "twelve_data"
    cfg["vars"]["AIDY_MARKET_DATA_OWNERSHIP"] = "public_independent"
    cfg["vars"]["AIDY_MARKET_POLL_SECONDS"] = "300"
    cfg["vars"]["AIDY_FORMAL_FORWARD_ENABLED"] = "false"
    assert cfg["triggers"]["crons"] == ["* * * * *"]
    with open("wrangler.jsonc", "w", encoding="utf-8") as handle:
        json.dump(cfg, handle, indent=2)

    migration_sql = open(
        "migrations/d1/0021_gold_movement_memory.sql",
        encoding="utf-8",
    ).read()
    migration = _cf_json(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{D1_ID}/query",
        token=token,
        data={"sql": migration_sql},
    )
    assert migration.get("success") is True, migration
    assert all(item.get("success") for item in (migration.get("result") or [])), migration
    print("gold_movement_tables_ready=true", flush=True)

    deploy_env = dict(os.environ)
    deploy_env["CLOUDFLARE_ACCOUNT_ID"] = account_id
    subprocess.run(["uv", "run", "pywrangler", "deploy"], env=deploy_env, check=True)

    last = None
    for _ in range(30):
        try:
            last = _health()
            if _target_live():
                break
        except Exception:
            pass
        time.sleep(5)
    else:
        raise SystemExit(
            f"worker health did not expose Gold movement versions: {last!r}"
        )
    print("worker_health_versions_verified=true", flush=True)

    schedules = _cf_json(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/workers/scripts/aidy-signals-test/schedules",
        token=token,
    )
    assert schedules.get("success") is True, schedules
    crons = {s.get("cron") for s in ((schedules.get("result") or {}).get("schedules") or [])}
    assert "* * * * *" in crons, schedules
    print("capture_cron_present=true", flush=True)

    schema = _cf_json(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{D1_ID}/query",
        token=token,
        data={
            "sql": (
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                "('aidy_gold_movement_investigations','aidy_gold_movement_learning_cards') "
                "ORDER BY name;"
            )
        },
    )
    rows = (schema.get("result") or [{}])[0].get("results") or []
    names = {row.get("name") for row in rows}
    assert names == {
        "aidy_gold_movement_investigations",
        "aidy_gold_movement_learning_cards",
    }, schema
    print("gold_movement_d1_schema_verified=true", flush=True)
    print("gold_movement_rollout_complete=true", flush=True)
    _serve_stdlib()


if __name__ == "__main__":
    main()
