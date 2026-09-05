from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"Expected exactly one match in {path}, found {text.count(old)}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# live_gold_recorder: expose exact-bucket lookup and stop rebuilding already materialized candles.
replace_once(
    "src/aidy/live_gold_recorder.py",
    '    async def latest_candle_ids(self, *, symbol: str, source: str) -> dict[str, UUID]: ...\n',
    '''    async def latest_candle_ids(self, *, symbol: str, source: str) -> dict[str, UUID]: ...\n\n    async def candle_id_for_bucket(\n        self,\n        *,\n        symbol: str,\n        source: str,\n        timeframe: str,\n        open_time_utc: datetime,\n    ) -> UUID | None: ...\n''',
)
replace_once(
    "src/aidy/live_gold_recorder.py",
    '''            for timeframe in _TIMEFRAME_SECONDS:\n                start, end = _closed_bucket(quote_time, timeframe)\n                rows = await self._quote_history.quote_observations(\n''',
    '''            for timeframe in _TIMEFRAME_SECONDS:\n                start, end = _closed_bucket(quote_time, timeframe)\n                existing_id = await self._quote_history.candle_id_for_bucket(\n                    symbol=SYMBOL,\n                    source=CANDLE_SOURCE,\n                    timeframe=timeframe,\n                    open_time_utc=start,\n                )\n                if existing_id is not None:\n                    latest_ids[timeframe] = existing_id\n                    candle_states[timeframe] = {\n                        "timeframe": timeframe,\n                        "bucket_start_utc": start.isoformat(),\n                        "bucket_end_utc": end.isoformat(),\n                        "state": "closed_bucket_already_materialized",\n                        "candle_id": str(existing_id),\n                    }\n                    continue\n                rows = await self._quote_history.quote_observations(\n''',
)

# cloudflare_storage: denormalized market-data source writer and bounded hot-table pruning.
replace_once(
    "src/aidy/cloudflare_storage.py",
    '''def _stamp(value: datetime) -> str:\n    return _utc(value).strftime("%Y%m%dT%H%M%S.%fZ")\n\n\n''',
    '''def _stamp(value: datetime) -> str:\n    return _utc(value).strftime("%Y%m%dT%H%M%S.%fZ")\n\n\ndef _snapshot_market_data_source(snapshot: dict[str, object]) -> str:\n    explicit = snapshot.get("market_data_source")\n    if isinstance(explicit, str) and explicit.strip():\n        return explicit.strip().lower()\n    raw = snapshot.get("data_availability_json")\n    if isinstance(raw, str):\n        try:\n            availability = json.loads(raw)\n        except (TypeError, ValueError):\n            availability = None\n        if isinstance(availability, dict):\n            source = availability.get("market_data_source")\n            if isinstance(source, str) and source.strip():\n                return source.strip().lower()\n    return "unknown"\n\n\n''',
)
replace_once(
    "src/aidy/cloudflare_storage.py",
    '''        archive_key = snapshot_archive_key(snapshot, evidence_id)\n        # The column is retained for historical Day 2 compatibility only.\n''',
    '''        archive_key = snapshot_archive_key(snapshot, evidence_id)\n        market_data_source = _snapshot_market_data_source(snapshot)\n        # The column is retained for historical Day 2 compatibility only.\n''',
)
replace_once(
    "src/aidy/cloudflare_storage.py",
    '''            INSERT INTO market_snapshots (\n                id,captured_at,symbol,capture_status,bid,ask,mid,spread,\n                quote_time,quote_age_seconds,session_code,position_state_json,\n                data_availability_json,event_observation_ids_json,\n                latest_m1_id,latest_m5_id,latest_m15_id,latest_h1_id,\n                latest_h4_id,latest_d1_id,snapshot_digest,archive_key\n            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)\n            """,\n            evidence_id,\n            captured,\n            snapshot["symbol"],\n            snapshot["capture_status"],\n            snapshot.get("bid"),\n''',
    '''            INSERT INTO market_snapshots (\n                id,captured_at,symbol,capture_status,market_data_source,bid,ask,mid,spread,\n                quote_time,quote_age_seconds,session_code,position_state_json,\n                data_availability_json,event_observation_ids_json,\n                latest_m1_id,latest_m5_id,latest_m15_id,latest_h1_id,\n                latest_h4_id,latest_d1_id,snapshot_digest,archive_key\n            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)\n            """,\n            evidence_id,\n            captured,\n            snapshot["symbol"],\n            snapshot["capture_status"],\n            market_data_source,\n            snapshot.get("bid"),\n''',
)
replace_once(
    "src/aidy/cloudflare_storage.py",
    '''    async def mark_archive_failure(self, *, outbox_id: UUID, error_code: str) -> None:\n''',
    '''    async def prune_archived_hot_data(\n        self,\n        *,\n        now: datetime,\n        snapshot_retention_days: int = 7,\n        candle_retention_days: int = 35,\n        snapshot_limit: int = 2000,\n        candle_limit: int = 5000,\n    ) -> None:\n        if snapshot_retention_days < 2:\n            raise ValueError("Snapshot retention must preserve at least two days of hot evidence.")\n        if candle_retention_days < 7:\n            raise ValueError("Candle retention must preserve at least seven days of hot evidence.")\n        if not 1 <= snapshot_limit <= 5000 or not 1 <= candle_limit <= 10000:\n            raise ValueError("Hot-data prune limits are outside the safe bounded range.")\n        prune_stamp = _utc(now).isoformat()\n        snapshot_cutoff = _utc(now) - timedelta(days=snapshot_retention_days)\n        candle_cutoff = _utc(now) - timedelta(days=candle_retention_days)\n        await self._db.batch(\n            [\n                self._stmt(\n                    """\n                    UPDATE archive_outbox\n                    SET hot_pruned_at=?\n                    WHERE id IN (\n                        SELECT id FROM archive_outbox\n                        WHERE record_type='snapshot' AND status='archived'\n                          AND hot_pruned_at IS NULL AND archived_at<?\n                        ORDER BY archived_at,id\n                        LIMIT ?\n                    )\n                    """,\n                    prune_stamp,\n                    snapshot_cutoff,\n                    snapshot_limit,\n                ),\n                self._stmt(\n                    """\n                    DELETE FROM market_snapshots\n                    WHERE id IN (\n                        SELECT evidence_id FROM archive_outbox\n                        WHERE record_type='snapshot' AND hot_pruned_at=?\n                    )\n                    """,\n                    prune_stamp,\n                ),\n                self._stmt(\n                    """\n                    UPDATE archive_outbox\n                    SET hot_pruned_at=?\n                    WHERE id IN (\n                        SELECT id FROM archive_outbox\n                        WHERE record_type='candle' AND status='archived'\n                          AND hot_pruned_at IS NULL AND archived_at<?\n                        ORDER BY archived_at,id\n                        LIMIT ?\n                    )\n                    """,\n                    prune_stamp,\n                    candle_cutoff,\n                    candle_limit,\n                ),\n                self._stmt(\n                    """\n                    DELETE FROM market_candles\n                    WHERE id IN (\n                        SELECT evidence_id FROM archive_outbox\n                        WHERE record_type='candle' AND hot_pruned_at=?\n                    )\n                    """,\n                    prune_stamp,\n                ),\n            ]\n        )\n\n    async def mark_archive_failure(self, *, outbox_id: UUID, error_code: str) -> None:\n''',
)

