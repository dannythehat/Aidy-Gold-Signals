-- AIDY Hub Phase A: durable point-in-time data-health history.
--
-- This table is deliberately append-only. It records what the production worker
-- could prove about its inputs at a particular observation time so the future Hub
-- can reconstruct whether AIDY's brain was genuinely fresh at any point in time.

CREATE TABLE IF NOT EXISTS aidy_data_health_events (
    id TEXT PRIMARY KEY,
    observed_at_utc TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN (
            'fresh',
            'open_grace',
            'session_closed',
            'capture_disabled',
            'stale_capture',
            'capture_failed',
            'stale_provider_context',
            'archive_backlog',
            'monitor_error'
        )
    ),
    alert INTEGER NOT NULL CHECK (alert IN (0,1)),
    session_open INTEGER NOT NULL CHECK (session_open IN (0,1)),
    capture_enabled INTEGER NOT NULL CHECK (capture_enabled IN (0,1)),
    market_data_source TEXT NOT NULL,
    scheduler TEXT NOT NULL,
    latest_scheduled_success_utc TEXT,
    latest_scheduled_request_utc TEXT,
    latest_scheduled_request_status TEXT,
    latest_scheduled_error_code TEXT,
    latest_provider_context_snapshot_utc TEXT,
    success_lag_seconds INTEGER,
    provider_context_snapshot_lag_seconds INTEGER,
    archive_pending_count INTEGER NOT NULL DEFAULT 0 CHECK (archive_pending_count >= 0),
    archive_backoff_count INTEGER NOT NULL DEFAULT 0 CHECK (archive_backoff_count >= 0),
    archive_dead_letter_count INTEGER NOT NULL DEFAULT 0 CHECK (archive_dead_letter_count >= 0),
    oldest_archive_unarchived_utc TEXT,
    cross_market_archive_pending_count INTEGER NOT NULL DEFAULT 0
        CHECK (cross_market_archive_pending_count >= 0),
    cross_market_archive_backoff_count INTEGER NOT NULL DEFAULT 0
        CHECK (cross_market_archive_backoff_count >= 0),
    cross_market_archive_dead_letter_count INTEGER NOT NULL DEFAULT 0
        CHECK (cross_market_archive_dead_letter_count >= 0),
    oldest_cross_market_archive_unarchived_utc TEXT,
    latest_cross_market_first_observed_at TEXT,
    latest_macro_event_first_observed_at TEXT,
    reason TEXT NOT NULL,
    checks_json TEXT NOT NULL CHECK (json_valid(checks_json)),
    health_version TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_aidy_data_health_events_observed
    ON aidy_data_health_events(observed_at_utc DESC, id DESC);

CREATE INDEX IF NOT EXISTS ix_aidy_data_health_events_status
    ON aidy_data_health_events(status, observed_at_utc DESC);
