from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from day26_acceptance_support import (
    BASE_SHA,
    CANDIDATE_COUNT,
    CANDIDATE_DIGEST,
    RESULT_TABLE,
    SUMMARY_TABLE,
    load_candidate_snapshot,
    load_pit_probe,
    load_research_windows,
    persist_results,
    persist_summary,
    utc,
)

from aidy.day23_research import canonical_json, digest
from aidy.price_structure_v2 import (
    FEED_HEALTH_VERSION,
    PRICE_STRUCTURE_VERSION,
    build_price_structure_packet,
    verify_price_structure_packet,
)

DEFAULT_PROJECT = "aidy-signals"
DEFAULT_DATASET = "aidy_analytics_test"
DEFAULT_LOCATION = "EU"
PIT_PROBE_CUTOFF = datetime(2026, 8, 21, 9, 30, tzinfo=UTC)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Day 26 price-structure warehouse acceptance")
    parser.add_argument(
        "--project",
        default=(
            os.environ.get("AIDY_GCP_PROJECT_ID")
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
            or os.environ.get("GCLOUD_PROJECT")
            or DEFAULT_PROJECT
        ),
    )
    parser.add_argument(
        "--dataset", default=os.environ.get("AIDY_BIGQUERY_DATASET", DEFAULT_DATASET)
    )
    parser.add_argument(
        "--location", default=os.environ.get("AIDY_BIGQUERY_LOCATION", DEFAULT_LOCATION)
    )
    parser.add_argument("--output-dir", default="day26_artifacts")
    return parser.parse_args()


def _opening_state_counts(packet: dict[str, Any]) -> Counter[str]:
    counts: Counter[str] = Counter()
    openings = packet["structure"]["opening_ranges"]
    for session in ("asia", "london", "new_york"):
        for horizon in ("15m", "30m", "60m"):
            counts[str(openings[session][horizon]["state"])] += 1
    return counts


def _assert_packet(packet: dict[str, Any], *, mode: str) -> None:
    if not verify_price_structure_packet(packet):
        raise RuntimeError("Day 26 packet digest/semantic contract failed.")
    if packet["price_structure_version"] != PRICE_STRUCTURE_VERSION:
        raise RuntimeError("Day 26 price-structure version drifted.")
    if packet["completed_bar_policy"] != "open_time_plus_nominal_duration_lte_as_of":
        raise RuntimeError("Day 26 completed-bar policy drifted.")
    if packet["future_values_used"] is not False or packet["predictive_edge_claimed"] is not False:
        raise RuntimeError("Day 26 descriptive/PIT boundary failed.")
    health = packet["feed_health"]
    if health["feed_health_version"] != FEED_HEALTH_VERSION:
        raise RuntimeError("Day 26 feed-health version drifted.")
    if health["threshold_based_health_classification"] is not False:
        raise RuntimeError("Day 26 introduced an unapproved feed-health gate.")
    if health["historical_spread_inference_included"] is not False:
        raise RuntimeError("Day 26 pre-empted Day 27 historical spread work.")
    if mode == "retrospective":
        if packet["pit_eligible"] is not False or health["quote"]["state"] != "unknown":
            raise RuntimeError("Retrospective Day 26 packet fabricated PIT state.")
        if any(
            payload["arrival_observation"]["state"] != "unknown"
            for payload in health["timeframes"].values()
        ):
            raise RuntimeError("Retrospective arrival latency was fabricated.")
    elif mode == "pit":
        if packet["pit_eligible"] is not True:
            raise RuntimeError("PIT Day 26 packet is not PIT eligible.")
    else:
        raise RuntimeError("Unexpected Day 26 mode.")


