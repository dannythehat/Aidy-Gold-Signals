from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from day26_acceptance_support import (
    CANDIDATE_COUNT,
    CANDIDATE_DIGEST,
    load_candidate_snapshot,
)
from day26_price_structure_acceptance import _bigquery_client

from aidy.bigquery_exporter import FieldSpec, TableSpec
from aidy.day23_research import digest
from aidy.historical_spread import (
    BASELINE_VERSION,
    J3_VERSION,
    RESEARCH_BIDASK_MANIFEST,
    RESEARCH_BIDASK_MINUTE_QUOTES,
    STRATA_VERSION,
    HistDataTickPeriod,
    build_case_covariates,
    build_spread_baseline,
    collapse_to_minute_quotes,
    download_histdata_tick_period,
    freeze_j3_strata,
    iter_histdata_ticks,
    run_j3,
    tick_archive_meta,
    verify_j3,
    verify_j3_strata,
    verify_spread_baseline,
)

BASE_SHA = "cab78a26acfbabdec6b3d2b5969eb3cf3b4831b3"
DEFAULT_PROJECT = "aidy-signals"
DEFAULT_DATASET = "aidy_analytics_test"
DEFAULT_LOCATION = "EU"
BASELINE_PERIOD = HistDataTickPeriod(2024, 12)
ANCHOR_PERIOD = HistDataTickPeriod(2025, 1)

BASELINE_TABLE = TableSpec(
    name="research_day27_spread_baseline",
    partition_field="recorded_at_utc",
    clustering_fields=("baseline_version", "source"),
    fields=(
        FieldSpec("experiment_id", "STRING", "REQUIRED"),
        FieldSpec("base_sha", "STRING", "REQUIRED"),
        FieldSpec("head_sha", "STRING", "REQUIRED"),
        FieldSpec("baseline_digest", "STRING", "REQUIRED"),
        FieldSpec("baseline_version", "STRING", "REQUIRED"),
        FieldSpec("source", "STRING", "REQUIRED"),
        FieldSpec("source_period", "STRING", "REQUIRED"),
        FieldSpec("source_file_sha256", "STRING", "REQUIRED"),
        FieldSpec("source_payload_sha256", "STRING", "REQUIRED"),
        FieldSpec("baseline_json", "JSON", "REQUIRED"),
        FieldSpec("recorded_at_utc", "TIMESTAMP", "REQUIRED"),
    ),
)

CASE_LIQUIDITY_TABLE = TableSpec(
    name="research_day27_case_liquidity",
    partition_field="as_of_utc",
    clustering_fields=("state", "spread_tercile", "volatility_tercile"),
    fields=(
        FieldSpec("experiment_id", "STRING", "REQUIRED"),
        FieldSpec("case_id", "STRING", "REQUIRED"),
        FieldSpec("as_of_utc", "TIMESTAMP", "REQUIRED"),
        FieldSpec("state", "STRING", "REQUIRED"),
        FieldSpec("quote_identity", "STRING"),
        FieldSpec("source_tick_time_utc", "TIMESTAMP"),
        FieldSpec("quote_age_seconds", "INTEGER"),
        FieldSpec("spread_bps", "STRING"),
        FieldSpec("spread_z", "STRING"),
        FieldSpec("h1_atr_14_bps", "STRING"),
        FieldSpec("session", "STRING"),
        FieldSpec("outcome_geometry_available", "BOOLEAN", "REQUIRED"),
        FieldSpec("spread_tercile", "STRING"),
        FieldSpec("volatility_tercile", "STRING"),
        FieldSpec("baseline_digest", "STRING", "REQUIRED"),
        FieldSpec("strata_digest", "STRING", "REQUIRED"),
        FieldSpec("covariate_digest", "STRING", "REQUIRED"),
        FieldSpec("recorded_at_utc", "TIMESTAMP", "REQUIRED"),
    ),
)

