-- Phase A production consistency repair.
--
-- Two legacy archive rows can have status='archived' while the additive Day 6
-- delivery_state column remains 'pending'. The immutable R2 write has already
-- succeeded in that state, so reconcile the secondary lifecycle marker rather
-- than re-delivering or treating the row as a live backlog.

UPDATE archive_outbox
SET delivery_state='archived',
    next_attempt_at=NULL,
    dead_lettered_at=NULL,
    last_error=NULL
WHERE status='archived'
  AND delivery_state!='archived';

UPDATE cross_market_archive_outbox
SET delivery_state='archived',
    next_attempt_at=NULL,
    dead_lettered_at=NULL,
    last_error=NULL
WHERE status='archived'
  AND delivery_state!='archived';
