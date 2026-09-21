-- Human-readable live calculator scorecard for AIDY's Gold cycle brain.
-- This view is read-only and derives from frozen cycle evidence plus resolved marker outcomes.

DROP VIEW IF EXISTS aidy_gold_calculator_scorecard_v1;

CREATE VIEW aidy_gold_calculator_scorecard_v1 AS
WITH reason_rows AS (
    SELECT
        v.cycle_view_id,
        v.window_start_utc,
        v.window_end_utc,
        v.decided_at_utc,
        v.session_code,
        v.observed_state,
        v.view_direction,
        json_extract(reason.value,'$.marker_id') AS marker_id,
        json_extract(reason.value,'$.surface') AS surface,
        json_extract(reason.value,'$.observation') AS observation,
        json_extract(reason.value,'$.vote') AS vote,
        json_extract(reason.value,'$.base_weight') AS base_weight,
        json_extract(reason.value,'$.learned_multiplier') AS learned_multiplier,
        json_extract(reason.value,'$.effective_weight') AS effective_weight,
        json_extract(reason.value,'$.selected_score_scope') AS selected_score_scope,
        json_extract(reason.value,'$.selected_score_scope_key') AS selected_score_scope_key,
        COALESCE(
            json_extract(reason.value,'$.selected_score_context'),
            'bootstrap_prior'
        ) AS readable_condition,
        json_extract(reason.value,'$.selected_score_sample_n') AS sample_n,
        json_extract(reason.value,'$.selected_score_net') AS net_score,
        json_extract(reason.value,'$.selected_score_accuracy') AS accuracy
    FROM aidy_gold_cycle_views v,
         json_each(v.evidence_json,'$.all_directional_reasons') AS reason
)
SELECT
    r.cycle_view_id,
    r.window_start_utc,
    r.window_end_utc,
    r.decided_at_utc,
    r.session_code,
    r.observed_state,
    r.view_direction,
    r.marker_id,
    r.surface,
    r.observation,
    r.vote,
    r.base_weight,
    r.learned_multiplier,
    r.effective_weight,
    r.selected_score_scope,
    r.selected_score_scope_key,
    r.readable_condition,
    r.sample_n,
    r.net_score,
    r.accuracy,
    m.marker_score,
    m.marker_correct,
    o.realised_direction,
    o.return_bps,
    o.resolved_at_utc
FROM reason_rows r
LEFT JOIN aidy_gold_cycle_marker_results m
  ON m.cycle_view_id=r.cycle_view_id
 AND m.marker_id=r.marker_id
LEFT JOIN aidy_gold_cycle_outcomes o
  ON o.cycle_view_id=r.cycle_view_id;
