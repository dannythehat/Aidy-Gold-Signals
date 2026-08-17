from __future__ import annotations

from pathlib import Path


PRODUCTION_FILES = (
    "src/entry.py",
    "src/aidy/config.py",
    "src/aidy/runtime.py",
    "src/aidy/market_recorder.py",
    "src/aidy/fed_recorder.py",
    "src/aidy/storage_contracts.py",
    "src/aidy/cloudflare_storage.py",
)
FORBIDDEN = ("sqlalchemy", "psycopg", "alembic", ".market_repository", ".db import")


def test_production_runtime_has_no_postgres_dependency() -> None:
    root = Path(__file__).parents[1]
    for relative in PRODUCTION_FILES:
        text = (root / relative).read_text(encoding="utf-8").lower()
        for forbidden in FORBIDDEN:
            assert forbidden not in text, f"{relative} contains runtime Postgres dependency {forbidden!r}"