J3_TABLE = TableSpec(
    name="research_day27_j3_summary",
    partition_field="recorded_at_utc",
    clustering_fields=("evidence_state", "gate_status"),
    fields=(
        FieldSpec("experiment_id", "STRING", "REQUIRED"),
        FieldSpec("base_sha", "STRING", "REQUIRED"),
        FieldSpec("head_sha", "STRING", "REQUIRED"),
        FieldSpec("strata_digest", "STRING", "REQUIRED"),
        FieldSpec("j3_digest", "STRING", "REQUIRED"),
        FieldSpec("evidence_state", "STRING", "REQUIRED"),
        FieldSpec("outcome_cases", "INTEGER", "REQUIRED"),
        FieldSpec("minimum_observed_cell_n", "INTEGER", "REQUIRED"),
        FieldSpec("gate_status", "STRING", "REQUIRED"),
        FieldSpec("j3_json", "JSON", "REQUIRED"),
        FieldSpec("recorded_at_utc", "TIMESTAMP", "REQUIRED"),
    ),
)

_ALLOWED_CHANGED_FILES = {
    "docs/day27-historical-spread-j3-contract.md",
    "scripts/day27_historical_spread_acceptance.py",
    "src/aidy/historical_spread.py",
    "tests/test_day27_historical_spread.py",
}


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AIDY Day 27 historical spread/J3 acceptance")
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
    parser.add_argument("--output-dir", default="day27_artifacts")
    parser.add_argument("--cache-dir", default=".cache/day27")
    return parser.parse_args()


def _schema(bigquery: Any, fields: tuple[FieldSpec, ...]) -> list[Any]:
    return [bigquery.SchemaField(field.name, field.field_type, mode=field.mode) for field in fields]


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
    table_id: str,
    spec: TableSpec,
) -> None:
    expected = _schema(bigquery, spec.fields)
    try:
        table = client.get_table(table_id)
    except not_found:
        table = bigquery.Table(table_id, schema=expected)
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field=spec.partition_field,
        )
        table.clustering_fields = list(spec.clustering_fields)
        client.create_table(table)
        return
    if _signature(table.schema) != _signature(expected):
        raise RuntimeError(f"Day 27 BigQuery schema drift: {table_id}")
    partition = getattr(table, "time_partitioning", None)
    if getattr(partition, "field", None) != spec.partition_field:
        raise RuntimeError(f"Day 27 BigQuery partition drift: {table_id}")
    if tuple(table.clustering_fields or ()) != spec.clustering_fields:
        raise RuntimeError(f"Day 27 BigQuery clustering drift: {table_id}")


def _ensure_stage(
    client: Any,
    bigquery: Any,
    not_found: type[Exception],
    stage_id: str,
    fields: tuple[FieldSpec, ...],
) -> None:
    expected = [bigquery.SchemaField("_run_id", "STRING", mode="REQUIRED"), *_schema(bigquery, fields)]
    try:
        table = client.get_table(stage_id)
    except not_found:
        client.create_table(bigquery.Table(stage_id, schema=expected))
        return
    if _signature(table.schema) != _signature(expected):
        raise RuntimeError(f"Day 27 BigQuery staging schema drift: {stage_id}")


def _changed_files(head_sha: str) -> list[str]:
    merge_base = subprocess.check_output(
        ["git", "merge-base", BASE_SHA, head_sha], text=True
    ).strip()
    if merge_base != BASE_SHA:
        raise RuntimeError("Day 27 branch is not based on the accepted Day 26 main SHA.")
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", f"{BASE_SHA}...{head_sha}"], text=True
    ).splitlines()
    unexpected = sorted(set(changed) - _ALLOWED_CHANGED_FILES)
    if unexpected:
        raise RuntimeError(f"Day 27 modified accepted prior files: {unexpected}")
    return sorted(changed)


def _case_rows(client: Any, project: str, dataset: str) -> list[dict[str, Any]]:
    table = f"{project}.{dataset}.research_gold_cases"
    rows = list(
        client.query(
            f"""SELECT case_id, case_digest, input_digest, as_of_utc,
                       future_available_after_utc, provenance_class, data_quality_grade,
                       input_boundary, future_evaluation
                FROM `{table}`
                WHERE symbol='XAUUSD'
                ORDER BY as_of_utc, case_id"""
        ).result()
    )
    if len(rows) != CANDIDATE_COUNT:
        raise RuntimeError(f"Expected {CANDIDATE_COUNT} Day 27 historical cases, found {len(rows)}")
    result = [dict(row.items()) for row in rows]
    if not all(
        datetime(2025, 1, 6, tzinfo=UTC) <= item["as_of_utc"] < datetime(2025, 1, 8, tzinfo=UTC)
        for item in result
    ):
        raise RuntimeError("Day 27 historical cases drifted outside the frozen Jan 6-7 window.")
    return result


