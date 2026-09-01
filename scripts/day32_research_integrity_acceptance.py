from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aidy.research_integrity import (
    ATTESTATION_MANIFEST_VERSION,
    LEAK_AUDIT_VERSION,
    TRIAL_REGISTRY_VERSION,
    audit_decision_eligibility,
    build_field_attestation_manifest,
    build_leak_finding,
    canonical_json,
    digest,
    finalize_trial,
    preregister_trial,
    verify_field_attestation_manifest,
    verify_trial_registry,
)

BASE_SHA = "f39a6f957f458cbb0dbbe569775de15fc511c556"
DEFAULT_PROJECT = "aidy-signals"
DEFAULT_DATASET = "aidy_analytics_test"
DEFAULT_LOCATION = "EU"
ATTESTATION_TABLE = "research_day32_field_attestations"
LEAK_TABLE = "research_day32_leak_audit"
TRIAL_TABLE = "research_day32_trial_registry"
SUMMARY_TABLE = "research_day32_summary"

ACTIVE_DECISION_ROOTS = {
    "aidy_signal_lifecycle",
    "as_of_utc",
    "broker_follower_state_included",
    "context_hash_algorithm",
    "context_packet_version",
    "cross_market",
    "data_quality",
    "event_risk",
    "gold",
    "objective_only",
    "provenance",
    "retrospective_history_included",
    "session",
    "source_contract_versions",
    "symbol",
}
STAGED_CONTEXT_ROOTS = {
    "cme_contract_context",
    "event_intelligence",
    "legacy_event_risk_superseded_by",
    "price_structure_context",
    "rates_macro_context",
    "structural_context",
    "volatility_state",
}
ACTIVE_ROOTS = ACTIVE_DECISION_ROOTS | STAGED_CONTEXT_ROOTS


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="day32_artifacts")
    parser.add_argument(
        "--project",
        default=os.environ.get("AIDY_GCP_PROJECT_ID", DEFAULT_PROJECT),
    )
    parser.add_argument(
        "--dataset",
        default=os.environ.get("AIDY_BIGQUERY_DATASET", DEFAULT_DATASET),
    )
    parser.add_argument(
        "--location",
        default=os.environ.get("AIDY_BIGQUERY_LOCATION", DEFAULT_LOCATION),
    )
    parser.add_argument("--as-of", default="2026-08-23T15:00:00+00:00")
    parser.add_argument("--bigquery", action="store_true")
    return parser.parse_args()


def _packet(now: datetime) -> dict[str, Any]:
    packet: dict[str, Any] = {
        "context_packet_version": "aidy_market_context_v7_volatility_state",
        "context_hash_algorithm": "sha256_canonical_json",
        "as_of_utc": now.isoformat(),
        "symbol": "XAUUSD",
        "objective_only": True,
        "retrospective_history_included": False,
        "broker_follower_state_included": False,
        "source_contract_versions": {
            "pit_query": "aidy_pit_query_v1",
            "gold_features": "aidy_gold_features_v1",
            "macro_event_window": "aidy_macro_event_window_v1",
            "cross_market_query": "aidy_cross_market_query_v1",
            "market_structure": "aidy_market_structure_v2",
            "price_structure": "aidy_price_structure_v2",
            "rates_decomposition": "aidy_rates_decomposition_v1",
            "macro_revision_intelligence": "aidy_macro_revision_intelligence_v1",
            "macro_event_intelligence": "aidy_macro_event_intelligence_v1",
            "cme_contract_intelligence": "aidy_cme_contract_intelligence_v1",
            "volatility_intelligence": "aidy_gold_volatility_intelligence_v1",
        },
        "gold": {
            "quote_context": {"mid": "3371.20", "state": "complete"},
            "atr": None,
        },
        "session": {
            "computed_session_code": "weekend_closed",
            "session_code_consistent": True,
        },
        "event_risk": {"state": "known", "events_in_window": []},
        "cross_market": {"state": "partial", "series": {}},
        "aidy_signal_lifecycle": {"state": "flat"},
        "data_quality": {"state": "partial", "unknown_is_not_absent": True},
        "provenance": {
            "gold_source_links": ["gold_api"],
            "context_hash_coverage": "complete",
        },
        "structural_context": {"market_structure_epoch": "post_2026_07_24_1oz"},
        "price_structure_context": {"state": "unknown_market_closed"},
        "rates_macro_context": {"pit_reconstructable": True, "state": "partial"},
        "event_intelligence": {
            "state": "known",
            "consensus_state": "unknown",
            "next_scheduled_event_at": (now + timedelta(days=1)).isoformat(),
        },
        "legacy_event_risk_superseded_by": "event_intelligence",
        "cme_contract_context": {
            "state": "known",
            "roll_state": "post_first_notice_active_shifted",
        },
        "volatility_state": {
            "state": "partial",
            "gvz": "27.29",
            "realized_volatility": None,
        },
    }
    if set(packet) != ACTIVE_ROOTS:
        raise RuntimeError("Day 32 context V7 root inventory drift")
    packet["context_hash"] = digest(packet)
    return packet


