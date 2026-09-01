from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aidy.replay_evaluation import HOLDOUT_ACCESS_VERSION, digest as replay_digest
from aidy.research_integrity import finalize_trial, preregister_trial, verify_trial_registry
from aidy.strategy_promotion import (
    REQUIRED_COMPONENTS,
    apply_registry_event,
    build_multiple_testing_control,
    build_promotion_event,
    build_promotion_policy,
    build_registry_snapshot,
    build_rollback_event,
    build_rollback_record,
    build_strategy_version,
    canonical_json,
    digest,
    evaluate_promotion,
    promotion_manifest,
    verify_multiple_testing_control,
    verify_promotion_decision,
    verify_registry_snapshot,
    verify_rollback_record,
    verify_strategy_version,
)

BASE_SHA = "a1d0306d23406962fab1b10aa5e18ce8df73bdb2"
EXPERIMENT_PREFIX = "day39-controlled-promotion-20260901-v1"
DEFAULT_PROJECT = "aidy-signals"
DEFAULT_DATASET = "aidy_analytics_test"
DEFAULT_LOCATION = "EU"

VERSION_TABLE = "research_day39_strategy_versions"
TRIAL_TABLE = "research_day39_trial_registry"
EVENT_TABLE = "research_day39_registry_events"
SUMMARY_TABLE = "research_day39_promotion_summary"

NOW = datetime(2026, 9, 1, 6, 0, tzinfo=UTC)
DATASET_VERSION = "day39-architecture-fixture-dataset-v1"
EVALUATION_IDENTITY = "day39-architecture-fixture-holdout-evaluation-v1"
HOLDOUT_IDENTITY = "day39-architecture-fixture-holdout-v1"


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="day39_artifacts")
    parser.add_argument(
        "--project", default=os.environ.get("AIDY_GCP_PROJECT_ID", DEFAULT_PROJECT)
    )
    parser.add_argument(
        "--dataset", default=os.environ.get("AIDY_BIGQUERY_DATASET", DEFAULT_DATASET)
    )
    parser.add_argument(
        "--location", default=os.environ.get("AIDY_BIGQUERY_LOCATION", DEFAULT_LOCATION)
    )
    parser.add_argument("--bigquery", action="store_true")
    return parser.parse_args()


def _components(prefix: str) -> dict[str, str]:
    return {name: f"{prefix}-{name}-v1" for name in REQUIRED_COMPONENTS}


def _policy() -> dict[str, Any]:
    return build_promotion_policy(
        metric_criteria=[
            {
                "metric": "judgement_score",
                "direction": "higher",
                "minimum_delta": "0.02",
            },
            {
                "metric": "risk_coverage_quality",
                "direction": "higher",
                "minimum_delta": "0.02",
            },
            {
                "metric": "decision_stability",
                "direction": "higher",
                "minimum_delta": "0.01",
            },
        ],
        safety_criteria=[
            {
                "metric": "safety_violation_rate",
                "direction": "lower",
                "minimum_delta": 0,
            },
            {
                "metric": "grounding_failure_rate",
                "direction": "lower",
                "minimum_delta": 0,
            },
        ],
        minimum_improved_metrics=2,
        dsr_min_probability="0.95",
    )


def _holdout_access(trial: dict[str, Any], challenger_digest: str) -> dict[str, Any]:
    record: dict[str, Any] = {
        "access_version": HOLDOUT_ACCESS_VERSION,
        "trial_identity": trial["trial_identity"],
        "trial_digest": trial["trial_digest"],
        "dataset_manifest_digest": "d" * 64,
        "split_digest": "s" * 64,
        "holdout_identity": HOLDOUT_IDENTITY,
        "frozen_version_digest": challenger_digest,
        "accessed_at": (NOW + timedelta(hours=1)).isoformat(),
        "accessed_case_ids": ["fixture-holdout-001", "fixture-holdout-002"],
        "accessed_case_count": 2,
        "score_digest": "c" * 64,
        "purpose": "score_frozen_version",
        "tuning_allowed_after_access": False,
        "same_holdout_reusable_for_tuning": False,
        "silent_promotion_allowed": False,
        "new_trial_required_for_changes": True,
    }
    record["access_digest"] = replay_digest(record)
    return record