def _bigquery_client(*, project: str, location: str) -> tuple[Any, Any, Any]:
    """Create a BigQuery client without coupling acceptance to GitHub Actions.

    Priority:
    1. Existing AIDY service-account JSON (CI-compatible path).
    2. Google Application Default Credentials (Cloud Shell / local gcloud path).
    3. Short-lived token from the already-authenticated gcloud CLI.

    No credential value is printed or persisted by this function.
    """

    from google.api_core.exceptions import NotFound
    from google.auth import default as google_auth_default
    from google.auth.exceptions import DefaultCredentialsError
    from google.cloud import bigquery
    from google.oauth2 import service_account
    from google.oauth2.credentials import Credentials

    secret = os.environ.get("AIDY_GCP_SERVICE_ACCOUNT_JSON")
    if secret:
        credentials = service_account.Credentials.from_service_account_info(json.loads(secret))
        return (
            bigquery.Client(project=project, credentials=credentials, location=location),
            bigquery,
            NotFound,
        )

    try:
        credentials, _ = google_auth_default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
    except DefaultCredentialsError:
        token = subprocess.check_output(
            ["gcloud", "auth", "print-access-token"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if not token:
            raise SystemExit("No Google credential available from ADC or authenticated gcloud.")
        credentials = Credentials(token=token)

    return (
        bigquery.Client(project=project, credentials=credentials, location=location),
        bigquery,
        NotFound,
    )


def main() -> int:
    args = _args()
    if not args.project:
        raise SystemExit("A Google Cloud project is required.")
    head_sha = (os.environ.get("DAY26_HEAD_SHA") or "").strip()
    if len(head_sha) != 40:
        raise SystemExit("DAY26_HEAD_SHA must be the exact 40-character PR head SHA.")
    experiment = f"day26-price-structure-20260824-{head_sha[:12]}"

    client, bigquery, NotFound = _bigquery_client(project=args.project, location=args.location)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    recorded_at = datetime.now(UTC).isoformat()

    snapshot = load_candidate_snapshot(client, args.project, args.dataset)
    research_windows = load_research_windows(client, args.project, args.dataset)

    results: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    reproducible = 0
    prior_known: Counter[str] = Counter()
    opening_states: Counter[str] = Counter()
    gap_states: Counter[str] = Counter()
    breakout_states: Counter[str] = Counter()
    swing_reversions: Counter[str] = Counter()

    for case in snapshot:
        case_id = str(case["case_id"])
        as_of = utc(case["as_of_utc"])
        rows = research_windows.get(case_id, [])
        packet = build_price_structure_packet(
            as_of=as_of,
            symbol="XAUUSD",
            candle_rows=rows,
            mode="retrospective",
        )
        reversed_packet = build_price_structure_packet(
            as_of=as_of,
            symbol="XAUUSD",
            candle_rows=reversed(rows),
            mode="retrospective",
        )
        _assert_packet(packet, mode="retrospective")
        if packet != reversed_packet:
            raise RuntimeError(f"Input-order determinism failed for {case_id}.")
        reproducible += 1

        prior = packet["structure"]["prior_periods"]
        for key in ("prior_day", "prior_week", "prior_month"):
            prior_known[key] += int(prior[key]["state"] == "known")
        opening_states.update(_opening_state_counts(packet))
        gap_states[str(packet["structure"]["utc_day_gap"]["state"])] += 1
        breakout_states[str(packet["structure"]["prior_day_breakout"]["state"])] += 1
        swing = packet["structure"]["swing_extreme_penetration_with_reversion"]
        swing_reversions["high"] += int(bool(swing["high_side"].get("reverted")))
        swing_reversions["low"] += int(bool(swing["low_side"].get("reverted")))

        results.append(
            {
                "experiment_id": experiment,
                "base_sha": BASE_SHA,
                "head_sha": head_sha,
                "anchor_id": case_id,
                "mode": "retrospective",
                "as_of_utc": as_of.isoformat(),
                "payload_digest": packet["price_structure_digest"],
                "semantic_digest": packet["structure_semantic_digest"],
                "payload_json": canonical_json(packet),
                "recorded_at_utc": recorded_at,
            }
        )
        evidence_rows.append(
            {
                "anchor_id": case_id,
                "mode": "retrospective",
                "as_of_utc": as_of.isoformat(),
                "payload_digest": packet["price_structure_digest"],
                "semantic_digest": packet["structure_semantic_digest"],
                "prior_period_states": {
                    key: prior[key]["state"] for key in ("prior_day", "prior_week", "prior_month")
                },
                "gap_state": packet["structure"]["utc_day_gap"]["state"],
                "breakout_state": packet["structure"]["prior_day_breakout"]["state"],
            }
        )

    if reproducible != CANDIDATE_COUNT:
        raise RuntimeError("Day 26 did not reproduce every frozen historical anchor.")
    if any(prior_known[key] == 0 for key in ("prior_day", "prior_week", "prior_month")):
        raise RuntimeError("Real history did not exercise every prior-period reference class.")

    pit_as_of, pit_snapshot, pit_rows = load_pit_probe(
        client,
        bigquery,
        args.project,
        args.dataset,
        PIT_PROBE_CUTOFF,
    )
    pit_packet = build_price_structure_packet(
        as_of=pit_as_of,
        symbol="XAUUSD",
        candle_rows=pit_rows,
        mode="pit",
        snapshot=pit_snapshot,
    )
    pit_reversed = build_price_structure_packet(
        as_of=pit_as_of,
        symbol="XAUUSD",
        candle_rows=reversed(pit_rows),
        mode="pit",
        snapshot=pit_snapshot,
    )
    _assert_packet(pit_packet, mode="pit")
    if pit_packet != pit_reversed:
        raise RuntimeError("Real PIT packet is not input-order deterministic.")
    if pit_packet["feed_health"]["quote"]["state"] != "observed":
        raise RuntimeError("Real PIT quote telemetry is unavailable.")

    pit_anchor = "pit_snapshot_" + str(pit_snapshot.get("load_identity") or pit_as_of.isoformat())
    results.append(
        {
            "experiment_id": experiment,
            "base_sha": BASE_SHA,
            "head_sha": head_sha,
            "anchor_id": pit_anchor,
            "mode": "pit",
            "as_of_utc": pit_as_of.isoformat(),
            "payload_digest": pit_packet["price_structure_digest"],
            "semantic_digest": pit_packet["structure_semantic_digest"],
            "payload_json": canonical_json(pit_packet),
            "recorded_at_utc": recorded_at,
        }
    )
    evidence_rows.append(
        {
            "anchor_id": pit_anchor,
            "mode": "pit",
            "as_of_utc": pit_as_of.isoformat(),
            "payload_digest": pit_packet["price_structure_digest"],
            "semantic_digest": pit_packet["structure_semantic_digest"],
            "quote_feed_state": pit_packet["feed_health"]["quote"]["quote_state"],
            "quote_age_seconds": pit_packet["feed_health"]["quote"]["quote_age_seconds"],
            "m1_feed_health": pit_packet["feed_health"]["timeframes"]["M1"],
        }
    )

    summary: dict[str, Any] = {
        "ok": True,
        "experiment_id": experiment,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "price_structure_version": PRICE_STRUCTURE_VERSION,
        "feed_health_version": FEED_HEALTH_VERSION,
        "candidate_store_snapshot_digest": CANDIDATE_DIGEST,
        "retrospective_anchor_count": CANDIDATE_COUNT,
        "retrospective_input_order_reproducible_count": reproducible,
        "real_pit_probe_count": 1,
        "pit_probe_cutoff_utc": PIT_PROBE_CUTOFF.isoformat(),
        "pit_probe_as_of_utc": pit_as_of.isoformat(),
        "pit_input_order_reproducible": True,
        "prior_period_known_anchor_counts": dict(sorted(prior_known.items())),
        "opening_range_state_counts": dict(sorted(opening_states.items())),
        "utc_day_gap_state_counts": dict(sorted(gap_states.items())),
        "prior_day_breakout_state_counts": dict(sorted(breakout_states.items())),
        "swing_reversion_anchor_counts": dict(sorted(swing_reversions.items())),
        "pit_quote_feed_state": pit_packet["feed_health"]["quote"]["quote_state"],
        "pit_quote_age_seconds": pit_packet["feed_health"]["quote"]["quote_age_seconds"],
        "pit_m1_last_observation_age_seconds": pit_packet["feed_health"]["timeframes"]["M1"][
            "last_observation_age_seconds"
        ],
        "pit_m1_interbar_gap_count": pit_packet["feed_health"]["timeframes"]["M1"][
            "interbar_gap_count"
        ],
        "retrospective_arrival_latency_fabricated": False,
        "historical_spread_inference_included": False,
        "threshold_based_feed_health_gate_included": False,
        "future_values_used": False,
        "predictive_edge_claimed": False,
        "accepted_prior_modules_modified": False,
        "bigquery_evidence": {
            "result_table": RESULT_TABLE,
            "summary_table": SUMMARY_TABLE,
            "result_rows": len(results),
        },
    }
    summary["summary_digest"] = digest(summary)

    persist_results(
        client,
        bigquery,
        NotFound,
        f"{args.project}.{args.dataset}.{RESULT_TABLE}",
        experiment,
        results,
    )
    persist_summary(
        client,
        bigquery,
        NotFound,
        f"{args.project}.{args.dataset}.{SUMMARY_TABLE}",
        experiment,
        summary,
        recorded_at,
        canonical_json,
    )

    (output / "summary.json").write_text(canonical_json(summary) + "\n", encoding="utf-8")
    with (output / "results.jsonl").open("w", encoding="utf-8") as handle:
        for payload in evidence_rows:
            handle.write(canonical_json(payload) + "\n")
    (output / "contract_reference.json").write_text(
        canonical_json(
            {
                "base_sha": BASE_SHA,
                "head_sha": head_sha,
                "candidate_store_snapshot_digest": CANDIDATE_DIGEST,
                "pit_probe_cutoff_utc": PIT_PROBE_CUTOFF.isoformat(),
                "price_structure_version": PRICE_STRUCTURE_VERSION,
                "feed_health_version": FEED_HEALTH_VERSION,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    print(canonical_json(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