def _base_policy(
    *,
    root: str,
    now: datetime,
    source: str,
    provenance_class: str,
    reconstruction_method: str,
    retrospective_eligible: bool,
    historical_backfill_allowed: bool,
    surface_state: str,
    timing_semantics: str = "derived_at_asof",
    observation_timestamp: datetime | None = None,
    publication_timestamp: datetime | None = None,
    first_observed_timestamp: datetime | None = None,
) -> dict[str, Any]:
    observation = observation_timestamp or now
    first_observed = first_observed_timestamp or observation
    return {
        "field_contract": root,
        "contract_version": "accepted_through_context_v7",
        "source": source,
        "evidence_family": root,
        "provenance_class": provenance_class,
        "pit_reconstructable": "true",
        "reconstruction_method": reconstruction_method,
        "reconstruction_version": "day32_v2",
        "retrospective_eligible": retrospective_eligible,
        "historical_backfill_allowed": historical_backfill_allowed,
        "evaluation_eligible": True,
        "decision_input_eligible": True,
        "staleness_rule": "inherit_accepted_source_contract",
        "observation_timestamp": observation.isoformat(),
        "publication_timestamp": (
            None if publication_timestamp is None else publication_timestamp.isoformat()
        ),
        "first_observed_timestamp": first_observed.isoformat(),
        "timing_semantics": timing_semantics,
        "surface_state": surface_state,
        "quality_state": "verified_or_explicit_unknown",
    }


