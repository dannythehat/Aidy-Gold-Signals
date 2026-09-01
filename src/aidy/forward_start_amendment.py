from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from aidy.forward_evaluation import (
    D1ForwardEvaluationStore,
    FREEZE_BREAK_REASON_CODES,
    ForwardEvaluationError,
    canonical_json,
    digest,
)

AMENDMENT_VERSION = "aidy_day53_immediate_start_amendment_v1"
FORWARD_COHORT_VERSION_V2 = "aidy_formal_forward_cohort_v2_immediate_start"
FORWARD_MANIFEST_VERSION_V2 = "aidy_day53_frozen_version_manifest_v2_immediate_start"
FORMER_PLANNING_START_UTC = "2026-09-20T00:00:00+00:00"
AMENDMENT_EFFECTIVE_UTC = "2026-09-01T16:07:00+00:00"
DAY54_EARLIEST_REVIEW_DATE = "2026-10-08"
DAY54_MINIMUM_EPISODE_INDEPENDENT_N = 300

_REQUIRED_COMPONENTS = frozenset(
    {
        "day52_runtime",
        "openai_gateway_v2",
        "self_consistency_v2",
        "immutable_decision_ledger",
        "selective_abstention_shadow",
        "gc_xau_shadow",
        "macro_surprise",
    }
)
_MODEL_RESOLVED_DISPOSITIONS = (
    "self_consistency_abstain",
    "no_trade",
    "decision_admitted",
    "management_admitted",
)


