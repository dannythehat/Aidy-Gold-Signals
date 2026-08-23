from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx

from aidy.macro_event_intelligence import (
    EVENT_CLASSES,
    EVENT_INTELLIGENCE_VERSION,
    EVENT_TIER_STUDY_VERSION,
    PRE_EVENT_FEATURE_VERSION,
    SOURCE_REGISTRY,
    SURPRISE_CAPTURE_VERSION,
    build_event_intelligence_state,
    build_pre_event_features,
    build_schedule_observation,
    build_surprise_state,
    canonical_json,
    digest,
    run_j4_j15_descriptive,
    verify_event_intelligence_state,
    verify_j4_j15_study,
)

BASE_SHA = "de96fd9e56a316a47895e849d8cab8ef125766b1"
DEFAULT_PROJECT = "aidy-signals"
DEFAULT_DATASET = "aidy_analytics_test"
DEFAULT_LOCATION = "EU"
SOURCE_TABLE = "research_day29_official_sources"
CLASS_TABLE = "research_day29_event_tiers"
FEATURE_TABLE = "research_day29_pre_event_features"
SUMMARY_TABLE = "research_day29_summary"
ISM_SCHEDULE_URL = (
    "https://www.ismworld.org/supply-management-news-and-reports/reports/"
    "rob-report-calendar/"
)
ISM_PROBE_URL = (
    "https://www.ismworld.org/globalassets/pub/research-and-surveys/rob/pmi/"
    "mwf4202607pmi.pdf"
)

SOURCE_PROBES = {
    "dol_initial_claims": (
        "https://oui.doleta.gov/unemploy/claims.asp",
        ("unemployment insurance weekly claims data", "initial claims"),
    ),
    "ism_reports": (
        ISM_PROBE_URL,
        ("ism logo", "ismworld.org"),
    ),
    "census_economic_indicators": (
        "https://www.census.gov/economic-indicators/calendar-listview.html",
        ("advance monthly sales", "retail"),
    ),
    "federal_reserve_calendar": (
        "https://www.federalreserve.gov/newsevents/calendar.htm",
        ("fomc", "speeches", "testimony"),
    ),
    "treasury_fiscal_data": (
        "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query?page[size]=1&sort=-auction_date",
        ("auction_date", "security_type"),
    ),
    "ecb_calendar": (
        "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html",
        ("monetary policy meeting", "press conference"),
    ),
    "boj_calendar": (
        "https://www.boj.or.jp/en/about/calendar/index.htm",
        ("monetary policy meeting", "release schedule"),
    ),
    "boe_calendar": (
        "https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates",
        ("mpc summary", "confirmed dates"),
    ),
}


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Day 29 macro-event intelligence acceptance")
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
    parser.add_argument("--output-dir", default="day29_artifacts")
    parser.add_argument("--cache-dir", default=".cache/day29/official_sources")
    return parser.parse_args()


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Day 29 warehouse timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _row(value: Any) -> dict[str, Any]:
    return dict(value.items())


def _changed_files(head_sha: str) -> list[str]:
    output = subprocess.check_output(
        ["git", "diff", "--name-only", f"{BASE_SHA}..{head_sha}"], text=True
    )
    return sorted(line for line in output.splitlines() if line)


