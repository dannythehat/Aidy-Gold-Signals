from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aidy.volatility_intelligence import (
    CBOE_GVZ_DASHBOARD_URL,
    CBOE_GVZ_HISTORY_URL,
    CBOE_GVZ_METHODOLOGY_NOTICE_URL,
    GVZ_RECORD_VERSION,
    J7_J8_FOUNDATION_VERSION,
    VOLATILITY_INTELLIGENCE_VERSION,
    CboeGvzGateway,
    build_j7_j8_foundation,
    build_volatility_state,
    canonical_json,
    digest,
    select_gvz_as_of,
    select_gvz_research_anchor,
    verify_gvz_record,
    verify_j7_j8_foundation,
    verify_volatility_state,
)

BASE_SHA = "a380932a2ad7ca0a26538c0b2fa2e846f0c77864"
DEFAULT_PROJECT = "aidy-signals"
DEFAULT_DATASET = "aidy_analytics_test"
DEFAULT_LOCATION = "EU"

GVZ_TABLE = "research_day31_gvz_observations"
STATE_TABLE = "research_day31_volatility_state"
FOUNDATION_TABLE = "research_day31_j7_j8_foundation"
SUMMARY_TABLE = "research_day31_summary"

RESEARCH_START = datetime(2025, 11, 20, tzinfo=UTC)
RESEARCH_END = datetime(2025, 12, 31, tzinfo=UTC)
RESEARCH_ANCHOR_MAX = "2025-12-30"


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Day 31 GVZ volatility intelligence acceptance")
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
    parser.add_argument("--output-dir", default="day31_artifacts")
    parser.add_argument("--cache-dir", default=".cache/day31/cboe_gvz")
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
            f"Day 31 acceptance clone lacks base {BASE_SHA}; fetch full history before retrying."
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


def _capture_gvz(cache_dir: Path, first_observed_at: str) -> tuple[list[dict[str, Any]], str]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    records_path = cache_dir / "gvz_observations.jsonl"
    transport_path = cache_dir / "capture_transport.json"
    if records_path.exists():
        records = _read_jsonl(records_path)
        transport = (
            str(json.loads(transport_path.read_text(encoding="utf-8"))["transport"])
            if transport_path.exists()
            else "cached_official_https"
        )
    else:
        records = CboeGvzGateway().fetch_history(first_observed_at=first_observed_at)
        transport = "official_https"
        _write_jsonl(records_path, records)
        _write_json(transport_path, {"transport": transport})
    if not records or not all(verify_gvz_record(row) for row in records):
        raise RuntimeError("Day 31 GVZ capture failed its immutable record contract.")
    if len({str(row["source_snapshot_sha256"]) for row in records}) != 1:
        raise RuntimeError("Day 31 GVZ capture unexpectedly contains multiple source snapshots.")
    return records, transport


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


def _row(value: Any) -> dict[str, Any]:
    if hasattr(value, "items"):
        return dict(value.items())
    return dict(value)


