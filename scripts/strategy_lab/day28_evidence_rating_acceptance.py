"""Day28 evidence scoring: genuine upstream replay, NEVER fabricated profit.

The prior Day24 ledger and Day25 fee stresses use INTERNAL SYNTHETIC prices.
Days26-27 use actual retrospectively sourced BID-only HistData bars. Mixing
these is a valid negative *qualification* check, NOT a real trading score.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aidy.strategy_lab_evidence_rating import (
    FACTOR_WEIGHTS,
    EvidenceBasis,
    FactorFinding,
    rate_strategy_evidence,
)
from aidy.strategy_lab_history_reader import ReadResult, Window, read_bigquery_window
from scripts.strategy_lab.day24_ledger_metrics_acceptance import main as day24_main
from scripts.strategy_lab.day25_baselines_cost_stress_acceptance import audit as day25_audit
from scripts.strategy_lab.day26_sealed_oos_real_history import audit as day26_audit
from scripts.strategy_lab.day27_real_market_regime_audit import audit_source as day27_audit

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/strategy_lab/day28_nine_factor_evidence_acceptance.json"
DAY24_OUT = ROOT / "artifacts/strategy_lab/day24_ledger_metrics_acceptance.json"


def audit_source(history: ReadResult) -> dict:
    if day24_main() != 0:
        raise ValueError("Day24 genuine two-journal source replay failed")
    journal = json.loads(DAY24_OUT.read_text(encoding="utf-8"))
    cost = day25_audit()
    oos = day26_audit(history)
    regime = day27_audit(history)
    if (journal["status"] != "PASS" or cost["status"] != "PASS"
            or oos["status"] != "PASS" or regime["status"] != "PASS"):
        raise ValueError("preceding source-bound stage failed")
    if (journal["historical_profitability_qualified"] is not False
            or cost["genuine_strategy_alpha_qualified"] is not False
            or cost["independent_real_market_benchmark_qualified"] is not False
            or oos["broker_costs_or_alpha_qualified"] is not False
            or oos["source_input_sha256"] != regime["report"]["source_input_sha256"]
            or oos["development"]["fold_evidence_sha256"] != regime["report"]["day26_fold_evidence_sha256"]
            or oos["development"]["holdout_sha256"] != regime["report"]["day26_holdout_commit_sha256"]
            or regime["report"]["evaluated_walkforward_predictions"] != 48
            or regime["report"]["sealed_holdout_decisions_consumed"] != 0):
        raise ValueError("invalid provenance or an attempted unqualified alpha upgrade")
    basis = EvidenceBasis(
        origin="retrospective_bid_only",
        strategy_rule_sha256=oos["development"]["model_sha256"],
        historical_input_sha256=history.input_digest,
        original_run_sha256=oos["development"]["development_sha256"],
        verified_costed_trade_ledger_sha256=None,
        oos_holdout_trial_tip_sha256=oos["trial_ledger"]["chain_tip_sha256"],
        fair_matched_benchmark_sha256=None,
        historical_source_independently_verified=True,
        actual_bid_ask_costed_trades_independently_replayed=False,
        chronological_oos_trading_independently_verified=False,
        fair_benchmark_independently_verified=False,
        full_trial_family_independently_registered=False,
        historical_trades=None,
        observed_net_expectancy_usd=None,
        observed_benchmark_edge_usd=None,
    )
    reasons = {
        "net_trading_expectancy": ("UNKNOWN", "Real bid/ask executed net trades and expectancy not available."),
        "out_of_sample_robustness": ("UNKNOWN", "Day26 BID-close sign holdout is not costed trade OOS."),
        "market_condition_performance": ("UNKNOWN", "Day27 has 48 causal BID-direction labels but no strategy trade returns."),
        "drawdown_and_risk": ("UNKNOWN", "Day24 observed-equity risk proof is synthetic, not original-market P&L."),
        "realistic_trading_costs": ("UNKNOWN", "Day25 3 scenarios and spreads are internal synthetic accounting controls."),
        "rule_clarity": ("UNKNOWN", "Toy Day26 rule is reproducible but no audited customer/native strategy ruleset."),
        "adequate_sample_size": ("INSUFFICIENT", "48 direction observations do not establish 30+ qualified completed trades."),
        "broker_compatibility": ("UNKNOWN", "Real broker executions or native platform parity not qualified."),
        "independent_reproducibility": ("UNKNOWN", "Historical data replays; real full trade performance not independently replicated."),
    }
    findings = tuple(FactorFinding(name, reasons[name][0], None, None, reasons[name][1])
                     for name, _ in FACTOR_WEIGHTS)
    rating = rate_strategy_evidence(basis, findings)
    if (rating.score_out_of_100 is not None
            or rating.governance != "ORANGE_INVESTIGATE"
            or rating.optimisation_suggestions_eligible
            or rating.historical_profitability_qualified
            or rating.automatically_authorised_for_live_trading):
        raise ValueError("unsupported strategy score or optimisation was issued")
    return {
        "status": "PASS",
        "scope": "OWNER_NINE_FACTOR_FAIL_CLOSED_GOVERNANCE_ON_ACTUAL_PREVIOUS_SOURCE_CHAIN",
        "rating": rating.to_wire(),
        "upstream_evidence": {
            "day24_known_answer_journal_original_sha256": journal["original_fixture_sha256"],
            "day24_two_replays_tip_sha256": journal["replay_journal_tip_sha256"],
            "day25_synthetic_quote_snapshot_sha256": cost["day12_quote_snapshot_sha256"],
            "day25_scenario_policy_sha256": cost["benchmark_and_stress"]["policy_sha256"],
            "day26_real_bid_source_sha256": oos["source_input_sha256"],
            "day26_registered_trial_chain_tip_sha256": oos["trial_ledger"]["chain_tip_sha256"],
            "day26_fold_sha256": oos["development"]["fold_evidence_sha256"],
            "day27_regime_policy_sha256": regime["report"]["regime_policy_sha256"],
            "day27_48_decisions_sha256": regime["report"]["decisions_sha256"],
            "historical_native_m1": oos["native_m1_count"],
            "fully_closed_m5": oos["closed_m5_count"],
            "walkforward_development_decisions": regime["report"]["evaluated_walkforward_predictions"],
            "held_out_final_oos_reused": regime["report"]["sealed_holdout_decisions_consumed"],
            "day24_synthetic": True,
            "day25_synthetic": True,
            "day26_day27_retrospective_bid_only": True,
        },
        "customer_optimisation_requires_separate_permission": True,
        "independent_real_bidask_net_alpha_qualified": False,
    }


def main() -> int:
    from google.cloud import bigquery
    from google.oauth2 import service_account

    OUT.parent.mkdir(parents=True, exist_ok=True)
    try:
        credentials = json.loads(os.environ["AIDY_GCP_SERVICE_ACCOUNT_JSON"])
        client = bigquery.Client(
            project=credentials["project_id"], location="EU",
            credentials=service_account.Credentials.from_service_account_info(credentials),
        )
        first = datetime(2025, 1, 6, 11, tzinfo=UTC)
        end = first + timedelta(minutes=600)
        history, first_job = read_bigquery_window(client, Window(first, end, end, 5))
        proof = audit_source(history)
        replay, second_job = read_bigquery_window(
            client, Window(first, end, end, 5, expected_digest=history.input_digest)
        )
        if replay != history or audit_source(replay) != proof:
            raise ValueError("two independent real historical reads did not reproduce Day28 evidence")
        proof["real_bigquery_source_job_id"] = first_job
        proof["real_bigquery_replay_job_id"] = second_job
        proof["read_only"] = True
    except Exception as exc:  # noqa: BLE001 - fail-closed evidence is archived
        proof = {
            "status": "BLOCKED", "error_type": type(exc).__name__,
            "message": str(exc)[:400], "independent_real_bidask_net_alpha_qualified": False,
        }
    OUT.write_text(json.dumps(proof, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps(proof, sort_keys=True))
    return 0 if proof["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
