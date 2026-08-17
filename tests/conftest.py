from __future__ import annotations

from importlib.util import find_spec

# PostgreSQL/Alembic files are retained as reference tests only. They should not
# make the Cloudflare runtime test suite fail collection when the optional
# postgres-reference dependencies are deliberately absent.
collect_ignore: list[str] = []

if find_spec("alembic") is None or find_spec("sqlalchemy") is None:
    collect_ignore.extend(
        [
            "test_migration_offline.py",
            "test_position_truth.py",
            "test_postgres_integration.py",
        ]
    )
