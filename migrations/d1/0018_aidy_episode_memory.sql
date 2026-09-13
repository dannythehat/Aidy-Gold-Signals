-- AIDY Hub Phase B: permanent episode -> outcome -> lesson memory.
--
-- This layer mirrors immutable formal-forward evidence into a point-in-time memory
-- spine.  It is research/shadow memory only: nothing in these tables is permitted
-- to become an authoritative trading input merely by being stored or retrieved.
--
-- PIT rule: a memory item is retrievable only when available_at_utc <= query as-of.

CREATE TABLE IF NOT EXISTS aidy_memory_episodes (
    memory_episode_id TEXT PRIMARY KEY,
    memory_version TEXT NOT NULL DEFAULT 'aidy_episode_memory_v1',
    forward_record_id TEXT NOT NULL UNIQUE,
    independent_episode_id TEXT NOT NULL,
    cohort_id TEXT NOT NULL,
    cycle_id TEXT NOT NULL,
    instruction_type TEXT NOT NULL,
    source_state TEXT NOT NULL,
    evaluated_at_utc TEXT NOT NULL,
    available_at_utc TEXT NOT NULL,
    context_hash TEXT NOT NULL CHECK (length(context_hash) = 64),
    disposition TEXT NOT NULL,
    data_quality_state TEXT NOT NULL,
    data_quality_reason_code TEXT,
    decision_id TEXT,
    ex_ante_digest TEXT,
    self_consistency_digest TEXT,
    retrieval_effective_n INTEGER NOT NULL CHECK (retrieval_effective_n >= 0),
    record_digest TEXT NOT NULL UNIQUE,
    episode_json TEXT NOT NULL CHECK (json_valid(episode_json)),
    ex_ante_json TEXT CHECK (ex_ante_json IS NULL OR json_valid(ex_ante_json)),
    decision_action TEXT,
    direction TEXT,
    setup_codes_json TEXT CHECK (setup_codes_json IS NULL OR json_valid(setup_codes_json)),
    strategy_version TEXT,
    model_id TEXT,
    evidence_grade TEXT,
    research_only INTEGER NOT NULL DEFAULT 1 CHECK (research_only = 1),
    authoritative_decision_input INTEGER NOT NULL DEFAULT 0 CHECK (authoritative_decision_input = 0),
    created_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS aidy_memory_outcomes (
    memory_outcome_id TEXT PRIMARY KEY,
    memory_version TEXT NOT NULL DEFAULT 'aidy_episode_outcome_memory_v1',
    memory_episode_id TEXT NOT NULL,
    forward_record_id TEXT NOT NULL,
    forward_attachment_id TEXT NOT NULL UNIQUE,
    outcome_type TEXT NOT NULL,
    attached_at_utc TEXT NOT NULL,
    available_at_utc TEXT NOT NULL,
    attachment_digest TEXT NOT NULL UNIQUE,
    outcome_json TEXT NOT NULL CHECK (json_valid(outcome_json)),
    research_only INTEGER NOT NULL DEFAULT 1 CHECK (research_only = 1),
    active_strategy_tuning_allowed INTEGER NOT NULL DEFAULT 0 CHECK (active_strategy_tuning_allowed = 0),
    authoritative_decision_input INTEGER NOT NULL DEFAULT 0 CHECK (authoritative_decision_input = 0),
    created_at_utc TEXT NOT NULL,
    FOREIGN KEY (memory_episode_id) REFERENCES aidy_memory_episodes(memory_episode_id)
);

CREATE TABLE IF NOT EXISTS aidy_memory_lessons (
    lesson_id TEXT PRIMARY KEY,
    lesson_version TEXT NOT NULL DEFAULT 'aidy_episode_lesson_v1',
    memory_episode_id TEXT NOT NULL,
    memory_outcome_id TEXT NOT NULL UNIQUE,
    independent_episode_id TEXT NOT NULL,
    learned_at_utc TEXT NOT NULL,
    available_at_utc TEXT NOT NULL,
    outcome_class TEXT NOT NULL CHECK (outcome_class IN ('positive','negative','flat','no_trade_shadow','unknown')),
    realized_r REAL,
    thesis_status TEXT,
    decision_action TEXT,
    direction TEXT,
    setup_codes_json TEXT CHECK (setup_codes_json IS NULL OR json_valid(setup_codes_json)),
    strategy_version TEXT,
    model_id TEXT,
    evidence_grade TEXT,
    lesson_json TEXT NOT NULL CHECK (json_valid(lesson_json)),
    lesson_digest TEXT NOT NULL UNIQUE,
    research_only INTEGER NOT NULL DEFAULT 1 CHECK (research_only = 1),
    active_strategy_tuning_allowed INTEGER NOT NULL DEFAULT 0 CHECK (active_strategy_tuning_allowed = 0),
    authoritative_decision_input INTEGER NOT NULL DEFAULT 0 CHECK (authoritative_decision_input = 0),
    FOREIGN KEY (memory_episode_id) REFERENCES aidy_memory_episodes(memory_episode_id),
    FOREIGN KEY (memory_outcome_id) REFERENCES aidy_memory_outcomes(memory_outcome_id)
);

CREATE TABLE IF NOT EXISTS aidy_memory_retrieval_events (
    retrieval_event_id TEXT PRIMARY KEY,
    retrieval_version TEXT NOT NULL DEFAULT 'aidy_episode_memory_retrieval_v1',
    queried_at_utc TEXT NOT NULL,
    as_of_utc TEXT NOT NULL,
    direction_filter TEXT,
    setup_code_filter TEXT,
    requested_limit INTEGER NOT NULL CHECK (requested_limit BETWEEN 1 AND 100),
    result_count INTEGER NOT NULL CHECK (result_count >= 0),
    selected_lesson_ids_json TEXT NOT NULL CHECK (json_valid(selected_lesson_ids_json)),
    query_digest TEXT NOT NULL,
    research_only INTEGER NOT NULL DEFAULT 1 CHECK (research_only = 1),
    authoritative_decision_input INTEGER NOT NULL DEFAULT 0 CHECK (authoritative_decision_input = 0)
);

CREATE INDEX IF NOT EXISTS ix_aidy_memory_episodes_available
    ON aidy_memory_episodes(available_at_utc DESC, memory_episode_id DESC);
CREATE INDEX IF NOT EXISTS ix_aidy_memory_episodes_episode
    ON aidy_memory_episodes(independent_episode_id, available_at_utc);
CREATE INDEX IF NOT EXISTS ix_aidy_memory_lessons_available
    ON aidy_memory_lessons(available_at_utc DESC, lesson_id DESC);
CREATE INDEX IF NOT EXISTS ix_aidy_memory_lessons_direction
    ON aidy_memory_lessons(direction, available_at_utc DESC);
CREATE INDEX IF NOT EXISTS ix_aidy_memory_retrieval_events_time
    ON aidy_memory_retrieval_events(queried_at_utc DESC, retrieval_event_id DESC);

-- Backfill every immutable formal-forward evaluation already known to AIDY.
INSERT OR IGNORE INTO aidy_memory_episodes (
    memory_episode_id,forward_record_id,independent_episode_id,cohort_id,cycle_id,
    instruction_type,source_state,evaluated_at_utc,available_at_utc,context_hash,
    disposition,data_quality_state,data_quality_reason_code,decision_id,ex_ante_digest,
    self_consistency_digest,retrieval_effective_n,record_digest,episode_json,ex_ante_json,
    decision_action,direction,setup_codes_json,strategy_version,model_id,evidence_grade,
    created_at_utc
)
SELECT
    f.record_id,
    f.record_id,
    f.episode_id,
    f.cohort_id,
    f.cycle_id,
    f.instruction_type,
    f.source_state,
    f.evaluated_at_utc,
    f.recorded_at_utc,
    f.context_hash,
    f.disposition,
    f.data_quality_state,
    f.data_quality_reason_code,
    f.decision_id,
    f.ex_ante_digest,
    f.self_consistency_digest,
    f.retrieval_effective_n,
    f.record_digest,
    f.record_json,
    e.ex_ante_json,
    json_extract(e.ex_ante_json,'$.decision.action'),
    json_extract(e.ex_ante_json,'$.decision.direction'),
    json_extract(e.ex_ante_json,'$.decision.setup_codes'),
    json_extract(e.ex_ante_json,'$.reproducibility_bundle.strategy_version'),
    json_extract(e.ex_ante_json,'$.reproducibility_bundle.model_id'),
    json_extract(e.ex_ante_json,'$.reproducibility_bundle.evidence_grade'),
    f.recorded_at_utc
FROM aidy_forward_evaluations AS f
LEFT JOIN aidy_end_to_end_cycles AS e
  ON e.ex_ante_digest=f.ex_ante_digest
 AND f.ex_ante_digest IS NOT NULL;

-- Every future formal-forward evaluation is mirrored automatically and immutably.
CREATE TRIGGER IF NOT EXISTS trg_aidy_memory_episode_from_forward
AFTER INSERT ON aidy_forward_evaluations
BEGIN
    INSERT OR IGNORE INTO aidy_memory_episodes (
        memory_episode_id,forward_record_id,independent_episode_id,cohort_id,cycle_id,
        instruction_type,source_state,evaluated_at_utc,available_at_utc,context_hash,
        disposition,data_quality_state,data_quality_reason_code,decision_id,ex_ante_digest,
        self_consistency_digest,retrieval_effective_n,record_digest,episode_json,ex_ante_json,
        decision_action,direction,setup_codes_json,strategy_version,model_id,evidence_grade,
        created_at_utc
    )
    SELECT
        NEW.record_id,NEW.record_id,NEW.episode_id,NEW.cohort_id,NEW.cycle_id,
        NEW.instruction_type,NEW.source_state,NEW.evaluated_at_utc,NEW.recorded_at_utc,
        NEW.context_hash,NEW.disposition,NEW.data_quality_state,NEW.data_quality_reason_code,
        NEW.decision_id,NEW.ex_ante_digest,NEW.self_consistency_digest,NEW.retrieval_effective_n,
        NEW.record_digest,NEW.record_json,e.ex_ante_json,
        json_extract(e.ex_ante_json,'$.decision.action'),
        json_extract(e.ex_ante_json,'$.decision.direction'),
        json_extract(e.ex_ante_json,'$.decision.setup_codes'),
        json_extract(e.ex_ante_json,'$.reproducibility_bundle.strategy_version'),
        json_extract(e.ex_ante_json,'$.reproducibility_bundle.model_id'),
        json_extract(e.ex_ante_json,'$.reproducibility_bundle.evidence_grade'),
        NEW.recorded_at_utc
    FROM (SELECT 1) AS one
    LEFT JOIN aidy_end_to_end_cycles AS e
      ON e.ex_ante_digest=NEW.ex_ante_digest
     AND NEW.ex_ante_digest IS NOT NULL
    LIMIT 1;
END;

-- Backfill outcome attachments already known to formal-forward storage.
INSERT OR IGNORE INTO aidy_memory_outcomes (
    memory_outcome_id,memory_episode_id,forward_record_id,forward_attachment_id,
    outcome_type,attached_at_utc,available_at_utc,attachment_digest,outcome_json,created_at_utc
)
SELECT
    o.attachment_id,
    o.record_id,
    o.record_id,
    o.attachment_id,
    o.outcome_type,
    o.attached_at_utc,
    o.recorded_at_utc,
    o.attachment_digest,
    o.attachment_json,
    o.recorded_at_utc
FROM aidy_forward_outcomes AS o
JOIN aidy_memory_episodes AS e ON e.forward_record_id=o.record_id;

CREATE TRIGGER IF NOT EXISTS trg_aidy_memory_outcome_from_forward
AFTER INSERT ON aidy_forward_outcomes
BEGIN
    INSERT OR IGNORE INTO aidy_memory_outcomes (
        memory_outcome_id,memory_episode_id,forward_record_id,forward_attachment_id,
        outcome_type,attached_at_utc,available_at_utc,attachment_digest,outcome_json,created_at_utc
    )
    SELECT
        NEW.attachment_id,e.memory_episode_id,NEW.record_id,NEW.attachment_id,
        NEW.outcome_type,NEW.attached_at_utc,NEW.recorded_at_utc,NEW.attachment_digest,
        NEW.attachment_json,NEW.recorded_at_utc
    FROM aidy_memory_episodes AS e
    WHERE e.forward_record_id=NEW.record_id
    LIMIT 1;
END;

-- Deterministic lessons are derived from immutable outcomes. They are deliberately
-- compact and factual: no LLM-generated hindsight narrative is allowed here.
CREATE TRIGGER IF NOT EXISTS trg_aidy_memory_lesson_from_outcome
AFTER INSERT ON aidy_memory_outcomes
BEGIN
    INSERT OR IGNORE INTO aidy_memory_lessons (
        lesson_id,memory_episode_id,memory_outcome_id,independent_episode_id,
        learned_at_utc,available_at_utc,outcome_class,realized_r,thesis_status,
        decision_action,direction,setup_codes_json,strategy_version,model_id,evidence_grade,
        lesson_json,lesson_digest
    )
    SELECT
        'lesson:' || NEW.memory_outcome_id,
        e.memory_episode_id,
        NEW.memory_outcome_id,
        e.independent_episode_id,
        NEW.available_at_utc,
        NEW.available_at_utc,
        CASE
          WHEN NEW.outcome_type='no_trade_shadow' THEN 'no_trade_shadow'
          WHEN json_extract(NEW.outcome_json,'$.outcome_payload.economic_outcome.realized_r') IS NULL THEN 'unknown'
          WHEN CAST(json_extract(NEW.outcome_json,'$.outcome_payload.economic_outcome.realized_r') AS REAL) > 0 THEN 'positive'
          WHEN CAST(json_extract(NEW.outcome_json,'$.outcome_payload.economic_outcome.realized_r') AS REAL) < 0 THEN 'negative'
          ELSE 'flat'
        END,
        CASE
          WHEN json_extract(NEW.outcome_json,'$.outcome_payload.economic_outcome.realized_r') IS NULL THEN NULL
          ELSE CAST(json_extract(NEW.outcome_json,'$.outcome_payload.economic_outcome.realized_r') AS REAL)
        END,
        json_extract(NEW.outcome_json,'$.outcome_payload.thesis_outcome.status'),
        e.decision_action,
        e.direction,
        e.setup_codes_json,
        e.strategy_version,
        e.model_id,
        e.evidence_grade,
        json_object(
          'lesson_version','aidy_episode_lesson_v1',
          'memory_episode_id',e.memory_episode_id,
          'memory_outcome_id',NEW.memory_outcome_id,
          'independent_episode_id',e.independent_episode_id,
          'available_at_utc',NEW.available_at_utc,
          'outcome_type',NEW.outcome_type,
          'outcome_class',CASE
            WHEN NEW.outcome_type='no_trade_shadow' THEN 'no_trade_shadow'
            WHEN json_extract(NEW.outcome_json,'$.outcome_payload.economic_outcome.realized_r') IS NULL THEN 'unknown'
            WHEN CAST(json_extract(NEW.outcome_json,'$.outcome_payload.economic_outcome.realized_r') AS REAL) > 0 THEN 'positive'
            WHEN CAST(json_extract(NEW.outcome_json,'$.outcome_payload.economic_outcome.realized_r') AS REAL) < 0 THEN 'negative'
            ELSE 'flat'
          END,
          'realized_r',json_extract(NEW.outcome_json,'$.outcome_payload.economic_outcome.realized_r'),
          'thesis_status',json_extract(NEW.outcome_json,'$.outcome_payload.thesis_outcome.status'),
          'decision_action',e.decision_action,
          'direction',e.direction,
          'setup_codes',CASE WHEN e.setup_codes_json IS NULL THEN json('null') ELSE json(e.setup_codes_json) END,
          'strategy_version',e.strategy_version,
          'model_id',e.model_id,
          'evidence_grade',e.evidence_grade,
          'research_only',json('true'),
          'authoritative_decision_input',json('false')
        ),
        lower(hex(sha3(
          json_object(
            'memory_episode_id',e.memory_episode_id,
            'memory_outcome_id',NEW.memory_outcome_id,
            'attachment_digest',NEW.attachment_digest,
            'available_at_utc',NEW.available_at_utc
          ),256
        )))
    FROM aidy_memory_episodes AS e
    WHERE e.memory_episode_id=NEW.memory_episode_id
    LIMIT 1;
END;

-- Backfilled outcomes predate the trigger above; derive their lessons now.
INSERT OR IGNORE INTO aidy_memory_lessons (
    lesson_id,memory_episode_id,memory_outcome_id,independent_episode_id,
    learned_at_utc,available_at_utc,outcome_class,realized_r,thesis_status,
    decision_action,direction,setup_codes_json,strategy_version,model_id,evidence_grade,
    lesson_json,lesson_digest
)
SELECT
    'lesson:' || o.memory_outcome_id,
    e.memory_episode_id,
    o.memory_outcome_id,
    e.independent_episode_id,
    o.available_at_utc,
    o.available_at_utc,
    CASE
      WHEN o.outcome_type='no_trade_shadow' THEN 'no_trade_shadow'
      WHEN json_extract(o.outcome_json,'$.outcome_payload.economic_outcome.realized_r') IS NULL THEN 'unknown'
      WHEN CAST(json_extract(o.outcome_json,'$.outcome_payload.economic_outcome.realized_r') AS REAL) > 0 THEN 'positive'
      WHEN CAST(json_extract(o.outcome_json,'$.outcome_payload.economic_outcome.realized_r') AS REAL) < 0 THEN 'negative'
      ELSE 'flat'
    END,
    CASE
      WHEN json_extract(o.outcome_json,'$.outcome_payload.economic_outcome.realized_r') IS NULL THEN NULL
      ELSE CAST(json_extract(o.outcome_json,'$.outcome_payload.economic_outcome.realized_r') AS REAL)
    END,
    json_extract(o.outcome_json,'$.outcome_payload.thesis_outcome.status'),
    e.decision_action,e.direction,e.setup_codes_json,e.strategy_version,e.model_id,e.evidence_grade,
    json_object(
      'lesson_version','aidy_episode_lesson_v1',
      'memory_episode_id',e.memory_episode_id,
      'memory_outcome_id',o.memory_outcome_id,
      'independent_episode_id',e.independent_episode_id,
      'available_at_utc',o.available_at_utc,
      'outcome_type',o.outcome_type,
      'outcome_class',CASE
        WHEN o.outcome_type='no_trade_shadow' THEN 'no_trade_shadow'
        WHEN json_extract(o.outcome_json,'$.outcome_payload.economic_outcome.realized_r') IS NULL THEN 'unknown'
        WHEN CAST(json_extract(o.outcome_json,'$.outcome_payload.economic_outcome.realized_r') AS REAL) > 0 THEN 'positive'
        WHEN CAST(json_extract(o.outcome_json,'$.outcome_payload.economic_outcome.realized_r') AS REAL) < 0 THEN 'negative'
        ELSE 'flat'
      END,
      'realized_r',json_extract(o.outcome_json,'$.outcome_payload.economic_outcome.realized_r'),
      'thesis_status',json_extract(o.outcome_json,'$.outcome_payload.thesis_outcome.status'),
      'decision_action',e.decision_action,
      'direction',e.direction,
      'setup_codes',CASE WHEN e.setup_codes_json IS NULL THEN json('null') ELSE json(e.setup_codes_json) END,
      'strategy_version',e.strategy_version,
      'model_id',e.model_id,
      'evidence_grade',e.evidence_grade,
      'research_only',json('true'),
      'authoritative_decision_input',json('false')
    ),
    lower(hex(sha3(json_object(
      'memory_episode_id',e.memory_episode_id,
      'memory_outcome_id',o.memory_outcome_id,
      'attachment_digest',o.attachment_digest,
      'available_at_utc',o.available_at_utc
    ),256)))
FROM aidy_memory_outcomes AS o
JOIN aidy_memory_episodes AS e ON e.memory_episode_id=o.memory_episode_id;

-- Hard append-only protection. Corrections must be new records, never rewrites.
CREATE TRIGGER IF NOT EXISTS trg_aidy_memory_episodes_no_update
BEFORE UPDATE ON aidy_memory_episodes BEGIN
    SELECT RAISE(ABORT,'aidy_memory_episodes is append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_aidy_memory_episodes_no_delete
BEFORE DELETE ON aidy_memory_episodes BEGIN
    SELECT RAISE(ABORT,'aidy_memory_episodes is append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_aidy_memory_outcomes_no_update
BEFORE UPDATE ON aidy_memory_outcomes BEGIN
    SELECT RAISE(ABORT,'aidy_memory_outcomes is append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_aidy_memory_outcomes_no_delete
BEFORE DELETE ON aidy_memory_outcomes BEGIN
    SELECT RAISE(ABORT,'aidy_memory_outcomes is append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_aidy_memory_lessons_no_update
BEFORE UPDATE ON aidy_memory_lessons BEGIN
    SELECT RAISE(ABORT,'aidy_memory_lessons is append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_aidy_memory_lessons_no_delete
BEFORE DELETE ON aidy_memory_lessons BEGIN
    SELECT RAISE(ABORT,'aidy_memory_lessons is append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_aidy_memory_retrieval_no_update
BEFORE UPDATE ON aidy_memory_retrieval_events BEGIN
    SELECT RAISE(ABORT,'aidy_memory_retrieval_events is append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_aidy_memory_retrieval_no_delete
BEFORE DELETE ON aidy_memory_retrieval_events BEGIN
    SELECT RAISE(ABORT,'aidy_memory_retrieval_events is append-only');
END;