# Queue: prune once per hour before capture, so a prune failure cannot duplicate a successful capture.
replace_once(
    "src/entry.py",
    '''                settings = AidySettings.from_worker_env(worker_env)\n                _, repository = _repository(worker_env)\n                scheduled_at = _scheduled_at_from_queue_body(message.body)\n                market_gateway, live_gold_history = _market_runtime_dependencies(\n''',
    '''                settings = AidySettings.from_worker_env(worker_env)\n                operational, repository = _repository(worker_env)\n                scheduled_at = _scheduled_at_from_queue_body(message.body)\n                if scheduled_at.minute == 0:\n                    await operational.prune_archived_hot_data(now=scheduled_at)\n                market_gateway, live_gold_history = _market_runtime_dependencies(\n''',
)

# Reference continuity: reject wide windows and cap snapshot rows.
replace_once(
    "src/aidy/reference_continuity.py",
    "from datetime import UTC, datetime\n",
    "from datetime import UTC, datetime, timedelta\n",
)
replace_once(
    "src/aidy/reference_continuity.py",
    '''def _percentile(values: list[float], percentile: float) -> float | None:\n''',
    '''_MAX_CONTINUITY_WINDOW = timedelta(hours=24)\n_MAX_CONTINUITY_SNAPSHOT_ROWS = 1600\n\n\ndef _percentile(values: list[float], percentile: float) -> float | None:\n''',
)
replace_once(
    "src/aidy/reference_continuity.py",
    '''        if window_end <= window_start:\n            raise ValueError("AIDY continuity audit end must be after start.")\n\n        snapshot_rows = await self._rows(\n''',
    '''        if window_end <= window_start:\n            raise ValueError("AIDY continuity audit end must be after start.")\n        if window_end - window_start > _MAX_CONTINUITY_WINDOW:\n            raise ValueError("AIDY continuity audit window is capped at 24 hours.")\n\n        snapshot_rows = await self._rows(\n''',
)
replace_once(
    "src/aidy/reference_continuity.py",
    '''            WHERE captured_at>=? AND captured_at<?\n            ORDER BY captured_at\n            """,\n            window_start,\n            window_end,\n        )\n        archive_count_row = await self._stmt(\n''',
    '''            WHERE captured_at>=? AND captured_at<?\n            ORDER BY captured_at\n            LIMIT ?\n            """,\n            window_start,\n            window_end,\n            _MAX_CONTINUITY_SNAPSHOT_ROWS + 1,\n        )\n        if len(snapshot_rows) > _MAX_CONTINUITY_SNAPSHOT_ROWS:\n            raise RuntimeError("AIDY continuity snapshot row bound exceeded.")\n        archive_count_row = await self._stmt(\n''',
)