def _policies(now: datetime) -> dict[str, dict[str, Any]]:
    policies: dict[str, dict[str, Any]] = {}
    metadata_roots = {
        "as_of_utc",
        "broker_follower_state_included",
        "context_hash_algorithm",
        "context_packet_version",
        "legacy_event_risk_superseded_by",
        "objective_only",
        "retrospective_history_included",
        "source_contract_versions",
        "symbol",
    }
    for root in metadata_roots:
        policies[f"$.{root}"] = _base_policy(
            root=root,
            now=now,
            source="context_composer_contract",
            provenance_class="deterministic_context_metadata",
            reconstruction_method="canonical_context_rebuild_from_attested_inputs",
            retrospective_eligible=True,
            historical_backfill_allowed=True,
            surface_state=(
                "active_decision_surface"
                if root in ACTIVE_DECISION_ROOTS
                else "accepted_staged_context"
            ),
        )

    deterministic = {
        "session": "accepted_session_clock_rules",
        "structural_context": "accepted_market_structure_rules_and_official_schedule",
    }
    for root, source in deterministic.items():
        policies[f"$.{root}"] = _base_policy(
            root=root,
            now=now,
            source=source,
            provenance_class="deterministic_asof",
            reconstruction_method="recompute_from_versioned_rules_and_asof",
            retrospective_eligible=True,
            historical_backfill_allowed=True,
            surface_state=(
                "active_decision_surface"
                if root in ACTIVE_DECISION_ROOTS
                else "accepted_staged_context"
            ),
        )

    observed_sources = {
        "gold": "immutable_gold_api_first_observed_archive",
        "cross_market": "official_cross_market_first_observed_archive",
        "cme_contract_context": "official_cme_first_observed_archive",
        "volatility_state": "cboe_gvz_first_observed_plus_pit_xau_state",
    }
    for root, source in observed_sources.items():
        policies[f"$.{root}"] = _base_policy(
            root=root,
            now=now,
            source=source,
            provenance_class="pit_observed",
            reconstruction_method="immutable_first_observed_archive_asof_selection",
            retrospective_eligible=True,
            historical_backfill_allowed=False,
            surface_state=(
                "active_decision_surface"
                if root in ACTIVE_DECISION_ROOTS
                else "accepted_staged_context"
            ),
        )

    derived_sources = {
        "aidy_signal_lifecycle": "versioned_aidy_signal_ledger",
        "data_quality": "derived_from_attested_context_inputs",
        "event_risk": "official_macro_asof_window",
        "price_structure_context": "completed_pit_gold_candles_only",
        "provenance": "context_source_lineage",
        "rates_macro_context": "alfred_vintage_conservative_availability",
        "event_intelligence": "official_schedule_and_forward_capture_contract",
    }
    for root, source in derived_sources.items():
        policies[f"$.{root}"] = _base_policy(
            root=root,
            now=now,
            source=source,
            provenance_class="derived_point_in_time",
            reconstruction_method="rebuild_from_versioned_pit_source_contracts",
            retrospective_eligible=True,
            historical_backfill_allowed=root in {"data_quality", "provenance"},
            surface_state=(
                "active_decision_surface"
                if root in ACTIVE_DECISION_ROOTS
                else "accepted_staged_context"
            ),
        )

    policies["$.event_intelligence.next_scheduled_event_at"] = _base_policy(
        root="event_intelligence.schedule",
        now=now,
        source="official_forward_schedule_first_observed",
        provenance_class="pit_observed_forward_schedule",
        reconstruction_method="select_schedule_version_known_by_context_asof",
        retrospective_eligible=True,
        historical_backfill_allowed=False,
        surface_state="accepted_staged_context",
        timing_semantics="knowledge_can_precede_effective",
        observation_timestamp=now + timedelta(days=1),
        publication_timestamp=now - timedelta(hours=3),
        first_observed_timestamp=now - timedelta(hours=2),
    )
    return policies


def _identity_for_path(manifest: Mapping[str, Any], path_prefix: str) -> str:
    matches = [
        row
        for row in manifest["attestations"]
        if str(row["json_path"]) == path_prefix
        or str(row["json_path"]).startswith(path_prefix + ".")
        or str(row["json_path"]).startswith(path_prefix + "[")
    ]
    if not matches:
        raise RuntimeError(f"Day 32 leak fixture path is not attested: {path_prefix}")
    selected = min(matches, key=lambda row: str(row["json_path"]))
    return str(selected["field_identity"])


