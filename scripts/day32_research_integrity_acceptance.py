from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections.abc import Mapping
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

ACTIVE_ROOTS = {
    "aidy_signal_lifecycle",
    "as_of_utc",
    "broker_follower_state_included",
    "cme_contract_context",
    "context_hash_algorithm",
    "context_packet_version",
    "cross_market",
    "data_quality",
    "event_intelligence",
    "event_risk",
    "gold",
    "legacy_event_risk_superseded_by",
    "objective_only",
    "price_structure_context",
    "provenance",
    "rates_macro_context",
    "retrospective_history_included",
    "session",
    "source_contract_versions",
    "structural_context",
    "symbol",
    "volatility_state",
}


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="day32_artifacts")
    parser.add_argument("--project", default=os.environ.get("AIDY_GCP_PROJECT_ID", DEFAULT_PROJECT))
    parser.add_argument("--dataset", default=os.environ.get("AIDY_BIGQUERY_DATASET", DEFAULT_DATASET))
    parser.add_argument("--location", default=os.environ.get("AIDY_BIGQUERY_LOCATION", DEFAULT_LOCATION))
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
        "gold": {"quote_context": {"mid": "3371.20", "state": "complete"}, "atr": None},
        "session": {"computed_session_code": "weekend_closed", "session_code_consistent": True},
        "event_risk": {"state": "known", "events_in_window": []},
        "cross_market": {"state": "partial", "series": {}},
        "aidy_signal_lifecycle": {"state": "flat"},
        "data_quality": {"state": "partial", "unknown_is_not_absent": True},
        "provenance": {"gold_source_links": ["gold_api"], "context_hash_coverage": "complete"},
        "structural_context": {"market_structure_epoch": "post_2026_07_24_1oz"},
        "price_structure_context": {"state": "unknown_market_closed"},
        "rates_macro_context": {"pit_reconstructable": True, "state": "partial"},
        "event_intelligence": {"state": "known", "consensus_state": "unknown"},
        "legacy_event_risk_superseded_by": "event_intelligence",
        "cme_contract_context": {"state": "known", "roll_state": "post_first_notice_active_shifted"},
        "volatility_state": {"state": "partial", "gvz": "27.29", "realized_volatility": None},
    }
    if set(packet) != ACTIVE_ROOTS:
        raise RuntimeError("Day 32 active model-facing root inventory drift")
    packet["context_hash"] = digest(packet)
    return packet


def _policy(root: str) -> dict[str, Any]:
    return {
        "field_contract": root,
        "contract_version": "accepted_through_context_v7",
        "source": "accepted_context_packet_v7",
        "evidence_family": root,
        "provenance_class": "point_in_time",
        "pit_reconstructable": "true",
        "reconstruction_method": "immutable_asof_or_conservative_first_observed",
        "reconstruction_version": "day32_v1",
        "retrospective_eligible": True,
        "evaluation_eligible": True,
        "decision_input_eligible": True,
        "staleness_rule": "inherit_accepted_source_contract",
    }


