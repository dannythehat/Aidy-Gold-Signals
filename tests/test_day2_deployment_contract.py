from __future__ import annotations

import json
from pathlib import Path


REQUIRED_METAAPI_SECRETS = {
    "AIDY_METAAPI_TOKEN",
    "AIDY_METAAPI_ACCOUNT_ID",
}


def _test_config() -> dict[str, object]:
    return json.loads(Path("wrangler.test.example.jsonc").read_text(encoding="utf-8"))


def test_day2_test_worker_capture_is_enabled_and_scheduled_each_minute() -> None:
    config = _test_config()
    vars_ = config["vars"]
    assert isinstance(vars_, dict)
    assert vars_["AIDY_ENV"] == "test"
    assert vars_["AIDY_CAPTURE_ENABLED"] == "true"
    assert config["triggers"] == {"crons": ["* * * * *"]}


def test_day2_metaapi_values_are_required_secrets_not_plaintext_vars() -> None:
    config = _test_config()
    vars_ = config["vars"]
    secrets = config["secrets"]
    assert isinstance(vars_, dict)
    assert isinstance(secrets, dict)
    assert set(secrets["required"]) == REQUIRED_METAAPI_SECRETS
    assert REQUIRED_METAAPI_SECRETS.isdisjoint(vars_)


def test_day2_keeps_test_d1_and_r2_bindings() -> None:
    config = _test_config()
    assert config["d1_databases"] == [
        {"binding": "AIDY_OPS", "migrations_dir": "migrations/d1"}
    ]
    assert config["r2_buckets"] == [{"binding": "AIDY_MEMORY"}]


def test_local_example_stays_capture_off() -> None:
    values: dict[str, str] = {}
    for raw_line in Path(".env.example").read_text(encoding="utf-8").splitlines():
        if not raw_line or raw_line.lstrip().startswith("#") or "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        values[key.strip()] = value.strip()
    assert values["AIDY_CAPTURE_ENABLED"] == "false"