def build_artifacts(head_sha: str) -> dict[str, Any]:
    manifest = promotion_manifest()
    champion = build_strategy_version(
        version_id="day39-fixture-champion-v1",
        registered_at=NOW,
        code_head=head_sha,
        components=_components("champion"),
        config={
            "fixture": "champion",
            "risk_authority": False,
            "live_strategy": False,
        },
        change_hypothesis="Fixture champion is the immutable baseline.",
    )
    challenger = build_strategy_version(
        version_id="day39-fixture-challenger-v2",
        registered_at=NOW + timedelta(minutes=1),
        code_head=head_sha,
        components=_components("challenger"),
        config={
            "fixture": "challenger",
            "risk_authority": False,
            "live_strategy": False,
        },
        change_hypothesis=(
            "Fixture challenger should improve multiple pre-specified judgement "
            "metrics without safety degradation."
        ),
        parent_version_digest=champion["version_digest"],
    )
    if not verify_strategy_version(champion) or not verify_strategy_version(challenger):
        raise RuntimeError("Day 39 fixture strategy version verification failed.")

    policy = _policy()
    trials: list[dict[str, Any]] = []
    terminal_states = ("null", "insufficient", "failed", "passed")
    for number, state in enumerate(terminal_states, start=1):
        final = number == len(terminal_states)
        holdout = HOLDOUT_IDENTITY if final else f"day39-fixture-holdout-{number}"
        frozen: dict[str, Any] = {"architecture_fixture_attempt": number}
        if final:
            frozen = {
                "champion_version_digest": champion["version_digest"],
                "challenger_version_digest": challenger["version_digest"],
                "promotion_policy_digest": policy["policy_digest"],
                "declared_trial_count": len(terminal_states),
                "architecture_fixture_only": True,
            }
        registered = preregister_trial(
            trials,
            trial_number=number,
            hypothesis=f"Day 39 architecture fixture attempt {number} improves broad metrics.",
            null_hypothesis=f"Day 39 architecture fixture attempt {number} does not improve them.",
            dataset_version=DATASET_VERSION,
            feature_context_version="aidy_market_context_v7_volatility_state",
            frozen_parameters=frozen,
            chronological_split={
                "train": "chronological_pre_holdout",
                "holdout": holdout,
            },
            purge="240m",
            embargo="240m",
            evaluation_identity=(
                EVALUATION_IDENTITY if final else f"day39-fixture-evaluation-{number}"
            ),
            holdout_identity=holdout,
            preregistered_at=NOW + timedelta(minutes=number),
            code_head=head_sha,
            evidence_digest=manifest["manifest_digest"],
            purpose="evaluation",
        )
        trials.append(
            finalize_trial(
                registered,
                executed_at=NOW + timedelta(minutes=number, seconds=30),
                result_state=state,
                result={
                    "architecture_fixture_attempt": number,
                    "state": state,
                    "real_strategy_result": False,
                },
            )
        )
    verify_trial_registry(trials)

    multiple_testing = build_multiple_testing_control(
        trials,
        sharpe_statistics={
            "observed_sharpe": "2.0",
            "observation_count": 300,
            "variance_across_trials": "0.01",
            "skewness": "0",
            "kurtosis": "3",
        },
    )
    if not verify_multiple_testing_control(multiple_testing):
        raise RuntimeError("Day 39 multiple-testing fixture verification failed.")

    holdout_access = _holdout_access(trials[-1], challenger["version_digest"])
    decision = evaluate_promotion(
        champion_version=champion,
        challenger_version=challenger,
        policy=policy,
        trial_registry=trials,
        challenger_trial_identity=trials[-1]["trial_identity"],
        champion_metrics={
            "judgement_score": "0.70",
            "risk_coverage_quality": "0.60",
            "decision_stability": "0.80",
        },
        challenger_metrics={
            "judgement_score": "0.75",
            "risk_coverage_quality": "0.64",
            "decision_stability": "0.81",
        },
        champion_safety={
            "safety_violation_rate": "0.01",
            "grounding_failure_rate": "0.02",
        },
        challenger_safety={
            "safety_violation_rate": "0.01",
            "grounding_failure_rate": "0.01",
        },
        multiple_testing_control=multiple_testing,
        holdout_access_record=holdout_access,
        evaluation_identity=EVALUATION_IDENTITY,
        holdout_identity=HOLDOUT_IDENTITY,
        evaluated_at=NOW + timedelta(hours=2),
    )
    if not verify_promotion_decision(decision) or decision["status"] != "promote":
        raise RuntimeError("Positive promotion path fixture did not pass.")

    registry = build_registry_snapshot(
        versions=[champion, challenger],
        active_champion_digest=champion["version_digest"],
    )
    promotion_event = build_promotion_event(
        registry=registry,
        decision=decision,
        approved_by="day39-architecture-fixture-owner",
        approved_at=NOW + timedelta(hours=3),
    )
    promoted_registry = apply_registry_event(registry, promotion_event)
    if promoted_registry["active_champion_digest"] != challenger["version_digest"]:
        raise RuntimeError("Fixture promotion did not move the active pointer.")

    rollback = build_rollback_record(
        registry=promoted_registry,
        rollback_to_version_digest=champion["version_digest"],
        trigger="safety_regression",
        evidence_digest="r" * 64,
        approved_by="day39-architecture-fixture-owner",
        approved_at=NOW + timedelta(hours=4),
    )
    if not verify_rollback_record(rollback):
        raise RuntimeError("Day 39 rollback fixture verification failed.")
    rollback_event = build_rollback_event(
        registry=promoted_registry,
        rollback_record=rollback,
    )
    rolled_back_registry = apply_registry_event(promoted_registry, rollback_event)
    if not verify_registry_snapshot(rolled_back_registry):
        raise RuntimeError("Day 39 final registry verification failed.")
    if rolled_back_registry["active_champion_digest"] != champion["version_digest"]:
        raise RuntimeError("Day 39 deterministic rollback did not restore the prior champion.")
    if rolled_back_registry["registered_version_count"] != 2:
        raise RuntimeError("Day 39 rollback mutated immutable strategy versions.")

    summary: dict[str, Any] = {
        "ok": True,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "experiment_id": f"{EXPERIMENT_PREFIX}-{head_sha[:12]}",
        "architecture_fixture_only": True,
        "actual_strategy_promotion_performed": False,
        "promotion_authorized_for_live_strategy": False,
        "fixture_positive_promotion_path_exercised": True,
        "fixture_deterministic_rollback_path_exercised": True,
        "strategy_version_count": 2,
        "trial_count": len(trials),
        "trial_result_states": [row["result_state"] for row in trials],
        "failed_null_insufficient_trials_retained": True,
        "complete_trial_count_used_for_multiple_testing": (
            multiple_testing["trial_count"] == len(trials)
        ),
        "multiple_testing_method": multiple_testing["method"],
        "deflated_sharpe_probability": multiple_testing["deflated_sharpe"][
            "deflated_sharpe_probability"
        ],
        "promotion_fixture_status": decision["status"],
        "promotion_owner_approval_required": decision["owner_approval_still_required"],
        "rollback_trigger": rollback["trigger"],
        "rollback_manual_execution_required": rollback["manual_execution_required"],
        "final_active_version_is_original_champion": True,
        "champion_overwrite_allowed": False,
        "version_deletion_allowed": False,
        "holdout_reuse_for_tuning_allowed": False,
        "autonomous_self_modification_allowed": False,
        "predictive_edge_claimed": False,
        "trading_gate_created": False,
        "broker_side_effects_allowed": False,
        "telegram_side_effects_allowed": False,
        "super_signals_side_effects_allowed": False,
        "promotion_manifest_digest": manifest["manifest_digest"],
        "promotion_policy_digest": policy["policy_digest"],
        "multiple_testing_digest": multiple_testing["multiple_testing_digest"],
        "promotion_decision_digest": decision["decision_digest"],
        "rollback_digest": rollback["rollback_digest"],
        "final_registry_digest": rolled_back_registry["registry_digest"],
        "bigquery_tables": {
            "versions": VERSION_TABLE,
            "trials": TRIAL_TABLE,
            "events": EVENT_TABLE,
            "summary": SUMMARY_TABLE,
        },
    }
    summary["summary_digest"] = digest(summary)
    return {
        "manifest": manifest,
        "versions": [champion, challenger],
        "trials": trials,
        "policy": policy,
        "multiple_testing": multiple_testing,
        "holdout_access": holdout_access,
        "promotion_decision": decision,
        "promotion_event": promotion_event,
        "rollback": rollback,
        "rollback_event": rollback_event,
        "final_registry": rolled_back_registry,
        "summary": summary,
    }