def _utc(value: datetime | str, *, name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError as exc:
            raise ForwardEvaluationError(f"{name} must be timezone-aware ISO-8601.") from exc
    else:
        raise TypeError(f"{name} must be a timezone-aware datetime or ISO-8601 string.")
    if parsed.tzinfo is None:
        raise ForwardEvaluationError(f"{name} must be timezone-aware.")
    return parsed.astimezone(UTC)


def _sha(value: Any, *, name: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 40 or any(ch not in "0123456789abcdef" for ch in text):
        raise ForwardEvaluationError(f"{name} must be a 40-character git SHA.")
    return text


def _component(value: Mapping[str, Any], *, name: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise TypeError(f"components.{name} must be a mapping.")
    version = str(value.get("version") or "").strip()
    component_digest = str(value.get("digest") or "").strip()
    if not version or not component_digest:
        raise ForwardEvaluationError(f"components.{name} requires version and digest.")
    return {"version": version, "digest": component_digest}


def build_amended_frozen_version_manifest(
    *,
    accepted_code_head: str,
    earliest_start_utc: datetime | str = AMENDMENT_EFFECTIVE_UTC,
    components: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    head = _sha(accepted_code_head, name="accepted_code_head")
    start = _utc(earliest_start_utc, name="earliest_start_utc")
    amendment_floor = _utc(AMENDMENT_EFFECTIVE_UTC, name="amendment_effective_utc")
    if start < amendment_floor:
        raise ForwardEvaluationError(
            "Formal forward start cannot precede the 1 Sep 2026 ex-ante amendment."
        )
    missing = sorted(_REQUIRED_COMPONENTS - set(components))
    if missing:
        raise ForwardEvaluationError(f"Frozen manifest is missing components: {missing}")
    normalized = {
        name: _component(components[name], name=name)
        for name in sorted(components)
    }
    manifest: dict[str, Any] = {
        "manifest_version": FORWARD_MANIFEST_VERSION_V2,
        "cohort_contract_version": FORWARD_COHORT_VERSION_V2,
        "amendment_version": AMENDMENT_VERSION,
        "amendment_effective_utc": AMENDMENT_EFFECTIVE_UTC,
        "former_planning_start_utc": FORMER_PLANNING_START_UTC,
        "former_planning_floor_superseded_before_forward_outcomes": True,
        "formal_forward_outcomes_existed_before_amendment": False,
        "accepted_code_head": head,
        "earliest_start_utc": start.isoformat(),
        "components": normalized,
        "pre_activation_backfill_allowed": False,
        "day52_or_earlier_performance_counts_as_formal_forward": False,
        "forward_outcomes_may_tune_active_cohort": False,
        "selective_abstention_can_gate_master_trader": False,
        "selective_abstention_can_gate_publication": False,
        "gc_shadow_promoted_to_authoritative_decision_input": False,
        "broker_or_account_state_allowed": False,
        "follower_state_allowed": False,
        "super_signals_dependency_allowed": False,
        "live_money_execution_allowed": False,
        "freeze_break_reason_codes": sorted(FREEZE_BREAK_REASON_CODES),
        "performance_improvement_is_valid_freeze_break": False,
        "day54_earliest_review_date": DAY54_EARLIEST_REVIEW_DATE,
        "minimum_day54_episode_independent_n": DAY54_MINIMUM_EPISODE_INDEPENDENT_N,
        "day54_gate_uses_model_resolved_episodes_only": True,
    }
    manifest["manifest_digest"] = digest(manifest)
    return manifest


def verify_amended_frozen_version_manifest(manifest: Mapping[str, Any]) -> bool:
    try:
        body = copy.deepcopy(dict(manifest))
        supplied = str(body.pop("manifest_digest", ""))
        if not supplied or supplied != digest(body):
            return False
        if body.get("manifest_version") != FORWARD_MANIFEST_VERSION_V2:
            return False
        if body.get("cohort_contract_version") != FORWARD_COHORT_VERSION_V2:
            return False
        if body.get("amendment_version") != AMENDMENT_VERSION:
            return False
        if body.get("former_planning_floor_superseded_before_forward_outcomes") is not True:
            return False
        if body.get("formal_forward_outcomes_existed_before_amendment") is not False:
            return False
        if body.get("pre_activation_backfill_allowed") is not False:
            return False
        _sha(body.get("accepted_code_head"), name="accepted_code_head")
        start = _utc(body.get("earliest_start_utc"), name="earliest_start_utc")
        if start < _utc(AMENDMENT_EFFECTIVE_UTC, name="amendment_effective_utc"):
            return False
        components = body.get("components")
        if not isinstance(components, Mapping):
            return False
        rebuilt = build_amended_frozen_version_manifest(
            accepted_code_head=str(body["accepted_code_head"]),
            earliest_start_utc=start,
            components=components,
        )
        if rebuilt["manifest_digest"] != supplied:
            return False
        return (
            body.get("day52_or_earlier_performance_counts_as_formal_forward") is False
            and body.get("forward_outcomes_may_tune_active_cohort") is False
            and body.get("selective_abstention_can_gate_master_trader") is False
            and body.get("selective_abstention_can_gate_publication") is False
            and body.get("gc_shadow_promoted_to_authoritative_decision_input") is False
            and body.get("broker_or_account_state_allowed") is False
            and body.get("follower_state_allowed") is False
            and body.get("super_signals_dependency_allowed") is False
            and body.get("live_money_execution_allowed") is False
            and body.get("performance_improvement_is_valid_freeze_break") is False
            and body.get("day54_earliest_review_date") == DAY54_EARLIEST_REVIEW_DATE
            and int(body.get("minimum_day54_episode_independent_n"))
            == DAY54_MINIMUM_EPISODE_INDEPENDENT_N
            and body.get("day54_gate_uses_model_resolved_episodes_only") is True
        )
    except (KeyError, TypeError, ValueError):
        return False


def amended_cohort_id_for_manifest(manifest: Mapping[str, Any]) -> str:
    if not verify_amended_frozen_version_manifest(manifest):
        raise ForwardEvaluationError("A valid amended frozen version manifest is required.")
    return f"aidy_fwd_v2_{str(manifest['manifest_digest'])[:32]}"


class D1ImmediateForwardEvaluationStore(D1ForwardEvaluationStore):
    """Day 53 amended cohort store using the existing append-only D1 tables."""

    async def prepare_cohort(
        self, manifest: Mapping[str, Any], *, prepared_at_utc: datetime | str
    ) -> dict[str, Any]:
        if not verify_amended_frozen_version_manifest(manifest):
            raise ForwardEvaluationError("Cannot prepare an invalid amended frozen manifest.")
        cohort_id = amended_cohort_id_for_manifest(manifest)
        stamp = _utc(prepared_at_utc, name="prepared_at_utc").isoformat()
        start = _utc(manifest["earliest_start_utc"], name="earliest_start_utc").isoformat()
        if _utc(stamp, name="prepared_at_utc") < _utc(
            AMENDMENT_EFFECTIVE_UTC, name="amendment_effective_utc"
        ):
            raise ForwardEvaluationError("Amended cohort cannot be prepared before the amendment.")
        text = canonical_json(manifest)
        await self._stmt(
            """
            INSERT INTO aidy_forward_cohorts (
                cohort_id,cohort_version,manifest_version,manifest_json,manifest_digest,
                accepted_code_head,earliest_start_utc,prepared_at_utc,state
            ) VALUES (?,?,?,?,?,?,?,?, 'prepared')
            ON CONFLICT(cohort_id) DO NOTHING
            """,
            cohort_id,
            FORWARD_COHORT_VERSION_V2,
            FORWARD_MANIFEST_VERSION_V2,
            text,
            manifest["manifest_digest"],
            manifest["accepted_code_head"],
            start,
            stamp,
        ).run()
        row = await self.get_cohort(cohort_id)
        if row is None:
            raise RuntimeError("Failed to persist amended Day 53 forward cohort.")
        if str(row.get("manifest_digest")) != str(manifest["manifest_digest"]):
            raise RuntimeError("Amended frozen forward cohort identity conflict.")
        return row

    async def cohort_progress(self, cohort_id: str) -> dict[str, Any]:
        cohort = await self.get_cohort(cohort_id)
        if cohort is None:
            raise KeyError(f"Unknown cohort_id: {cohort_id}")
        row = await self._first(
            """
            SELECT
                COUNT(*) AS raw_evaluation_count,
                COUNT(DISTINCT episode_id) AS all_evaluation_episode_n,
                COUNT(DISTINCT CASE WHEN disposition IN (
                    'self_consistency_abstain','no_trade','decision_admitted','management_admitted'
                ) THEN episode_id END) AS model_resolved_episode_independent_n,
                SUM(CASE WHEN disposition='no_trade' THEN 1 ELSE 0 END) AS raw_no_trade_count,
                SUM(CASE WHEN disposition IN ('decision_admitted','management_admitted') THEN 1 ELSE 0 END)
                    AS raw_admitted_count,
                SUM(CASE WHEN disposition='self_consistency_abstain' THEN 1 ELSE 0 END)
                    AS raw_self_consistency_abstain_count,
                SUM(CASE WHEN disposition='pre_model_blocked' THEN 1 ELSE 0 END)
                    AS raw_pre_model_blocked_count,
                SUM(CASE WHEN data_quality_state='failure' THEN 1 ELSE 0 END)
                    AS data_quality_failure_count
            FROM aidy_forward_evaluations
            WHERE cohort_id=?
            """,
            cohort_id,
        )
        values = dict(row) if row is not None else {}
        resolved_n = int(values.get("model_resolved_episode_independent_n") or 0)
        result: dict[str, Any] = {
            "cohort_id": cohort_id,
            "cohort_state": cohort["state"],
            "raw_evaluation_count": int(values.get("raw_evaluation_count") or 0),
            "all_evaluation_episode_n": int(values.get("all_evaluation_episode_n") or 0),
            "model_resolved_episode_independent_n": resolved_n,
            "episode_independent_n": resolved_n,
            "raw_no_trade_count": int(values.get("raw_no_trade_count") or 0),
            "raw_admitted_count": int(values.get("raw_admitted_count") or 0),
            "raw_self_consistency_abstain_count": int(
                values.get("raw_self_consistency_abstain_count") or 0
            ),
            "raw_pre_model_blocked_count": int(values.get("raw_pre_model_blocked_count") or 0),
            "data_quality_failure_count": int(values.get("data_quality_failure_count") or 0),
            "day54_sample_gate_episode_independent_n": DAY54_MINIMUM_EPISODE_INDEPENDENT_N,
            "day54_sample_gate_met": resolved_n >= DAY54_MINIMUM_EPISODE_INDEPENDENT_N,
            "blocked_or_failed_cycles_can_satisfy_day54_gate": False,
            "raw_count_can_substitute_for_effective_n": False,
        }
        result["progress_digest"] = digest(result)
        return result


def day53_immediate_start_manifest() -> dict[str, Any]:
    result: dict[str, Any] = {
        "manifest_version": "aidy_day53_immediate_start_architecture_manifest_v1",
        "amendment_version": AMENDMENT_VERSION,
        "amendment_effective_utc": AMENDMENT_EFFECTIVE_UTC,
        "former_planning_start_utc": FORMER_PLANNING_START_UTC,
        "immediate_start_allowed_after_exact_head_merge": True,
        "pre_activation_backfill_allowed": False,
        "formal_forward_outcomes_existed_before_amendment": False,
        "day54_earliest_review_date": DAY54_EARLIEST_REVIEW_DATE,
        "day54_sample_gate_episode_independent_n": DAY54_MINIMUM_EPISODE_INDEPENDENT_N,
        "day54_gate_uses_model_resolved_episodes_only": True,
        "blocked_cycles_count_as_model_resolved_episodes": False,
        "selective_layer_remains_shadow_only": True,
        "gc_remains_shadow_only": True,
        "performance_improvement_freeze_break_allowed": False,
        "super_signals_dependency_allowed": False,
        "broker_or_account_state_allowed": False,
        "follower_state_allowed": False,
        "live_money_execution_allowed": False,
    }
    result["manifest_digest"] = digest(result)
    return result
