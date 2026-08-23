from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from day26_acceptance_support import CANDIDATE_COUNT, CANDIDATE_DIGEST, load_candidate_snapshot
from day26_price_structure_acceptance import _bigquery_client

from aidy.day23_research import digest
from aidy.macro_vintages import (
    EVIDENCE_FAMILY,
    REAL_YIELD_DIRECTIONAL_INFLUENCE,
    REAL_YIELD_ROLE,
    SERIES,
    SERIES_CPI,
    AlfredSnapshot,
    alfred_url,
    build_rates_macro_state,
    build_version_history,
    parse_alfred_csv,
    verify_rates_macro_state,
    verify_version_record,
)

BASE_SHA = "794ff67b52944f9a27e805c3b55beb363c199087"
DEFAULT_PROJECT = "aidy-signals"
DEFAULT_DATASET = "aidy_analytics_test"
DEFAULT_LOCATION = "EU"
VINTAGE_START = date(2024, 12, 1)
VINTAGE_END = date(2025, 1, 8)
OBSERVATION_START = date(2024, 10, 1)
OBSERVATION_END = date(2025, 1, 8)
EXPECTED_SNAPSHOT_COUNT = len(SERIES) * ((VINTAGE_END - VINTAGE_START).days + 1)

SNAPSHOT_TABLE = "research_day28_alfred_snapshots"
VERSION_TABLE = "research_day28_macro_versions"
CASE_TABLE = "research_day28_case_rates"
SUMMARY_TABLE = "research_day28_summary"

_ALLOWED_CHANGED_FILES = {
    "docs/day28-pit-vintaged-rates-contract.md",
    "scripts/day28_macro_vintage_acceptance.py",
    "src/aidy/context_packet_v4.py",
    "src/aidy/macro_vintages.py",
    "tests/test_day28_macro_vintages.py",
}


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AIDY Day 28 PIT vintaged rates acceptance")
    parser.add_argument(
        "--project",
        default=(
            os.environ.get("AIDY_GCP_PROJECT_ID")
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
            or os.environ.get("GCLOUD_PROJECT")
            or DEFAULT_PROJECT
        ),
    )
    parser.add_argument("--dataset", default=os.environ.get("AIDY_BIGQUERY_DATASET", DEFAULT_DATASET))
    parser.add_argument("--location", default=os.environ.get("AIDY_BIGQUERY_LOCATION", DEFAULT_LOCATION))
    parser.add_argument("--output-dir", default="day28_artifacts")
    parser.add_argument("--cache-dir", default=".cache/day28")
    return parser.parse_args()


def _changed_files(head_sha: str) -> list[str]:
    merge_base = subprocess.check_output(["git", "merge-base", BASE_SHA, head_sha], text=True).strip()
    if merge_base != BASE_SHA:
        raise RuntimeError("Day 28 branch is not based on accepted Day-27 main.")
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", f"{BASE_SHA}...{head_sha}"], text=True
    ).splitlines()
    unexpected = sorted(set(changed) - _ALLOWED_CHANGED_FILES)
    if unexpected:
        raise RuntimeError(f"Day 28 modified accepted prior files: {unexpected}")
    return sorted(changed)


def _date_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=index) for index in range((end - start).days + 1)]


def _load_snapshots(cache_dir: Path) -> list[AlfredSnapshot]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    vintages = _date_range(VINTAGE_START, VINTAGE_END)
    snapshots: list[AlfredSnapshot] = []
    total = len(SERIES) * len(vintages)
    completed = 0
    with httpx.Client(
        timeout=60.0,
        follow_redirects=False,
        headers={"User-Agent": "AIDY-Gold-Day28-PIT-Vintage-Acceptance/1.0"},
    ) as client:
        for series_id in SERIES:
            series_dir = cache_dir / series_id
            series_dir.mkdir(parents=True, exist_ok=True)
            for vintage in vintages:
                url = alfred_url(
                    series_id=series_id,
                    vintage_date=vintage,
                    observation_start=OBSERVATION_START,
                    observation_end=OBSERVATION_END,
                )
                path = series_dir / f"{vintage.isoformat()}.csv"
                if path.exists() and path.stat().st_size > 0:
                    raw = path.read_bytes()
                else:
                    response = client.get(url)
                    if response.status_code != 200:
                        raise RuntimeError(
                            f"Day 28 ALFRED fetch failed {series_id} {vintage}: "
                            f"HTTP {response.status_code}"
                        )
                    raw = response.content
                snapshot = parse_alfred_csv(
                    raw,
                    series_id=series_id,
                    vintage_date=vintage,
                    observation_start=OBSERVATION_START,
                    observation_end=OBSERVATION_END,
                    source_url=url,
                )
                if not path.exists():
                    path.write_bytes(raw)
                snapshots.append(snapshot)
                completed += 1
                if completed == 1 or completed % 20 == 0 or completed == total:
                    print(f"DAY28 SOURCE snapshots={completed}/{total}", flush=True)
    if len(snapshots) != EXPECTED_SNAPSHOT_COUNT:
        raise RuntimeError(
            f"Day 28 expected {EXPECTED_SNAPSHOT_COUNT} frozen snapshots, found {len(snapshots)}."
        )
    return snapshots


