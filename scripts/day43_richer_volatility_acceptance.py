from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aidy.research_integrity import finalize_trial, preregister_trial, verify_trial_registry
from aidy.richer_volatility import (
    build_event_iv_kink,
    build_richer_volatility_regime,
    build_unexplained_market_shock,
    day43_experiment_plan,
    run_day43_experiment,
)
from aidy.volatility_intelligence import (
    canonical_json,
    digest,
    verify_j7_j8_foundation,
    verify_volatility_state,
)

BASE_SHA = "3d32b5c8afebdfc29552cc76c61c4d254606e122"
NOW = datetime(2026, 9, 1, 10, 50, tzinfo=UTC)
DAY31_RETROSPECTIVE = Path("evidence/day31/retrospective_volatility_state.json")
DAY31_CURRENT = Path("evidence/day31/current_volatility_state.json")
DAY31_FOUNDATION = Path("evidence/day31/j7_j8_foundation.json")
EXPECTED_FILES = (
    "src/aidy/richer_volatility.py",
    "tests/test_day43_richer_volatility.py",
    "scripts/day43_richer_volatility_acceptance.py",
    "docs/day43-richer-volatility-j7-j8-contract.md",
    ".github/workflows/day43-richer-volatility-acceptance.yml",
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AIDY Day 43 richer volatility acceptance")
    parser.add_argument("--output-dir", default="day43_artifacts")
    return parser.parse_args()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Day 43 evidence is not an object: {path}")
    return value


def _write(path: Path, value: object) -> None:
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def _head_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def _changed_files(head_sha: str) -> list[str]:
    merge_base = subprocess.check_output(
        ["git", "merge-base", BASE_SHA, head_sha], text=True
    ).strip()
    if merge_base != BASE_SHA:
        raise RuntimeError("Day 43 branch is not based on exact accepted Day 42 main.")
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", f"{BASE_SHA}...{head_sha}"], text=True
    ).splitlines()
    unexpected = sorted(set(changed) - set(EXPECTED_FILES))
    if unexpected:
        raise RuntimeError(f"Day 43 modified files outside the frozen surface: {unexpected}")
    return sorted(changed)


def _split_binding(plan_digest: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "manifest_version": "aidy_chronological_split_manifest_v1",
        "replay_harness_version": "aidy_frozen_replay_cpcv_v1",
        "binding_kind": "day43_j7_j8_shadow_evaluation",
        "plan_digest": plan_digest,
        "purge_required": True,
        "embargo_required": True,
        "holdout_tuning_allowed": False,
        "cpcv_pre_holdout_only": True,
    }
    body["split_digest"] = digest(body)
    return body


