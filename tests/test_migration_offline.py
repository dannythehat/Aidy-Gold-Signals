from __future__ import annotations

import importlib.util
import io
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations


_MIGRATION = Path("migrations/versions/0001_aidy_market_evidence.py")


def _load_migration():
    spec = importlib.util.spec_from_file_location("aidy_migration_0001", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _render_sql(function_name: str) -> str:
    module = _load_migration()
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    with Operations.context(context):
        getattr(module, function_name)()
    return output.getvalue()


def test_upgrade_compiles_for_postgresql() -> None:
    sql = _render_sql("upgrade")
    assert "CREATE TABLE market_candles" in sql
    assert "CREATE TABLE market_snapshots" in sql
    assert "CREATE TABLE market_event_observations" in sql
    assert "position_state_json JSONB" in sql


def test_downgrade_compiles_for_postgresql() -> None:
    sql = _render_sql("downgrade")
    assert "DROP TABLE market_event_observations" in sql
    assert "DROP TABLE market_snapshots" in sql
    assert "DROP TABLE market_candles" in sql
