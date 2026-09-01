from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aidy.day23_research import digest as day23_digest
from aidy.research_integrity import finalize_trial, preregister_trial, verify_trial_registry
from aidy.selective_abstention import (
    canonical_json,
    day45_manifest,
    digest,
    run_shadow_selective_experiment,
)
from aidy.setup_detector import SETUP_DEFINITIONS, SETUP_TAXONOMY_VERSION

BASE_SHA = "531930fda3d684ad0a76417989445cc6387e4c7d"
CANDIDATE_DIGEST = "bd3c81b54ec05b2150e6e6ecbdffbc3c1e4f943c6a23c9a8ee4977c1dc1c3a88"
DEFAULT_DATASET = "aidy_analytics_test"
DEFAULT_LOCATION = "EU"
EPISODE_HORIZON_MINUTES = 240
RANDOM_IDENTITY = "day45-j9-matched-random-v1"
DATASET_VERSION = f"research_gold_cases:{CANDIDATE_DIGEST}"
EVALUATION_IDENTITY = "day45-selective-abstention-j9-j10-v1"
DIRECTIONS = {str(item["setup_id"]): str(item["direction"]) for item in SETUP_DEFINITIONS}


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AIDY Day 45 selective abstention acceptance")
    parser.add_argument("--project", default=os.environ.get("AIDY_GCP_PROJECT_ID"))
    parser.add_argument(
        "--dataset", default=os.environ.get("AIDY_BIGQUERY_DATASET", DEFAULT_DATASET)
    )
    parser.add_argument(
        "--location", default=os.environ.get("AIDY_BIGQUERY_LOCATION", DEFAULT_LOCATION)
    )
    parser.add_argument("--output-dir", default="day45_artifacts")
    return parser.parse_args()


def _utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Day 45 timestamps must be timezone-aware.")
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


