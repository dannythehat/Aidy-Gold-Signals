-- AIDY Day 51 durable publication/delivery ledger.
-- Delivery state is operational truth only and never mutates trading-decision truth.

CREATE TABLE IF NOT EXISTS publication_deliveries (
    publication_id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL,
    ex_ante_digest TEXT NOT NULL CHECK (length(ex_ante_digest) = 64),
    message_digest TEXT NOT NULL CHECK (length(message_digest) = 64),
    envelope_digest TEXT NOT NULL CHECK (length(envelope_digest) = 64),
    group_name TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    exact_message_text TEXT NOT NULL,
    source_state TEXT NOT NULL CHECK (source_state = 'live_admitted'),
    action TEXT NOT NULL CHECK (action IN ('new_trade','manage_trade','close_trade')),
    created_at_utc TEXT NOT NULL,
    delivery_state TEXT NOT NULL DEFAULT 'pending'
        CHECK (delivery_state IN ('pending','retryable_failed','delivery_uncertain','sent','permanent_failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    lease_token TEXT,
    lease_until_utc TEXT,
    last_attempt_at_utc TEXT,
    last_error_code TEXT,
    telegram_message_id INTEGER,
    sent_at_utc TEXT,
    transport TEXT,
    receipt_digest TEXT,
    correction_of_publication_id TEXT,
    correction_reason_code TEXT,
    CHECK (
        (delivery_state = 'sent' AND telegram_message_id IS NOT NULL AND sent_at_utc IS NOT NULL)
        OR delivery_state != 'sent'
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_publication_deliveries_decision_message_chat
    ON publication_deliveries(decision_id,message_digest,chat_id);
CREATE INDEX IF NOT EXISTS ix_publication_deliveries_state_created
    ON publication_deliveries(delivery_state,created_at_utc);
CREATE INDEX IF NOT EXISTS ix_publication_deliveries_decision
    ON publication_deliveries(decision_id,created_at_utc);

CREATE TABLE IF NOT EXISTS publication_attempts (
    attempt_id TEXT PRIMARY KEY,
    publication_id TEXT NOT NULL,
    attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
    attempted_at_utc TEXT NOT NULL,
    completed_at_utc TEXT,
    result_state TEXT NOT NULL
        CHECK (result_state IN ('started','retryable_failed','delivery_uncertain','sent','permanent_failed')),
    error_code TEXT,
    telegram_message_id INTEGER,
    transport TEXT,
    lease_token TEXT NOT NULL,
    attempt_digest TEXT,
    FOREIGN KEY(publication_id) REFERENCES publication_deliveries(publication_id),
    UNIQUE(publication_id,attempt_number),
    UNIQUE(publication_id,lease_token)
);

CREATE INDEX IF NOT EXISTS ix_publication_attempts_publication
    ON publication_attempts(publication_id,attempt_number);

CREATE TABLE IF NOT EXISTS publication_reconciliation_events (
    reconciliation_id TEXT PRIMARY KEY,
    publication_id TEXT NOT NULL,
    observed_at_utc TEXT NOT NULL,
    event_type TEXT NOT NULL
        CHECK (event_type IN ('confirmed_sent','confirmed_not_sent','operator_hold','operator_release')),
    reason_code TEXT NOT NULL,
    telegram_message_id INTEGER,
    event_digest TEXT NOT NULL CHECK (length(event_digest) = 64),
    FOREIGN KEY(publication_id) REFERENCES publication_deliveries(publication_id)
);

CREATE INDEX IF NOT EXISTS ix_publication_reconciliation_publication
    ON publication_reconciliation_events(publication_id,observed_at_utc);
