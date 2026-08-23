from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from aidy.cme_contract_intelligence import (
    CME_CALENDAR_VERSION,
    CME_CONTRACT_INTELLIGENCE_VERSION,
    CME_DAILY_RECORD_VERSION,
    CME_GOLD_CALENDAR_DOWNLOAD_URL,
    J6_VERSION,
    CmeContractError,
    CmePublicBulletinGateway,
    CmePublicCalendarGateway,
    build_contract_roll_state,
    build_daily_contract_records,
    canonical_json,
    digest,
    run_j6_descriptive,
    verify_contract_calendar_observation,
    verify_contract_roll_state,
    verify_daily_contract_record,
    verify_j6_study,
)
from aidy.market_structure_context import market_structure_epoch_at

BASE_SHA = "a22fccf04586c3b8407c8e9707ec1a7c9f0248cf"
DEFAULT_PROJECT = "aidy-signals"
DEFAULT_DATASET = "aidy_analytics_test"
DEFAULT_LOCATION = "EU"
DAILY_TABLE = "research_day30_cme_daily_contracts"
CALENDAR_TABLE = "research_day30_cme_contract_calendar"
J6_TABLE = "research_day30_j6_open_interest"
SUMMARY_TABLE = "research_day30_summary"
SOURCE_SEED_DIR = Path(__file__).with_name("day30_official_source_seed")


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Day 30 CME contract intelligence acceptance")
    parser.add_argument(
        "--project",
        default=(
            os.environ.get("AIDY_GCP_PROJECT_ID")
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
            or DEFAULT_PROJECT
        ),
    )
    parser.add_argument(
        "--dataset", default=os.environ.get("AIDY_BIGQUERY_DATASET", DEFAULT_DATASET)
    )
    parser.add_argument(
        "--location", default=os.environ.get("AIDY_BIGQUERY_LOCATION", DEFAULT_LOCATION)
    )
    parser.add_argument("--output-dir", default="day30_artifacts")
    parser.add_argument("--cache-dir", default=".cache/day30/cme_public")
    return parser.parse_args()


