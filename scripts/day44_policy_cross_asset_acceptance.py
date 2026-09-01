from __future__ import annotations

import argparse
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aidy.policy_cross_asset import (
    PROHIBITED_GOLD_PROXIES,
    SERIES_BROAD_USD,
    SERIES_ES,
    SERIES_EURUSD,
    SERIES_GC,
    SERIES_REAL10Y,
    SERIES_SI,
    SERIES_SR3,
    SERIES_USDJPY,
    SERIES_VIX,
    SERIES_ZN,
    SERIES_ZQ,
    build_gold_silver_state,
    build_observation,
    build_policy_path_state,
    build_risk_state,
    build_usd_composition_state,
    canonical_json,
    day44_experiment_plan,
    day44_manifest,
    day44_source_contracts,
    digest,
    real_yield_policy_after_j12,
    run_day44_experiment,
    verify_observation,
    verify_source_contract,
)
from aidy.research_integrity import finalize_trial, preregister_trial, verify_trial_registry

BASE_SHA = "5d3c21077c918db0df789898fec3dacb762fb6b3"
NOW = datetime(2026, 9, 1, 11, 0, tzinfo=UTC)
EXPECTED_FILES = (
    "src/aidy/policy_cross_asset.py",
    "tests/test_day44_policy_cross_asset.py",
    "scripts/day44_policy_cross_asset_acceptance.py",
    "docs/day44-policy-cross-asset-j11-j14-contract.md",
    ".github/workflows/day44-policy-cross-asset-acceptance.yml",
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AIDY Day 44 policy/cross-asset acceptance")
    parser.add_argument("--output-dir", default="day44_artifacts")
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
        raise RuntimeError("Day 44 branch is not based on exact accepted Day 43 main.")
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", f"{BASE_SHA}...{head_sha}"], text=True
    ).splitlines()
    unexpected = sorted(set(changed) - set(EXPECTED_FILES))
    if unexpected:
        raise RuntimeError(f"Day 44 modified files outside the frozen surface: {unexpected}")
    return sorted(changed)


def _split_binding(plan_digest: str) -> dict[str, Any]:
    record: dict[str, Any] = {
        "manifest_version": "aidy_chronological_split_manifest_v1",
        "replay_harness_version": "aidy_frozen_replay_cpcv_v1",
        "binding_kind": "day44_j11_j14_shadow_evaluation",
        "plan_digest": plan_digest,
        "purge_required": True,
        "embargo_required": True,
        "holdout_tuning_allowed": False,
        "cpcv_pre_holdout_only": True,
        "episode_independence_required": True,
    }
    record["split_digest"] = digest(record)
    return record


def _fixture_observations() -> dict[str, dict[str, Any]]:
    values = {
        SERIES_ZQ: "95.75",
        SERIES_SR3: "96.10",
        SERIES_ZN: "115.25",
        SERIES_GC: "3500",
        SERIES_SI: "35",
        SERIES_EURUSD: "1.18",
        SERIES_USDJPY: "145",
        SERIES_VIX: "20",
        SERIES_ES: "6500",
        SERIES_BROAD_USD: "120",
        SERIES_REAL10Y: "1.85",
    }
    retrospective = {SERIES_ZQ, SERIES_SR3, SERIES_ZN, SERIES_GC, SERIES_SI, SERIES_ES}
    records: dict[str, dict[str, Any]] = {}
    for index, (series, value) in enumerate(values.items()):
        observed = NOW + timedelta(seconds=index)
        records[series] = build_observation(
            series_id=series,
            value=value,
            observed_at=observed,
            first_observed_at=observed + timedelta(seconds=5),
            source_snapshot_digest=digest({"fixture_series": series, "value": value}),
            provenance_class=(
                "retrospective_history" if series in retrospective else "first_observed_capture"
            ),
            pit_reconstructable=True,
        )
    if not all(verify_observation(record) for record in records.values()):
        raise RuntimeError("Day 44 fixture observation verification failed.")
    return records


