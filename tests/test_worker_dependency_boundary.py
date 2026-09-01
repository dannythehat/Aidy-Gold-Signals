from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _project() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _names(values: list[str]) -> set[str]:
    return {value.split("[", 1)[0].split(">", 1)[0].split("=", 1)[0].strip() for value in values}


def test_pdf_research_stack_is_not_a_cloudflare_worker_runtime_dependency() -> None:
    project = _project()
    runtime = _names(project["project"]["dependencies"])
    assert "pdfplumber" not in runtime
    assert "pypdfium2" not in runtime
    assert "pillow" not in runtime


def test_offline_pdf_research_remains_available_for_tests_and_explicit_research_installs() -> None:
    project = _project()
    dev = _names(project["dependency-groups"]["dev"])
    optional = _names(project["project"]["optional-dependencies"]["offline-pdf-research"])
    assert "pdfplumber" in dev
    assert "pdfplumber" in optional


def test_worker_runtime_keeps_only_packages_needed_by_live_import_graph() -> None:
    project = _project()
    runtime = _names(project["project"]["dependencies"])
    assert "httpx" in runtime
    assert "xlrd" in runtime