def _source_fact_digest(manifest: dict[str, Any]) -> str:
    return digest(
        {
            key: value
            for key, value in manifest.items()
            if key not in {"manifest_digest", "ingested_at"}
        }
    )


def _merge_quote_rows(
    client: Any,
    bigquery: Any,
    not_found: type[Exception],
    *,
    project: str,
    dataset: str,
    rows: list[dict[str, Any]],
    run_id: str,
) -> int:
    table_id = f"{project}.{dataset}.{RESEARCH_BIDASK_MINUTE_QUOTES.name}"
    stage_id = f"{project}.{dataset}._stage_day27_bidask_minute_quotes"
    _ensure_table(client, bigquery, not_found, table_id, RESEARCH_BIDASK_MINUTE_QUOTES)
    _ensure_stage(client, bigquery, not_found, stage_id, RESEARCH_BIDASK_MINUTE_QUOTES.fields)
    client.query(f"TRUNCATE TABLE `{stage_id}`").result()
    for offset in range(0, len(rows), 20_000):
        batch = [{"_run_id": run_id, **row} for row in rows[offset : offset + 20_000]]
        job = client.load_table_from_json(batch, stage_id)
        job.result()
        if job.errors:
            raise RuntimeError(f"Day 27 quote staging failed: {job.errors}")
    columns = [field.name for field in RESEARCH_BIDASK_MINUTE_QUOTES.fields]
    column_sql = ", ".join(f"`{name}`" for name in columns)
    value_sql = ", ".join(f"S.`{name}`" for name in columns)
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("run_id", "STRING", run_id)]
    )
    client.query(
        f"""MERGE `{table_id}` T
            USING (
              SELECT {column_sql}
              FROM `{stage_id}`
              WHERE _run_id=@run_id
              QUALIFY ROW_NUMBER() OVER (PARTITION BY quote_identity ORDER BY minute_utc)=1
            ) S
            ON T.quote_identity=S.quote_identity
            WHEN NOT MATCHED THEN INSERT ({column_sql}) VALUES ({value_sql})""",
        job_config=config,
    ).result()
    duplicate = next(
        client.query(
            f"""SELECT COUNT(*) AS duplicate_groups FROM (
                  SELECT source_file_sha256, minute_utc, COUNT(*) n
                  FROM `{table_id}`
                  WHERE source='histdata' AND source_dataset='generic_ascii_tick'
                  GROUP BY source_file_sha256, minute_utc HAVING n > 1
                )"""
        ).result()
    )
    if int(duplicate["duplicate_groups"]):
        raise RuntimeError("Day 27 quote table contains duplicate logical source minutes.")
    source_hashes = sorted({str(row["source_file_sha256"]) for row in rows})
    reconcile_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("hashes", "STRING", source_hashes)]
    )
    reconciled = next(
        client.query(
            f"""SELECT COUNT(*) rows, COUNT(DISTINCT quote_identity) identities
                FROM `{table_id}` WHERE source_file_sha256 IN UNNEST(@hashes)""",
            job_config=reconcile_config,
        ).result()
    )
    client.query(f"DELETE FROM `{stage_id}` WHERE _run_id=@run_id", job_config=config).result()
    if int(reconciled["rows"]) != len(rows) or int(reconciled["identities"]) != len(rows):
        raise RuntimeError("Day 27 quote reconciliation differs from canonical source rows.")
    return int(reconciled["rows"])


