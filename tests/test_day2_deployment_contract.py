from __future__ import annotations

import json
from pathlib import Path


def _test_config() -> dict[str, object]:
    return json.loads(Path("wrangler.test.example.jsonc").read_text(encoding="utf-8"))


def _scheduler_config() -> dict[str, object]:
    return json.loads(Path("wrangler.scheduler.test.jsonc").read_text(encoding="utf-8"))


def test_boundary_correction_keeps_capture_worker_safe_off() -> None:
    config = _test_config()
    vars_ = config["vars"]
    assert isinstance(vars_, dict)
    assert vars_["AIDY_ENV"] == "test"
    assert vars_["AIDY_CAPTURE_ENABLED"] == "false"
    assert vars_["AIDY_MARKET_DATA_SOURCE"] == "gold_api"
    assert vars_["AIDY_MARKET_DATA_OWNERSHIP"] == "public_independent"
    assert config["triggers"] == {"crons": []}
    consumers = config["queues"]["consumers"]
    assert consumers == [
        {
            "queue": "aidy-capture-test",
            "max_batch_size": 1,
            "max_batch_timeout": 1,
            "max_retries": 3,
            "max_concurrency": 1,
            "retry_delay": 30,
        }
    ]


def test_day2_python_queue_handler_uses_cloudflare_runtime_signature() -> None:
    source = Path("src/entry.py").read_text(encoding="utf-8")
    assert "async def queue(self, batch, env, ctx):" in source


def test_day2_scheduler_is_minimal_one_minute_queue_producer() -> None:
    config = _scheduler_config()
    assert config["name"] == "aidy-signals-scheduler-test"
    assert config["main"] == "src/day2_scheduler.js"
    assert config["triggers"] == {"crons": []}
    assert config["queues"] == {
        "producers": [
            {
                "binding": "AIDY_CAPTURE_QUEUE",
                "queue": "aidy-capture-test",
            }
        ]
    }
    source = Path("src/day2_scheduler.js").read_text(encoding="utf-8")
    assert "AIDY_CAPTURE_QUEUE.send" in source
    assert "fetch(" not in source
    assert "AIDY_METAAPI" not in source


def test_broker_free_capture_requires_no_market_secrets() -> None:
    config = _test_config()
    vars_ = config["vars"]
    secrets = config["secrets"]
    assert isinstance(vars_, dict)
    assert isinstance(secrets, dict)
    assert secrets["required"] == []
    assert "AIDY_METAAPI_TOKEN" not in vars_
    assert "AIDY_METAAPI_ACCOUNT_ID" not in vars_


def test_active_runtime_contains_no_metaapi_or_broker_position_path() -> None:
    runtime = Path("src/aidy/runtime.py").read_text(encoding="utf-8")
    entry = Path("src/entry.py").read_text(encoding="utf-8")
    gateway = Path("src/aidy/gold_api_gateway.py").read_text(encoding="utf-8")
    recorder = Path("src/aidy/reference_price_recorder.py").read_text(encoding="utf-8")
    active = "\n".join((runtime, entry, gateway, recorder))
    assert "MetaApi" not in active
    assert "metaapi" not in active.lower()
    assert "read_positions" not in active
    assert "openPosition" not in active
    assert "position_state_json\": None" in recorder


def test_day3_audit_endpoint_is_test_only_and_read_only() -> None:
    entry = Path("src/entry.py").read_text(encoding="utf-8")
    auditor = Path("src/aidy/reference_continuity.py").read_text(encoding="utf-8")
    assert 'request.method == "GET" and url.path == "/day3/continuity"' in entry
    assert 'str(self.env.AIDY_ENV).lower() != "test"' in entry
    assert "read_positions" not in auditor
    assert "MetaApi" not in auditor
    assert "super_signals" not in auditor.lower()


def test_day2_keeps_test_d1_and_r2_bindings() -> None:
    config = _test_config()
    assert config["d1_databases"] == [{"binding": "AIDY_OPS", "migrations_dir": "migrations/d1"}]
    assert config["r2_buckets"] == [{"binding": "AIDY_MEMORY"}]


def test_local_example_stays_capture_off_and_keyless() -> None:
    values: dict[str, str] = {}
    for raw_line in Path(".env.example").read_text(encoding="utf-8").splitlines():
        if not raw_line or raw_line.lstrip().startswith("#") or "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        values[key.strip()] = value.strip()
    assert values["AIDY_CAPTURE_ENABLED"] == "false"
    assert values["AIDY_MARKET_DATA_SOURCE"] == "gold_api"
    assert values["AIDY_MARKET_DATA_OWNERSHIP"] == "public_independent"
    assert "AIDY_METAAPI_TOKEN" not in values
    assert "AIDY_METAAPI_ACCOUNT_ID" not in values
