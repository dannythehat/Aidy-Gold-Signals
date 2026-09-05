from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one match in {path}, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "src/aidy/private_forward_context.py",
    'PRIVATE_FORWARD_SIGNAL_STATE_VERSION = "aidy_private_forward_signal_state_v1"\n',
    'PRIVATE_FORWARD_SIGNAL_STATE_VERSION = "aidy_private_forward_signal_state_v1"\n'
    '_MAX_PRIVATE_FORWARD_M1_ROWS = 3500\n',
)
replace_once(
    "src/aidy/private_forward_context.py",
    '''    m1_result = await d1.prepare(\n        """\n        SELECT * FROM twelve_data_decision_admitted_m1_v1\n        WHERE open_time_utc>=? AND first_observed_at<=?\n        ORDER BY open_time_utc,revision_index\n        """\n    ).bind(m1_start, cutoff).all()\n''',
    '''    m1_rows = _results(\n        await d1.prepare(\n            """\n            SELECT * FROM twelve_data_decision_admitted_m1_v1\n            WHERE open_time_utc>=? AND open_time_utc<? AND first_observed_at<=?\n            ORDER BY open_time_utc,revision_index\n            LIMIT ?\n            """\n        ).bind(m1_start, cutoff, cutoff, _MAX_PRIVATE_FORWARD_M1_ROWS + 1).all()\n    )\n    if len(m1_rows) > _MAX_PRIVATE_FORWARD_M1_ROWS:\n        raise RuntimeError("Private-forward M1 row bound exceeded.")\n''',
)
replace_once(
    "src/aidy/private_forward_context.py",
    '    return _dedupe_candles(_results(m1_result) + aggregate_rows)\n',
    '    return _dedupe_candles(m1_rows + aggregate_rows)\n',
)

replace_once(
    "src/aidy/twelve_data_storage.py",
    '''                SELECT\n                  COALESCE(SUM(CASE WHEN requested_at_utc>=? THEN internal_accounted_credits ELSE 0 END),0) AS utc_day,\n                  COALESCE(SUM(CASE WHEN requested_at_utc>=? THEN internal_accounted_credits ELSE 0 END),0) AS rolling_24h\n                FROM twelve_data_request_ledger\n                WHERE requested_at_utc<=?\n                """\n            ).bind(\n                utc_day_start.isoformat(),\n                rolling_start.isoformat(),\n                observed.isoformat(),\n            ).first()\n''',
    '''                SELECT\n                  (\n                    SELECT COALESCE(SUM(internal_accounted_credits),0)\n                    FROM twelve_data_request_ledger\n                    WHERE requested_at_utc>=? AND requested_at_utc<=?\n                  ) AS utc_day,\n                  (\n                    SELECT COALESCE(SUM(internal_accounted_credits),0)\n                    FROM twelve_data_request_ledger\n                    WHERE requested_at_utc>=? AND requested_at_utc<=?\n                  ) AS rolling_24h\n                """\n            ).bind(\n                utc_day_start.isoformat(),\n                observed.isoformat(),\n                rolling_start.isoformat(),\n                observed.isoformat(),\n            ).first()\n''',
)
replace_once(
    "src/aidy/twelve_data_storage.py",
    '''    async def latest_candle_ids(self) -> dict[str, UUID]:\n        result = await self._d1.prepare(\n            f"""\n            WITH admitted_m1 AS (\n              SELECT * FROM {DECISION_ADMITTED_M1_VIEW}\n            ), latest_m1 AS (\n              SELECT timeframe,id FROM admitted_m1\n              ORDER BY open_time_utc DESC,revision_index DESC LIMIT 1\n            ), latest_aggregates AS (\n              SELECT c.timeframe,c.id FROM market_candles c\n              WHERE c.symbol=? AND c.timeframe IN ('5m','15m','1h','4h','1d') AND c.source=?\n                AND NOT EXISTS (\n                  SELECT 1 FROM market_candles newer\n                  WHERE newer.source=c.source AND newer.symbol=c.symbol\n                    AND newer.timeframe=c.timeframe AND (newer.open_time_utc>c.open_time_utc OR\n                    (newer.open_time_utc=c.open_time_utc AND newer.revision_index>c.revision_index))\n                )\n            )\n            SELECT timeframe,id FROM latest_m1\n            UNION ALL\n            SELECT timeframe,id FROM latest_aggregates\n            ORDER BY timeframe\n            """\n        ).bind(AIDY_SYMBOL, AGGREGATE_SOURCE).all()\n        return {str(row["timeframe"]): UUID(str(row["id"])) for row in _results(result)}\n''',
    '''    async def latest_candle_ids(self) -> dict[str, UUID]:\n        latest: dict[str, UUID] = {}\n        m1 = _row(\n            await self._d1.prepare(\n                f"""\n                SELECT timeframe,id FROM {DECISION_ADMITTED_M1_VIEW}\n                ORDER BY open_time_utc DESC,revision_index DESC LIMIT 1\n                """\n            ).first()\n        )\n        if m1 is not None:\n            latest[str(m1["timeframe"])] = UUID(str(m1["id"]))\n        for timeframe in ("5m", "15m", "1h", "4h", "1d"):\n            row = _row(\n                await self._d1.prepare(\n                    """\n                    SELECT timeframe,id FROM market_candles\n                    WHERE source=? AND symbol=? AND timeframe=?\n                    ORDER BY open_time_utc DESC,revision_index DESC LIMIT 1\n                    """\n                ).bind(AGGREGATE_SOURCE, AIDY_SYMBOL, timeframe).first()\n            )\n            if row is not None:\n                latest[timeframe] = UUID(str(row["id"]))\n        return latest\n''',
)