def _persist_manifests(
    client: Any,
    bigquery: Any,
    not_found: type[Exception],
    *,
    project: str,
    dataset: str,
    manifests: list[dict[str, Any]],
) -> int:
    table_id = f"{project}.{dataset}.{RESEARCH_BIDASK_MANIFEST.name}"
    _ensure_table(client, bigquery, not_found, table_id, RESEARCH_BIDASK_MANIFEST)
    for manifest in manifests:
        config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("file_sha", "STRING", manifest["source_file_sha256"]),
                bigquery.ScalarQueryParameter(
                    "payload_sha", "STRING", manifest["source_payload_sha256"]
                ),
            ]
        )
        existing = list(
            client.query(
                f"""SELECT manifest_digest FROM `{table_id}`
                    WHERE source_file_sha256=@file_sha AND source_payload_sha256=@payload_sha""",
                job_config=config,
            ).result()
        )
        if len(existing) > 1:
            raise RuntimeError("Day 27 source manifest is not unique by immutable source hashes.")
        if not existing:
            job = client.load_table_from_json([manifest], table_id)
            job.result()
            if job.errors:
                raise RuntimeError(f"Day 27 manifest insert failed: {job.errors}")
    hashes = [str(item["source_file_sha256"]) for item in manifests]
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("hashes", "STRING", hashes)]
    )
    count = int(
        next(
            client.query(
                f"SELECT COUNT(*) n FROM `{table_id}` WHERE source_file_sha256 IN UNNEST(@hashes)",
                job_config=config,
            ).result()
        )["n"]
    )
    if count != 2:
        raise RuntimeError(f"Expected exactly two frozen Day 27 source manifests, found {count}.")
    return count


def _persist_singleton(
    client: Any,
    bigquery: Any,
    not_found: type[Exception],
    *,
    table_id: str,
    spec: TableSpec,
    experiment_id: str,
    digest_field: str,
    digest_value: str,
    row: dict[str, Any],
) -> int:
    _ensure_table(client, bigquery, not_found, table_id, spec)
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("experiment", "STRING", experiment_id)]
    )
    existing = list(
        client.query(
            f"SELECT `{digest_field}` FROM `{table_id}` WHERE experiment_id=@experiment",
            job_config=config,
        ).result()
    )
    if len(existing) > 1:
        raise RuntimeError(f"Day 27 duplicate experiment rows in {table_id}.")
    if existing:
        if str(existing[0][digest_field]) != digest_value:
            raise RuntimeError(f"Day 27 deterministic drift in {table_id}.")
    else:
        job = client.load_table_from_json([row], table_id)
        job.result()
        if job.errors:
            raise RuntimeError(f"Day 27 singleton insert failed for {table_id}: {job.errors}")
    return 1


def _persist_case_rows(
    client: Any,
    bigquery: Any,
    not_found: type[Exception],
    *,
    project: str,
    dataset: str,
    experiment_id: str,
    rows: list[dict[str, Any]],
) -> int:
    table_id = f"{project}.{dataset}.{CASE_LIQUIDITY_TABLE.name}"
    stage_id = f"{project}.{dataset}._stage_day27_case_liquidity"
    _ensure_table(client, bigquery, not_found, table_id, CASE_LIQUIDITY_TABLE)
    _ensure_stage(client, bigquery, not_found, stage_id, CASE_LIQUIDITY_TABLE.fields)
    run_id = f"{experiment_id}-cases"
    client.query(f"TRUNCATE TABLE `{stage_id}`").result()
    job = client.load_table_from_json([{"_run_id": run_id, **row} for row in rows], stage_id)
    job.result()
    if job.errors:
        raise RuntimeError(f"Day 27 case-liquidity staging failed: {job.errors}")
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("run_id", "STRING", run_id)]
    )
    conflicts = int(
        next(
            client.query(
                f"""SELECT COUNT(*) n FROM `{stage_id}` S JOIN `{table_id}` T
                    USING (experiment_id, case_id)
                    WHERE S._run_id=@run_id AND S.covariate_digest != T.covariate_digest""",
                job_config=config,
            ).result()
        )["n"]
    )
    if conflicts:
        raise RuntimeError("Day 27 case covariates drifted for an existing experiment.")
    columns = [field.name for field in CASE_LIQUIDITY_TABLE.fields]
    column_sql = ", ".join(f"`{name}`" for name in columns)
    value_sql = ", ".join(f"S.`{name}`" for name in columns)
    client.query(
        f"""MERGE `{table_id}` T
            USING (SELECT {column_sql} FROM `{stage_id}` WHERE _run_id=@run_id) S
            ON T.experiment_id=S.experiment_id AND T.case_id=S.case_id
            WHEN NOT MATCHED THEN INSERT ({column_sql}) VALUES ({value_sql})""",
        job_config=config,
    ).result()
    exp_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("experiment", "STRING", experiment_id)]
    )
    count = int(
        next(
            client.query(
                f"SELECT COUNT(*) n FROM `{table_id}` WHERE experiment_id=@experiment",
                job_config=exp_config,
            ).result()
        )["n"]
    )
    client.query(f"DELETE FROM `{stage_id}` WHERE _run_id=@run_id", job_config=config).result()
    if count != CANDIDATE_COUNT:
        raise RuntimeError(f"Day 27 case-liquidity reconciliation found {count} rows.")
    return count


