from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

FORWARD_COHORT_VERSION = "aidy_formal_forward_cohort_v1"
FORWARD_MANIFEST_VERSION = "aidy_day53_frozen_version_manifest_v1"
FORWARD_EVALUATION_VERSION = "aidy_formal_forward_evaluation_v1"
FORWARD_OUTCOME_VERSION = "aidy_formal_forward_outcome_attachment_v1"
FORWARD_STORE_VERSION = "aidy_day53_forward_store_v1"
EARLIEST_FORMAL_START_UTC = "2026-09-20T00:00:00+00:00"

COHORT_STATES = frozenset({"prepared", "active", "closed"})
FORWARD_SOURCE_STATE = "private_forward"
FREEZE_BREAK_REASON_CODES = frozenset(
    {
        "material_safety_or_data_integrity_defect",
        "forced_model_or_api_deprecation",
        "objective_market_structure_or_venue_rule_change",
    }
)
FORWARD_DISPOSITIONS = frozenset(
    {
        "pre_model_blocked",
        "model_failed",
        "self_consistency_abstain",
        "no_trade",
        "decision_admitted",
        "management_admitted",
        "failed_closed",
    }
)
DATA_QUALITY_STATES = frozenset({"known_good", "failure", "unknown"})
OUTCOME_TYPES = frozenset({"trade_outcome", "no_trade_shadow"})
_SHA40 = re.compile(r"^[0-9a-f]{40}$")


class ForwardEvaluationError(ValueError):
    pass


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


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
    if not _SHA40.fullmatch(text):
        raise ForwardEvaluationError(f"{name} must be a 40-character git SHA.")
    return text