# Full continuity reader: hard caps for snapshots/candles plus 24h window.
replace_once(
    "src/aidy/continuity_auditor.py",
    '''TIMEFRAME_SECONDS = {\n''',
    '''_MAX_CONTINUITY_WINDOW = timedelta(hours=24)\n_MAX_CONTINUITY_SNAPSHOT_ROWS = 1600\n_MAX_CONTINUITY_CANDLE_ROWS = 10000\n\nTIMEFRAME_SECONDS = {\n''',
)
replace_once(
    "src/aidy/continuity_auditor.py",
    '''        window_start = _utc(start)\n        window_end = _utc(end)\n        snapshot_rows = await self._rows(\n''',
    '''        window_start = _utc(start)\n        window_end = _utc(end)\n        if window_end <= window_start:\n            raise ValueError("AIDY continuity audit end must be after start.")\n        if window_end - window_start > _MAX_CONTINUITY_WINDOW:\n            raise ValueError("AIDY continuity audit window is capped at 24 hours.")\n        snapshot_rows = await self._rows(\n''',
)
replace_once(
    "src/aidy/continuity_auditor.py",
    '''            WHERE captured_at>=? AND captured_at<?\n            ORDER BY captured_at\n            """,\n            window_start,\n            window_end,\n        )\n        candle_rows = await self._rows(\n''',
    '''            WHERE captured_at>=? AND captured_at<?\n            ORDER BY captured_at\n            LIMIT ?\n            """,\n            window_start,\n            window_end,\n            _MAX_CONTINUITY_SNAPSHOT_ROWS + 1,\n        )\n        if len(snapshot_rows) > _MAX_CONTINUITY_SNAPSHOT_ROWS:\n            raise RuntimeError("AIDY continuity snapshot row bound exceeded.")\n        candle_rows = await self._rows(\n''',
)
replace_once(
    "src/aidy/continuity_auditor.py",
    '''            WHERE open_time_utc>=? AND open_time_utc<?\n            ORDER BY timeframe,open_time_utc,revision_index\n            """,\n            window_start,\n            window_end,\n        )\n        archive_count_row = await self._stmt(\n''',
    '''            WHERE open_time_utc>=? AND open_time_utc<?\n            ORDER BY timeframe,open_time_utc,revision_index\n            LIMIT ?\n            """,\n            window_start,\n            window_end,\n            _MAX_CONTINUITY_CANDLE_ROWS + 1,\n        )\n        if len(candle_rows) > _MAX_CONTINUITY_CANDLE_ROWS:\n            raise RuntimeError("AIDY continuity candle row bound exceeded.")\n        archive_count_row = await self._stmt(\n''',
)

# Local D1 integration tests must include the new migration.
replace_once(
    "tests/test_d1_storage_local.py",
    '''        schema = Path("migrations/d1/0001_aidy_ops.sql").read_text()\n        self.connection.executescript(schema)\n''',
    '''        schema = Path("migrations/d1/0001_aidy_ops.sql").read_text()\n        self.connection.executescript(schema)\n        hot_path = Path("migrations/d1/0012_live_gold_free_tier_read_budget.sql").read_text()\n        self.connection.executescript(hot_path)\n''',
)
replace_once(
    "tests/test_d1_storage_local.py",
    '''    assert row[0] is None\n\n\n@pytest.mark.asyncio\nasync def test_d1_event_revision_is_point_in_time''',
    '''    assert row[0] is None\n    source = operational._db.connection.execute(\n        "SELECT market_data_source FROM market_snapshots WHERE id=?",\n        (str(committed.evidence_id),),\n    ).fetchone()[0]\n    assert source == "unknown"\n\n\n@pytest.mark.asyncio\nasync def test_d1_event_revision_is_point_in_time''',
)

