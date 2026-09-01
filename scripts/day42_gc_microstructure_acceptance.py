from __future__ import annotations

import argparse
import os
import subprocess
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from aidy.databento_gc import (
    DATABENTO_DATASET,
    GC_CONTINUOUS_SYMBOL,
    DatabentoHistoricalClient,
    HistoricalRequest,
)
from aidy.gc_microstructure import (
    BASELINE_VERSION,
    MinuteMicrostructure,
    aggregate_tbbo_minutes,
    build_weekday_clock_baseline,
    canonical_json,
    day42_experiment_plan,
    parse_databento_tbbo_jsonl,
    run_shadow_experiment,
    verify_weekday_clock_baseline,
)
from aidy.gc_shadow_spine import digest, normalize_databento_api_key, resolve_gc_contract_map
from aidy.research_integrity import finalize_trial, preregister_trial, verify_trial_registry

BASE_SHA = "8672ad19ba40ceaed2cf0f042c8e2af3694896a5"
HISTORICAL_SMOKE_MAX_COST_USD = Decimal("0.25")
DATABENTO_SYMBOLOGY_URL = "https://hist.databento.com/v0/symbology.resolve"
NOW = datetime(2026, 9, 1, 10, 10, tzinfo=UTC)
EXPECTED_FILES = (
    "src/aidy/gc_microstructure.py",
    "tests/test_day42_gc_microstructure.py",
    "scripts/day42_gc_microstructure_acceptance.py",
    "docs/day42-gc-microstructure-j2-j3-contract.md",
    ".github/workflows/day42-gc-microstructure-acceptance.yml",
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AIDY Day 42 GC microstructure acceptance")
    parser.add_argument("--output-dir", default="day42_artifacts")
    parser.add_argument("--genuine", action="store_true")
    parser.add_argument("--raw-tbbo", default="/tmp/day42_gc_tbbo.jsonl")
    return parser.parse_args()


def _write(path: Path, value: object) -> None:
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def _head_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def _changed_files(head_sha: str) -> list[str]:
    merge_base = subprocess.check_output(
        ["git", "merge-base", BASE_SHA, head_sha], text=True
    ).strip()
    if merge_base != BASE_SHA:
        raise RuntimeError("Day 42 branch is not based on the exact accepted Day 41 main SHA.")
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", f"{BASE_SHA}...{head_sha}"], text=True
    ).splitlines()
    unexpected = sorted(set(changed) - set(EXPECTED_FILES))
    if unexpected:
        raise RuntimeError(f"Day 42 modified files outside the frozen surface: {unexpected}")
    return sorted(changed)


def _split_binding(plan_digest: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "manifest_version": "aidy_chronological_split_manifest_v1",
        "replay_harness_version": "aidy_frozen_replay_cpcv_v1",
        "binding_kind": "day42_shadow_evaluation_contract",
        "plan_digest": plan_digest,
        "train": "chronological_before_evaluation",
        "dev": "chronological_after_train",
        "calibration": "chronological_after_dev",
        "holdout": "chronological_final_only",
        "purge_required": True,
        "embargo_required": True,
        "holdout_tuning_allowed": False,
        "cpcv_pre_holdout_only": True,
    }
    body["split_digest"] = digest(body)
    return body


def _finalize_trials(
    *,
    head_sha: str,
    plan: dict[str, Any],
    split: dict[str, Any],
    j2_result: dict[str, Any],
    j3_result: dict[str, Any],
) -> list[dict[str, Any]]:
    trials: list[dict[str, Any]] = []
    specifications_frozen_at = NOW
    for number, (experiment, result) in enumerate(
        (("J2", j2_result), ("J3", j3_result)), start=1
    ):
        hypothesis_key = "j2_hypothesis" if experiment == "J2" else "j3_hypothesis"
        null_key = "j2_null_hypothesis" if experiment == "J2" else "j3_null_hypothesis"
        registered = preregister_trial(
            trials,
            trial_number=number,
            hypothesis=str(plan[hypothesis_key]),
            null_hypothesis=str(plan[null_key]),
            dataset_version="day42-genuine-gc-tbbo-shadow-v1",
            feature_context_version=BASELINE_VERSION,
            frozen_parameters={
                "experiment": experiment,
                "experiment_plan_digest": plan["plan_digest"],
                "normalization": BASELINE_VERSION,
                "minimum_independent_evaluation_n": plan[
                    "minimum_independent_evaluation_n"
                ],
                "ordinary_session_activity_can_count_as_alpha": False,
                "single_result_can_promote_gate": False,
                "specifications_frozen_before_any_day42_result": True,
                "specifications_frozen_at_utc": specifications_frozen_at.isoformat(),
            },
            chronological_split=split,
            purge="required_by_day37_split_manifest",
            embargo="required_by_day37_split_manifest",
            evaluation_identity=f"day42-{experiment.lower()}-shadow-evaluation-v1",
            holdout_identity=f"day42-{experiment.lower()}-shadow-holdout-v1",
            preregistered_at=NOW + timedelta(minutes=number),
            code_head=head_sha,
            evidence_digest=plan["plan_digest"],
            purpose="evaluation",
        )
        terminal_state = str(result["result_state"])
        if terminal_state == "descriptive_non_null":
            terminal_state = "passed"
        trials.append(
            finalize_trial(
                registered,
                executed_at=NOW + timedelta(minutes=number, seconds=30),
                result_state=terminal_state,
                result={
                    **result,
                    "experiment_plan_digest": plan["plan_digest"],
                    "features_shadow_only": True,
                    "formal_forward_evidence_created": False,
                    "gate_promoted": False,
                },
            )
        )
    verify_trial_registry(trials)
    return trials