def _nonempty(value: Any, *, name: str, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ForwardEvaluationError(f"{name} must be non-empty text.")
    text = value.strip()
    if len(text) > maximum:
        raise ForwardEvaluationError(f"{name} exceeds {maximum} characters.")
    return text


def _snapshot(value: Mapping[str, Any] | None, *, kind: str) -> dict[str, Any]:
    if value is None:
        body = {"state": "unknown", "reason_code": f"{kind}_not_available"}
    elif not isinstance(value, Mapping):
        raise TypeError(f"{kind} must be a mapping or null.")
    else:
        body = copy.deepcopy(dict(value))
        if not body:
            raise ForwardEvaluationError(f"{kind} cannot be an empty mapping.")
    return body


def _component_snapshot(value: Mapping[str, Any], *, name: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise TypeError(f"components.{name} must be a mapping.")
    version = _nonempty(value.get("version"), name=f"components.{name}.version")
    component_digest = _nonempty(
        value.get("digest"), name=f"components.{name}.digest", maximum=128
    )
    return {"version": version, "digest": component_digest}


def build_frozen_version_manifest(
    *,
    accepted_code_head: str,
    earliest_start_utc: datetime | str,
    components: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    head = _sha(accepted_code_head, name="accepted_code_head")
    start = _utc(earliest_start_utc, name="earliest_start_utc")
    architecture_floor = _utc(EARLIEST_FORMAL_START_UTC, name="architecture_floor")
    if start < architecture_floor:
        raise ForwardEvaluationError(
            "Formal forward start cannot precede the Architecture V2 20 Sep 2026 floor."
        )
    required = {
        "day52_runtime",
        "openai_gateway_v2",
        "self_consistency_v2",
        "immutable_decision_ledger",
        "selective_abstention_shadow",
        "gc_xau_shadow",
        "macro_surprise",
    }
    supplied = set(components)
    missing = sorted(required - supplied)
    if missing:
        raise ForwardEvaluationError(f"Frozen manifest is missing components: {missing}")
    normalized = {
        name: _component_snapshot(components[name], name=name)
        for name in sorted(components)
    }
    manifest: dict[str, Any] = {
        "manifest_version": FORWARD_MANIFEST_VERSION,
        "cohort_contract_version": FORWARD_COHORT_VERSION,
        "accepted_code_head": head,
        "earliest_start_utc": start.isoformat(),
        "components": normalized,
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
        "minimum_day54_episode_independent_n": 300,
    }
    manifest["manifest_digest"] = digest(manifest)
    return manifest


def verify_frozen_version_manifest(manifest: Mapping[str, Any]) -> bool:
    try:
        body = copy.deepcopy(dict(manifest))
        supplied = str(body.pop("manifest_digest", ""))
        if not supplied or supplied != digest(body):
            return False
        if body.get("manifest_version") != FORWARD_MANIFEST_VERSION:
            return False
        if body.get("cohort_contract_version") != FORWARD_COHORT_VERSION:
            return False
        _sha(body.get("accepted_code_head"), name="accepted_code_head")
        start = _utc(body.get("earliest_start_utc"), name="earliest_start_utc")
        if start < _utc(EARLIEST_FORMAL_START_UTC, name="architecture_floor"):
            return False
        components = body.get("components")
        if not isinstance(components, Mapping):
            return False
        build_frozen_version_manifest(
            accepted_code_head=str(body["accepted_code_head"]),
            earliest_start_utc=start,
            components=components,
        )
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
            and int(body.get("minimum_day54_episode_independent_n")) == 300
        )
    except (KeyError, TypeError, ValueError):
        return False


def cohort_id_for_manifest(manifest: Mapping[str, Any]) -> str:
    if not verify_frozen_version_manifest(manifest):
        raise ForwardEvaluationError("A valid frozen version manifest is required.")
    return f"aidy_fwd_{str(manifest['manifest_digest'])[:32]}"


def build_forward_evaluation_record(
    *,
    cohort: Mapping[str, Any],
    cycle_id: str,
    instruction_type: str,
    evaluated_at_utc: datetime | str,
    context_hash: str,
    disposition: str,
    data_quality_state: str,
    data_quality_reason_code: str | None,
    episode_id: str,
    decision_id: str | None,
    ex_ante_digest: str | None,
    self_consistency: Mapping[str, Any] | None,
    retrieval_effective_n: int,
    gc_shadow: Mapping[str, Any] | None,
    gc_feed_health: Mapping[str, Any] | None,
    macro_surprise: Mapping[str, Any] | None,
    selective_shadow: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if cohort.get("state") != "active":
        raise ForwardEvaluationError("Formal forward evaluation requires an active cohort.")
    cohort_id = _nonempty(cohort.get("cohort_id"), name="cohort_id")
    manifest_digest = _nonempty(cohort.get("manifest_digest"), name="manifest_digest")
    activated = _utc(cohort.get("activated_at_utc"), name="activated_at_utc")
    earliest = _utc(cohort.get("earliest_start_utc"), name="earliest_start_utc")
    evaluated = _utc(evaluated_at_utc, name="evaluated_at_utc")
    if evaluated < earliest or evaluated < activated:
        raise ForwardEvaluationError("Evaluation predates the active formal-forward window.")
    if disposition not in FORWARD_DISPOSITIONS:
        raise ForwardEvaluationError("Unsupported formal-forward disposition.")
    if data_quality_state not in DATA_QUALITY_STATES:
        raise ForwardEvaluationError("Unsupported data_quality_state.")
    if disposition == "no_trade" and data_quality_state != "known_good":
        raise ForwardEvaluationError(
            "A genuine no_trade must be distinct from data-quality failure/unknown state."
        )
    if data_quality_state == "failure" and disposition == "no_trade":
        raise ForwardEvaluationError("Data-quality failure cannot be recorded as no_trade.")
    if data_quality_state == "failure" and not data_quality_reason_code:
        raise ForwardEvaluationError("Data-quality failure requires a reason code.")
    if isinstance(retrieval_effective_n, bool) or not isinstance(retrieval_effective_n, int):
        raise TypeError("retrieval_effective_n must be an integer.")
    if retrieval_effective_n < 0:
        raise ForwardEvaluationError("retrieval_effective_n cannot be negative.")

    cycle = _nonempty(cycle_id, name="cycle_id")
    instruction = _nonempty(instruction_type, name="instruction_type")
    episode = _nonempty(episode_id, name="episode_id")
    context = _nonempty(context_hash, name="context_hash", maximum=64)
    if len(context) != 64:
        raise ForwardEvaluationError("context_hash must be a sha256 digest.")

    disagreement: dict[str, Any]
    sc_digest: str | None = None
    if self_consistency is None:
        disagreement = {"state": "not_run", "reason_code": disposition}
    else:
        if not isinstance(self_consistency, Mapping):
            raise TypeError("self_consistency must be a mapping or null.")
        sc_digest = _nonempty(
            self_consistency.get("self_consistency_digest"),
            name="self_consistency_digest",
            maximum=128,
        )
        raw_disagreement = self_consistency.get("disagreement")
        if not isinstance(raw_disagreement, Mapping):
            raise ForwardEvaluationError("Self-consistency result is missing disagreement metrics.")
        disagreement = copy.deepcopy(dict(raw_disagreement))

    if disposition in {"no_trade", "decision_admitted", "management_admitted"} and sc_digest is None:
        raise ForwardEvaluationError("Model-resolved dispositions require k=3 disagreement evidence.")

    gc = _snapshot(gc_shadow, kind="gc_shadow")
    gc_health = _snapshot(gc_feed_health, kind="gc_feed_health")
    macro = _snapshot(macro_surprise, kind="macro_surprise")
    selective = _snapshot(selective_shadow, kind="selective_shadow")
    if selective.get("master_trader_block_allowed") is True:
        raise ForwardEvaluationError("Day 45 selective output cannot gate Master Trader.")
    if selective.get("publication_block_allowed") is True:
        raise ForwardEvaluationError("Day 45 selective output cannot gate publication.")

    record: dict[str, Any] = {
        "record_version": FORWARD_EVALUATION_VERSION,
        "cohort_id": cohort_id,
        "cohort_manifest_digest": manifest_digest,
        "cycle_id": cycle,
        "instruction_type": instruction,
        "source_state": FORWARD_SOURCE_STATE,
        "evaluated_at_utc": evaluated.isoformat(),
        "context_hash": context,
        "disposition": disposition,
        "data_quality_state": data_quality_state,
        "data_quality_reason_code": data_quality_reason_code,
        "episode_id": episode,
        "decision_id": decision_id,
        "ex_ante_digest": ex_ante_digest,
        "self_consistency_digest": sc_digest,
        "disagreement": disagreement,
        "disagreement_digest": digest(disagreement),
        "retrieval_effective_n": retrieval_effective_n,
        "gc_shadow": gc,
        "gc_shadow_digest": digest(gc),
        "gc_feed_health": gc_health,
        "gc_feed_health_digest": digest(gc_health),
        "macro_surprise": macro,
        "macro_surprise_digest": digest(macro),
        "selective_shadow": selective,
        "selective_shadow_digest": digest(selective),
        "selective_shadow_can_gate": False,
        "gc_shadow_is_authoritative_decision_input": False,
        "outcome_fields_present": False,
        "forward_outcome_attached": False,
        "formal_forward_eligible": True,
        "broker_or_account_state_used": False,
        "follower_state_used": False,
        "super_signals_used": False,
        "live_money_execution_used": False,
    }
    record_identity = {
        "cohort_id": cohort_id,
        "cycle_id": cycle,
        "context_hash": context,
        "instruction_type": instruction,
    }
    record["record_id"] = f"aidy_fwd_eval_{digest(record_identity)[:32]}"
    record["record_digest"] = digest(record)
    return record


def verify_forward_evaluation_record(
    record: Mapping[str, Any], *, cohort: Mapping[str, Any]
) -> bool:
    try:
        body = copy.deepcopy(dict(record))
        supplied = str(body.pop("record_digest", ""))
        if not supplied or supplied != digest(body):
            return False
        if body.get("record_version") != FORWARD_EVALUATION_VERSION:
            return False
        if body.get("cohort_id") != cohort.get("cohort_id"):
            return False
        if body.get("cohort_manifest_digest") != cohort.get("manifest_digest"):
            return False
        if body.get("source_state") != FORWARD_SOURCE_STATE:
            return False
        if body.get("formal_forward_eligible") is not True:
            return False
        if body.get("outcome_fields_present") is not False:
            return False
        if body.get("forward_outcome_attached") is not False:
            return False
        if body.get("selective_shadow_can_gate") is not False:
            return False
        if body.get("gc_shadow_is_authoritative_decision_input") is not False:
            return False
        for key in (
            "broker_or_account_state_used",
            "follower_state_used",
            "super_signals_used",
            "live_money_execution_used",
        ):
            if body.get(key) is not False:
                return False
        _utc(body["evaluated_at_utc"], name="evaluated_at_utc")
        if body["disposition"] not in FORWARD_DISPOSITIONS:
            return False
        if body["data_quality_state"] not in DATA_QUALITY_STATES:
            return False
        return not (
            body["disposition"] == "no_trade"
            and body["data_quality_state"] != "known_good"
        )
    except (KeyError, TypeError, ValueError):
        return False


def build_forward_outcome_attachment(
    *,
    evaluation_record: Mapping[str, Any],
    outcome_type: str,
    attached_at_utc: datetime | str,
    outcome_payload: Mapping[str, Any],
) -> dict[str, Any]:
    if outcome_type not in OUTCOME_TYPES:
        raise ForwardEvaluationError("Unsupported forward outcome type.")
    evaluated = _utc(evaluation_record.get("evaluated_at_utc"), name="evaluated_at_utc")
    attached = _utc(attached_at_utc, name="attached_at_utc")
    if attached <= evaluated:
        raise ForwardEvaluationError("Forward outcome must be attached after evaluation.")
    disposition = str(evaluation_record.get("disposition") or "")
    if outcome_type == "no_trade_shadow" and disposition != "no_trade":
        raise ForwardEvaluationError("no_trade_shadow can attach only to a no_trade evaluation.")
    if outcome_type == "trade_outcome" and disposition not in {
        "decision_admitted",
        "management_admitted",
    }:
        raise ForwardEvaluationError("trade_outcome requires an actionable formal-forward record.")
    if not isinstance(outcome_payload, Mapping):
        raise TypeError("outcome_payload must be a mapping.")
    payload = copy.deepcopy(dict(outcome_payload))
    attachment: dict[str, Any] = {
        "attachment_version": FORWARD_OUTCOME_VERSION,
        "cohort_id": evaluation_record["cohort_id"],
        "record_id": evaluation_record["record_id"],
        "record_digest": evaluation_record["record_digest"],
        "outcome_type": outcome_type,
        "attached_at_utc": attached.isoformat(),
        "outcome_payload": payload,
        "active_cohort_tuning_allowed": False,
    }
    identity = {
        "record_id": attachment["record_id"],
        "outcome_type": outcome_type,
    }
    attachment["attachment_id"] = f"aidy_fwd_out_{digest(identity)[:32]}"
    attachment["attachment_digest"] = digest(attachment)
    return attachment


class D1ForwardEvaluationStore:
    def __init__(self, database: object) -> None:
        self._db = database

    def _stmt(self, sql: str, *params: object) -> object:
        return self._db.prepare(sql).bind(*params)

    async def _first(self, sql: str, *params: object) -> object:
        return await self._stmt(sql, *params).first()

    async def get_cohort(self, cohort_id: str) -> dict[str, Any] | None:
        row = await self._first(
            "SELECT * FROM aidy_forward_cohorts WHERE cohort_id=? LIMIT 1",
            cohort_id,
        )
        return dict(row) if row is not None else None

    async def prepare_cohort(
        self, manifest: Mapping[str, Any], *, prepared_at_utc: datetime | str
    ) -> dict[str, Any]:
        if not verify_frozen_version_manifest(manifest):
            raise ForwardEvaluationError("Cannot prepare an invalid frozen version manifest.")
        cohort_id = cohort_id_for_manifest(manifest)
        stamp = _utc(prepared_at_utc, name="prepared_at_utc").isoformat()
        start = _utc(manifest["earliest_start_utc"], name="earliest_start_utc").isoformat()
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
            FORWARD_COHORT_VERSION,
            FORWARD_MANIFEST_VERSION,
            text,
            manifest["manifest_digest"],
            manifest["accepted_code_head"],
            start,
            stamp,
        ).run()
        row = await self.get_cohort(cohort_id)
        if row is None:
            raise RuntimeError("Failed to persist Day 53 forward cohort.")
        if (
            str(row.get("manifest_digest")) != str(manifest["manifest_digest"])
            or str(row.get("manifest_json")) != text
        ):
            raise RuntimeError("Frozen forward cohort identity conflict.")
        return row

    async def activate_cohort(
        self, cohort_id: str, *, activated_at_utc: datetime | str
    ) -> dict[str, Any]:
        current = await self.get_cohort(cohort_id)
        if current is None:
            raise KeyError(f"Unknown cohort_id: {cohort_id}")
        if current["state"] == "closed":
            raise ForwardEvaluationError("Closed formal-forward cohorts cannot be reactivated.")
        if current["state"] == "active":
            return current
        activated = _utc(activated_at_utc, name="activated_at_utc")
        earliest = _utc(current["earliest_start_utc"], name="earliest_start_utc")
        if activated < earliest:
            raise ForwardEvaluationError(
                "Formal forward cohort cannot activate before the frozen earliest start."
            )
        await self._stmt(
            """
            UPDATE aidy_forward_cohorts
            SET state='active',activated_at_utc=?
            WHERE cohort_id=? AND state='prepared'
            """,
            activated.isoformat(),
            cohort_id,
        ).run()
        row = await self.get_cohort(cohort_id)
        if row is None or row.get("state") != "active":
            raise RuntimeError("Failed to activate Day 53 formal-forward cohort.")
        return row

    async def close_cohort(
        self,
        cohort_id: str,
        *,
        closed_at_utc: datetime | str,
        reason_code: str,
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        if reason_code not in FREEZE_BREAK_REASON_CODES:
            raise ForwardEvaluationError("Invalid Day 53 freeze-break reason code.")
        if not isinstance(evidence, Mapping) or not evidence:
            raise ForwardEvaluationError("Freeze break requires machine-readable evidence.")
        current = await self.get_cohort(cohort_id)
        if current is None:
            raise KeyError(f"Unknown cohort_id: {cohort_id}")
        if current["state"] == "closed":
            existing_reason = str(current.get("freeze_break_reason_code") or "")
            existing_digest = str(current.get("freeze_break_evidence_digest") or "")
            if existing_reason == reason_code and existing_digest == digest(dict(evidence)):
                return current
            raise ForwardEvaluationError("Closed cohort is immutable.")
        if current["state"] != "active":
            raise ForwardEvaluationError("Only an active cohort can be freeze-broken.")
        stamp = _utc(closed_at_utc, name="closed_at_utc")
        activated = _utc(current["activated_at_utc"], name="activated_at_utc")
        if stamp < activated:
            raise ForwardEvaluationError("Cohort close cannot precede activation.")
        evidence_body = copy.deepcopy(dict(evidence))
        evidence_text = canonical_json(evidence_body)
        evidence_digest = digest(evidence_body)
        await self._stmt(
            """
            UPDATE aidy_forward_cohorts
            SET state='closed',closed_at_utc=?,freeze_break_reason_code=?,
                freeze_break_evidence_json=?,freeze_break_evidence_digest=?
            WHERE cohort_id=? AND state='active'
            """,
            stamp.isoformat(),
            reason_code,
            evidence_text,
            evidence_digest,
            cohort_id,
        ).run()
        row = await self.get_cohort(cohort_id)
        if row is None or row.get("state") != "closed":
            raise RuntimeError("Failed to close formal-forward cohort.")
        return row

    async def record_evaluation(
        self, record: Mapping[str, Any], *, recorded_at_utc: datetime | str
    ) -> dict[str, Any]:
        cohort = await self.get_cohort(str(record.get("cohort_id") or ""))
        if cohort is None:
            raise ForwardEvaluationError("Forward evaluation references an unknown cohort.")
        if not verify_forward_evaluation_record(record, cohort=cohort):
            raise ForwardEvaluationError("Invalid formal-forward evaluation record.")
        if cohort["state"] != "active":
            raise ForwardEvaluationError("Cannot add evidence to a non-active cohort.")
        stamp = _utc(recorded_at_utc, name="recorded_at_utc").isoformat()
        text = canonical_json(record)
        await self._stmt(
            """
            INSERT INTO aidy_forward_evaluations (
                record_id,record_version,record_json,record_digest,cohort_id,cycle_id,
                instruction_type,source_state,evaluated_at_utc,context_hash,disposition,
                data_quality_state,data_quality_reason_code,episode_id,decision_id,
                ex_ante_digest,self_consistency_digest,disagreement_digest,
                retrieval_effective_n,gc_shadow_digest,gc_feed_health_digest,
                macro_surprise_digest,selective_shadow_digest,formal_forward_eligible,
                recorded_at_utc
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(record_id) DO NOTHING
            """,
            record["record_id"],
            FORWARD_EVALUATION_VERSION,
            text,
            record["record_digest"],
            record["cohort_id"],
            record["cycle_id"],
            record["instruction_type"],
            FORWARD_SOURCE_STATE,
            record["evaluated_at_utc"],
            record["context_hash"],
            record["disposition"],
            record["data_quality_state"],
            record["data_quality_reason_code"],
            record["episode_id"],
            record["decision_id"],
            record["ex_ante_digest"],
            record["self_consistency_digest"],
            record["disagreement_digest"],
            record["retrieval_effective_n"],
            record["gc_shadow_digest"],
            record["gc_feed_health_digest"],
            record["macro_surprise_digest"],
            record["selective_shadow_digest"],
            1,
            stamp,
        ).run()
        row = await self._first(
            "SELECT * FROM aidy_forward_evaluations WHERE record_id=? LIMIT 1",
            record["record_id"],
        )
        if row is None:
            raise RuntimeError("Failed to persist formal-forward evaluation.")
        row = dict(row)
        if (
            str(row.get("record_digest")) != str(record["record_digest"])
            or str(row.get("record_json")) != text
        ):
            raise RuntimeError("Immutable formal-forward evaluation conflict.")
        return row

    async def attach_outcome(
        self, attachment: Mapping[str, Any], *, recorded_at_utc: datetime | str
    ) -> dict[str, Any]:
        record_row = await self._first(
            "SELECT * FROM aidy_forward_evaluations WHERE record_id=? LIMIT 1",
            attachment.get("record_id"),
        )
        if record_row is None:
            raise ForwardEvaluationError("Outcome references an unknown forward evaluation.")
        record = json.loads(str(dict(record_row)["record_json"]))
        expected = build_forward_outcome_attachment(
            evaluation_record=record,
            outcome_type=str(attachment.get("outcome_type") or ""),
            attached_at_utc=str(attachment.get("attached_at_utc") or ""),
            outcome_payload=attachment.get("outcome_payload")
            if isinstance(attachment.get("outcome_payload"), Mapping)
            else {},
        )
        if canonical_json(expected) != canonical_json(attachment):
            raise ForwardEvaluationError("Invalid or mutated forward outcome attachment.")
        stamp = _utc(recorded_at_utc, name="recorded_at_utc").isoformat()
        text = canonical_json(attachment)
        await self._stmt(
            """
            INSERT INTO aidy_forward_outcomes (
                attachment_id,attachment_version,attachment_json,attachment_digest,
                cohort_id,record_id,outcome_type,attached_at_utc,recorded_at_utc
            ) VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(attachment_id) DO NOTHING
            """,
            attachment["attachment_id"],
            FORWARD_OUTCOME_VERSION,
            text,
            attachment["attachment_digest"],
            attachment["cohort_id"],
            attachment["record_id"],
            attachment["outcome_type"],
            attachment["attached_at_utc"],
            stamp,
        ).run()
        row = await self._first(
            "SELECT * FROM aidy_forward_outcomes WHERE attachment_id=? LIMIT 1",
            attachment["attachment_id"],
        )
        if row is None:
            raise RuntimeError("Failed to persist forward outcome attachment.")
        row = dict(row)
        if (
            str(row.get("attachment_digest")) != str(attachment["attachment_digest"])
            or str(row.get("attachment_json")) != text
        ):
            raise RuntimeError("Immutable forward outcome attachment conflict.")
        return row

    async def cohort_progress(self, cohort_id: str) -> dict[str, Any]:
        cohort = await self.get_cohort(cohort_id)
        if cohort is None:
            raise KeyError(f"Unknown cohort_id: {cohort_id}")
        row = await self._first(
            """
            SELECT
                COUNT(*) AS raw_evaluation_count,
                COUNT(DISTINCT episode_id) AS episode_independent_n,
                SUM(CASE WHEN disposition='no_trade' THEN 1 ELSE 0 END) AS raw_no_trade_count,
                SUM(CASE WHEN data_quality_state='failure' THEN 1 ELSE 0 END) AS data_quality_failure_count
            FROM aidy_forward_evaluations
            WHERE cohort_id=? AND formal_forward_eligible=1
            """,
            cohort_id,
        )
        values = dict(row) if row is not None else {}
        raw_n = int(values.get("raw_evaluation_count") or 0)
        effective_n = int(values.get("episode_independent_n") or 0)
        result: dict[str, Any] = {
            "store_version": FORWARD_STORE_VERSION,
            "cohort_id": cohort_id,
            "cohort_state": cohort["state"],
            "raw_evaluation_count": raw_n,
            "episode_independent_n": effective_n,
            "raw_no_trade_count": int(values.get("raw_no_trade_count") or 0),
            "data_quality_failure_count": int(values.get("data_quality_failure_count") or 0),
            "day54_minimum_episode_independent_n": 300,
            "day54_sample_gate_met": effective_n >= 300,
            "raw_count_can_substitute_for_effective_n": False,
            "tuning_on_forward_outcomes_allowed": False,
        }
        result["progress_digest"] = digest(result)
        return result


def day53_manifest() -> dict[str, Any]:
    result: dict[str, Any] = {
        "manifest_version": "aidy_day53_formal_forward_manifest_v1",
        "cohort_version": FORWARD_COHORT_VERSION,
        "frozen_version_manifest": FORWARD_MANIFEST_VERSION,
        "evaluation_version": FORWARD_EVALUATION_VERSION,
        "outcome_attachment_version": FORWARD_OUTCOME_VERSION,
        "store_version": FORWARD_STORE_VERSION,
        "earliest_formal_start_utc": EARLIEST_FORMAL_START_UTC,
        "formal_forward_source_state": FORWARD_SOURCE_STATE,
        "pre_day53_backfill_allowed": False,
        "all_evaluations_including_no_trade_ledgered": True,
        "data_quality_failure_distinct_from_no_trade": True,
        "j17_disagreement_logged": True,
        "j20_raw_and_episode_independent_n_logged": True,
        "gc_shadow_and_feed_health_logged": True,
        "macro_consensus_surprise_logged_forward_only": True,
        "selective_layer_remains_shadow_only": True,
        "freeze_break_reason_codes": sorted(FREEZE_BREAK_REASON_CODES),
        "performance_improvement_freeze_break_allowed": False,
        "closed_cohort_mutation_allowed": False,
        "affected_acceptance_rerun_required_before_replacement_evidence": True,
        "day54_sample_gate_episode_independent_n": 300,
        "broker_or_account_state_allowed": False,
        "follower_state_allowed": False,
        "super_signals_dependency_allowed": False,
        "live_money_execution_allowed": False,
    }
    result["manifest_digest"] = digest(result)
    return result