def _snapshot_payload(snapshot: AlfredSnapshot) -> dict[str, Any]:
    return {
        "series_id": snapshot.series_id,
        "vintage_date": snapshot.vintage_date.isoformat(),
        "observation_start": snapshot.observation_start.isoformat(),
        "observation_end": snapshot.observation_end.isoformat(),
        "values": [
            {"observation_date": day.isoformat(), "value": value}
            for day, value in snapshot.values
        ],
        "source_url": snapshot.source_url,
        "source_sha256": snapshot.source_sha256,
        "snapshot_digest": snapshot.snapshot_digest,
    }


def _source_fingerprint(snapshot: AlfredSnapshot) -> dict[str, Any]:
    return {
        "series_id": snapshot.series_id,
        "vintage_date": snapshot.vintage_date.isoformat(),
        "source_sha256": snapshot.source_sha256,
        "snapshot_digest": snapshot.snapshot_digest,
        "value_count": len(snapshot.values),
    }


def _schema(bigquery: Any, fields: list[tuple[str, str, str]]) -> list[Any]:
    return [bigquery.SchemaField(name, kind, mode=mode) for name, kind, mode in fields]


def _signature(fields: Any) -> tuple[tuple[str, str, str], ...]:
    aliases = {"FLOAT": "FLOAT64", "INTEGER": "INT64", "BOOL": "BOOLEAN"}
    return tuple(
        (
            field.name,
            aliases.get(str(field.field_type).upper(), str(field.field_type).upper()),
            str(field.mode).upper(),
        )
        for field in fields
    )


def _ensure_table(
    client: Any,
    bigquery: Any,
    not_found: type[Exception],
    *,
    table_id: str,
    fields: list[tuple[str, str, str]],
    partition_field: str,
    clustering_fields: tuple[str, ...],
) -> None:
    expected = _schema(bigquery, fields)
    try:
        table = client.get_table(table_id)
    except not_found:
        table = bigquery.Table(table_id, schema=expected)
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field=partition_field,
        )
        table.clustering_fields = list(clustering_fields)
        client.create_table(table)
        return
    if _signature(table.schema) != _signature(expected):
        raise RuntimeError(f"Day 28 BigQuery schema drift: {table_id}")
    partition = getattr(table, "time_partitioning", None)
    if getattr(partition, "field", None) != partition_field:
        raise RuntimeError(f"Day 28 BigQuery partition drift: {table_id}")
    if tuple(table.clustering_fields or ()) != clustering_fields:
        raise RuntimeError(f"Day 28 BigQuery clustering drift: {table_id}")


def _existing_rows(
    client: Any,
    bigquery: Any,
    *,
    table_id: str,
    experiment_id: str,
    identity_field: str,
) -> list[str]:
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("experiment", "STRING", experiment_id)]
    )
    rows = client.query(
        f"SELECT `{identity_field}` identity_value FROM `{table_id}` "
        "WHERE experiment_id=@experiment ORDER BY identity_value",
        job_config=config,
    ).result()
    return [str(row["identity_value"]) for row in rows]