def _fetch_sources(cache_dir: Path, recorded_at: str) -> list[dict[str, Any]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    with httpx.Client(
        timeout=httpx.Timeout(45),
        follow_redirects=True,
        headers={"User-Agent": "AIDY-Gold-Signals/Day29 official-source acceptance"},
    ) as client:
        for source_key, (url, required_tokens) in SOURCE_PROBES.items():
            path = cache_dir / f"{source_key}.body"
            metadata_path = cache_dir / f"{source_key}.json"
            cached_for_current_probe = False
            if path.exists() and metadata_path.exists():
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                cached_for_current_probe = metadata.get("requested_url") == url
            if cached_for_current_probe:
                body = path.read_bytes()
                final_url = str(metadata["final_url"])
                status_code = 200
            else:
                response = client.get(url)
                response.raise_for_status()
                body = response.content
                path.write_bytes(body)
                final_url = str(response.url)
                status_code = response.status_code
                metadata_path.write_text(
                    canonical_json({"final_url": final_url, "requested_url": url}) + "\n",
                    encoding="utf-8",
                )
            text = body.decode("utf-8", errors="ignore").lower()
            missing = [token for token in required_tokens if token not in text]
            if missing:
                raise RuntimeError(f"Day 29 official source {source_key} lost tokens: {missing}")
            host = httpx.URL(final_url).host
            if host not in SOURCE_REGISTRY[source_key]["hosts"]:
                raise RuntimeError(f"Day 29 source {source_key} redirected off its allowlist.")
            rows.append(
                {
                    "source_key": source_key,
                    "source_url": url,
                    "final_url": final_url,
                    "status_code": status_code,
                    "transport": "official_https_or_frozen_cache",
                    "body_sha256": sha256(body).hexdigest(),
                    "body_bytes": len(body),
                    "required_tokens": list(required_tokens),
                    "recorded_at_utc": recorded_at,
                }
            )
    return rows


def _load_research_candles(client: Any, bigquery: Any, project: str, dataset: str) -> list[dict[str, Any]]:
    start = datetime(2025, 1, 7, 10, 0, tzinfo=UTC)
    end = datetime(2025, 1, 7, 16, 1, tzinfo=UTC)
    table = f"{project}.{dataset}.research_candles"
    sql = f"""
        SELECT research_identity, provenance_class, pit_eligible, symbol, timeframe,
               open_time_utc, open, high, low, close, source,
               source_file_sha256, source_payload_sha256
        FROM `{table}`
        WHERE source='histdata' AND symbol='XAUUSD' AND timeframe='M1'
          AND open_time_utc >= @start AND open_time_utc < @end
        ORDER BY open_time_utc
    """
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start", "TIMESTAMP", start),
            bigquery.ScalarQueryParameter("end", "TIMESTAMP", end),
        ]
    )
    rows = [_row(item) for item in client.query(sql, job_config=config).result()]
    if len(rows) < 348:
        raise RuntimeError(f"Day 29 bounded HistData cohort is incomplete: {len(rows)} rows.")
    for row in rows:
        row["open_time_utc"] = _utc(row["open_time_utc"]).isoformat()
    return rows


def _historical_episode(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    schedule = build_schedule_observation(
        event_class="ism_services",
        source_key="ism_reports",
        external_id="ism-services-2025-01-07-1000-et",
        scheduled_date=date(2025, 1, 7),
        scheduled_time=time(10, 0),
        timezone_name="America/New_York",
        first_observed_at=datetime(2026, 8, 23, tzinfo=UTC),
        source_url=ISM_SCHEDULE_URL,
        provenance_class="retrospective_official_schedule",
    )
    event_at = _utc(schedule["scheduled_at"])
    pre = build_pre_event_features(schedule=schedule, candle_rows=rows, as_of=event_at)
    if pre["state"] != "known" or pre["future_values_used"] is not False:
        raise RuntimeError("Day 29 real pre-event structure was not PIT-clean and known.")
    by_time = {_utc(item["open_time_utc"]): item for item in rows}
    anchor = float(by_time[event_at - timedelta(minutes=1)]["close"])
    closes = [
        float(by_time[event_at + timedelta(minutes=index)]["close"])
        for index in range(60)
        if event_at + timedelta(minutes=index) in by_time
    ]
    if len(closes) < 48 or anchor <= 0 or any(value <= 0 for value in closes):
        raise RuntimeError("Day 29 post-event descriptive episode lacks coverage.")
    returns = [math.log(right / left) * 10_000 for left, right in zip([anchor, *closes[:-1]], closes)]
    mean = sum(returns) / len(returns)
    realized = math.sqrt(sum((value - mean) ** 2 for value in returns) / (len(returns) - 1))
    outcome = math.log(closes[-1] / anchor) * 10_000
    episode = {
        "event_class": "ism_services",
        "independent_episode_id": "ism-services-2025-01-07",
        "post_abs_return_bps": str(abs(outcome)),
        "post_realized_vol_bps": str(realized),
        "outcome_return_bps": str(outcome),
    }
    return pre, episode


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
    partition_field: str,
    clustering_fields: tuple[str, ...],
) -> None:
    schema = [bigquery.SchemaField(name, kind, mode=mode) for name, kind, mode in fields]
    try:
        existing = client.get_table(table_id)
    except not_found:
        table = bigquery.Table(table_id, schema=schema)
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY, field=partition_field
        )
        table.clustering_fields = list(clustering_fields)
        client.create_table(table)
        return
    actual = [(field.name, field.field_type, field.mode) for field in existing.schema]
    expected = [(field.name, field.field_type, field.mode) for field in schema]
    if actual != expected:
        raise RuntimeError(f"Day 29 BigQuery schema drift for {table_id}.")
    if getattr(existing.time_partitioning, "field", None) != partition_field:
        raise RuntimeError(f"Day 29 BigQuery partition drift for {table_id}.")
    if tuple(existing.clustering_fields or ()) != clustering_fields:
        raise RuntimeError(f"Day 29 BigQuery clustering drift for {table_id}.")