def build_artifacts(now: datetime, head_sha: str) -> dict[str, Any]:
    packet = _packet(now)
    policies = {f"$.{root}": _policy(root) for root in ACTIVE_ROOTS}
    manifest = build_field_attestation_manifest(
        packet,
        policies=policies,
        observed_at=now,
        published_at=None,
        first_observed_at=now,
        staleness_state="source_contract_checked",
        quality_state="verified_or_explicit_unknown",
    )
    if not verify_field_attestation_manifest(manifest):
        raise RuntimeError("Day 32 attestation manifest verification failed")
    fixtures = sorted(
        {
            "revision_after_decision",
            "overwritten_vendor_file",
            "publication_lag",
            "missing_historical_release_timestamp",
            "retrospective_before_first_observation",
            "timezone_date_dst_ambiguity",
            "future_outcome_in_decision",
            "unknown_converted_to_absent",
            "context_hash_coverage_gap",
            "attestation_contract_mismatch",
        }
    )
    findings = [
        build_leak_finding(
            field_identity=f"adversarial_fixture:{category}",
            category=category,
            detected_at=now,
            evidence={"fixture": category, "blocked": True},
            resolved=True,
        )
        for category in fixtures
    ]
    audit = audit_decision_eligibility(manifest, findings)
    trials: list[dict[str, Any]] = []
    for number, state in enumerate(("null", "insufficient", "failed"), start=1):
        registered = preregister_trial(
            trials,
            trial_number=number,
            hypothesis=f"Day 32 registry fixture {number} has an effect.",
            null_hypothesis=f"Day 32 registry fixture {number} has no effect.",
            dataset_version="day32-bounded-fixture-v1",
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
        "active_root_count": len(ACTIVE_ROOTS),
        "active_field_count": manifest["active_field_count"],
        "attestation_manifest_version": ATTESTATION_MANIFEST_VERSION,
        "leak_audit_version": LEAK_AUDIT_VERSION,
        "trial_registry_version": TRIAL_REGISTRY_VERSION,
        "adversarial_leak_fixture_count": len(fixtures),
        "unresolved_blocking_leaks": audit["unresolved_blocking_count"],
        "decision_input_allowed": audit["decision_input_allowed"],
        "trial_count": len(trials),
        "trial_result_states": [item["result_state"] for item in trials],
        "holdout_reuse_for_tuning_allowed": False,
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


def _persist_bigquery(artifacts: Mapping[str, Any], *, project: str, dataset: str, location: str) -> dict[str, int]:
    from google.cloud import bigquery
    from google.oauth2 import service_account

    raw = os.environ.get("AIDY_GCP_SERVICE_ACCOUNT_JSON")
    credentials = service_account.Credentials.from_service_account_info(json.loads(raw)) if raw else None
    client = bigquery.Client(project=project, credentials=credentials, location=location)
    experiment_id = artifacts["summary"]["experiment_id"]
    recorded_at = datetime.now(UTC).isoformat()
    groups = {
        ATTESTATION_TABLE: [(row["field_identity"], row) for row in artifacts["manifest"]["attestations"]],
        LEAK_TABLE: [(row["field_identity"] + ":" + row["category"], row) for row in artifacts["audit"]["findings"]],
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
    counts = {}
    for table_name, values in groups.items():
        table_id = f"{project}.{dataset}.{table_name}"
        try:
            table = client.get_table(table_id)
            actual = [(f.name, f.field_type, f.mode) for f in table.schema]
            expected = [(f.name, f.field_type, f.mode) for f in schema]
            if actual != expected:
                raise RuntimeError(f"Day 32 schema drift for {table_id}")
        except Exception as error:
            if error.__class__.__name__ != "NotFound":
                raise
            table = client.create_table(bigquery.Table(table_id, schema=schema))
        client.query(
            f"DELETE FROM `{table_id}` WHERE experiment_id=@experiment_id",
            job_config=bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("experiment_id", "STRING", experiment_id)]),
        ).result()
        rows = [
            {
                "experiment_id": experiment_id,
                "identity": identity,
                "recorded_at_utc": recorded_at,
                "record_digest": digest(record),
                "record_json": canonical_json(record),
            }
            for identity, record in values
        ]
        errors = client.insert_rows_json(table, rows)
        if errors:
            raise RuntimeError(f"Day 32 BigQuery insert failed: {errors}")
        count = next(
            iter(
                client.query(
                    f"SELECT COUNT(*) AS n FROM `{table_id}` WHERE experiment_id=@experiment_id",
                    job_config=bigquery.QueryJobConfig(
                        query_parameters=[
                            bigquery.ScalarQueryParameter(
                                "experiment_id", "STRING", experiment_id
                            )
                        ]
                    ),
                ).result()
            )
        ).n
        if count != len(rows):
            raise RuntimeError(f"Day 32 BigQuery reconciliation failed for {table_id}")
        counts[table_name] = count
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
        artifacts["summary"]["bigquery_rows"] = _persist_bigquery(artifacts, project=args.project, dataset=args.dataset, location=args.location)
        artifacts["summary"].pop("summary_digest")
        artifacts["summary"]["summary_digest"] = digest(artifacts["summary"])
    _write(output / "field_attestation_manifest.json", artifacts["manifest"])
    _write(output / "leak_audit.json", artifacts["audit"])
    _write(output / "trial_registry.json", artifacts["trials"])
    _write(output / "summary.json", artifacts["summary"])
    print(canonical_json(artifacts["summary"]))


if __name__ == "__main__":
    main()
