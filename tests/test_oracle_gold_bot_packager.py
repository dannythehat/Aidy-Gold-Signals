"""Packaging fixture is synthetic. This does not certify or deploy a bot."""
import copy
import json
from pathlib import Path
import zipfile

import pytest

from scripts.oracle_hub.build_gold_bot_package import build
from test_oracle_gold_bot_package_contract import candidate


def source_fixture(tmp_path: Path) -> Path:
    src = tmp_path / "source"
    for directory in ("strategy", "config", "contracts", "tests", "evidence"):
        (src / directory).mkdir(parents=True)
    (src / "manifest.json").write_text(json.dumps(candidate()), encoding="utf-8")
    (src / "README.md").write_text(
        "TEST FIXTURE ONLY; no real code, no broker connection.\n", encoding="utf-8")
    (src / "strategy/bot.py").write_text(
        "def on_bar(closed_candles):\n    return None\n", encoding="utf-8")
    (src / "config/defaults.json").write_text("{}\n", encoding="utf-8")
    (src / "contracts/signal-v1.json").write_text("{}\n", encoding="utf-8")
    (src / "requirements.lock").write_text("# No dependencies\n", encoding="utf-8")
    (src / "tests/test_signal.py").write_text(
        "def test_idle():\n    assert True\n", encoding="utf-8")
    (src / "evidence/readme.md").write_text(
        "Synthetic fixture, NOT independently verified AIDY evidence.\n",
        encoding="utf-8")
    return src


def test_reproducible_zip_and_digest_no_execution(tmp_path):
    src = source_fixture(tmp_path)
    p, sha = build(src, tmp_path / "out1")
    q, sha2 = build(src, tmp_path / "out2")
    assert p.name == "GoldBot-S083-synthetic-test-candidate-1.0.0.zip"
    assert p.read_bytes() == q.read_bytes() and sha == sha2
    with zipfile.ZipFile(p) as archive:
        names = set(archive.namelist())
        assert "SHA256SUMS.json" in names
        assert "strategy/bot.py" in names
        assert "manifest.json" in names
        hashes = json.loads(archive.read("SHA256SUMS.json"))
        assert "manifest.json" in hashes
        assert "SHA256SUMS.json" not in hashes
    assert (tmp_path / "out1" / (p.name + ".sha256")).is_file()
    with pytest.raises(FileExistsError):
        build(src, tmp_path / "out1")


def test_reject_unreviewed_file_and_secret(tmp_path):
    src = source_fixture(tmp_path)
    (src / ".env").write_text("API_KEY=not-real-sample-data\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unreviewed file"):
        build(src, tmp_path / "bad1")
    (src / ".env").unlink()
    (src / "strategy/bot.py").write_text(
        'SECRET_TOKEN=supersecretfixture123\n', encoding="utf-8")
    with pytest.raises(ValueError, match="Potential plaintext secret"):
        build(src, tmp_path / "bad2")


def test_reject_stage_approval_inside_immutable_manifest(tmp_path):
    src = source_fixture(tmp_path)
    item = candidate()
    item["stage"] = "CENT_TESTING"
    (src / "manifest.json").write_text(json.dumps(item), encoding="utf-8")
    with pytest.raises(Exception):
        build(src, tmp_path / "bad")


def test_reject_missing_tests_or_research_summary(tmp_path):
    src = source_fixture(tmp_path)
    (src / "tests/test_signal.py").unlink()
    with pytest.raises(ValueError, match="no tests"):
        build(src, tmp_path / "bad")
    (src / "tests/test_signal.py").write_text("pass\n", encoding="utf-8")
    (src / "evidence/readme.md").unlink()
    with pytest.raises(ValueError, match="no research evidence"):
        build(src, tmp_path / "bad2")