def build_artifacts(now: datetime, head_sha: str) -> dict[str, Any]:
    packet = _packet(now)
    manifest = build_field_attestation_manifest(packet, policies=_policies(now))
    if not verify_field_attestation_manifest(manifest):
        raise RuntimeError("Day 32 attestation manifest verification failed")

    fixture_paths = {
        "revision_after_decision": "$.rates_macro_context",
        "overwritten_vendor_file": "$.volatility_state",
        "publication_lag": "$.rates_macro_context",
        "missing_historical_release_timestamp": "$.volatility_state.gvz",
        "retrospective_before_first_observation": "$.gold",
        "timezone_date_dst_ambiguity": "$.event_intelligence.next_scheduled_event_at",
        "future_outcome_in_decision": "$.gold",
        "unknown_converted_to_absent": "$.data_quality",
        "context_hash_coverage_gap": "$.provenance.context_hash_coverage",
        "attestation_contract_mismatch": "$.source_contract_versions",
    }
    findings = [
        build_leak_finding(
            field_identity=_identity_for_path(manifest, path),
            category=category,
            detected_at=now,
            evidence={"fixture": category, "blocked": True, "json_path": path},
            resolved=True,
        )
        for category, path in sorted(fixture_paths.items())
    ]
    audit = audit_decision_eligibility(manifest, findings)

    trials: list[dict[str, Any]] = []
    for number, state in enumerate(("null", "insufficient", "failed"), start=1):
        registered = preregister_trial(
            trials,
            trial_number=number,
            hypothesis=f"Day 32 registry fixture {number} has an effect.",
            null_hypothesis=f"Day 32 registry fixture {number} has no effect.",
            dataset_version="day32-bounded-fixture-v2",
            feature_context_version="aidy_market_context_v7_volatility_state",
            frozen_parameters={"fixture": number},
            chronological_split={"train": "before_T", "holdout": f"holdout-{number}"},
            purge="24h",
            embargo="24h",
            evaluation_identity=f"evaluation-{number}",
            holdout_identity=f"holdout-{number}",
            preregistered_at=now + timedelta(seconds=number),
            code_head=head_sha,
            evidence_digest=manifest["manifest_digest"],
            purpose="evaluation",
        )
        trials.append(
            finalize_trial(
                registered,
                executed_at=now + timedelta(seconds=number + 10),
                result_state=state,
                result={"fixture_result": state},
            )
        )
    verify_trial_registry(trials)

    experiment_id = f"day32-integrity-{head_sha[:12]}-{manifest['manifest_digest'][:8]}"
    summary: dict[str, Any] = {
        "ok": True,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "experiment_id": experiment_id,
        "context_v7_root_count": len(ACTIVE_ROOTS),
        "active_decision_root_count": len(ACTIVE_DECISION_ROOTS),
        "accepted_staged_root_count": len(STAGED_CONTEXT_ROOTS),
        "active_field_count": manifest["active_field_count"],
        "active_decision_field_count": manifest["active_decision_field_count"],
        "accepted_staged_field_count": manifest["accepted_staged_field_count"],
        "master_trader_context_version": "aidy_market_context_v1",
        "context_v7_promoted_to_master_trader": False,
        "attestation_manifest_version": ATTESTATION_MANIFEST_VERSION,
        "leak_audit_version": LEAK_AUDIT_VERSION,
        "trial_registry_version": TRIAL_REGISTRY_VERSION,
        "adversarial_leak_fixture_count": len(findings),
        "unresolved_blocking_leaks": audit["unresolved_blocking_count"],
        "decision_input_allowed": audit["decision_input_allowed"],
        "trial_count": len(trials),
        "trial_result_states": [item["result_state"] for item in trials],
        "holdout_reuse_for_tuning_allowed": False,
        "bigquery_write_contract": "insert_only_idempotent_reconciliation",
        "accepted_prior_modules_modified": False,
        "super_signals_modified": False,
        "predictive_edge_claimed": False,
        "trading_gate_created": False,
        "manifest_digest": manifest["manifest_digest"],
        "audit_digest": audit["audit_digest"],
        "trial_registry_digest": digest([item["trial_digest"] for item in trials]),
    }
    summary["summary_digest"] = digest(summary)
    return {"manifest": manifest, "audit": audit, "trials": trials, "summary": summary}


def _write(path: Path, value: object) -> None:
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def _expected_records(
    values: Iterable[tuple[str, Mapping[str, Any]]],
) -> dict[str, dict[str, str]]:
    expected: dict[str, dict[str, str]] = {}
    for identity, record in values:
        if identity in expected:
            raise RuntimeError(f"Day 32 duplicate analytical identity: {identity}")
        expected[identity] = {
            "record_digest": digest(record),
            "record_json": canonical_json(record),
        }
    return expected


def _reconcile_existing_records(
    *,
    existing: Iterable[Mapping[str, Any]],
    expected: Mapping[str, Mapping[str, str]],
) -> bool:
    rows = list(existing)
    identities = [str(row["identity"]) for row in rows]
    if len(identities) != len(set(identities)):
        raise RuntimeError("Day 32 BigQuery contains duplicate immutable identities")
    if not rows:
        return False
    if set(identities) != set(expected):
        raise RuntimeError("Day 32 BigQuery immutable identity set drift")
    for row in rows:
        identity = str(row["identity"])
        wanted = expected[identity]
        if str(row["record_digest"]) != wanted["record_digest"]:
            raise RuntimeError(f"Day 32 immutable digest mismatch for {identity}")
        if str(row["record_json"]) != wanted["record_json"]:
            raise RuntimeError(f"Day 32 immutable payload mismatch for {identity}")
    return True