def _changed_files(head_sha: str) -> list[str]:
    check = subprocess.run(
        ["git", "cat-file", "-e", f"{BASE_SHA}^{{commit}}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if check.returncode != 0:
        raise RuntimeError(
            f"Day 30 acceptance clone lacks base {BASE_SHA}; fetch full history before retrying."
        )
    output = subprocess.check_output(
        ["git", "diff", "--name-only", f"{BASE_SHA}..{head_sha}"], text=True
    )
    return sorted(line for line in output.splitlines() if line)


def _write_json(path: Path, value: object) -> None:
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[object]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _capture_sources(
    cache_dir: Path, recorded_at: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    daily_path = cache_dir / "daily_contract_records.jsonl"
    calendar_path = cache_dir / "contract_calendar.jsonl"
    transport_path = cache_dir / "capture_transport.json"
    if daily_path.exists() and calendar_path.exists():
        daily_records = _read_jsonl(daily_path)
        calendar_records = _read_jsonl(calendar_path)
        transport = (
            str(json.loads(transport_path.read_text(encoding="utf-8"))["transport"])
            if transport_path.exists()
            else "cached_official_capture"
        )
    else:
        try:
            snapshot = CmePublicBulletinGateway().fetch_current(first_observed_at=recorded_at)
            daily_records = build_daily_contract_records(snapshot)
            calendar_records = CmePublicCalendarGateway().fetch_current(
                first_observed_at=recorded_at
            )
            transport = "official_https"
        except (CmeContractError, httpx.HTTPError):
            seed_daily = SOURCE_SEED_DIR / "daily_contract_records.jsonl"
            seed_calendar = SOURCE_SEED_DIR / "contract_calendar.jsonl"
            if not seed_daily.exists() or not seed_calendar.exists():
                raise RuntimeError(
                    "Day 30 live CME capture failed and the verified official seed is absent."
                ) from None
            daily_records = _read_jsonl(seed_daily)
            calendar_records = _read_jsonl(seed_calendar)
            transport = "checked_in_verified_official_capture"
        _write_jsonl(daily_path, daily_records)
        _write_jsonl(calendar_path, calendar_records)
        _write_json(transport_path, {"transport": transport})
    if not daily_records or not all(verify_daily_contract_record(row) for row in daily_records):
        raise RuntimeError("Day 30 daily CME capture failed its immutable record contract.")
    if not calendar_records or not all(
        verify_contract_calendar_observation(row) for row in calendar_records
    ):
        raise RuntimeError("Day 30 CME calendar capture failed its immutable record contract.")
    return daily_records, calendar_records, transport


def _client(project: str, location: str) -> tuple[Any, Any, type[Exception]]:
    from google.api_core.exceptions import NotFound
    from google.cloud import bigquery

    raw = os.environ.get("AIDY_GCP_SERVICE_ACCOUNT_JSON")
    if raw:
        from google.oauth2 import service_account

        credentials = service_account.Credentials.from_service_account_info(json.loads(raw))
        client = bigquery.Client(project=project, credentials=credentials, location=location)
    else:
        client = bigquery.Client(project=project, location=location)
    return client, bigquery, NotFound


def _ensure_table(
    client: Any,
    bigquery: Any,
    not_found: type[Exception],
    *,
    table_id: str,
    fields: list[tuple[str, str, str]],
    clustering_fields: tuple[str, ...],
) -> None:
    schema = [bigquery.SchemaField(name, kind, mode=mode) for name, kind, mode in fields]
    try:
        existing = client.get_table(table_id)
    except not_found:
        table = bigquery.Table(table_id, schema=schema)
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY, field="recorded_at_utc"
        )
        table.clustering_fields = list(clustering_fields)
        client.create_table(table)
        return
    actual = [(field.name, field.field_type, field.mode) for field in existing.schema]
    expected = [(field.name, field.field_type, field.mode) for field in schema]
    if actual != expected:
        raise RuntimeError(f"Day 30 BigQuery schema drift for {table_id}.")
    if getattr(existing.time_partitioning, "field", None) != "recorded_at_utc":
        raise RuntimeError(f"Day 30 BigQuery partition drift for {table_id}.")
    if tuple(existing.clustering_fields or ()) != clustering_fields:
        raise RuntimeError(f"Day 30 BigQuery clustering drift for {table_id}.")


def _persist(
    client: Any,
    bigquery: Any,
    not_found: type[Exception],
    *,
    table_id: str,
    fields: list[tuple[str, str, str]],
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
        clustering_fields=clustering_fields,
    )
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("experiment", "STRING", experiment_id)]
    )
    existing = {
        str(item[identity_field]): str(item["row_digest"])
        for item in client.query(
            f"SELECT `{identity_field}`, row_digest FROM `{table_id}` "
            "WHERE experiment_id=@experiment",
            job_config=config,
        ).result()
    }
    for row in rows:
        identity = str(row[identity_field])
        if identity in existing and existing[identity] != row["row_digest"]:
            raise RuntimeError(f"Day 30 immutable evidence conflict in {table_id}.")
    missing = [row for row in rows if str(row[identity_field]) not in existing]
    if missing:
        job = client.load_table_from_json(missing, table_id)
        job.result()
        if job.errors:
            raise RuntimeError(f"Day 30 BigQuery load failed for {table_id}: {job.errors}")
    observed = sorted(
        (str(item[identity_field]), str(item["row_digest"]))
        for item in client.query(
            f"SELECT `{identity_field}`, row_digest FROM `{table_id}` "
            "WHERE experiment_id=@experiment",
            job_config=config,
        ).result()
    )
    expected = sorted((str(row[identity_field]), str(row["row_digest"])) for row in rows)
    if observed != expected:
        raise RuntimeError(f"Day 30 BigQuery reconciliation failed for {table_id}.")
    return len(observed)


def _row_digest(row: dict[str, Any]) -> str:
    body = dict(row)
    body.pop("recorded_at_utc", None)
    return digest(body)


