"""A future AI cannot label an unqualified release as deployable by JSON alone."""
import copy
import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT/"contracts/oracle_hub_gold_bot_manifest_v1.schema.json").read_text())


def candidate():
    """Test-only synthetic fixture: no real S005 artifact or grant."""
    return {
        "schema": "oracle.gold.bot-package.v1",
        "strategy_id": "S083",
        "name": "Synthetic Test Candidate (NOT RELEASED)",
        "slug": "synthetic-test-candidate",
        "version": "1.0.0",
        "market": "XAUUSD",
        "engine": "python",
        "entrypoint": "strategy/bot.py",
        "timeframe": "H1",
        "source": {
            "uri": "https://example.org/research/test-fixture",
            "commit_sha": "a"*40,
            "license": "TEST_FIXTURE_NOT_FOR_DISTRIBUTION",
            "mechanism_verified": True,
        },
        "research": {
            "aidy_evidence_uri": "https://example.org/research/test-fixture",
            "tested_calendar_years": [2024, 2025],
            "verdict": "HISTORICALLY_QUALIFIED",
            "source_digest_sha256": "b"*64,
        },
        "ui": {"icon_path": None, "detail_slug": "synthetic-test-candidate"},
        "stage": "RESEARCH_ONLY",
        "execution_enabled": False,
        "real_money_enabled": False,
    }


def test_example_research_only_manifest_is_structurally_valid():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    jsonschema.validate(candidate(), SCHEMA)
    assert SCHEMA["properties"]["execution_enabled"]["const"] is False
    assert SCHEMA["properties"]["real_money_enabled"]["const"] is False


@pytest.mark.parametrize("field,value", [
    ("stage", "CENT_TESTING"),
    ("stage", "APPROVED"),
    ("execution_enabled", True),
    ("real_money_enabled", True),
    ("strategy_id", "S5"),
    ("slug", "../attacker"),
    ("entrypoint", "../../live.py"),
    ("market", "BTCUSDT"),
])
def test_invalid_release_and_account_permissions_rejected(field, value):
    payload = candidate()
    payload[field] = value
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, SCHEMA)


def test_untested_research_and_mql5_python_mismatch_rejected():
    payload = candidate()
    payload["research"]["verdict"] = "DISCOVERED"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, SCHEMA)
    payload = candidate()
    payload["engine"] = "mql5"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, SCHEMA)


def test_release_manifest_has_no_account_ids_or_credentials():
    payload = candidate()
    payload["broker_password"] = "none-of-your-business"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, SCHEMA)
    payload = candidate()
    payload["cent_account_id"] = "1234"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, SCHEMA)