def _artifact(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def main() -> int:
    args = _args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    changed = _changed_files(head_sha)
    experiment_id = f"day27-historical-spread-j3-20260825-{head_sha[:12]}"
    recorded_at = datetime.now(UTC)

    client, bigquery, not_found = _bigquery_client(project=args.project, location=args.location)
    snapshot = load_candidate_snapshot(client, args.project, args.dataset)
    if len(snapshot) != CANDIDATE_COUNT or CANDIDATE_DIGEST != digest(snapshot):
        raise RuntimeError("Day 27 frozen candidate snapshot drifted.")
    cases = _case_rows(client, args.project, args.dataset)

    print("DAY27 SOURCE december-2024 download/start", flush=True)
    december_path = download_histdata_tick_period(BASELINE_PERIOD, cache_dir=cache_dir)
    december_meta = tick_archive_meta(december_path)
    print("DAY27 SOURCE december-2024 parse/collapse", flush=True)
    december_quotes, december_manifest = collapse_to_minute_quotes(
        iter_histdata_ticks(december_path), meta=december_meta, ingested_at=recorded_at
    )
    december_manifest["source_period"] = "2024-12"
    december_manifest["manifest_digest"] = digest(
        {key: value for key, value in december_manifest.items() if key != "manifest_digest"}
    )

    print("DAY27 SOURCE january-2025 download/start", flush=True)
    january_path = download_histdata_tick_period(ANCHOR_PERIOD, cache_dir=cache_dir)
    january_meta = tick_archive_meta(january_path)
    print("DAY27 SOURCE january-2025 parse/collapse", flush=True)
    january_quotes, january_manifest = collapse_to_minute_quotes(
        iter_histdata_ticks(january_path), meta=january_meta, ingested_at=recorded_at
    )
    january_manifest["source_period"] = "2025-01"
    january_manifest["manifest_digest"] = digest(
        {key: value for key, value in january_manifest.items() if key != "manifest_digest"}
    )

    if december_meta.source_file_sha256 == january_meta.source_file_sha256:
        raise RuntimeError("Frozen Day 27 source archives unexpectedly have the same SHA256.")
    if any(item.get("depth_included") for item in (december_manifest, january_manifest)):
        raise RuntimeError("Day 27 source manifest introduced depth.")
    if any(item.get("true_exchange_volume_claimed") for item in (december_manifest, january_manifest)):
        raise RuntimeError("Day 27 source manifest introduced exchange-volume claims.")
    if any(item.get("order_flow_claimed") for item in (december_manifest, january_manifest)):
        raise RuntimeError("Day 27 source manifest introduced order-flow claims.")

    # Freeze the baseline BEFORE January cases are normalized and before outcomes are read.
    baseline = build_spread_baseline(december_quotes)
    if not verify_spread_baseline(baseline) or baseline.get("outcome_fields_used") is not False:
        raise RuntimeError("Day 27 baseline freeze failed.")
    _artifact(output_dir / "baseline.json", baseline)

    covariates = build_case_covariates(cases, january_quotes, baseline)
    if any(item.get("future_evaluation_read") is not False for item in covariates):
        raise RuntimeError("Day 27 covariate construction crossed the outcome boundary.")
    known_covariates = sum(item["state"] == "known" for item in covariates)
    unknown_covariates = len(covariates) - known_covariates
    if known_covariates == 0:
        raise RuntimeError("Day 27 found no historical cases with a known normalized spread state.")

    # Freeze input-side J3 assignments BEFORE calling run_j3, which is the first outcome read.
    strata = freeze_j3_strata(covariates)
    if not verify_j3_strata(strata) or strata.get("future_outcomes_used_for_strata") is not False:
        raise RuntimeError("Day 27 input strata freeze failed.")
    _artifact(output_dir / "strata.json", strata)
    if int(strata["eligible_cases"]) == 0:
        raise RuntimeError("Day 27 has no cases eligible for the frozen J3 stratification.")

    j3 = run_j3(cases, strata)
    if not verify_j3(j3):
        raise RuntimeError("Day 27 J3 digest does not match contents.")
    if int(j3["outcome_cases"]) == 0:
        raise RuntimeError("Day 27 J3 had no accepted trade-outcome cases to describe.")
    if j3["proposed_trading_gate"] is not None or j3["gate_status"] != "provisional_no_gate":
        raise RuntimeError("Day 27 improperly promoted J3 into a trading gate.")
    if j3["predictive_edge_claimed"] is not False:
        raise RuntimeError("Day 27 improperly claimed predictive edge.")
    _artifact(output_dir / "j3.json", j3)

    print("DAY27 WAREHOUSE quote persistence start", flush=True)
    quote_rows = [quote.to_row() for quote in december_quotes + january_quotes]
    quote_count = _merge_quote_rows(
        client,
        bigquery,
        not_found,
        project=args.project,
        dataset=args.dataset,
        rows=quote_rows,
        run_id=f"{experiment_id}-quotes",
    )
    manifest_count = _persist_manifests(
        client,
        bigquery,
        not_found,
        project=args.project,
        dataset=args.dataset,
        manifests=[december_manifest, january_manifest],
    )

    baseline_table_id = f"{args.project}.{args.dataset}.{BASELINE_TABLE.name}"
    _persist_singleton(
        client,
        bigquery,
        not_found,
        table_id=baseline_table_id,
        spec=BASELINE_TABLE,
        experiment_id=experiment_id,
        digest_field="baseline_digest",
        digest_value=str(baseline["baseline_digest"]),
        row={
            "experiment_id": experiment_id,
            "base_sha": BASE_SHA,
            "head_sha": head_sha,
            "baseline_digest": baseline["baseline_digest"],
            "baseline_version": BASELINE_VERSION,
            "source": "histdata",
            "source_period": "2024-12",
            "source_file_sha256": december_meta.source_file_sha256,
            "source_payload_sha256": december_meta.source_payload_sha256,
            "baseline_json": baseline,
            "recorded_at_utc": recorded_at.isoformat(),
        },
    )

    assignments = {str(item["case_id"]): item for item in strata["assignments"]}
    case_rows: list[dict[str, Any]] = []
    for covariate in covariates:
        assignment = assignments.get(str(covariate["case_id"]), {})
        body = {
            "experiment_id": experiment_id,
            "case_id": covariate["case_id"],
            "as_of_utc": covariate["as_of_utc"],
            "state": covariate["state"],
            "quote_identity": covariate["quote_identity"],
            "source_tick_time_utc": covariate["source_tick_time_utc"],
            "quote_age_seconds": covariate["quote_age_seconds"],
            "spread_bps": covariate["spread_bps"],
            "spread_z": covariate["spread_z"],
            "h1_atr_14_bps": covariate["h1_atr_14_bps"],
            "session": covariate["session"],
            "outcome_geometry_available": bool(covariate["outcome_geometry_available"]),
            "spread_tercile": assignment.get("spread_tercile"),
            "volatility_tercile": assignment.get("volatility_tercile"),
            "baseline_digest": baseline["baseline_digest"],
            "strata_digest": strata["strata_digest"],
        }
        body["covariate_digest"] = digest(body)
        body["recorded_at_utc"] = recorded_at.isoformat()
        case_rows.append(body)
    case_count = _persist_case_rows(
        client,
        bigquery,
        not_found,
        project=args.project,
        dataset=args.dataset,
        experiment_id=experiment_id,
        rows=case_rows,
    )

    j3_table_id = f"{args.project}.{args.dataset}.{J3_TABLE.name}"
    _persist_singleton(
        client,
        bigquery,
        not_found,
        table_id=j3_table_id,
        spec=J3_TABLE,
        experiment_id=experiment_id,
        digest_field="j3_digest",
        digest_value=str(j3["j3_digest"]),
        row={
            "experiment_id": experiment_id,
            "base_sha": BASE_SHA,
            "head_sha": head_sha,
            "strata_digest": strata["strata_digest"],
            "j3_digest": j3["j3_digest"],
            "evidence_state": j3["evidence_state"],
            "outcome_cases": j3["outcome_cases"],
            "minimum_observed_cell_n": j3["minimum_observed_cell_n"],
            "gate_status": j3["gate_status"],
            "j3_json": j3,
            "recorded_at_utc": recorded_at.isoformat(),
        },
    )

    source_facts = {
        "baseline_2024_12": {
            "source_file": december_meta.source_file,
            "source_file_sha256": december_meta.source_file_sha256,
            "source_payload_sha256": december_meta.source_payload_sha256,
            "source_fact_digest": _source_fact_digest(december_manifest),
            "tick_rows": december_manifest["tick_rows"],
            "minute_quote_rows": december_manifest["minute_quote_rows"],
        },
        "anchors_2025_01": {
            "source_file": january_meta.source_file,
            "source_file_sha256": january_meta.source_file_sha256,
            "source_payload_sha256": january_meta.source_payload_sha256,
            "source_fact_digest": _source_fact_digest(january_manifest),
            "tick_rows": january_manifest["tick_rows"],
            "minute_quote_rows": january_manifest["minute_quote_rows"],
        },
    }
    summary: dict[str, Any] = {
        "ok": True,
        "experiment_id": experiment_id,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "changed_files": changed,
        "candidate_store_snapshot_digest": CANDIDATE_DIGEST,
        "candidate_case_count": CANDIDATE_COUNT,
        "source": "histdata",
        "source_dataset": "generic_ascii_tick",
        "source_usage_scope": "internal_research_backtesting_no_raw_redistribution",
        "baseline_source_period": "2024-12",
        "anchor_source_period": "2025-01",
        "source_facts": source_facts,
        "raw_bid_ask_preserved": True,
        "vendor_volume_used": False,
        "depth_included": False,
        "true_exchange_volume_claimed": False,
        "order_flow_claimed": False,
        "future_tick_join_used": False,
        "baseline_uses_later_january_quotes": False,
        "baseline_version": BASELINE_VERSION,
        "baseline_digest": baseline["baseline_digest"],
        "known_case_spread_states": known_covariates,
        "unknown_case_spread_states": unknown_covariates,
        "strata_version": STRATA_VERSION,
        "strata_digest": strata["strata_digest"],
        "strata_eligible_cases": strata["eligible_cases"],
        "future_outcomes_used_for_strata": False,
        "j3_version": J3_VERSION,
        "j3_digest": j3["j3_digest"],
        "j3_outcome_cases": j3["outcome_cases"],
        "j3_cell_count": len(j3["cells"]),
        "j3_minimum_observed_cell_n": j3["minimum_observed_cell_n"],
        "j3_evidence_state": j3["evidence_state"],
        "gate_status": j3["gate_status"],
        "proposed_trading_gate": None,
        "predictive_edge_claimed": False,
        "accepted_prior_modules_modified": False,
        "bigquery_evidence": {
            "quote_table": RESEARCH_BIDASK_MINUTE_QUOTES.name,
            "quote_rows_for_frozen_archives": quote_count,
            "manifest_table": RESEARCH_BIDASK_MANIFEST.name,
            "manifest_rows_for_frozen_archives": manifest_count,
            "baseline_table": BASELINE_TABLE.name,
            "baseline_rows_for_experiment": 1,
            "case_liquidity_table": CASE_LIQUIDITY_TABLE.name,
            "case_liquidity_rows_for_experiment": case_count,
            "j3_table": J3_TABLE.name,
            "j3_rows_for_experiment": 1,
        },
    }
    summary["summary_digest"] = digest(summary)
    _artifact(output_dir / "summary.json", summary)
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