def _persist(
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
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("experiment", "STRING", experiment_id)]
    )
    existing = {
        str(item[identity_field]): str(item["row_digest"])
        for item in client.query(
            f"SELECT `{identity_field}`, row_digest FROM `{table_id}` WHERE experiment_id=@experiment",
            job_config=config,
        ).result()
    }
    for row in rows:
        identity = str(row[identity_field])
        if identity in existing and existing[identity] != row["row_digest"]:
            raise RuntimeError(f"Day 29 immutable evidence conflict in {table_id}.")
    missing = [row for row in rows if str(row[identity_field]) not in existing]
    if missing:
        job = client.load_table_from_json(missing, table_id)
        job.result()
        if job.errors:
            raise RuntimeError(f"Day 29 BigQuery load failed for {table_id}: {job.errors}")
    check = list(
        client.query(
            f"SELECT `{identity_field}`, row_digest FROM `{table_id}` WHERE experiment_id=@experiment ORDER BY `{identity_field}`",
            job_config=config,
        ).result()
    )
    expected = sorted((str(row[identity_field]), str(row["row_digest"])) for row in rows)
    observed = [(str(item[identity_field]), str(item["row_digest"])) for item in check]
    if observed != expected:
        raise RuntimeError(f"Day 29 BigQuery reconciliation failed for {table_id}.")
    return len(observed)


def _write_json(path: Path, value: object) -> None:
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[object]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")


def _row_digest(row: dict[str, Any]) -> str:
    body = dict(row)
    body.pop("recorded_at_utc", None)
    return digest(body)


