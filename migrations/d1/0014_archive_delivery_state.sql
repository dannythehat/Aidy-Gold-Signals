-- Day 6 production hardening: bounded D1 -> R2 archive retry lifecycle.
--
-- This migration is deliberately additive. The legacy `status` column remains
-- unchanged (`pending` / `archived`) so the previously deployed Worker can keep
-- running safely if this migration is applied before the Day 6 runtime deploy.
-- New code uses `delivery_state` for retry/backoff/dead-letter semantics.

ALTER TABLE archive_outbox ADD COLUMN delivery_state TEXT NOT NULL DEFAULT 'pending'
    CHECK (delivery_state IN ('pending','backoff','dead_letter','archived'));
ALTER TABLE archive_outbox ADD COLUMN next_attempt_at TEXT;
ALTER TABLE archive_outbox ADD COLUMN first_failed_at TEXT;
ALTER TABLE archive_outbox ADD COLUMN dead_lettered_at TEXT;

UPDATE archive_outbox
SET delivery_state = CASE WHEN status='archived' THEN 'archived' ELSE 'pending' END;

CREATE INDEX IF NOT EXISTS ix_archive_outbox_delivery_due
    ON archive_outbox(delivery_state,next_attempt_at,created_at,id);

ALTER TABLE cross_market_archive_outbox ADD COLUMN delivery_state TEXT NOT NULL DEFAULT 'pending'
    CHECK (delivery_state IN ('pending','backoff','dead_letter','archived'));
ALTER TABLE cross_market_archive_outbox ADD COLUMN next_attempt_at TEXT;
ALTER TABLE cross_market_archive_outbox ADD COLUMN first_failed_at TEXT;
ALTER TABLE cross_market_archive_outbox ADD COLUMN dead_lettered_at TEXT;

UPDATE cross_market_archive_outbox
SET delivery_state = CASE WHEN status='archived' THEN 'archived' ELSE 'pending' END;

CREATE INDEX IF NOT EXISTS ix_cross_market_archive_outbox_delivery_due
    ON cross_market_archive_outbox(delivery_state,next_attempt_at,created_at,id);
