from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aidy.day23_research import realized_dispersion
from aidy.evaluation_scoring import (
    build_j16_grade_validity_report,
    build_j21_setup_differentiation_report,
    canonical_json,
    digest,
    evaluation_manifest,
)
from aidy.setup_detector import SETUP_DEFINITIONS, SETUP_TAXONOMY_VERSION

BASE_SHA = "d800f417c8a93671875ed22378ef01eb8018c3c6"
DAY23_EXPERIMENT = "day23-j1-j16-baseline-20260821-v1"
DAY24_EXPERIMENT = "day24-independent-episode-retrieval-20260822-v1"
DAY23_MANIFEST_DIGEST = "119d8c2a1a11cba44d8195fff81be640f7b9c084d0d7b8c28a61dedfa64e5ac5"
CANDIDATE_DIGEST = "bd3c81b54ec05b2150e6e6ecbdffbc3c1e4f943c6a23c9a8ee4977c1dc1c3a88"
QUERY_COUNT = 1000
DEFAULT_DATASET = "aidy_analytics_test"
DEFAULT_LOCATION = "EU"
SUMMARY_TABLE = "research_day38_evaluation_summary"
EXPERIMENT = "day38-evaluation-scorers-j16-j21-20260901-v1"

DIRECTIONS = {
    str(item["setup_id"]): str(item["direction"]) for item in SETUP_DEFINITIONS
}


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Day 38 genuine warehouse evaluation")
    parser.add_argument("--project", default=os.environ.get("AIDY_GCP_PROJECT_ID"))
    parser.add_argument(
        "--dataset", default=os.environ.get("AIDY_BIGQUERY_DATASET", DEFAULT_DATASET)
    )
    parser.add_argument(
        "--location", default=os.environ.get("AIDY_BIGQUERY_LOCATION", DEFAULT_LOCATION)
    )
    parser.add_argument("--output-dir", default="day38_artifacts")
    return parser.parse_args()


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Day 38 timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    decoded = json.loads(value) if isinstance(value, str) else None
    if not isinstance(decoded, dict):
        raise TypeError("Expected JSON object.")
    return decoded


def _row(value: Any) -> dict[str, Any]:
    return dict(value.items())


def _query_config(bigquery: Any, pairs: list[tuple[str, str, Any]]) -> Any:
    return bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(name, kind, value)
            for name, kind, value in pairs
        ]
    )


def _load_day24_results(
    client: Any, bigquery: Any, project: str, dataset: str
) -> list[dict[str, Any]]:
    table = f"{project}.{dataset}.research_day24_retrieval_results"
    config = _query_config(
        bigquery,
        [
            ("experiment", "STRING", DAY24_EXPERIMENT),
            ("manifest", "STRING", DAY23_MANIFEST_DIGEST),
        ],
    )
    rows = list(
        client.query(
            f"""SELECT query_index, query_id, payload_digest, result_payload
                FROM `{table}`
                WHERE experiment_id=@experiment AND manifest_digest=@manifest
                ORDER BY query_index""",
            job_config=config,
        ).result()
    )
    if len(rows) != QUERY_COUNT:
        raise SystemExit(
            f"Expected {QUERY_COUNT} accepted Day-24 rows, found {len(rows)}."
        )
    results = []
    ids = set()
    for raw in rows:
        payload = _object(raw["result_payload"])
        payload_digest = str(raw["payload_digest"])
        supplied = str(payload.get("result_digest") or "")
        body = dict(payload)
        body.pop("result_digest", None)
        if not supplied or supplied != payload_digest or supplied != digest(body):
            raise SystemExit("Day-24 immutable result payload digest mismatch.")
        query_id = str(payload["query_id"])
        if query_id != str(raw["query_id"]) or query_id in ids:
            raise SystemExit("Day-24 query identity mismatch or duplicate.")
        ids.add(query_id)
        results.append(payload)
    return results


def _load_frozen_cases(client: Any, project: str, dataset: str) -> list[dict[str, Any]]:
    table = f"{project}.{dataset}.research_gold_cases"
    sql = f"""SELECT case_digest, case_version, case_id, symbol, as_of_utc,
                     provenance_class, input_digest, feature_definition_version,
                     regime_definition_version, setup_taxonomy_version,
                     setup_detector_version, data_quality_grade, regime_key,
                     detector_state, candidate_setup_ids, future_available_after_utc,
                     input_boundary, future_evaluation
              FROM `{table}` WHERE symbol='XAUUSD' ORDER BY as_of_utc, case_id"""
    rows = [_row(item) for item in client.query(sql).result()]
    snapshot = [
        {
            "case_id": str(item["case_id"]),
            "case_digest": str(item["case_digest"]),
            "input_digest": str(item["input_digest"]),
            "as_of_utc": _utc(item["as_of_utc"]).isoformat(),
            "future_available_after_utc": (
                None
                if item.get("future_available_after_utc") is None
                else _utc(item["future_available_after_utc"]).isoformat()
            ),
            "provenance_class": str(item["provenance_class"]),
            "data_quality_grade": str(item["data_quality_grade"]),
        }
        for item in rows
    ]
    if digest(snapshot) != CANDIDATE_DIGEST:
        raise SystemExit("Frozen candidate case store changed since accepted Day 24.")
    return rows