def _query_config(bigquery: Any, pairs: list[tuple[str, str, Any]]) -> Any:
    return bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(name, kind, value)
            for name, kind, value in pairs
        ]
    )


def _ensure_table(
    client: Any,
    bigquery: Any,
    not_found: type[Exception],
    table_id: str,
    schema: list[Any],
) -> None:
    try:
        table = client.get_table(table_id)
    except not_found:
        client.create_table(bigquery.Table(table_id, schema=schema))
        return
    actual = [(field.name, field.field_type, field.mode) for field in table.schema]
    expected = [(field.name, field.field_type, field.mode) for field in schema]
    if actual != expected:
        raise RuntimeError(f"BigQuery schema drift for {table_id}.")


def _persist_payload_rows(
    client: Any,
    bigquery: Any,
    not_found: type[Exception],
    *,
    table_id: str,
    experiment_id: str,
    rows: list[dict[str, Any]],
) -> None:
    schema = [
        bigquery.SchemaField("experiment_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("record_type", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("record_identity", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("payload_digest", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("payload", "JSON", mode="REQUIRED"),
        bigquery.SchemaField("recorded_at_utc", "TIMESTAMP", mode="REQUIRED"),
    ]
    _ensure_table(client, bigquery, not_found, table_id, schema)
    config = _query_config(bigquery, [("experiment", "STRING", experiment_id)])
    existing = {
        str(row["record_identity"]): str(row["payload_digest"])
        for row in client.query(
            f"""SELECT record_identity,payload_digest
                FROM `{table_id}` WHERE experiment_id=@experiment""",
            job_config=config,
        ).result()
    }
    for row in rows:
        identity = str(row["record_identity"])
        if identity in existing and existing[identity] != row["payload_digest"]:
            raise RuntimeError(f"Immutable Day 39 payload conflict: {identity}.")
    missing = [row for row in rows if str(row["record_identity"]) not in existing]
    if missing:
        errors = client.insert_rows_json(table_id, missing)
        if errors:
            raise RuntimeError(f"Day 39 BigQuery insert failed for {table_id}: {errors}")


def _persist_summary(
    client: Any,
    bigquery: Any,
    not_found: type[Exception],
    *,
    table_id: str,
    summary: dict[str, Any],
) -> None:
    schema = [
        bigquery.SchemaField("experiment_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("base_sha", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("head_sha", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("payload_digest", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("summary_payload", "JSON", mode="REQUIRED"),
        bigquery.SchemaField("recorded_at_utc", "TIMESTAMP", mode="REQUIRED"),
    ]
    _ensure_table(client, bigquery, not_found, table_id, schema)
    config = _query_config(bigquery, [("experiment", "STRING", summary["experiment_id"])])
    existing = list(
        client.query(
            f"""SELECT payload_digest,summary_payload
                FROM `{table_id}` WHERE experiment_id=@experiment""",
            job_config=config,
        ).result()
    )
    if len(existing) > 1:
        raise RuntimeError("Day 39 immutable summary is duplicated.")
    if existing:
        if str(existing[0]["payload_digest"]) != summary["summary_digest"]:
            raise RuntimeError("Day 39 immutable summary digest conflict.")
        stored = existing[0]["summary_payload"]
        if isinstance(stored, str):
            stored = json.loads(stored)
        if canonical_json(stored) != canonical_json(summary):
            raise RuntimeError("Day 39 immutable summary payload conflict.")
        return
    errors = client.insert_rows_json(
        table_id,
        [
            {
                "experiment_id": summary["experiment_id"],
                "base_sha": summary["base_sha"],
                "head_sha": summary["head_sha"],
                "payload_digest": summary["summary_digest"],
                "summary_payload": canonical_json(summary),
                "recorded_at_utc": datetime.now(UTC).isoformat(),
            }
        ],
    )
    if errors:
        raise RuntimeError(f"Day 39 BigQuery summary insert failed: {errors}")


def persist_bigquery(
    artifacts: dict[str, Any],
    *,
    project: str,
    dataset: str,
    location: str,
) -> None:
    secret = os.environ.get("AIDY_GCP_SERVICE_ACCOUNT_JSON")
    if not secret:
        raise SystemExit("AIDY_GCP_SERVICE_ACCOUNT_JSON is required for --bigquery.")

    from google.api_core.exceptions import NotFound
    from google.cloud import bigquery
    from google.oauth2 import service_account

    credentials = service_account.Credentials.from_service_account_info(json.loads(secret))
    client = bigquery.Client(project=project, credentials=credentials, location=location)
    experiment_id = artifacts["summary"]["experiment_id"]
    recorded_at = datetime.now(UTC).isoformat()

    def rows(
        values: list[dict[str, Any]],
        *,
        record_type: str,
        identity_field: str,
        digest_field: str,
    ) -> list[dict[str, Any]]:
        return [
            {
                "experiment_id": experiment_id,
                "record_type": record_type,
                "record_identity": str(value[identity_field]),
                "payload_digest": str(value[digest_field]),
                "payload": canonical_json(value),
                "recorded_at_utc": recorded_at,
            }
            for value in values
        ]

    _persist_payload_rows(
        client,
        bigquery,
        NotFound,
        table_id=f"{project}.{dataset}.{VERSION_TABLE}",
        experiment_id=experiment_id,
        rows=rows(
            artifacts["versions"],
            record_type="strategy_version",
            identity_field="version_id",
            digest_field="version_digest",
        ),
    )
    _persist_payload_rows(
        client,
        bigquery,
        NotFound,
        table_id=f"{project}.{dataset}.{TRIAL_TABLE}",
        experiment_id=experiment_id,
        rows=rows(
            artifacts["trials"],
            record_type="trial",
            identity_field="trial_identity",
            digest_field="trial_digest",
        ),
    )
    events = [artifacts["promotion_event"], artifacts["rollback_event"]]
    event_rows = []
    for value in events:
        event_rows.append(
            {
                "experiment_id": experiment_id,
                "record_type": str(value["event_type"]),
                "record_identity": f"event-{int(value['event_number']):06d}",
                "payload_digest": str(value["event_digest"]),
                "payload": canonical_json(value),
                "recorded_at_utc": recorded_at,
            }
        )
    _persist_payload_rows(
        client,
        bigquery,
        NotFound,
        table_id=f"{project}.{dataset}.{EVENT_TABLE}",
        experiment_id=experiment_id,
        rows=event_rows,
    )
    _persist_summary(
        client,
        bigquery,
        NotFound,
        table_id=f"{project}.{dataset}.{SUMMARY_TABLE}",
        summary=artifacts["summary"],
    )


def _write(output: Path, name: str, value: object) -> None:
    (output / name).write_text(canonical_json(value) + "\n", encoding="utf-8")


def main() -> int:
    args = _args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    artifacts = build_artifacts(head_sha)

    _write(output, "promotion_manifest.json", artifacts["manifest"])
    _write(output, "trial_registry.json", artifacts["trials"])
    _write(output, "promotion_fixture.json", artifacts["promotion_decision"])
    _write(output, "rollback_fixture.json", artifacts["rollback"])
    _write(output, "summary.json", artifacts["summary"])

    if args.bigquery:
        persist_bigquery(
            artifacts,
            project=args.project,
            dataset=args.dataset,
            location=args.location,
        )
    print(canonical_json(artifacts["summary"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