# Genuine live-gold tests: exact source column and already-materialized bucket bypass.
replace_once(
    "tests/test_day53_genuine_live_gold_feed.py",
    '''    async def quote_observations(self, *, symbol: str, source: str, start_utc, end_utc):\n''',
    '''    async def candle_id_for_bucket(\n        self, *, symbol: str, source: str, timeframe: str, open_time_utc\n    ) -> UUID | None:\n        assert symbol == "XAUUSD"\n        assert source == CANDLE_SOURCE\n        return None\n\n    async def quote_observations(self, *, symbol: str, source: str, start_utc, end_utc):\n''',
)
replace_once(
    "tests/test_day53_genuine_live_gold_feed.py",
    '''            CREATE TABLE market_snapshots (\n                id TEXT PRIMARY KEY, captured_at TEXT, symbol TEXT, capture_status TEXT,\n                bid TEXT, ask TEXT, mid TEXT, spread TEXT, quote_time TEXT,\n                quote_age_seconds REAL, data_availability_json TEXT, snapshot_digest TEXT\n            );\n''',
    '''            CREATE TABLE market_snapshots (\n                id TEXT PRIMARY KEY, captured_at TEXT, symbol TEXT, capture_status TEXT,\n                market_data_source TEXT, bid TEXT, ask TEXT, mid TEXT, spread TEXT, quote_time TEXT,\n                quote_age_seconds REAL, data_availability_json TEXT, snapshot_digest TEXT\n            );\n            CREATE INDEX ix_market_snapshots_quote_history\n                ON market_snapshots(symbol,market_data_source,capture_status,quote_time,captured_at,id);\n            CREATE INDEX ix_market_candles_source_symbol_timeframe_latest\n                ON market_candles(source,symbol,timeframe,open_time_utc DESC,revision_index DESC,id);\n''',
)
replace_once(
    "tests/test_day53_genuine_live_gold_feed.py",
    '''            "INSERT INTO market_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",\n            (\n                f"snap-{suffix}",\n                "2026-09-02T11:59:10+00:00",\n                "XAUUSD",\n                "complete",\n                "3499",\n''',
    '''            "INSERT INTO market_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",\n            (\n                f"snap-{suffix}",\n                "2026-09-02T11:59:10+00:00",\n                "XAUUSD",\n                "complete",\n                source,\n                "3499",\n''',
)