def _move_240(future: dict[str, Any]) -> dict[str, Any] | None:
    bundle = future.get("move_bundle")
    if not isinstance(bundle, dict):
        return None
    labels = bundle.get("labels")
    if not isinstance(labels, list):
        return None
    for label in labels:
        if (
            isinstance(label, dict)
            and int(label.get("horizon_minutes", -1)) == 240
            and label.get("coverage_state") == "complete"
        ):
            return label
    return None


def _j16_rows(
    day24_results: list[dict[str, Any]],
    frozen_cases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    case_map = {
        str(row["case_id"]): {
            "case_id": str(row["case_id"]),
            "future_evaluation": _object(row["future_evaluation"]),
        }
        for row in frozen_cases
    }
    output = []
    for result in day24_results:
        selected_ids = [str(item) for item in result["selected_case_ids"]]
        if len(selected_ids) != len(set(selected_ids)):
            raise SystemExit(
                "Day-24 selected case IDs must remain unique after episode dedup."
            )
        try:
            matches = [case_map[case_id] for case_id in selected_ids]
        except KeyError as exc:
            raise SystemExit(
                f"Day-24 selected case missing from frozen store: {exc}"
            ) from exc
        dispersion = realized_dispersion(matches)
        if int(dispersion["outcome_n_240m"]) > int(result["grading_effective_n"]):
            raise SystemExit(
                "J16 outcome count cannot exceed Day-24 grading effective N."
            )
        output.append(
            {
                "query_id": result["query_id"],
                "as_of_utc": result["query_as_of_utc"],
                "dataset_grade": result["dataset_grade"],
                "raw_n": int(result["pre_dedup_raw_n"]),
                "effective_n": int(result["grading_effective_n"]),
                "terminal_return_stddev_bps": dispersion[
                    "terminal_return_stddev_bps"
                ],
                "terminal_return_iqr_bps": dispersion["terminal_return_iqr_bps"],
                "terminal_return_mad_bps": dispersion["terminal_return_mad_bps"],
                "outcome_n_240m": dispersion["outcome_n_240m"],
            }
        )
    return output


def _j21_rows(frozen_cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in frozen_cases:
        if str(row.get("detector_state") or "") != "single":
            continue
        candidate_ids = [str(item) for item in (row.get("candidate_setup_ids") or [])]
        if len(candidate_ids) != 1:
            continue
        setup_id = candidate_ids[0]
        if setup_id not in DIRECTIONS:
            raise SystemExit(f"Unknown setup in frozen case store: {setup_id}")
        if str(row.get("setup_taxonomy_version") or "") != SETUP_TAXONOMY_VERSION:
            raise SystemExit("Frozen case setup taxonomy version drifted.")

        future = _object(row["future_evaluation"])
        label = _move_240(future)
        if label is None:
            continue
        path_stats = label.get("path_stats")
        if not isinstance(path_stats, dict) or path_stats.get("terminal_return_bps") is None:
            continue
        boundary = _object(row["input_boundary"])
        regime = boundary.get("regime")
        if not isinstance(regime, dict):
            continue
        labels = regime.get("labels")
        if not isinstance(labels, dict):
            continue
        regime_key = (
            f"trend={labels.get('trend_structure', 'unknown')}|"
            f"vol={labels.get('volatility_band', 'unknown')}"
        )
        output.append(
            {
                "case_id": str(row["case_id"]),
                "as_of_utc": _utc(row["as_of_utc"]).isoformat(),
                "setup_id": setup_id,
                "taxonomy_version": SETUP_TAXONOMY_VERSION,
                "direction": DIRECTIONS[setup_id],
                "regime": regime_key,
                "session": str(labels.get("session") or "unknown"),
                "terminal_return_bps": str(path_stats["terminal_return_bps"]),
            }
        )
    if not output:
        raise SystemExit("No single-setup complete-outcome cases available for J21.")
    return output


def _ensure_summary_table(
    client: Any, bigquery: Any, not_found: type[Exception], table_id: str
) -> None:
    schema = [
        bigquery.SchemaField("experiment_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("base_sha", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("head_sha", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("payload_digest", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("summary_payload", "JSON", mode="REQUIRED"),
        bigquery.SchemaField("recorded_at_utc", "TIMESTAMP", mode="REQUIRED"),
    ]
    try:
        table = client.get_table(table_id)
    except not_found:
        client.create_table(bigquery.Table(table_id, schema=schema))
        return
    actual = [(field.name, field.field_type, field.mode) for field in table.schema]
    expected = [(field.name, field.field_type, field.mode) for field in schema]
    if actual != expected:
        raise RuntimeError(f"BigQuery schema drift for {table_id}.")


def _persist_summary(
    client: Any,
    bigquery: Any,
    not_found: type[Exception],
    table_id: str,
    summary: dict[str, Any],
) -> None:
    _ensure_summary_table(client, bigquery, not_found, table_id)
    config = _query_config(bigquery, [("experiment", "STRING", EXPERIMENT)])
    existing = list(
        client.query(
            f"""SELECT payload_digest, summary_payload
                FROM `{table_id}` WHERE experiment_id=@experiment""",
            job_config=config,
        ).result()
    )
    if len(existing) > 1:
        raise RuntimeError("Day-38 immutable summary is duplicated.")
    if existing:
        if str(existing[0]["payload_digest"]) != summary["summary_digest"]:
            raise RuntimeError("Day-38 immutable summary conflict.")
        if canonical_json(_object(existing[0]["summary_payload"])) != canonical_json(
            summary
        ):
            raise RuntimeError("Day-38 immutable summary payload drift.")
        return
    errors = client.insert_rows_json(
        table_id,
        [
            {
                "experiment_id": EXPERIMENT,
                "base_sha": summary["base_sha"],
                "head_sha": summary["head_sha"],
                "payload_digest": summary["summary_digest"],
                "summary_payload": summary,
                "recorded_at_utc": datetime.now(UTC).isoformat(),
            }
        ],
    )
    if errors:
        raise RuntimeError(f"Day-38 BigQuery summary insert failed: {errors}")


def main() -> int:
    args = _args()
    if not args.project:
        raise SystemExit("AIDY_GCP_PROJECT_ID or --project is required.")
    secret = os.environ.get("AIDY_GCP_SERVICE_ACCOUNT_JSON")
    if not secret:
        raise SystemExit("AIDY_GCP_SERVICE_ACCOUNT_JSON is required.")

    from google.api_core.exceptions import NotFound
    from google.cloud import bigquery
    from google.oauth2 import service_account

    credentials = service_account.Credentials.from_service_account_info(json.loads(secret))
    client = bigquery.Client(
        project=args.project, credentials=credentials, location=args.location
    )
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()

    day24_results = _load_day24_results(client, bigquery, args.project, args.dataset)
    frozen_cases = _load_frozen_cases(client, args.project, args.dataset)
    j16_input = _j16_rows(day24_results, frozen_cases)
    j21_input = _j21_rows(frozen_cases)

    j16 = build_j16_grade_validity_report(
        j16_input,
        evaluation_set_identity=(
            f"{DAY24_EXPERIMENT}:{DAY23_MANIFEST_DIGEST}:{CANDIDATE_DIGEST}"
        ),
    )
    j21 = build_j21_setup_differentiation_report(
        j21_input,
        evaluation_set_identity=f"research_gold_cases:{CANDIDATE_DIGEST}",
    )
    manifest = evaluation_manifest()
    summary: dict[str, Any] = {
        "ok": True,
        "experiment_id": EXPERIMENT,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "day23_experiment_id": DAY23_EXPERIMENT,
        "day24_experiment_id": DAY24_EXPERIMENT,
        "frozen_query_manifest_digest": DAY23_MANIFEST_DIGEST,
        "frozen_candidate_store_digest": CANDIDATE_DIGEST,
        "frozen_day24_query_count": len(day24_results),
        "candidate_store_row_count": len(frozen_cases),
        "j16_input_query_count": len(j16_input),
        "j21_single_setup_complete_outcome_case_count": len(j21_input),
        "evaluation_manifest": manifest,
        "j16": j16,
        "j21": j21,
        "j16_actual_frozen_day24_warehouse_evaluation": True,
        "j21_actual_frozen_case_store_evaluation": True,
        "j16_pass_required_for_day38_architecture_acceptance": False,
        "j21_differentiation_required_for_day38_architecture_acceptance": False,
        "null_and_inconclusive_scientific_results_retained": True,
        "outcome_values_used_to_define_setup_labels": False,
        "evaluation_episode_selection_uses_outcome_values": False,
        "predictive_edge_claimed": False,
        "trading_gate_created": False,
        "telegram_side_effects_allowed": False,
        "broker_side_effects_allowed": False,
        "super_signals_side_effects_allowed": False,
        "bigquery_evidence": {"summary_table": SUMMARY_TABLE},
    }
    summary["summary_digest"] = digest(summary)

    (output / "evaluation_manifest.json").write_text(
        canonical_json(manifest) + "\n", encoding="utf-8"
    )
    (output / "j16_post_hardening.json").write_text(
        canonical_json(j16) + "\n", encoding="utf-8"
    )
    (output / "j21_setup_differentiation.json").write_text(
        canonical_json(j21) + "\n", encoding="utf-8"
    )
    (output / "summary.json").write_text(
        canonical_json(summary) + "\n", encoding="utf-8"
    )

    _persist_summary(
        client,
        bigquery,
        NotFound,
        f"{args.project}.{args.dataset}.{SUMMARY_TABLE}",
        summary,
    )
    print(canonical_json(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