def main() -> int:
    args = _args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    capture_attempted_at = datetime.now(UTC).isoformat()
    head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if len(head_sha) != 40:
        raise RuntimeError("Day 30 requires an exact Git head SHA.")

    daily_records, calendar_records, source_capture_transport = _capture_sources(
        Path(args.cache_dir), capture_attempted_at
    )
    recorded_at = str(daily_records[0]["first_observed_at"])
    if any(str(row["first_observed_at"]) != recorded_at for row in daily_records):
        raise RuntimeError("Day 30 cached bulletin rows disagree on first-observed time.")
    trade_date = max(str(row["trade_date"]) for row in daily_records)
    source_manifest_digest = digest(
        {
            "daily_source_urls": sorted(
                {
                    str(url)
                    for row in daily_records
                    for url in (row["source_url"], row["final_url"])
                }
            ),
            "bulletin_source_sha256": sorted({row["source_sha256"] for row in daily_records}),
            "calendar_url": CME_GOLD_CALENDAR_DOWNLOAD_URL,
            "calendar_source_sha256": sorted(
                {row["source_document_sha256"] for row in calendar_records}
            ),
        }
    )
    experiment_id = f"day30-cme-public-{trade_date}-{head_sha[:12]}-{source_manifest_digest[:8]}"
    as_of = datetime.fromisoformat(recorded_at)
    state = build_contract_roll_state(
        as_of=as_of,
        daily_records=daily_records,
        calendar_records=calendar_records,
    )
    if not verify_contract_roll_state(state) or state["state"] != "known":
        raise RuntimeError("Day 30 real CME contract state was not PIT-known and verified.")
    active_code = str(state["active_contract"])
    active = next(row for row in daily_records if row["contract_code"] == active_code)
    epoch = market_structure_epoch_at(as_of)
    episode = {
        "trade_date": active["trade_date"],
        "contract_code": active_code,
        "price_change_bps": active["settlement_change_bps"],
        "open_interest_change": active["open_interest_change"],
        "trend_state": "unknown_insufficient_history",
        "market_structure_epoch": epoch["market_structure_epoch"],
        "roll_state": state["roll_state"],
        "next_return_bps": {"1": None, "3": None, "5": None},
    }
    study = run_j6_descriptive([episode])
    if not verify_j6_study(study):
        raise RuntimeError("Day 30 J6 study failed its digest contract.")
    if any(
        horizon["state"] != "insufficient"
        for result in study["quadrant_results"].values()
        for horizon in result["horizons"].values()
    ):
        raise RuntimeError("Day 30 promoted a one-observation J6 result.")

    client, bigquery, not_found = _client(args.project, args.location)
    daily_rows = []
    for item in daily_records:
        row = {
            "experiment_id": experiment_id,
            "base_sha": BASE_SHA,
            "head_sha": head_sha,
            "record_digest": item["record_digest"],
            "trade_date": item["trade_date"],
            "contract_code": item["contract_code"],
            "publication_state": item["publication_state"],
            "daily_payload": item,
            "recorded_at_utc": recorded_at,
        }
        row["row_digest"] = _row_digest(row)
        daily_rows.append(row)
    calendar_rows = []
    relevant_codes = {str(row["contract_code"]) for row in daily_records}
    for item in calendar_records:
        if item["contract_code"] not in relevant_codes:
            continue
        row = {
            "experiment_id": experiment_id,
            "base_sha": BASE_SHA,
            "head_sha": head_sha,
            "calendar_digest": item["calendar_digest"],
            "contract_code": item["contract_code"],
            "first_notice_date": item["first_notice_date"],
            "calendar_payload": item,
            "recorded_at_utc": recorded_at,
        }
        row["row_digest"] = _row_digest(row)
        calendar_rows.append(row)
    j6_rows = []
    for quadrant, result in study["quadrant_results"].items():
        row = {
            "experiment_id": experiment_id,
            "base_sha": BASE_SHA,
            "head_sha": head_sha,
            "quadrant": quadrant,
            "independent_episode_n": result["independent_daily_episode_n"],
            "study_digest": study["study_digest"],
            "quadrant_payload": result,
            "recorded_at_utc": recorded_at,
        }
        row["row_digest"] = _row_digest(row)
        j6_rows.append(row)

    daily_count = _persist(
        client,
        bigquery,
        not_found,
        table_id=f"{args.project}.{args.dataset}.{DAILY_TABLE}",
        fields=[
            ("experiment_id", "STRING", "REQUIRED"),
            ("base_sha", "STRING", "REQUIRED"),
            ("head_sha", "STRING", "REQUIRED"),
            ("record_digest", "STRING", "REQUIRED"),
            ("trade_date", "DATE", "REQUIRED"),
            ("contract_code", "STRING", "REQUIRED"),
            ("publication_state", "STRING", "REQUIRED"),
            ("daily_payload", "JSON", "REQUIRED"),
            ("recorded_at_utc", "TIMESTAMP", "REQUIRED"),
            ("row_digest", "STRING", "REQUIRED"),
        ],
        clustering_fields=("contract_code", "trade_date", "head_sha"),
        rows=daily_rows,
        experiment_id=experiment_id,
        identity_field="record_digest",
    )
    calendar_count = _persist(
        client,
        bigquery,
        not_found,
        table_id=f"{args.project}.{args.dataset}.{CALENDAR_TABLE}",
        fields=[
            ("experiment_id", "STRING", "REQUIRED"),
            ("base_sha", "STRING", "REQUIRED"),
            ("head_sha", "STRING", "REQUIRED"),
            ("calendar_digest", "STRING", "REQUIRED"),
            ("contract_code", "STRING", "REQUIRED"),
            ("first_notice_date", "DATE", "REQUIRED"),
            ("calendar_payload", "JSON", "REQUIRED"),
            ("recorded_at_utc", "TIMESTAMP", "REQUIRED"),
            ("row_digest", "STRING", "REQUIRED"),
        ],
        clustering_fields=("contract_code", "head_sha"),
        rows=calendar_rows,
        experiment_id=experiment_id,
        identity_field="calendar_digest",
    )
    j6_count = _persist(
        client,
        bigquery,
        not_found,
        table_id=f"{args.project}.{args.dataset}.{J6_TABLE}",
        fields=[
            ("experiment_id", "STRING", "REQUIRED"),
            ("base_sha", "STRING", "REQUIRED"),
            ("head_sha", "STRING", "REQUIRED"),
            ("quadrant", "STRING", "REQUIRED"),
            ("independent_episode_n", "INTEGER", "REQUIRED"),
            ("study_digest", "STRING", "REQUIRED"),
            ("quadrant_payload", "JSON", "REQUIRED"),
            ("recorded_at_utc", "TIMESTAMP", "REQUIRED"),
            ("row_digest", "STRING", "REQUIRED"),
        ],
        clustering_fields=("quadrant", "head_sha"),
        rows=j6_rows,
        experiment_id=experiment_id,
        identity_field="quadrant",
    )

    summary: dict[str, Any] = {
        "ok": True,
        "experiment_id": experiment_id,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "changed_files": _changed_files(head_sha),
        "contract_intelligence_version": CME_CONTRACT_INTELLIGENCE_VERSION,
        "daily_record_version": CME_DAILY_RECORD_VERSION,
        "calendar_version": CME_CALENDAR_VERSION,
        "j6_version": J6_VERSION,
        "trade_date": trade_date,
        "official_source_count": 2,
        "official_source_auth_required": False,
        "official_source_paid_api_used": False,
        "official_source_capture_transport": source_capture_transport,
        "official_source_seed_used": (
            source_capture_transport == "checked_in_verified_official_capture"
        ),
        "official_source_manifest_digest": source_manifest_digest,
        "daily_contract_count": len(daily_records),
        "calendar_contract_count": len(calendar_records),
        "contract_state": state,
        "j6": study,
        "j6_current_episode": episode,
        "j6_descriptive_only": True,
        "j6_outcomes_matured": False,
        "historical_bulk_backfilled": False,
        "intraday_open_interest_inferred": False,
        "tas_reference_state": "unknown_not_ingested",
        "trader_intent_inferred": False,
        "predictive_edge_claimed": False,
        "trading_gate_created": False,
        "accepted_prior_modules_modified": False,
        "super_signals_modified": False,
        "bigquery_evidence": {
            "daily_table": DAILY_TABLE,
            "daily_rows_for_experiment": daily_count,
            "calendar_table": CALENDAR_TABLE,
            "calendar_rows_for_experiment": calendar_count,
            "j6_table": J6_TABLE,
            "j6_rows_for_experiment": j6_count,
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
        "summary_payload": summary,
        "recorded_at_utc": recorded_at,
    }
    summary_row["row_digest"] = _row_digest(summary_row)
    _persist(
        client,
        bigquery,
        not_found,
        table_id=f"{args.project}.{args.dataset}.{SUMMARY_TABLE}",
        fields=[
            ("experiment_id", "STRING", "REQUIRED"),
            ("base_sha", "STRING", "REQUIRED"),
            ("head_sha", "STRING", "REQUIRED"),
            ("summary_digest", "STRING", "REQUIRED"),
            ("ok", "BOOLEAN", "REQUIRED"),
            ("summary_payload", "JSON", "REQUIRED"),
            ("recorded_at_utc", "TIMESTAMP", "REQUIRED"),
            ("row_digest", "STRING", "REQUIRED"),
        ],
        clustering_fields=("head_sha",),
        rows=[summary_row],
        experiment_id=experiment_id,
        identity_field="summary_digest",
    )

    _write_jsonl(output / "cme_daily_contracts.jsonl", daily_records)
    _write_jsonl(output / "cme_contract_calendar.jsonl", calendar_records)
    _write_json(output / "contract_roll_state.json", state)
    _write_json(output / "j6_open_interest_study.json", study)
    _write_json(output / "summary.json", summary)
    _write_json(
        output / "contract_reference.json",
        {
            "base_sha": BASE_SHA,
            "head_sha": head_sha,
            "contract": "docs/day30-cme-contract-intelligence-contract.md",
            "official_source_manifest_digest": source_manifest_digest,
            "contract_state_digest": state["contract_state_digest"],
            "study_digest": study["study_digest"],
        },
    )
    print(canonical_json(summary), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