def _persist_bigquery(
    artifacts: Mapping[str, Any],
    *,
    project: str,
    dataset: str,
    location: str,
) -> dict[str, int]:
    from google.cloud import bigquery
    from google.oauth2 import service_account

    raw = os.environ.get("AIDY_GCP_SERVICE_ACCOUNT_JSON")
    credentials = (
        service_account.Credentials.from_service_account_info(json.loads(raw)) if raw else None
    )
    client = bigquery.Client(project=project, credentials=credentials, location=location)
    experiment_id = artifacts["summary"]["experiment_id"]
    groups = {
        ATTESTATION_TABLE: [
            (row["field_identity"], row) for row in artifacts["manifest"]["attestations"]
        ],
        LEAK_TABLE: [
            (row["field_identity"] + ":" + row["category"], row)
            for row in artifacts["audit"]["findings"]
        ],
        TRIAL_TABLE: [(row["trial_identity"], row) for row in artifacts["trials"]],
        SUMMARY_TABLE: [("summary", artifacts["summary"])],
    }
    schema = [
        bigquery.SchemaField("experiment_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("identity", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("recorded_at_utc", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("record_digest", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("record_json", "STRING", mode="REQUIRED"),
    ]
    counts: dict[str, int] = {}
    for table_name, values in groups.items():
        table_id = f"{project}.{dataset}.{table_name}"
        try:
            table = client.get_table(table_id)
            actual = [(field.name, field.field_type, field.mode) for field in table.schema]
            expected_schema = [(field.name, field.field_type, field.mode) for field in schema]
            if actual != expected_schema:
                raise RuntimeError(f"Day 32 schema drift for {table_id}")
        except Exception as error:
            if error.__class__.__name__ != "NotFound":
                raise
            table = client.create_table(bigquery.Table(table_id, schema=schema))

        expected = _expected_records(values)
        query = client.query(
            (
                f"SELECT identity, record_digest, record_json FROM `{table_id}` "
                "WHERE experiment_id=@experiment_id"
            ),
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("experiment_id", "STRING", experiment_id)
                ]
            ),
        )
        existing = [dict(row.items()) for row in query.result()]
        already_present = _reconcile_existing_records(existing=existing, expected=expected)
        if not already_present:
            recorded_at = datetime.now(UTC).isoformat()
            rows = [
                {
                    "experiment_id": experiment_id,
                    "identity": identity,
                    "recorded_at_utc": recorded_at,
                    **payload,
                }
                for identity, payload in sorted(expected.items())
            ]
            errors = client.insert_rows_json(table, rows)
            if errors:
                raise RuntimeError(f"Day 32 BigQuery insert failed: {errors}")
            verify_query = client.query(
                (
                    f"SELECT identity, record_digest, record_json FROM `{table_id}` "
                    "WHERE experiment_id=@experiment_id"
                ),
                job_config=bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter(
                            "experiment_id", "STRING", experiment_id
                        )
                    ]
                ),
            )
            verified = [dict(row.items()) for row in verify_query.result()]
            if not _reconcile_existing_records(existing=verified, expected=expected):
                raise RuntimeError(f"Day 32 BigQuery reconciliation failed for {table_id}")
        counts[table_name] = len(expected)
    return counts


def main() -> None:
    args = _args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    as_of = datetime.fromisoformat(args.as_of)
    if as_of.tzinfo is None:
        raise RuntimeError("Day 32 --as-of must be timezone-aware")
    artifacts = build_artifacts(as_of.astimezone(UTC), head_sha)
    if args.bigquery:
        artifacts["summary"]["bigquery_rows"] = _persist_bigquery(
            artifacts,
            project=args.project,
            dataset=args.dataset,
            location=args.location,
        )
        artifacts["summary"].pop("summary_digest")
        artifacts["summary"]["summary_digest"] = digest(artifacts["summary"])
    _write(output / "field_attestation_manifest.json", artifacts["manifest"])
    _write(output / "leak_audit.json", artifacts["audit"])
    _write(output / "trial_registry.json", artifacts["trials"])
    _write(output / "summary.json", artifacts["summary"])
    print(canonical_json(artifacts["summary"]))


if __name__ == "__main__":
    main()