def _fixture_minutes() -> list[MinuteMicrostructure]:
    result: list[MinuteMicrostructure] = []
    for index in range(20):
        minute = datetime(2026, 1, 5, 15, 0, tzinfo=UTC) + timedelta(weeks=index)
        volume = Decimal(100 + index)
        spread = Decimal(1) + Decimal(index) / Decimal(100)
        signed = Decimal("0.10") + Decimal(index) / Decimal(1000)
        anchor = Decimal(4500)
        last = anchor * (
            Decimal(1)
            + (Decimal("0.5") + Decimal(index) / Decimal(100)) / Decimal(10000)
        )
        result.append(
            MinuteMicrostructure(
                minute_utc=minute,
                contract_symbol="GCG6",
                session="london_new_york_overlap",
                trade_count=3,
                trade_volume=volume,
                buy_aggressor_volume=Decimal(2),
                sell_aggressor_volume=Decimal(1),
                unknown_side_volume=Decimal(0),
                known_side_volume=Decimal(3),
                signed_trade_imbalance=signed,
                vwap=anchor,
                last_trade_price=last,
                mean_spread_bps=spread,
                median_spread_bps=spread,
                session_vwap=anchor,
                anchored_vwap=anchor,
                anchor_identity=(
                    f"GCG6:{minute.date().isoformat()}:london_new_york_overlap"
                ),
                source_trade_digests=(f"{index:064x}",),
            )
        )
    return result


def _fixture_summary(head_sha: str) -> dict[str, Any]:
    plan = day42_experiment_plan()
    split = _split_binding(str(plan["plan_digest"]))
    baseline = build_weekday_clock_baseline(_fixture_minutes())
    if not verify_weekday_clock_baseline(baseline):
        raise RuntimeError("Day 42 deterministic baseline fixture failed verification.")
    j2 = run_shadow_experiment(experiment="J2", eligible_rows=[], split_binding=split)
    j3 = run_shadow_experiment(experiment="J3", eligible_rows=[], split_binding=split)
    trials = _finalize_trials(
        head_sha=head_sha,
        plan=plan,
        split=split,
        j2_result=j2,
        j3_result=j3,
    )
    summary: dict[str, Any] = {
        "ok": True,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "changed_files": _changed_files(head_sha),
        "source_dataset": DATABENTO_DATASET,
        "source_schema": "tbbo",
        "volume_from_genuine_trades_required": True,
        "spread_from_genuine_quotes_required": True,
        "vwap_price_times_volume_required": True,
        "signed_trade_flow_only": True,
        "unknown_aggressor_side_imputed": False,
        "depth_claimed": False,
        "order_book_imbalance_claimed": False,
        "mbo_allowed": False,
        "mbp10_allowed": False,
        "weekday_clock_normalization_frozen_before_outcomes": True,
        "ordinary_session_activity_can_count_as_alpha": False,
        "day32_trial_registry_bound": True,
        "day37_chronological_purge_embargo_bound": True,
        "j2_result_state": j2["result_state"],
        "j3_result_state": j3["result_state"],
        "null_or_insufficient_results_retained": True,
        "features_shadow_only": True,
        "formal_forward_evidence_created": False,
        "gate_promoted": False,
        "predictive_edge_claimed": False,
        "plan_digest": plan["plan_digest"],
        "split_digest": split["split_digest"],
        "baseline_digest": baseline["baseline_digest"],
        "trial_digests": [trial["trial_digest"] for trial in trials],
    }
    summary["summary_digest"] = digest(summary)
    return summary


def _parse_utc(value: object, *, name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"Databento {name} is missing.")
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is None:
        raise RuntimeError(f"Databento {name} must be timezone-aware.")
    return parsed.astimezone(UTC)