(ROOT / "tests/test_day53_twelve_free_tier_read_budget.py").write_text(
    r'''from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _plan(db: sqlite3.Connection, sql: str, params: tuple[object, ...]) -> str:
    return " | ".join(str(row[3]) for row in db.execute("EXPLAIN QUERY PLAN " + sql, params))


def test_twelve_hot_path_migration_supports_ledger_window_and_quota_ranges() -> None:
    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        CREATE TABLE twelve_data_request_ledger (
          id TEXT PRIMARY KEY, requested_at_utc TEXT NOT NULL, completed_at_utc TEXT,
          request_kind TEXT NOT NULL, status TEXT NOT NULL, outputsize INTEGER,
          internal_accounted_credits INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE twelve_data_bootstrap_requests (
          bootstrap_id TEXT NOT NULL, window_index INTEGER NOT NULL,
          request_ledger_id TEXT NOT NULL, window_start_utc TEXT NOT NULL,
          window_end_utc TEXT NOT NULL, state TEXT NOT NULL,
          PRIMARY KEY (bootstrap_id,window_index)
        );
        CREATE TABLE market_candles (
          id TEXT PRIMARY KEY, source TEXT NOT NULL, symbol TEXT NOT NULL, timeframe TEXT NOT NULL,
          open_time_utc TEXT NOT NULL, first_observed_at TEXT NOT NULL, revision_index INTEGER NOT NULL
        );
        CREATE TABLE market_snapshots(id TEXT PRIMARY KEY);
        CREATE TABLE archive_outbox(id TEXT PRIMARY KEY);
        """
    )
    migration = (ROOT / "migrations/d1/0013_twelve_private_forward_read_budget.sql").read_text(
        encoding="utf-8"
    )
    # 0013 contains only indexes over the three hot-path tables used by this focused schema.
    for statement in migration.split(";"):
        if "archive_outbox" in statement or "market_snapshots" in statement:
            continue
        if statement.strip():
            db.execute(statement)

    bootstrap_plan = _plan(
        db,
        "SELECT 1 FROM twelve_data_bootstrap_requests WHERE request_ledger_id=? AND state='succeeded' AND ?>=window_start_utc AND ?<window_end_utc LIMIT 1",
        ("r1", "2026-09-05T00:00:00+00:00", "2026-09-05T00:00:00+00:00"),
    )
    quota_plan = _plan(
        db,
        "SELECT COALESCE(SUM(internal_accounted_credits),0) FROM twelve_data_request_ledger WHERE requested_at_utc>=? AND requested_at_utc<=?",
        ("2026-09-05T00:00:00+00:00", "2026-09-05T23:59:59+00:00"),
    )
    m1_plan = _plan(
        db,
        "SELECT id FROM market_candles WHERE source=? AND symbol=? AND timeframe=? AND open_time_utc>=? AND open_time_utc<? AND first_observed_at<=? ORDER BY open_time_utc,revision_index LIMIT 3501",
        (
            "twelve_data_vendor_m1_v1", "XAUUSD", "1m",
            "2026-09-03T00:00:00+00:00", "2026-09-05T00:00:00+00:00",
            "2026-09-05T00:00:00+00:00",
        ),
    )
    assert "idx_twelve_data_bootstrap_requests_by_ledger_window" in bootstrap_plan
    assert "idx_twelve_data_request_ledger_requested_at_credits" in quota_plan
    assert "idx_market_candles_twelve_private_forward_m1" in m1_plan


def test_private_forward_m1_query_is_two_sided_and_hard_bounded() -> None:
    text = (ROOT / "src/aidy/private_forward_context.py").read_text(encoding="utf-8")
    assert "open_time_utc>=? AND open_time_utc<? AND first_observed_at<=?" in text
    assert "_MAX_PRIVATE_FORWARD_M1_ROWS = 3500" in text
    assert "Private-forward M1 row bound exceeded." in text
    assert "LIMIT ?" in text


def test_twelve_quota_scan_is_index_range_bounded() -> None:
    text = (ROOT / "src/aidy/twelve_data_storage.py").read_text(encoding="utf-8")
    assert text.count("WHERE requested_at_utc>=? AND requested_at_utc<=?") >= 2
    assert "SUM(CASE WHEN requested_at_utc>=?" not in text


def test_twelve_latest_aggregate_lookup_has_no_correlated_antijoin() -> None:
    text = (ROOT / "src/aidy/twelve_data_storage.py").read_text(encoding="utf-8")
    section = text[text.index("async def latest_candle_ids"):text.index("async def latest_m1_bar")]
    assert "NOT EXISTS" not in section
    assert "ORDER BY open_time_utc DESC,revision_index DESC LIMIT 1" in section
''',
    encoding="utf-8",
)