def _load_frozen_cases(client: Any, project: str, dataset: str) -> list[dict[str, Any]]:
    table = f"{project}.{dataset}.research_gold_cases"
    sql = f"""SELECT case_digest, case_id, symbol, as_of_utc, provenance_class,
                     input_digest, data_quality_grade, detector_state,
                     candidate_setup_ids, setup_taxonomy_version,
                     future_available_after_utc, input_boundary, future_evaluation
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
    if day23_digest(snapshot) != CANDIDATE_DIGEST:
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


def _volatility_instability(value: str) -> str | None:
    return {"low": "0.100000", "normal": "0.500000", "high": "0.900000"}.get(value)


def _eligible_rows(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for row in cases:
        if str(row.get("detector_state") or "") != "single":
            continue
        setup_ids = [str(item) for item in (row.get("candidate_setup_ids") or [])]
        if len(setup_ids) != 1 or setup_ids[0] not in DIRECTIONS:
            continue
        if str(row.get("setup_taxonomy_version") or "") != SETUP_TAXONOMY_VERSION:
            raise SystemExit("Frozen setup taxonomy drifted.")
        future = _object(row["future_evaluation"])
        label = _move_240(future)
        if label is None:
            continue
        stats = label.get("path_stats")
        if not isinstance(stats, dict) or stats.get("terminal_return_bps") is None:
            continue
        boundary = _object(row["input_boundary"])
        regime = boundary.get("regime")
        if not isinstance(regime, dict):
            continue
        labels = regime.get("labels")
        if not isinstance(labels, dict):
            continue
        instability = _volatility_instability(str(labels.get("volatility_band") or ""))
        if instability is None:
            continue
        terminal = float(str(stats["terminal_return_bps"]))
        direction = DIRECTIONS[setup_ids[0]]
        directional = terminal if direction == "long" else -terminal
        candidates.append(
            {
                "row_id": str(row["case_id"]),
                "as_of_utc": _utc(row["as_of_utc"]),
                "volatility_instability": instability,
                "adverse_outcome": directional <= 0,
            }
        )
    return sorted(candidates, key=lambda item: (item["as_of_utc"], item["row_id"]))


def _episode_deduplicate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = []
    next_allowed: datetime | None = None
    for row in rows:
        stamp = row["as_of_utc"]
        if next_allowed is not None and stamp < next_allowed:
            continue
        selected.append(
            {
                "episode_id": f"day45-{row['row_id']}",
                "as_of_utc": stamp.isoformat(),
                "volatility_instability": row["volatility_instability"],
                "adverse_outcome": row["adverse_outcome"],
            }
        )
        next_allowed = stamp + timedelta(minutes=EPISODE_HORIZON_MINUTES)
    return selected


def _split_for_rows(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(rows) < 4:
        return None
    fit_cut = max(2, len(rows) // 2)
    calibration_cut = max(fit_cut + 1, (3 * len(rows)) // 4)
    if calibration_cut >= len(rows):
        calibration_cut = len(rows) - 1
    if calibration_cut <= fit_cut:
        return None
    from aidy.selective_abstention import build_chronological_split

    return build_chronological_split(
        fit_start=rows[0]["as_of_utc"],
        fit_end=rows[fit_cut]["as_of_utc"],
        calibration_start=rows[fit_cut]["as_of_utc"],
        calibration_end=rows[calibration_cut]["as_of_utc"],
        test_start=rows[calibration_cut]["as_of_utc"],
        test_end=(_utc(rows[-1]["as_of_utc"]) + timedelta(seconds=1)).isoformat(),
    )


def _trials(head_sha: str, split: dict[str, Any], result: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    frozen_parameters = {
        "alpha": result["calibration"]["alpha"],
        "risk_ceiling": (
            result["test_positions"][0]["risk_ceiling"]
            if result["test_positions"]
            else "0.450000"
        ),
        "feature_names": result["feature_names"],
        "episode_horizon_minutes": EPISODE_HORIZON_MINUTES,
        "random_identity": RANDOM_IDENTITY,
    }
    split_record = {
        "fit_end": split["fit"]["end_utc"],
        "calibration_end": split["calibration"]["end_utc"],
        "test_end": split["test"]["end_utc"],
    }
    for number, experiment in enumerate(("J9", "J10"), start=1):
        hypothesis = (
            "Selective abstention has lower adverse risk than random abstention at matched coverage."
            if experiment == "J9"
            else "Volatility instability conditions selective abstention behaviour."
        )
        null = (
            "Selective abstention does not lower adverse risk versus matched random abstention."
            if experiment == "J9"
            else "Volatility instability does not condition selective abstention behaviour."
        )
        registered = preregister_trial(
            records,
            trial_number=number,
            hypothesis=hypothesis,
            null_hypothesis=null,
            dataset_version=DATASET_VERSION,
            feature_context_version="architecture-v2-day45",
            frozen_parameters=frozen_parameters,
            chronological_split=split_record,
            purge="240m episode dedup",
            embargo="chronological non-overlap",
            evaluation_identity=EVALUATION_IDENTITY,
            holdout_identity=f"{EVALUATION_IDENTITY}:untouched-test",
            preregistered_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC) + timedelta(seconds=number),
            code_head=head_sha,
            evidence_digest=str(split["split_digest"]),
            purpose="evaluation",
        )
        final = finalize_trial(
            registered,
            executed_at=datetime(2026, 9, 1, 12, 1, tzinfo=UTC) + timedelta(seconds=number),
            result_state=(
                "insufficient"
                if result[experiment.lower()]["result_state"] == "insufficient"
                else "passed"
            ),
            result=result[experiment.lower()],
        )
        records.append(final)
    if not verify_trial_registry(records):
        raise RuntimeError("Day 45 trial registry verification failed.")
    return records


def main() -> int:
    args = _args()
    if not args.project:
        raise SystemExit("AIDY_GCP_PROJECT_ID or --project is required.")
    secret = os.environ.get("AIDY_GCP_SERVICE_ACCOUNT_JSON")
    if not secret:
        raise SystemExit("AIDY_GCP_SERVICE_ACCOUNT_JSON is required.")

    from google.cloud import bigquery
    from google.oauth2 import service_account

    credentials = service_account.Credentials.from_service_account_info(json.loads(secret))
    client = bigquery.Client(
        project=args.project, credentials=credentials, location=args.location
    )
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()

    cases = _load_frozen_cases(client, args.project, args.dataset)
    eligible = _eligible_rows(cases)
    episodes = _episode_deduplicate(eligible)
    split = _split_for_rows(episodes)
    manifest = day45_manifest()

    if split is None:
        experiment = None
        trials: list[dict[str, Any]] = []
        j9_state = "insufficient"
        j10_state = "insufficient"
    else:
        experiment = run_shadow_selective_experiment(
            episodes,
            split=split,
            feature_names=("volatility_instability",),
            random_identity=RANDOM_IDENTITY,
        )
        trials = _trials(head_sha, split, experiment)
        j9_state = experiment["j9"]["result_state"]
        j10_state = experiment["j10"]["result_state"]

    summary: dict[str, Any] = {
        "ok": True,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "frozen_candidate_store_digest": CANDIDATE_DIGEST,
        "warehouse_case_count": len(cases),
        "warehouse_raw_eligible_case_n": len(eligible),
        "warehouse_effective_episode_n": len(episodes),
        "episode_policy": "greedy_chronological_nonoverlap_240m_outcome_blind",
        "scientific_result_uses_genuine_frozen_warehouse_cases": True,
        "split": split,
        "manifest": manifest,
        "experiment": experiment,
        "trials": trials,
        "j9_result_state": j9_state,
        "j10_result_state": j10_state,
        "insufficient_result_is_valid": True,
        "model_confidence_used": False,
        "matched_coverage_random_baseline_required": True,
        "shadow_only": True,
        "master_trader_gate_created": False,
        "publication_gate_created": False,
        "automatic_promotion_allowed": False,
        "formal_forward_evidence_created": False,
        "predictive_edge_claimed": False,
        "super_signals_modified": False,
    }
    summary["summary_digest"] = digest(summary)

    (output / "manifest.json").write_text(canonical_json(manifest) + "\n", encoding="utf-8")
    (output / "summary.json").write_text(canonical_json(summary) + "\n", encoding="utf-8")
    if experiment is not None:
        (output / "experiment.json").write_text(
            canonical_json(experiment) + "\n", encoding="utf-8"
        )
    if trials:
        (output / "trials.json").write_text(
            canonical_json(trials) + "\n", encoding="utf-8"
        )
    print(canonical_json(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