def _latest_full_tbbo_day(dataset_range: dict[str, Any]) -> datetime:
    schema = dataset_range.get("schema")
    if not isinstance(schema, dict):
        raise TypeError("Databento dataset range lacks per-schema availability.")
    available = schema.get("tbbo")
    if not isinstance(available, dict):
        raise TypeError("Databento entitlement has no TBBO availability range.")
    start = _parse_utc(available.get("start"), name="TBBO start")
    end = _parse_utc(available.get("end"), name="TBBO end")
    if end <= start:
        raise RuntimeError("Databento TBBO availability range is empty.")
    target_date = end.date() - timedelta(days=1)
    while target_date.weekday() >= 5:
        target_date -= timedelta(days=1)
    target = datetime.combine(target_date, time(hour=15), tzinfo=UTC)
    if target < start or target + timedelta(minutes=5) > end:
        raise RuntimeError("No fully entitled weekday TBBO smoke window is available.")
    return target


def _symbology_resolve(
    api_key: str,
    *,
    symbols: str,
    stype_in: str,
    stype_out: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    response = httpx.post(
        DATABENTO_SYMBOLOGY_URL,
        auth=httpx.BasicAuth(api_key, ""),
        timeout=20.0,
        data={
            "dataset": DATABENTO_DATASET,
            "symbols": symbols,
            "stype_in": stype_in,
            "stype_out": stype_out,
            "start_date": start_date,
            "end_date": end_date,
        },
        headers={"User-Agent": "AIDY-Signals/Day42"},
    )
    if response.is_error:
        safe = response.text.replace(api_key, "***")[:1000]
        raise RuntimeError(
            f"Databento Day 42 symbology failed with HTTP {response.status_code}: {safe}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise TypeError("Databento Day 42 symbology returned a non-object payload.")
    return payload


def _continuous_instrument_ids(payload: dict[str, Any]) -> list[str]:
    result = payload.get("result")
    if not isinstance(result, dict):
        raise TypeError("Databento continuous resolution lacks a result mapping.")
    entries = result.get(GC_CONTINUOUS_SYMBOL)
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("Databento continuous resolution returned no GC instruments.")
    ids = sorted(
        {
            str(entry.get("s"))
            for entry in entries
            if isinstance(entry, dict) and str(entry.get("s", "")).isdigit()
        }
    )
    if not ids:
        raise RuntimeError("Databento continuous resolution returned no numeric instrument IDs.")
    return ids


def _genuine_summary(head_sha: str, *, raw_path: Path) -> dict[str, Any]:
    plan = day42_experiment_plan()
    split = _split_binding(str(plan["plan_digest"]))
    raw_secret = os.environ.get("DATABENTO_API_KEY", "")
    if not raw_secret.strip():
        raise RuntimeError("DATABENTO_API_KEY is required for genuine Day 42 evidence.")
    api_key = normalize_databento_api_key(raw_secret)
    os.environ["DATABENTO_API_KEY"] = api_key

    with DatabentoHistoricalClient.from_env() as client:
        entitlement = client.assert_gc_entitlement()
        dataset_range = client.dataset_range()
        anchor = _latest_full_tbbo_day(dataset_range)
        request = HistoricalRequest(
            schema="tbbo",
            start=anchor.isoformat(),
            end=(anchor + timedelta(minutes=5)).isoformat(),
        )
        quote = client.estimate_cost(request)
        if quote.quoted_cost_usd > HISTORICAL_SMOKE_MAX_COST_USD:
            raise RuntimeError("Day 42 TBBO quote exceeds the strict $0.25 acceptance cap.")
        receipt = client.download_jsonl(request, quote=quote, output_path=raw_path)

    start_date = anchor.date().isoformat()
    end_date = (anchor.date() + timedelta(days=1)).isoformat()
    continuous = _symbology_resolve(
        api_key,
        symbols=GC_CONTINUOUS_SYMBOL,
        stype_in="continuous",
        stype_out="instrument_id",
        start_date=start_date,
        end_date=end_date,
    )
    raw_resolutions: dict[str, dict[str, Any]] = {}
    for instrument_id in _continuous_instrument_ids(continuous):
        raw_resolutions[instrument_id] = _symbology_resolve(
            api_key,
            symbols=instrument_id,
            stype_in="instrument_id",
            stype_out="raw_symbol",
            start_date=start_date,
            end_date=end_date,
        )
    contract_map = resolve_gc_contract_map(continuous, raw_resolutions)
    raw_text = raw_path.read_text(encoding="utf-8")
    trades = parse_databento_tbbo_jsonl(
        raw_text, contract_by_instrument_id=contract_map
    )
    if not trades:
        raise RuntimeError("Databento genuine TBBO smoke returned no GC trades.")
    minutes = aggregate_tbbo_minutes(trades)
    if not minutes:
        raise RuntimeError("Databento genuine TBBO trades produced no minute features.")
    baseline = build_weekday_clock_baseline(minutes)
    if not verify_weekday_clock_baseline(baseline):
        raise RuntimeError("Genuine Day 42 baseline artifact failed verification.")

    j2 = run_shadow_experiment(experiment="J2", eligible_rows=[], split_binding=split)
    j3 = run_shadow_experiment(experiment="J3", eligible_rows=[], split_binding=split)
    trials = _finalize_trials(
        head_sha=head_sha,
        plan=plan,
        split=split,
        j2_result=j2,
        j3_result=j3,
    )
    total_volume = sum((trade.size for trade in trades), Decimal(0))
    unknown_volume = sum(
        (trade.size for trade in trades if trade.aggressor_side == "N"), Decimal(0)
    )
    known_volume = total_volume - unknown_volume
    summary: dict[str, Any] = {
        "evidence_version": "aidy_day42_genuine_tbbo_shadow_evidence_v1",
        "ok": True,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "observed_at_utc": datetime.now(UTC).isoformat(),
        "target_historical_window_start_utc": anchor.isoformat(),
        "target_historical_window_end_utc": (anchor + timedelta(minutes=5)).isoformat(),
        "source_provider": "Databento",
        "source_dataset": DATABENTO_DATASET,
        "source_schema": "tbbo",
        "continuous_symbol": GC_CONTINUOUS_SYMBOL,
        "resolved_contracts": sorted(set(contract_map.values())),
        "genuine_trade_rows": len(trades),
        "genuine_microstructure_minutes": len(minutes),
        "genuine_exchange_trade_volume": str(total_volume),
        "known_aggressor_volume": str(known_volume),
        "unknown_aggressor_volume": str(unknown_volume),
        "unknown_aggressor_side_imputed": False,
        "first_trade_utc": min(trade.observed_at for trade in trades).isoformat(),
        "last_trade_utc": max(trade.observed_at for trade in trades).isoformat(),
        "mean_minute_spread_bps": str(
            sum((minute.mean_spread_bps for minute in minutes), Decimal(0))
            / Decimal(len(minutes))
        ),
        "last_session_vwap": str(minutes[-1].session_vwap),
        "last_anchored_vwap": str(minutes[-1].anchored_vwap),
        "databento_entitlement": entitlement,
        "databento_request": request.payload(),
        "databento_quote_usd": str(quote.quoted_cost_usd),
        "databento_smoke_cost_cap_usd": str(HISTORICAL_SMOKE_MAX_COST_USD),
        "databento_download_receipt": receipt,
        "databento_contract_map": {
            str(key): value for key, value in sorted(contract_map.items())
        },
        "databento_symbology_digest": digest(
            {"continuous": continuous, "raw": raw_resolutions}
        ),
        "microstructure_minute_digests": [
            minute.as_dict()["minute_digest"] for minute in minutes
        ],
        "baseline_digest": baseline["baseline_digest"],
        "baseline_state": "insufficient_genuine_smoke_sample",
        "normalization_frozen_before_outcome_analysis": True,
        "ordinary_session_activity_can_count_as_alpha": False,
        "depth_claimed": False,
        "order_book_imbalance_claimed": False,
        "mbo_used": False,
        "mbp10_used": False,
        "j2_result": j2,
        "j3_result": j3,
        "trial_digests": [trial["trial_digest"] for trial in trials],
        "experiment_plan_digest": plan["plan_digest"],
        "split_digest": split["split_digest"],
        "null_or_insufficient_results_retained": True,
        "features_shadow_only": True,
        "pit_eligible": False,
        "formal_forward_evidence_created": False,
        "gate_promoted": False,
        "predictive_edge_claimed": False,
        "paid_subscription_activated": False,
        "live_gc_subscription_activated": False,
        "broker_market_data_dependency": False,
        "api_key_recorded": False,
    }
    summary["evidence_digest"] = digest(summary)
    return summary


def main() -> int:
    args = _args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    head_sha = _head_sha()
    if args.genuine:
        genuine = _genuine_summary(head_sha, raw_path=Path(args.raw_tbbo))
        _write(output / "genuine_tbbo_shadow_evidence.json", genuine)
        print(canonical_json(genuine))
        return 0

    summary = _fixture_summary(head_sha)
    plan = day42_experiment_plan()
    _write(output / "experiment_plan.json", plan)
    _write(output / "summary.json", summary)
    print(canonical_json(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