def main() -> int:
    args = _args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    recorded_at = datetime.now(UTC).isoformat()
    head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if len(head_sha) != 40:
        raise RuntimeError("Day 29 requires an exact Git head SHA.")
    experiment_id = f"day29-tiered-macro-events-20260823-{head_sha[:12]}"

    source_checks = _fetch_sources(Path(args.cache_dir), recorded_at)
    if set(SOURCE_PROBES) != set(SOURCE_REGISTRY):
        raise RuntimeError("Day 29 official source registry and live probes diverged.")
    covered_classes = {
        event_class
        for source_key in source_checks
        for event_class in SOURCE_REGISTRY[str(source_key["source_key"])]["event_classes"]
    }
    if covered_classes != set(EVENT_CLASSES):
        raise RuntimeError("Day 29 live sources do not cover every registered event class.")

    client, bigquery, not_found = _client(args.project, args.location)
    candles = _load_research_candles(client, bigquery, args.project, args.dataset)
    feature, episode = _historical_episode(candles)
    study = run_j4_j15_descriptive([episode])
    if not verify_j4_j15_study(study):
        raise RuntimeError("Day 29 J4/J15 study failed its digest contract.")
    if study["class_results"]["ism_services"]["tier_state"] != "unclassified_insufficient_evidence":
        raise RuntimeError("Day 29 promoted a sparse event class to a severity tier.")

    forward_schedule = build_schedule_observation(
        event_class="ism_services",
        source_key="ism_reports",
        external_id="ism-services-2026-09-03-1000-et",
        scheduled_date=date(2026, 9, 3),
        scheduled_time=time(10, 0),
        timezone_name="America/New_York",
        first_observed_at=datetime(2026, 8, 23, tzinfo=UTC),
        source_url=ISM_SCHEDULE_URL,
    )
    event_state = build_event_intelligence_state(
        as_of=datetime(2026, 8, 23, tzinfo=UTC),
        schedule_records=[forward_schedule],
        tier_study=study,
    )
    if not verify_event_intelligence_state(event_state):
        raise RuntimeError("Day 29 event-intelligence state failed its digest contract.")
    surprise = build_surprise_state(
        schedule=forward_schedule,
        consensus_observations=[],
        actual_observations=[],
        as_of=datetime(2026, 8, 23, tzinfo=UTC),
    )
    if surprise["consensus_state"] != "unknown" or surprise["surprise_state"] != "unknown":
        raise RuntimeError("Day 29 backfilled unavailable historical/forward consensus.")

    source_rows = []
    for item in source_checks:
        source_payload = {
            key: value for key, value in item.items() if key != "recorded_at_utc"
        }
        row = {
            "experiment_id": experiment_id,
            "base_sha": BASE_SHA,
            "head_sha": head_sha,
            **item,
            "source_payload": source_payload,
        }
        row["row_digest"] = _row_digest(row)
        source_rows.append(row)
    class_rows = []
    for event_class, result in study["class_results"].items():
        row = {
            "experiment_id": experiment_id,
            "base_sha": BASE_SHA,
            "head_sha": head_sha,
            "event_class": event_class,
            "independent_episode_n": result["independent_episode_n"],
            "tier_state": result["tier_state"],
            "class_payload": result,
            "study_digest": study["study_digest"],
            "recorded_at_utc": recorded_at,
        }
        row["row_digest"] = _row_digest(row)
        class_rows.append(row)
    feature_row = {
        "experiment_id": experiment_id,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "feature_digest": feature["feature_digest"],
        "event_class": "ism_services",
        "release_at_utc": feature["release_at_utc"],
        "feature_state": feature["state"],
        "feature_payload": feature,
        "recorded_at_utc": recorded_at,
    }
    feature_row["row_digest"] = _row_digest(feature_row)

    source_count = _persist(
        client,
        bigquery,
        not_found,
        table_id=f"{args.project}.{args.dataset}.{SOURCE_TABLE}",
        fields=[
            ("experiment_id", "STRING", "REQUIRED"),
            ("base_sha", "STRING", "REQUIRED"),
            ("head_sha", "STRING", "REQUIRED"),
            ("source_key", "STRING", "REQUIRED"),
            ("source_url", "STRING", "REQUIRED"),
            ("final_url", "STRING", "REQUIRED"),
            ("status_code", "INTEGER", "REQUIRED"),
            ("transport", "STRING", "REQUIRED"),
            ("body_sha256", "STRING", "REQUIRED"),
            ("body_bytes", "INTEGER", "REQUIRED"),
            ("required_tokens", "STRING", "REPEATED"),
            ("recorded_at_utc", "TIMESTAMP", "REQUIRED"),
            ("source_payload", "JSON", "REQUIRED"),
            ("row_digest", "STRING", "REQUIRED"),
        ],
        partition_field="recorded_at_utc",
        clustering_fields=("source_key", "head_sha"),
        rows=source_rows,
        experiment_id=experiment_id,
        identity_field="source_key",
    )
    class_count = _persist(
        client,
        bigquery,
        not_found,
        table_id=f"{args.project}.{args.dataset}.{CLASS_TABLE}",
        fields=[
            ("experiment_id", "STRING", "REQUIRED"),
            ("base_sha", "STRING", "REQUIRED"),
            ("head_sha", "STRING", "REQUIRED"),
            ("event_class", "STRING", "REQUIRED"),
            ("independent_episode_n", "INTEGER", "REQUIRED"),
            ("tier_state", "STRING", "REQUIRED"),
            ("class_payload", "JSON", "REQUIRED"),
            ("study_digest", "STRING", "REQUIRED"),
            ("recorded_at_utc", "TIMESTAMP", "REQUIRED"),
            ("row_digest", "STRING", "REQUIRED"),
        ],
        partition_field="recorded_at_utc",
        clustering_fields=("event_class", "tier_state", "head_sha"),
        rows=class_rows,
        experiment_id=experiment_id,
        identity_field="event_class",
    )
    feature_count = _persist(
        client,
        bigquery,
        not_found,
        table_id=f"{args.project}.{args.dataset}.{FEATURE_TABLE}",
        fields=[
            ("experiment_id", "STRING", "REQUIRED"),
            ("base_sha", "STRING", "REQUIRED"),
            ("head_sha", "STRING", "REQUIRED"),
            ("feature_digest", "STRING", "REQUIRED"),
            ("event_class", "STRING", "REQUIRED"),
            ("release_at_utc", "TIMESTAMP", "REQUIRED"),
            ("feature_state", "STRING", "REQUIRED"),
            ("feature_payload", "JSON", "REQUIRED"),
            ("recorded_at_utc", "TIMESTAMP", "REQUIRED"),
            ("row_digest", "STRING", "REQUIRED"),
        ],
        partition_field="release_at_utc",
        clustering_fields=("event_class", "head_sha"),
        rows=[feature_row],
        experiment_id=experiment_id,
        identity_field="feature_digest",
    )

    summary: dict[str, Any] = {
        "ok": True,
        "experiment_id": experiment_id,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "changed_files": _changed_files(head_sha),
        "event_intelligence_version": EVENT_INTELLIGENCE_VERSION,
        "event_tier_study_version": EVENT_TIER_STUDY_VERSION,
        "pre_event_feature_version": PRE_EVENT_FEATURE_VERSION,
        "surprise_capture_version": SURPRISE_CAPTURE_VERSION,
        "registered_event_classes": list(EVENT_CLASSES),
        "official_source_count": len(source_checks),
        "official_source_manifest_digest": digest(
            [{key: value for key, value in row.items() if key != "recorded_at_utc"} for row in source_checks]
        ),
        "official_source_auth_required": False,
        "official_source_paid_api_used": False,
        "official_schedule_utc_dst_safe": True,
        "j4_j15": study,
        "j4_j15_descriptive_only": True,
        "tiering_uses_trade_pnl": False,
        "tiering_sparse_class_promoted": False,
        "historical_independent_episode_count": 1,
        "pre_event_feature_state": feature["state"],
        "pre_event_future_values_used": False,
        "forward_schedule_state": event_state,
        "forward_consensus_state": surprise["consensus_state"],
        "forward_surprise_state": surprise["surprise_state"],
        "historical_consensus_backfilled": False,
        "first_print_revision_contract_enabled": True,
        "predictive_edge_claimed": False,
        "trading_gate_created": False,
        "accepted_prior_modules_modified": False,
        "super_signals_modified": False,
        "bigquery_evidence": {
            "source_table": SOURCE_TABLE,
            "source_rows_for_experiment": source_count,
            "class_table": CLASS_TABLE,
            "class_rows_for_experiment": class_count,
            "feature_table": FEATURE_TABLE,
            "feature_rows_for_experiment": feature_count,
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
        partition_field="recorded_at_utc",
        clustering_fields=("head_sha",),
        rows=[summary_row],
        experiment_id=experiment_id,
        identity_field="summary_digest",
    )

    _write_jsonl(output / "official_sources.jsonl", source_checks)
    _write_json(output / "j4_j15_study.json", study)
    _write_json(output / "pre_event_feature.json", feature)
    _write_json(output / "forward_schedule.json", forward_schedule)
    _write_json(output / "forward_surprise_state.json", surprise)
    _write_json(output / "summary.json", summary)
    _write_json(
        output / "contract_reference.json",
        {
            "base_sha": BASE_SHA,
            "head_sha": head_sha,
            "contract": "docs/day29-tiered-macro-event-intelligence-contract.md",
            "official_source_manifest_digest": summary["official_source_manifest_digest"],
            "study_digest": study["study_digest"],
        },
    )
    print(canonical_json(summary), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