def _persist_experiment_rows(
    client: Any,
    bigquery: Any,
    not_found: type[Exception],
    *,
    table_id: str,
    fields: list[tuple[str, str, str]],
    partition_field: str,
    clustering_fields: tuple[str, ...],
    rows: list[dict[str, Any]],
    experiment_id: str,
    identity_field: str,
) -> int:
    _ensure_table(
        client,
        bigquery,
        not_found,
        table_id=table_id,
        fields=fields,
        partition_field=partition_field,
        clustering_fields=clustering_fields,
    )
    expected = sorted(str(row[identity_field]) for row in rows)
    if len(expected) != len(set(expected)):
        raise RuntimeError(f"Day 28 duplicate {identity_field} in in-memory evidence.")
    existing = _existing_rows(
        client,
        bigquery,
        table_id=table_id,
        experiment_id=experiment_id,
        identity_field=identity_field,
    )
    if existing:
        if existing != expected:
            raise RuntimeError(f"Day 28 deterministic drift in existing {table_id} rows.")
        return len(existing)
    job = client.load_table_from_json(rows, table_id)
    job.result()
    if job.errors:
        raise RuntimeError(f"Day 28 BigQuery insert failed for {table_id}: {job.errors}")
    persisted = _existing_rows(
        client,
        bigquery,
        table_id=table_id,
        experiment_id=experiment_id,
        identity_field=identity_field,
    )
    if persisted != expected:
        raise RuntimeError(f"Day 28 BigQuery reconciliation failed for {table_id}.")
    return len(persisted)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def main() -> int:
    args = _args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    cache = Path(args.cache_dir)
    head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if len(head_sha) != 40:
        raise RuntimeError("Day 28 requires an exact 40-character Git head SHA.")
    changed_files = _changed_files(head_sha)
    experiment_id = f"day28-pit-vintaged-rates-20260826-{head_sha[:12]}"
    recorded_at = datetime.now(UTC).isoformat()

    client, bigquery, not_found = _bigquery_client(project=args.project, location=args.location)
    candidates = load_candidate_snapshot(client, args.project, args.dataset)
    if len(candidates) != CANDIDATE_COUNT or digest(candidates) != CANDIDATE_DIGEST:
        raise RuntimeError("Day 28 frozen candidate cohort drifted.")

    print("DAY28 SOURCE frozen ALFRED capture start", flush=True)
    snapshots = _load_snapshots(cache)
    source_manifest = [_snapshot_payload(snapshot) for snapshot in snapshots]
    source_fingerprints = [_source_fingerprint(snapshot) for snapshot in snapshots]
    source_manifest_digest = digest(source_fingerprints)
    _write_json(output / "source_manifest.json", source_manifest)
    _write_json(output / "source_fingerprints.json", source_fingerprints)

    versions = build_version_history(snapshots)
    if versions != build_version_history(reversed(snapshots)):
        raise RuntimeError("Day 28 vintage lineage depends on snapshot input order.")
    if not versions or not all(verify_version_record(record) for record in versions):
        raise RuntimeError("Day 28 vintage lineage contains an invalid version record.")
    first_print_known_count = sum(record["first_print_state"] == "known" for record in versions)
    revision_count = sum(str(record["revision_type"]).startswith("revision") for record in versions)
    if first_print_known_count == 0:
        raise RuntimeError("Day 28 real vintage window produced no observable first prints.")
    _write_jsonl(output / "versions.jsonl", versions)

    case_states: list[dict[str, Any]] = []
    known_breakeven = 0
    known_slope = 0
    known_cpi = 0
    official_validation = 0
    input_order_reproducible = 0
    selected_series_state_counts: Counter[str] = Counter()

    for case in candidates:
        as_of = datetime.fromisoformat(str(case["as_of_utc"])).astimezone(UTC)
        state = build_rates_macro_state(versions, as_of=as_of)
        reverse_state = build_rates_macro_state(reversed(versions), as_of=as_of)
        if state != reverse_state:
            raise RuntimeError(f"Day 28 case {case['case_id']} depends on version input order.")
        input_order_reproducible += 1
        if not verify_rates_macro_state(state) or state["pit_reconstructable"] is not True:
            raise RuntimeError(f"Day 28 case {case['case_id']} failed rates-state verification.")
        if state["evidence_family"] != EVIDENCE_FAMILY:
            raise RuntimeError("Day 28 rates family drifted.")
        if state["independent_confirmation_units"] != 1:
            raise RuntimeError("Day 28 rates components were double-counted.")
        if state["components_not_independent"] is not True:
            raise RuntimeError("Day 28 rates components lost non-independent labelling.")
        if state["real_yield_role"] != REAL_YIELD_ROLE:
            raise RuntimeError("Day 28 real-yield role drifted.")
        if state["directional_influence"] != REAL_YIELD_DIRECTIONAL_INFLUENCE:
            raise RuntimeError("Day 28 improperly promoted real-yield direction.")
        if state["predictive_edge_claimed"] is not False or state["trading_gate_created"] is not False:
            raise RuntimeError("Day 28 made an unapproved edge/gate claim.")

        for series_id, payload in state["series"].items():
            selected_series_state_counts[f"{series_id}:{payload['state']}"] += 1
        breakeven = state["derived"]["breakeven_10y"]
        slope = state["derived"]["slope_2s10s"]
        cpi = state["series"][SERIES_CPI]
        if breakeven["state"] == "known":
            known_breakeven += 1
        if slope["state"] == "known":
            known_slope += 1
        if cpi["state"] == "known":
            known_cpi += 1
        if state["official_breakeven_reference"]["derived_minus_official"] is not None:
            official_validation += 1

        cpi_fact = cpi.get("fact") if isinstance(cpi, dict) else None
        case_states.append(
            {
                "experiment_id": experiment_id,
                "case_id": str(case["case_id"]),
                "as_of_utc": as_of.isoformat(),
                "state_digest": state["state_digest"],
                "pit_reconstructable": True,
                "evidence_family": state["evidence_family"],
                "independent_confirmation_units": 1,
                "components_not_independent": True,
                "real_yield_role": state["real_yield_role"],
                "directional_influence": state["directional_influence"],
                "breakeven_state": breakeven["state"],
                "breakeven_value": breakeven["value"],
                "breakeven_observation_date": breakeven["observation_date"],
                "slope_state": slope["state"],
                "slope_value": slope["value"],
                "slope_observation_date": slope["observation_date"],
                "cpi_state": cpi["state"],
                "cpi_revision_index": (
                    None if not isinstance(cpi_fact, dict) else cpi_fact["revision_index"]
                ),
                "cpi_first_print_state": (
                    None if not isinstance(cpi_fact, dict) else cpi_fact["first_print_state"]
                ),
                "cpi_publication_date": (
                    None if not isinstance(cpi_fact, dict) else cpi_fact["publication_date"]
                ),
                "cpi_vintage_date": (
                    None if not isinstance(cpi_fact, dict) else cpi_fact["vintage_date"]
                ),
                "official_breakeven_validation_delta": state[
                    "official_breakeven_reference"
                ]["derived_minus_official"],
                "state_json": state,
                "recorded_at_utc": recorded_at,
            }
        )

    if input_order_reproducible != CANDIDATE_COUNT:
        raise RuntimeError("Day 28 did not reproduce all frozen cases.")
    if known_breakeven != CANDIDATE_COUNT or known_slope != CANDIDATE_COUNT:
        raise RuntimeError(
            "Day 28 expected same-date derived rates for all cases; "
            f"breakeven={known_breakeven}, slope={known_slope}."
        )
    if known_cpi != CANDIDATE_COUNT:
        raise RuntimeError(f"Day 28 expected PIT-known CPI context for all cases, found {known_cpi}.")
    if official_validation == 0:
        raise RuntimeError("Day 28 found no same-date official breakeven validation references.")
    _write_jsonl(output / "case_states.jsonl", case_states)

    snapshot_rows = [
        {
            "experiment_id": experiment_id,
            "base_sha": BASE_SHA,
            "head_sha": head_sha,
            "snapshot_digest": snapshot.snapshot_digest,
            "series_id": snapshot.series_id,
            "vintage_date": snapshot.vintage_date.isoformat(),
            "observation_start": snapshot.observation_start.isoformat(),
            "observation_end": snapshot.observation_end.isoformat(),
            "source_url": snapshot.source_url,
            "source_sha256": snapshot.source_sha256,
            "value_count": len(snapshot.values),
            "snapshot_json": _snapshot_payload(snapshot),
            "recorded_at_utc": recorded_at,
        }
        for snapshot in snapshots
    ]
    version_rows = [
        {
            "experiment_id": experiment_id,
            "base_sha": BASE_SHA,
            "head_sha": head_sha,
            **record,
            "recorded_at_utc": recorded_at,
        }
        for record in versions
    ]

    snapshot_table_id = f"{args.project}.{args.dataset}.{SNAPSHOT_TABLE}"
    version_table_id = f"{args.project}.{args.dataset}.{VERSION_TABLE}"
    case_table_id = f"{args.project}.{args.dataset}.{CASE_TABLE}"
    summary_table_id = f"{args.project}.{args.dataset}.{SUMMARY_TABLE}"

    snapshot_count = _persist_experiment_rows(
        client,
        bigquery,
        not_found,
        table_id=snapshot_table_id,
        fields=[
            ("experiment_id", "STRING", "REQUIRED"),
            ("base_sha", "STRING", "REQUIRED"),
            ("head_sha", "STRING", "REQUIRED"),
            ("snapshot_digest", "STRING", "REQUIRED"),
            ("series_id", "STRING", "REQUIRED"),
            ("vintage_date", "DATE", "REQUIRED"),
            ("observation_start", "DATE", "REQUIRED"),
            ("observation_end", "DATE", "REQUIRED"),
            ("source_url", "STRING", "REQUIRED"),
            ("source_sha256", "STRING", "REQUIRED"),
            ("value_count", "INTEGER", "REQUIRED"),
            ("snapshot_json", "JSON", "REQUIRED"),
            ("recorded_at_utc", "TIMESTAMP", "REQUIRED"),
        ],
        partition_field="vintage_date",
        clustering_fields=("series_id", "head_sha"),
        rows=snapshot_rows,
        experiment_id=experiment_id,
        identity_field="snapshot_digest",
    )
    version_count = _persist_experiment_rows(
        client,
        bigquery,
        not_found,
        table_id=version_table_id,
        fields=[
            ("experiment_id", "STRING", "REQUIRED"),
            ("base_sha", "STRING", "REQUIRED"),
            ("head_sha", "STRING", "REQUIRED"),
            ("version", "STRING", "REQUIRED"),
            ("source", "STRING", "REQUIRED"),
            ("series_id", "STRING", "REQUIRED"),
            ("series_role", "STRING", "REQUIRED"),
            ("observation_date", "DATE", "REQUIRED"),
            ("value", "STRING", "NULLABLE"),
            ("publication_date", "DATE", "REQUIRED"),
            ("vintage_date", "DATE", "REQUIRED"),
            ("publication_time_precision", "STRING", "REQUIRED"),
            ("pit_available_after_utc", "TIMESTAMP", "REQUIRED"),
            ("pit_reconstructable", "BOOLEAN", "REQUIRED"),
            ("revision_index", "INTEGER", "REQUIRED"),
            ("revision_type", "STRING", "REQUIRED"),
            ("first_print_state", "STRING", "REQUIRED"),
            ("previous_value", "STRING", "NULLABLE"),
            ("revision_delta", "STRING", "NULLABLE"),
            ("source_url", "STRING", "REQUIRED"),
            ("source_sha256", "STRING", "REQUIRED"),
            ("snapshot_digest", "STRING", "REQUIRED"),
            ("version_identity", "STRING", "REQUIRED"),
            ("recorded_at_utc", "TIMESTAMP", "REQUIRED"),
        ],
        partition_field="publication_date",
        clustering_fields=("series_id", "observation_date", "head_sha"),
        rows=version_rows,
        experiment_id=experiment_id,
        identity_field="version_identity",
    )
    case_count = _persist_experiment_rows(
        client,
        bigquery,
        not_found,
        table_id=case_table_id,
        fields=[
            ("experiment_id", "STRING", "REQUIRED"),
            ("case_id", "STRING", "REQUIRED"),
            ("as_of_utc", "TIMESTAMP", "REQUIRED"),
            ("state_digest", "STRING", "REQUIRED"),
            ("pit_reconstructable", "BOOLEAN", "REQUIRED"),
            ("evidence_family", "STRING", "REQUIRED"),
            ("independent_confirmation_units", "INTEGER", "REQUIRED"),
            ("components_not_independent", "BOOLEAN", "REQUIRED"),
            ("real_yield_role", "STRING", "REQUIRED"),
            ("directional_influence", "STRING", "REQUIRED"),
            ("breakeven_state", "STRING", "REQUIRED"),
            ("breakeven_value", "STRING", "NULLABLE"),
            ("breakeven_observation_date", "DATE", "NULLABLE"),
            ("slope_state", "STRING", "REQUIRED"),
            ("slope_value", "STRING", "NULLABLE"),
            ("slope_observation_date", "DATE", "NULLABLE"),
            ("cpi_state", "STRING", "REQUIRED"),
            ("cpi_revision_index", "INTEGER", "NULLABLE"),
            ("cpi_first_print_state", "STRING", "NULLABLE"),
            ("cpi_publication_date", "DATE", "NULLABLE"),
            ("cpi_vintage_date", "DATE", "NULLABLE"),
            ("official_breakeven_validation_delta", "STRING", "NULLABLE"),
            ("state_json", "JSON", "REQUIRED"),
            ("recorded_at_utc", "TIMESTAMP", "REQUIRED"),
        ],
        partition_field="as_of_utc",
        clustering_fields=("evidence_family", "head_sha"),
        rows=case_states,
        experiment_id=experiment_id,
        identity_field="case_id",
    )

    summary: dict[str, Any] = {
        "ok": True,
        "experiment_id": experiment_id,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "changed_files": changed_files,
        "candidate_store_snapshot_digest": CANDIDATE_DIGEST,
        "candidate_case_count": CANDIDATE_COUNT,
        "source": "FRED_ALFRED",
        "source_auth_required": False,
        "source_endpoint": "alfredgraph.csv",
        "series": list(SERIES),
        "vintage_start": VINTAGE_START.isoformat(),
        "vintage_end": VINTAGE_END.isoformat(),
        "observation_start": OBSERVATION_START.isoformat(),
        "observation_end": OBSERVATION_END.isoformat(),
        "frozen_snapshot_count": len(snapshots),
        "source_manifest_digest": source_manifest_digest,
        "version_record_count": len(versions),
        "first_print_known_count": first_print_known_count,
        "observed_revision_count": revision_count,
        "publication_time_precision": "date_only",
        "same_day_vintage_conservative_policy": "usable_from_next_utc_day_00_00",
        "input_order_reproducible_case_count": input_order_reproducible,
        "known_breakeven_case_count": known_breakeven,
        "known_2s10s_case_count": known_slope,
        "known_cpi_case_count": known_cpi,
        "official_breakeven_validation_case_count": official_validation,
        "selected_series_state_counts": dict(sorted(selected_series_state_counts.items())),
        "evidence_family": EVIDENCE_FAMILY,
        "independent_confirmation_units": 1,
        "components_not_independent": True,
        "real_yield_role": REAL_YIELD_ROLE,
        "directional_influence": REAL_YIELD_DIRECTIONAL_INFLUENCE,
        "future_vintage_values_used": False,
        "revised_modern_values_substituted": False,
        "predictive_edge_claimed": False,
        "trading_gate_created": False,
        "accepted_prior_modules_modified": False,
        "bigquery_evidence": {
            "snapshot_table": SNAPSHOT_TABLE,
            "snapshot_rows_for_experiment": snapshot_count,
            "version_table": VERSION_TABLE,
            "version_rows_for_experiment": version_count,
            "case_table": CASE_TABLE,
            "case_rows_for_experiment": case_count,
            "summary_table": SUMMARY_TABLE,
            "summary_rows_for_experiment": 1,
        },
    }
    summary["summary_digest"] = digest(summary)
    summary_row = {
        "experiment_id": experiment_id,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "summary_digest": summary["summary_digest"],
        "ok": True,
        "summary_json": summary,
        "recorded_at_utc": recorded_at,
    }
    _persist_experiment_rows(
        client,
        bigquery,
        not_found,
        table_id=summary_table_id,
        fields=[
            ("experiment_id", "STRING", "REQUIRED"),
            ("base_sha", "STRING", "REQUIRED"),
            ("head_sha", "STRING", "REQUIRED"),
            ("summary_digest", "STRING", "REQUIRED"),
            ("ok", "BOOLEAN", "REQUIRED"),
            ("summary_json", "JSON", "REQUIRED"),
            ("recorded_at_utc", "TIMESTAMP", "REQUIRED"),
        ],
        partition_field="recorded_at_utc",
        clustering_fields=("head_sha",),
        rows=[summary_row],
        experiment_id=experiment_id,
        identity_field="summary_digest",
    )

    _write_json(output / "summary.json", summary)
    _write_json(
        output / "contract_reference.json",
        {
            "base_sha": BASE_SHA,
            "head_sha": head_sha,
            "contract": "docs/day28-pit-vintaged-rates-contract.md",
            "candidate_digest": CANDIDATE_DIGEST,
            "source_manifest_digest": source_manifest_digest,
        },
    )
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
