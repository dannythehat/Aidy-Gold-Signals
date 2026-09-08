from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_provider_entry_declares_concrete_queue_handler() -> None:
    """The configured Worker entrypoint must expose queue directly.

    This is intentionally a source-level contract test. Importing Cloudflare's
    Python Worker runtime under normal CPython requires the Pyodide ``js`` module,
    so an import-based unit test would test the wrong runtime rather than the
    production entrypoint shape.
    """

    source = (ROOT / "src" / "provider_entry.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    default = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Default"
    )
    async_methods = {
        node.name for node in default.body if isinstance(node, ast.AsyncFunctionDef)
    }
    assert "fetch" in async_methods
    assert "queue" in async_methods