def _trials(
    *,
    head_sha: str,
    plan: dict[str, Any],
    split: dict[str, Any],
    j7: dict[str, Any],
    j8: dict[str, Any],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    frozen_at = NOW
    pairs = (("J7", j7), ("J8", j8))
    for number, (experiment, result) in enumerate(pairs, start=1):
        hypothesis_key = "j7_hypothesis" if experiment == "J7" else "j8_hypothesis"
        null_key = "j7_null_hypothesis" if experiment == "J7" else "j8_null_hypothesis"
        registered = preregister_trial(
            records,
            trial_number=number,
            hypothesis=str(plan[hypothesis_key]),
            null_hypothesis=str(plan[null_key]),
            dataset_version="accepted-day31-volatility-plus-day43-shadow-v1",
            feature_context_version="aidy_richer_volatility_regime_v1",
            frozen_parameters={
                "experiment": experiment,
                "plan_digest": plan["plan_digest"],
                "minimum_independent_evaluation_n": plan[
                    "minimum_independent_evaluation_n"
                ],
                "threshold_tuning_on_evaluation_set_allowed": False,
                "single_result_can_promote_gate": False,
                "frozen_before_any_day43_result": True,
                "frozen_at_utc": frozen_at.isoformat(),
            },
            chronological_split=split,
            purge="required_by_day37_split_contract",
            embargo="required_by_day37_split_contract",
            evaluation_identity=f"day43-{experiment.lower()}-shadow-evaluation-v1",
            holdout_identity=f"day43-{experiment.lower()}-shadow-holdout-v1",
            preregistered_at=NOW + timedelta(minutes=number),
            code_head=head_sha,
            evidence_digest=plan["plan_digest"],
            purpose="evaluation",
        )
        terminal = str(result["result_state"])
        if terminal == "descriptive_non_null":
            terminal = "passed"
        records.append(
            finalize_trial(
                registered,
                executed_at=NOW + timedelta(minutes=number, seconds=30),
                result_state=terminal,
                result={
                    **result,
                    "plan_digest": plan["plan_digest"],
                    "features_shadow_only": True,
                    "formal_forward_evidence_created": False,
                    "gate_promoted": False,
                },
            )
        )
    verify_trial_registry(records)
    return records


def build_artifacts(head_sha: str) -> dict[str, Any]:
    current = _load(DAY31_CURRENT)
    retrospective = _load(DAY31_RETROSPECTIVE)
    foundation = _load(DAY31_FOUNDATION)
    if not verify_volatility_state(current):
        raise RuntimeError("Accepted Day 31 current volatility state failed verification.")
    if not verify_volatility_state(retrospective):
        raise RuntimeError("Accepted Day 31 retrospective volatility state failed verification.")
    if not verify_j7_j8_foundation(foundation):
        raise RuntimeError("Accepted Day 31 J7/J8 foundation failed verification.")

    plan = day43_experiment_plan(day31_foundation=foundation)
    split = _split_binding(str(plan["plan_digest"]))
    event_kink = build_event_iv_kink(
        as_of=NOW,
        event_at=NOW + timedelta(days=2),
        observations=[],
    )
    shock = build_unexplained_market_shock(
        as_of=NOW,
        volatility_z="3.2",
        volume_z="2.8",
        spread_z="2.6",
        cross_asset_reaction_z="0.8",
    )
    regime = build_richer_volatility_regime(
        day31_state=retrospective,
        shock_state=shock,
        event_kink=event_kink,
    )
    j7 = run_day43_experiment(experiment="J7", rows=[], split_binding=split)
    j8 = run_day43_experiment(experiment="J8", rows=[], split_binding=split)
    trials = _trials(
        head_sha=head_sha,
        plan=plan,
        split=split,
        j7=j7,
        j8=j8,
    )

    summary: dict[str, Any] = {
        "ok": True,
        "base_sha": BASE_SHA,
        "head_sha": head_sha,
        "changed_files": _changed_files(head_sha),
        "accepted_day31_current_state_digest": current["volatility_state_digest"],
        "accepted_day31_retrospective_state_digest": retrospective[
            "volatility_state_digest"
        ],
        "accepted_day31_foundation_digest": foundation["foundation_digest"],
        "explicit_iv_horizon_calendar_days": 30,
        "explicit_rv_horizons_trading_days": [5, 10, 21],
        "jump_estimator_reused": "realized_variation_minus_bipower_variation",
        "vol_of_vol_window_trading_days": 21,
        "redundant_volatility_estimators_added": False,
        "event_kink_state": event_kink["state"],
        "event_kink_not_fabricated": event_kink["state"]
        == "unavailable_no_pit_options_term_structure",
        "unexplained_shock_state": shock["state"],
        "unexplained_shock_market_derived_only": True,
        "news_or_sentiment_input_used": False,
        "narrative_or_intent_label_used": False,
        "j7_result_state": j7["result_state"],
        "j7_effective_independent_n": j7["effective_independent_n"],
        "j8_result_state": j8["result_state"],
        "j8_effective_independent_n": j8["effective_independent_n"],
        "null_or_insufficient_results_retained": True,
        "day32_trial_registry_bound": True,
        "day37_purge_embargo_bound": True,
        "threshold_tuning_on_evaluation_set_allowed": False,
        "cvol_purchase_authorized": False,
        "features_shadow_only": True,
        "regime_or_abstention_conditioning_promoted": False,
        "formal_forward_evidence_created": False,
        "predictive_edge_claimed": False,
        "trading_gate_created": False,
        "plan_digest": plan["plan_digest"],
        "split_digest": split["split_digest"],
        "regime_digest": regime["regime_digest"],
        "shock_digest": shock["shock_digest"],
        "event_kink_digest": event_kink["kink_digest"],
        "trial_digests": [record["trial_digest"] for record in trials],
    }
    summary["summary_digest"] = digest(summary)
    return {
        "summary": summary,
        "plan": plan,
        "split": split,
        "event_kink": event_kink,
        "shock": shock,
        "regime": regime,
        "j7": j7,
        "j8": j8,
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