# Add focused plan/backfill/read-budget tests.
(ROOT / "tests/test_day53_d1_free_tier_hot_paths.py").write_text(
    r'''from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

OLD_QUOTE = """
SELECT id,captured_at,bid,ask,mid,spread,quote_time,quote_age_seconds,
       data_availability_json,snapshot_digest
FROM market_snapshots
WHERE symbol=? AND capture_status='complete'
  AND quote_time>=? AND quote_time<?
  AND bid IS NOT NULL AND ask IS NOT NULL AND mid IS NOT NULL AND spread IS NOT NULL
  AND json_extract(data_availability_json,'$.market_data_source')=?
ORDER BY quote_time ASC,captured_at ASC,id ASC
"""

NEW_QUOTE = """
SELECT id,captured_at,bid,ask,mid,spread,quote_time,quote_age_seconds,
       data_availability_json,snapshot_digest
FROM market_snapshots
WHERE symbol=? AND market_data_source=? AND capture_status='complete'
  AND quote_time>=? AND quote_time<?
  AND bid IS NOT NULL AND ask IS NOT NULL AND mid IS NOT NULL AND spread IS NOT NULL
ORDER BY quote_time ASC,captured_at ASC,id ASC
LIMIT ?
"""

OLD_LATEST = """
SELECT c.timeframe,c.id
FROM market_candles c
WHERE c.source=? AND c.symbol=?
  AND NOT EXISTS (
    SELECT 1 FROM market_candles newer
    WHERE newer.source=c.source AND newer.symbol=c.symbol
      AND newer.timeframe=c.timeframe
      AND (
        newer.open_time_utc>c.open_time_utc OR
        (newer.open_time_utc=c.open_time_utc AND newer.revision_index>c.revision_index)
      )
  )
ORDER BY c.timeframe
"""

NEW_LATEST = """
SELECT id
FROM market_candles
WHERE source=? AND symbol=? AND timeframe=?
ORDER BY open_time_utc DESC,revision_index DESC
LIMIT 1
"""


def _plan(db: sqlite3.Connection, sql: str, params: tuple[object, ...]) -> str:
    rows = db.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    return " | ".join(str(row[3]) for row in rows)


def test_migration_backfills_source_and_changes_both_hot_query_plans() -> None:
    db = sqlite3.connect(":memory:")
    db.executescript((ROOT / "migrations/d1/0001_aidy_ops.sql").read_text(encoding="utf-8"))
    availability = json.dumps({"market_data_source": "argentapi"})
    db.execute(
        """INSERT INTO market_snapshots(
        id,captured_at,symbol,capture_status,bid,ask,mid,spread,quote_time,quote_age_seconds,
        session_code,position_state_json,data_availability_json,event_observation_ids_json,
        latest_m1_id,latest_m5_id,latest_m15_id,latest_h1_id,latest_h4_id,latest_d1_id,
        snapshot_digest,archive_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "snap-1","2026-09-02T12:00:10+00:00","XAUUSD","complete","3499","3501","3500","2",
            "2026-09-02T12:00:00+00:00",10.0,"new_york",None,availability,"[]",None,None,None,None,None,None,
            "a" * 64,"gold/snapshots/test.json",
        ),
    )
    db.execute(
        """INSERT INTO market_candles(
        id,symbol,timeframe,open_time_utc,broker_open_time,open,high,low,close,tick_volume,spread,volume,
        source,revision_index,payload_digest,first_observed_at,archive_key)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "candle-1","XAUUSD","1m","2026-09-02T12:00:00+00:00",None,"1","1","1","1",1,"0",None,
            "argentapi_quote_rollup_v1",1,"b" * 64,"2026-09-02T12:01:00+00:00","gold/candles/test.json",
        ),
    )
    db.commit()

    old_quote_plan = _plan(
        db,
        OLD_QUOTE,
        ("XAUUSD","2026-09-02T11:00:00+00:00","2026-09-02T13:00:00+00:00","argentapi"),
    )
    old_latest_plan = _plan(db, OLD_LATEST, ("argentapi_quote_rollup_v1","XAUUSD"))
    assert "CORRELATED SCALAR SUBQUERY" in old_latest_plan
    assert "ix_market_snapshots_quote_history" not in old_quote_plan

    db.executescript(
        (ROOT / "migrations/d1/0012_live_gold_free_tier_read_budget.sql").read_text(encoding="utf-8")
    )
    assert db.execute("SELECT market_data_source FROM market_snapshots WHERE id='snap-1'").fetchone()[0] == "argentapi"

    new_quote_plan = _plan(
        db,
        NEW_QUOTE,
        ("XAUUSD","argentapi","2026-09-02T11:00:00+00:00","2026-09-02T13:00:00+00:00",3001),
    )
    new_latest_plan = _plan(
        db,
        NEW_LATEST,
        ("argentapi_quote_rollup_v1","XAUUSD","1m"),
    )
    assert "ix_market_snapshots_quote_history" in new_quote_plan
    assert "ix_market_candles_source_symbol_timeframe_latest" in new_latest_plan
    assert "CORRELATED SCALAR SUBQUERY" not in new_latest_plan


def test_live_gold_storage_has_no_json_source_predicate_or_not_exists_latest_scan() -> None:
    text = (ROOT / "src/aidy/live_gold_storage.py").read_text(encoding="utf-8")
    assert "json_extract(data_availability_json,'$.market_data_source')" not in text
    assert "NOT EXISTS" not in text
    assert "market_data_source=?" in text
    assert "LIMIT ?" in text


def test_recorder_skips_quote_history_for_already_materialized_closed_bucket() -> None:
    text = (ROOT / "src/aidy/live_gold_recorder.py").read_text(encoding="utf-8")
    marker = "existing_id = await self._quote_history.candle_id_for_bucket"
    assert marker in text
    assert text.index(marker) < text.index("rows = await self._quote_history.quote_observations", text.index(marker))
    assert "closed_bucket_already_materialized" in text


def test_continuity_store_reads_are_hard_bounded() -> None:
    reference = (ROOT / "src/aidy/reference_continuity.py").read_text(encoding="utf-8")
    full = (ROOT / "src/aidy/continuity_auditor.py").read_text(encoding="utf-8")
    for text in (reference, full):
        assert "capped at 24 hours" in text
        assert "LIMIT ?" in text
        assert "row bound exceeded" in text


def test_archive_hot_prune_is_bounded_and_archive_gated() -> None:
    text = (ROOT / "src/aidy/cloudflare_storage.py").read_text(encoding="utf-8")
    assert "prune_archived_hot_data" in text
    assert "status='archived'" in text
    assert "hot_pruned_at IS NULL" in text
    assert "LIMIT ?" in text
    assert "DELETE FROM market_snapshots" in text
    assert "DELETE FROM market_candles" in text
''',
    encoding="utf-8",
)