def _trials(
    *,
    head_sha: str,
    plan: dict[str, Any],
    split: dict[str, Any],
    results: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for trial_number, experiment in enumerate(("J11", "J12", "J13", "J14"), start=1):
        spec = plan[experiment.lower()]
        result = results[experiment]
        registered = preregister_trial(
            records,
            trial_number=trial_number,
            hypothesis=str(spec["hypothesis"]),
            null_hypothesis=str(spec["null_hypothesis"]),
            dataset_version="day44-no-outcome-linked-independent-cohort-v1",
            feature_context_version="aidy_policy_cross_asset_v1",
            frozen_parameters={
                "experiment": experiment,
                "plan_digest": plan["plan_digest"],
                "minimum_independent_evaluation_n": plan[
                    "minimum_independent_evaluation_n"
                ],
                "correlation_mining_allowed": False,
                "threshold_tuning_on_evaluation_set_allowed": False,
                "single_result_can_promote_mandatory_feature": False,
                "frozen_before_any_day44_result": True,
            },
            chronological_split=split,
            purge="required_by_day37_split_contract",
            embargo="required_by_day37_split_contract",
            evaluation_identity=f"day44-{experiment.lower()}-shadow-evaluation-v1",
            holdout_identity=f"day44-{experiment.lower()}-shadow-holdout-v1",
            preregistered_at=NOW + timedelta(minutes=trial_number),
            code_head=head_sha,
            evidence_digest=plan["plan_digest"],
            purpose="evaluation",
        )
        records.append(
            finalize_trial(
                registered,
                executed_at=NOW + timedelta(minutes=trial_number, seconds=30),
                result_state=str(result["result_state"]),
                result={
                    **result,
                    "architecture_fixture_used_as_outcome_data": False,
                    "formal_forward_evidence_created": False,
                    "mandatory_feature_promoted": False,
                },
            )
        )
    verify_trial_registry(records)
    return records


def build_artifacts(head_sha: str) -> dict[str, Any]:
    contracts = day44_source_contracts()
    if not all(verify_source_contract(contract) for contract in contracts.values()):
        raise RuntimeError("Day 44 source contract verification failed.")
    plan = day44_experiment_plan()
    split = _split_binding(str(plan["plan_digest"]))
    fixture = _fixture_observations()
    mechanism_fixture = {
        "policy_path": build_policy_path_state(
            zq=fixture[SERIES_ZQ], sr3=fixture[SERIES_SR3]
        ),
        "precious_complex": build_gold_silver_state(
            gold=fixture[SERIES_GC], silver=fixture[SERIES_SI]
        ),
        "usd_composition": build_usd_composition_state(
            broad_usd=fixture[SERIES_BROAD_USD],
            eurusd=fixture[SERIES_EURUSD],
            usdjpy=fixture[SERIES_USDJPY],
        ),
        "risk_state": build_risk_state(vix=fixture[SERIES_VIX], es=fixture[SERIES_ES]),
    }
    results = {
        experiment: run_day44_experiment(
            experiment=experiment,
            rows=[],
            split_binding=split,
        )
        for experiment in ("J11", "J12", "J13", "J14")
    }
    j12_policy = real_yield_policy_after_j12(results["J12"])
    trials = _trials(
        head_sha=head_sha,
        plan=plan,
        split=split,
        results=results,
    )
    manifest = day44_manifest()
    summary: dict[str, Any] = {
        "ok": True,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "changed_files": _changed_files(head_sha),
        "source_contract_count": len(contracts),
        "all_series_have_source_timestamp_pit_contract": True,
        "all_source_contracts_valid": True,
        "architecture_fixture_only": True,
        "architecture_fixture_used_as_outcome_data": False,
        "retrospective_fixture_decision_input_allowed": False,
        "policy_path_independent_confirmation_units": mechanism_fixture["policy_path"][
            "independent_confirmation_units"
        ],
        "rates_independent_confirmation_units": manifest[
            "rates_independent_confirmation_units"
        ],
        "rates_double_counting_allowed": False,
        "gold_silver_ratio_state": mechanism_fixture["precious_complex"]["state"],
        "usd_composition_state": mechanism_fixture["usd_composition"]["state"],
        "risk_state_is_context_not_gold_proxy": mechanism_fixture["risk_state"][
            "risk_state_is_context_not_gold_proxy"
        ],
        "j11_result_state": results["J11"]["result_state"],
        "j11_effective_independent_n": results["J11"]["effective_independent_n"],
        "j12_result_state": results["J12"]["result_state"],
        "j12_effective_independent_n": results["J12"]["effective_independent_n"],
        "j13_result_state": results["J13"]["result_state"],
        "j13_effective_independent_n": results["J13"]["effective_independent_n"],
        "j14_result_state": results["J14"]["result_state"],
        "j14_effective_independent_n": results["J14"]["effective_independent_n"],
        "j12_directional_use_demoted": j12_policy["directional_use_demoted"],
        "j12_directional_use_promoted": j12_policy["directional_use_promoted"],
        "real_yield_directional_influence": j12_policy["directional_influence"],
        "null_or_insufficient_results_retained": True,
        "day32_trial_registry_bound": True,
        "day37_purge_embargo_bound": True,
        "correlation_mining_allowed": False,
        "cross_asset_features_mandatory": [],
        "prohibited_gold_proxies": list(PROHIBITED_GOLD_PROXIES),
        "crude_copper_bitcoin_added": False,
        "paid_live_market_data_activation_performed": False,
        "formal_forward_evidence_created": False,
        "predictive_edge_claimed": False,
        "trading_gate_created": False,
        "super_signals_modified": False,
        "manifest_digest": manifest["manifest_digest"],
        "plan_digest": plan["plan_digest"],
        "split_digest": split["split_digest"],
        "j12_policy_digest": j12_policy["policy_digest"],
        "trial_digests": [record["trial_digest"] for record in trials],
    }
    summary["summary_digest"] = digest(summary)
    return {
        "summary": summary,
        "manifest": manifest,
        "source_contracts": contracts,
        "experiment_plan": plan,
        "split": split,
        "observation_fixture": fixture,
        "mechanism_fixture": mechanism_fixture,
        "j11": results["J11"],
        "j12": results["J12"],
        "j13": results["J13"],
        "j14": results["J14"],
        "j12_policy": j12_policy,
        "trials": trials,
    }


def main() -> int:
    args = _args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    artifacts = build_artifacts(_head_sha())
    for name, value in artifacts.items():
        _write(output / f"{name}.json", value)
    print(canonical_json(artifacts["summary"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
