"""Source recovery, confidential history caches and protected prior evidence."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from scripts.oracle_gold.minute_history import load, write
from scripts.oracle_gold.recover_sources import recover, tv_metadata

ROOT = Path(__file__).resolve().parents[1]


def test_every_prior_audit_and_historical_result_remains_byte_identical():
    manifest = json.loads((ROOT/"research/gold_oracle/phase03/prior_evidence_protected.json").read_text())
    assert manifest["base_remote_commit"] == "0ddbf8b2bd94ed127468a564fb6bdef04b4112c6"
    assert len(manifest["protected_file_sha256"]) == 225
    for path, expected in manifest["protected_file_sha256"].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == expected


def test_minute_snapshot_rejects_nonfinite_duplicate_and_tampered_input(tmp_path):
    row = {"open_time_utc": "2099-01-01T00:00:00+00:00", "open": 10., "high": 12., "low": 9., "close": 11.}
    with pytest.raises(ValueError, match="OHLC"):
        write(tmp_path/"bad", [{**row, "high": float("inf")}], [], "SYNTHETIC_TEST_ONLY", 2099)
    with pytest.raises(ValueError, match="duplicate"):
        write(tmp_path/"dup", [row, row], [], "SYNTHETIC_TEST_ONLY", 2099)
    write(tmp_path/"ok", [row], [], "SYNTHETIC_TEST_ONLY", 2099)
    assert load(tmp_path/"ok")[0] == [row]
    with pytest.raises(ValueError, match="exists"):
        write(tmp_path/"ok", [row], [], "SYNTHETIC_TEST_ONLY", 2099)
    p = tmp_path/"ok/minute.csv"
    p.write_text(p.read_text().replace("12.0", "13.0"))
    with pytest.raises(ValueError, match="changed"):
        load(tmp_path/"ok")


def test_public_pine_recovery_uses_public_id_and_never_protected_source(tmp_path, monkeypatch):
    page = '<script type="application/prs.init-data+json">'+json.dumps({"a": {"ssrIdeaData": {
        "script": {"id": 12, "script_id_part": "PUB;publication", "version_maj": 1, "access": 2},
        "user": {"username": "fixture"}}}})+'</script>'
    assert tv_metadata(page)["script"]["script_id_part"].startswith("PUB;")
    calls = []
    def fake_get(url):
        calls.append(url)
        return page.encode(), {"url": url, "http_status": 200}
    monkeypatch.setattr("scripts.oracle_gold.recover_sources.get", fake_get)
    r = recover({"id": "TEST", "source_url": "https://www.tradingview.com/script/fixture/"}, tmp_path, None)
    assert r["status"].startswith("BLOCKED_PROTECTED")
    assert len(calls) == 1 and not r["source_files"]


def test_history_envelope_requires_authorised_recipient_and_preserves_exact_bytes(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public, private = tmp_path/"public.pem", tmp_path/"private.pem"
    public.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    source = tmp_path/"synthetic"
    source.mkdir()
    original = b"SYNTHETIC_TEST_ONLY\r\n123.45,not-real-market-history\r\n"
    (source/"fixture.csv").write_bytes(original)
    fake = "TEST_ONLY_NOT_AN_AUTHENTICATION_CREDENTIAL"
    env = {**os.environ, "AIDY_GCP_SERVICE_ACCOUNT_JSON": json.dumps({"private_key": fake})}
    command = [sys.executable, "-m", "scripts.oracle_gold.snapshot_bundle"]
    sealed = tmp_path/"sealed.json"
    subprocess.run(command+["seal", "--source", str(source), "--out", str(sealed), "--key", str(public)], env=env, check=True)
    assert fake not in sealed.read_text() and "123.45" not in sealed.read_text()
    for mode in ("open-ci", "open-local"):
        out = tmp_path/mode
        subprocess.run(command+[mode, "--source", str(sealed), "--out", str(out), "--key", str(private)], env=env, check=True)
        assert (out/"fixture.csv").read_bytes() == original
    wrong = {**env, "AIDY_GCP_SERVICE_ACCOUNT_JSON": json.dumps({"private_key": "WRONG_TEST_KEY"})}
    result = subprocess.run(command+["open-ci", "--source", str(sealed), "--out", str(tmp_path/"wrong")], env=wrong, capture_output=True, check=False)
    assert result.returncode != 0 and fake.encode() not in result.stderr