def _load_research_candles(
    client: Any, bigquery: Any, project: str, dataset: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    table = f"{project}.{dataset}.research_candles"
    sql = f"""
        SELECT research_identity, provenance_class, pit_eligible, symbol, timeframe,
               open_time_utc, close, source
        FROM `{table}`
        WHERE source='histdata' AND symbol='XAUUSD'
          AND timeframe IN ('M1', 'D1')
          AND open_time_utc >= @start AND open_time_utc < @end
        ORDER BY timeframe, open_time_utc
    """
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start", "TIMESTAMP", RESEARCH_START),
            bigquery.ScalarQueryParameter("end", "TIMESTAMP", RESEARCH_END),
        ]
    )
    rows = [_row(item) for item in client.query(sql, job_config=config).result()]
    for item in rows:
        value = item["open_time_utc"]
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        item["open_time_utc"] = parsed.astimezone(UTC).isoformat()
    daily = [item for item in rows if item["timeframe"] == "D1"]
    intraday = [item for item in rows if item["timeframe"] == "M1"]
    if len(daily) < 22:
        raise RuntimeError(f"Day 31 bounded D1 research cohort is incomplete: {len(daily)} rows.")
    if len(intraday) < 6_000:
        raise RuntimeError(
            f"Day 31 bounded M1 research cohort is incomplete: {len(intraday)} rows."
        )
    return daily, intraday


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
        raise RuntimeError(f"Day 31 BigQuery schema drift for {table_id}.")
    if getattr(existing.time_partitioning, "field", None) != "recorded_at_utc":
        raise RuntimeError(f"Day 31 BigQuery partition drift for {table_id}.")
    if tuple(existing.clustering_fields or ()) != clustering_fields:
        raise RuntimeError(f"Day 31 BigQuery clustering drift for {table_id}.")


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
            raise RuntimeError(f"Day 31 immutable evidence conflict in {table_id}.")
    missing = [row for row in rows if str(row[identity_field]) not in existing]
    if missing:
        job = client.load_table_from_json(missing, table_id)
        job.result()
        if job.errors:
            raise RuntimeError(f"Day 31 BigQuery load failed for {table_id}: {job.errors}")
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
        raise RuntimeError(f"Day 31 BigQuery reconciliation failed for {table_id}.")
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
        raise RuntimeError("Day 31 requires an exact Git head SHA.")

    gvz_records, source_transport = _capture_gvz(
        Path(args.cache_dir), capture_attempted_at
    )
    recorded_at = str(gvz_records[0]["first_observed_at"])
    if any(str(item["first_observed_at"]) != recorded_at for item in gvz_records):
        raise RuntimeError("Day 31 GVZ rows disagree on first-observed time.")
    as_of = datetime.fromisoformat(recorded_at)
    current_gvz = select_gvz_as_of(gvz_records, as_of=as_of)
    if current_gvz is None:
        raise RuntimeError("Day 31 current GVZ was not PIT-known after official capture.")
    current_state = build_volatility_state(
        as_of=as_of,
        gvz_record=current_gvz,
        daily_candles=[],
        intraday_candles=[],
        mode="pit",
    )
    if not verify_volatility_state(current_state):
        raise RuntimeError("Day 31 current volatility state failed its digest contract.")
    if current_state["gvz"]["state"] != "known":
        raise RuntimeError("Day 31 failed to make official current GVZ known.")
    if current_state["realized_volatility"]["state"] != "unknown_insufficient_daily_history":
        raise RuntimeError("Day 31 fabricated missing forward XAUUSD realised volatility.")

    client, bigquery, not_found = _client(args.project, args.location)
    daily, intraday = _load_research_candles(client, bigquery, args.project, args.dataset)
    research_gvz = select_gvz_research_anchor(
        gvz_records, anchor_date=RESEARCH_ANCHOR_MAX
    )
    if research_gvz is None:
        raise RuntimeError("Day 31 official GVZ history does not cover the frozen research anchor.")
    research_anchor = str(research_gvz["observation_date"])
    research_state = build_volatility_state(
        as_of=as_of,
        gvz_record=research_gvz,
        daily_candles=daily,
        intraday_candles=intraday,
        mode="retrospective_research",
        anchor_date=research_anchor,
    )
    if not verify_volatility_state(research_state) or research_state["state"] != "known":
        raise RuntimeError("Day 31 frozen retrospective volatility state was not fully known.")
    if research_state["decision_input_allowed"] is not False:
        raise RuntimeError("Day 31 retrospective volatility state entered the decision surface.")
    foundation = build_j7_j8_foundation()
    if not verify_j7_j8_foundation(foundation):
        raise RuntimeError("Day 31 J7/J8 foundation failed its digest contract.")

    source_snapshot_sha = str(gvz_records[0]["source_snapshot_sha256"])
    experiment_id = (
        f"day31-gvz-volatility-{current_gvz['observation_date']}-"
        f"{head_sha[:12]}-{source_snapshot_sha[:8]}"
    )

    gvz_rows = []
    for item in gvz_records:
        row = {
            "experiment_id": experiment_id,
            "base_sha": BASE_SHA,
            "head_sha": head_sha,
            "record_digest": item["record_digest"],
            "observation_date": item["observation_date"],
            "gvz_value": item["value"],
            "source_snapshot_sha256": item["source_snapshot_sha256"],
            "gvz_payload": item,
            "recorded_at_utc": recorded_at,
        }
        row["row_digest"] = _row_digest(row)
        gvz_rows.append(row)
    state_rows = []
    for state_key, item in (("current_pit", current_state), ("retrospective_research", research_state)):
        row = {
            "experiment_id": experiment_id,
            "base_sha": BASE_SHA,
            "head_sha": head_sha,
            "state_key": state_key,
            "mode": item["mode"],
            "anchor_date": item["anchor_date"],
            "volatility_state_digest": item["volatility_state_digest"],
            "state_payload": item,
            "recorded_at_utc": recorded_at,
        }
        row["row_digest"] = _row_digest(row)
        state_rows.append(row)
    foundation_row = {
        "experiment_id": experiment_id,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "foundation_version": foundation["foundation_version"],
        "foundation_digest": foundation["foundation_digest"],
        "foundation_payload": foundation,
        "recorded_at_utc": recorded_at,
    }
    foundation_row["row_digest"] = _row_digest(foundation_row)

    gvz_count = _persist(
        client,
        bigquery,
        not_found,
        table_id=f"{args.project}.{args.dataset}.{GVZ_TABLE}",
        fields=[
            ("experiment_id", "STRING", "REQUIRED"),
            ("base_sha", "STRING", "REQUIRED"),
            ("head_sha", "STRING", "REQUIRED"),
            ("record_digest", "STRING", "REQUIRED"),
            ("observation_date", "DATE", "REQUIRED"),
            ("gvz_value", "NUMERIC", "REQUIRED"),
            ("source_snapshot_sha256", "STRING", "REQUIRED"),
            ("gvz_payload", "JSON", "REQUIRED"),
            ("recorded_at_utc", "TIMESTAMP", "REQUIRED"),
            ("row_digest", "STRING", "REQUIRED"),
        ],
        clustering_fields=("observation_date", "head_sha"),
        rows=gvz_rows,
        experiment_id=experiment_id,
        identity_field="record_digest",
    )
    state_count = _persist(
        client,
        bigquery,
        not_found,
        table_id=f"{args.project}.{args.dataset}.{STATE_TABLE}",
        fields=[
            ("experiment_id", "STRING", "REQUIRED"),
            ("base_sha", "STRING", "REQUIRED"),
            ("head_sha", "STRING", "REQUIRED"),
            ("state_key", "STRING", "REQUIRED"),
            ("mode", "STRING", "REQUIRED"),
            ("anchor_date", "DATE", "REQUIRED"),
            ("volatility_state_digest", "STRING", "REQUIRED"),
            ("state_payload", "JSON", "REQUIRED"),
            ("recorded_at_utc", "TIMESTAMP", "REQUIRED"),
            ("row_digest", "STRING", "REQUIRED"),
        ],
        clustering_fields=("state_key", "head_sha"),
        rows=state_rows,
        experiment_id=experiment_id,
        identity_field="state_key",
    )
    foundation_count = _persist(
        client,
        bigquery,
        not_found,
        table_id=f"{args.project}.{args.dataset}.{FOUNDATION_TABLE}",
        fields=[
            ("experiment_id", "STRING", "REQUIRED"),
            ("base_sha", "STRING", "REQUIRED"),
            ("head_sha", "STRING", "REQUIRED"),
            ("foundation_version", "STRING", "REQUIRED"),
            ("foundation_digest", "STRING", "REQUIRED"),
            ("foundation_payload", "JSON", "REQUIRED"),
            ("recorded_at_utc", "TIMESTAMP", "REQUIRED"),
            ("row_digest", "STRING", "REQUIRED"),
        ],
        clustering_fields=("foundation_version", "head_sha"),
        rows=[foundation_row],
        experiment_id=experiment_id,
        identity_field="foundation_version",
    )

    changed_files = _changed_files(head_sha)
    accepted_prior_modules_modified = any(
        path.startswith("src/aidy/")
        and path not in {"src/aidy/volatility_intelligence.py", "src/aidy/context_packet_v7.py"}
        for path in changed_files
    )
    super_signals_modified = any("super" in path.lower() and "signal" in path.lower() for path in changed_files)
    source_manifest = {
        "source_url": CBOE_GVZ_HISTORY_URL,
        "dashboard_url": CBOE_GVZ_DASHBOARD_URL,
        "methodology_notice_url": CBOE_GVZ_METHODOLOGY_NOTICE_URL,
        "source_snapshot_sha256": source_snapshot_sha,
        "source_last_modified_at": gvz_records[0]["source_last_modified_at"],
        "first_observed_at": recorded_at,
        "capture_transport": source_transport,
        "record_count": len(gvz_records),
        "earliest_observation_date": gvz_records[0]["observation_date"],
        "latest_observation_date": gvz_records[-1]["observation_date"],
        "historical_row_release_times_known": False,
        "authentication_required": False,
        "paid_api_used": False,
    }
    source_manifest["source_manifest_digest"] = digest(source_manifest)

    summary: dict[str, Any] = {
        "ok": True,
        "experiment_id": experiment_id,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "changed_files": changed_files,
        "accepted_prior_modules_modified": accepted_prior_modules_modified,
        "super_signals_modified": super_signals_modified,
        "volatility_intelligence_version": VOLATILITY_INTELLIGENCE_VERSION,
        "gvz_record_version": GVZ_RECORD_VERSION,
        "j7_j8_foundation_version": J7_J8_FOUNDATION_VERSION,
        "official_source_count": 1,
        "official_source_auth_required": False,
        "official_source_paid_api_used": False,
        "official_source_capture_transport": source_transport,
        "source_manifest_digest": source_manifest["source_manifest_digest"],
        "gvz_record_count": len(gvz_records),
        "gvz_latest_observation_date": current_gvz["observation_date"],
        "gvz_latest_value_annualized_percent": current_gvz["value"],
        "historical_row_release_times_known": False,
        "current_state": current_state,
        "current_realized_volatility_known": False,
        "retrospective_research_state": research_state,
        "retrospective_decision_input_allowed": False,
        "j7_j8_foundation": foundation,
        "j7_j8_formal_test_run": False,
        "cme_cvol_state": "deferred_pending_evidence_and_owner_approval",
        "predictive_edge_claimed": False,
        "trading_gate_created": False,
        "bigquery_evidence": {
            "gvz_table": GVZ_TABLE,
            "gvz_rows_for_experiment": gvz_count,
            "state_table": STATE_TABLE,
            "state_rows_for_experiment": state_count,
            "foundation_table": FOUNDATION_TABLE,
            "foundation_rows_for_experiment": foundation_count,
            "summary_table": SUMMARY_TABLE,
            "summary_rows_for_experiment": 1,
        },
    }
    if accepted_prior_modules_modified or super_signals_modified:
        raise RuntimeError("Day 31 changed an accepted prior module or Super Signals surface.")
    summary["summary_digest"] = digest(summary)

    summary_row = {
        "experiment_id": experiment_id,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "summary_digest": summary["summary_digest"],
        "summary_payload": summary,
        "recorded_at_utc": recorded_at,
    }
    summary_row["row_digest"] = _row_digest(summary_row)
    summary_count = _persist(
        client,
        bigquery,
        not_found,
        table_id=f"{args.project}.{args.dataset}.{SUMMARY_TABLE}",
        fields=[
            ("experiment_id", "STRING", "REQUIRED"),
            ("base_sha", "STRING", "REQUIRED"),
            ("head_sha", "STRING", "REQUIRED"),
            ("summary_digest", "STRING", "REQUIRED"),
            ("summary_payload", "JSON", "REQUIRED"),
            ("recorded_at_utc", "TIMESTAMP", "REQUIRED"),
            ("row_digest", "STRING", "REQUIRED"),
        ],
        clustering_fields=("head_sha",),
        rows=[summary_row],
        experiment_id=experiment_id,
        identity_field="summary_digest",
    )
    if summary_count != 1:
        raise RuntimeError("Day 31 summary reconciliation returned an unexpected row count.")

    _write_jsonl(output / "gvz_observations.jsonl", gvz_records)
    _write_json(output / "current_volatility_state.json", current_state)
    _write_json(output / "retrospective_volatility_state.json", research_state)
    _write_json(output / "j7_j8_foundation.json", foundation)
    _write_json(output / "source_manifest.json", source_manifest)
    _write_json(output / "summary.json", summary)
    print(canonical_json(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
