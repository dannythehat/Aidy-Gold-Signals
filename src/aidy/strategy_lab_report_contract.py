"""Day29 canonical AIDY research results -> future GoldThinker publication contract.

A report is ONE identified study/evidence bundle, never the sum of individual
simulated accounts. All example accounting data are synthetic: the genuinely
observed HistData XAUUSD data only supplies retrospective BID signals.
AIDY research, forward paper and a GoldThinker combined portfolio are distinct.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256

SCHEMA = "aidy.strategy_lab.canonical_result.v1"
HEX = re.compile(r"^[0-9a-f]{64}$")
PERIODS = ("day", "week", "month", "year", "all_time")


def _hash(obj: object) -> str:
    return sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _stamp(s: str) -> datetime:
    if not isinstance(s, str) or not s.endswith("Z"):
        raise ValueError("UTC Z timestamp required")
    parsed = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if parsed.utcoffset() != timedelta(0):
        raise ValueError("non-UTC report timestamp")
    return parsed


def _number(raw: object) -> Decimal:
    if not isinstance(raw, str) or not raw or "e" in raw.lower():
        raise ValueError("exact fixed-point Decimal string required")
    try:
        value = Decimal(raw)
    except Exception as e:
        raise ValueError("invalid money/value") from e
    if not value.is_finite():
        raise ValueError("non-finite money/value")
    return value


def _money(value: Decimal) -> str:
    value = value.quantize(Decimal("0.01"))
    return format(value, "f")


def _digest(value: object) -> bool:
    return isinstance(value, str) and bool(HEX.fullmatch(value))


def _check_sources(journal: dict, cost: dict, evidence: dict) -> dict:
    if (not all(isinstance(x, dict) and x.get("status") == "PASS"
                for x in (journal, cost, evidence))
            or journal.get("scope") != "INTERNAL_SYNTHETIC_CENT_EXACT_REAL_SQLITE_REPLAY"
            or cost.get("scope") != "INTERNAL_SYNTHETIC_FIXED_WINDOW_ACCOUNTING_CONTROL"
            or evidence.get("scope")
            != "OWNER_NINE_FACTOR_FAIL_CLOSED_GOVERNANCE_ON_ACTUAL_PREVIOUS_SOURCE_CHAIN"):
        raise ValueError("Day24/25/28 source-qualified original receipts required")
    m, ref, rating = journal["metrics"], evidence["upstream_evidence"], evidence["rating"]
    if (journal.get("historical_profitability_qualified") is not False
            or evidence.get("independent_real_bidask_net_alpha_qualified") is not False
            or cost.get("genuine_strategy_alpha_qualified") is not False
            or cost.get("independent_real_market_benchmark_qualified") is not False
            or rating.get("score_out_of_100") is not None
            or rating.get("governance") != "ORANGE_INVESTIGATE"
            or rating.get("historical_profitability_qualified") is not False
            or rating.get("optimisation_suggestions_eligible") is not False):
        raise ValueError("unqualified historical evidence must never become a winning report")
    anchors = {
        "day24_original_fixture": journal["original_fixture_sha256"],
        "day24_sqlite_journal": journal["replay_journal_tip_sha256"],
        "day25_synthetic_quotes": cost["day12_quote_snapshot_sha256"],
        "day25_cost_policy": cost["benchmark_and_stress"]["policy_sha256"],
        "day26_real_historical_bid": ref["day26_real_bid_source_sha256"],
        "day26_registered_trial": ref["day26_registered_trial_chain_tip_sha256"],
        "day26_fold_evidence": ref["day26_fold_sha256"],
        "day27_asof_regimes": ref["day27_48_decisions_sha256"],
        "day28_rating_policy": rating["scoring_policy_sha256"],
        "day28_rating_input": rating["evidence_input_sha256"],
    }
    if (any(not _digest(v) for v in anchors.values())
            or anchors["day24_original_fixture"] != ref["day24_known_answer_journal_original_sha256"]
            or anchors["day24_sqlite_journal"] != ref["day24_two_replays_tip_sha256"]
            or anchors["day25_synthetic_quotes"] != ref["day25_synthetic_quote_snapshot_sha256"]
            or anchors["day25_cost_policy"] != ref["day25_scenario_policy_sha256"]
            or m["verified_journal_tip_sha256"] != anchors["day24_sqlite_journal"]
            or m["closed_trades"] != len(m["trades"])
            or m["broker_source_sha256"] != "a"*64
            or m.get("original_broker_trades_verified") is not False
            or ref["held_out_final_oos_reused"] != 0
            or ref["historical_native_m1"] != 600
            or ref["fully_closed_m5"] != 120
            or ref["walkforward_development_decisions"] != 48
            or cost["benchmark_and_stress"]["reference_journal_tip_sha256"]
            != cost["reference_journal_tip_sha256"]
            or len(cost["benchmark_and_stress"]["scenario_results"]) != 3):
        raise ValueError("canonical source trace or independent journal reconciliation mismatch")
    return anchors


def _check_ledger(m: dict) -> None:
    trades = m["trades"]
    gross = costs = net = Decimal(0)
    seen: set[str] = set()
    months: dict[str, Decimal] = {}
    count = {"wins": 0, "losses": 0, "breakeven": 0}
    for trade in trades:
        identifier = trade["position_id"]
        if identifier in seen:
            raise ValueError("duplicate original journal trade")
        seen.add(identifier)
        opened, closed = _stamp(trade["opened_at_utc"]), _stamp(trade["closed_at_utc"])
        if opened > closed or trade["direction"] not in {"long", "short"}:
            raise ValueError("invalid trade time or direction")
        row_gross = _number(trade["gross_usd"])
        row_cost = _number(trade["costs_usd"])
        row_net = _number(trade["net_usd"])
        if row_net != row_gross + row_cost or row_cost > 0:
            raise ValueError("trade cash fees and P&L do not reconcile")
        gross += row_gross
        costs += row_cost
        net += row_net
        count["wins" if row_net > 0 else "losses" if row_net < 0 else "breakeven"] += 1
        months[closed.strftime("%Y-%m")] = months.get(
            closed.strftime("%Y-%m"), Decimal(0)
        ) + row_net
    starting, ending = _number(m["initial_capital_usd"]), _number(m["final_cash_usd"])
    if (gross != _number(m["realized_gross_usd"])
            or costs != _number(m["transaction_costs_usd"])
            or net != _number(m["net_profit_usd"])
            or ending != starting + net
            or ending != _number(m["final_equity_usd"])
            or any(m[k] != n for k, n in count.items())
            or m["closed_trades"] != len(trades)
            or len(months) != len(m["monthly"])
            or any(months.get(x["month_utc"]) != _number(x["net_usd"])
                   or sum(t["closed_at_utc"][:7] == x["month_utc"] for t in trades)
                   != x["closed_trades"] for x in m["monthly"])):
        raise ValueError("ledger accounting or monthly source-of-truth discrepancy")


def _period_views(m: dict, as_of: datetime, journal_sha: str):
    periods = {}
    lineage = {}
    selected = m["trades"]
    for name in PERIODS:
        if name == "day":
            matching = [(i, t) for i, t in enumerate(selected)
                        if _stamp(t["closed_at_utc"]).date() == as_of.date()]
        elif name == "week":
            anchor = as_of.date() - timedelta(days=as_of.weekday())
            matching = [(i, t) for i, t in enumerate(selected)
                        if anchor <= _stamp(t["closed_at_utc"]).date() <= as_of.date()]
        elif name == "month":
            matching = [(i, t) for i, t in enumerate(selected)
                        if _stamp(t["closed_at_utc"]).strftime("%Y-%m")
                        == as_of.strftime("%Y-%m")]
        elif name == "year":
            matching = [(i, t) for i, t in enumerate(selected)
                        if _stamp(t["closed_at_utc"]).year == as_of.year]
        else:
            matching = list(enumerate(selected))
        if any(_stamp(t["closed_at_utc"]) > as_of for _, t in matching):
            raise ValueError("report as-of precedes a counted closure")
        total = sum((_number(t["net_usd"]) for _, t in matching), Decimal(0))
        costs = sum((_number(t["costs_usd"]) for _, t in matching), Decimal(0))
        wins = sum(_number(t["net_usd"]) > 0 for _, t in matching)
        period_trades = [i for i, _ in matching]
        periods[name] = {
            "closed_trades": len(matching),
            "wins": wins,
            "realised_net_pnl_usd": _money(total),
            "allocated_cash_costs_usd": _money(costs),
            "historical_sample_type": "internal_synthetic_research_fixture",
            "source_trade_indices": period_trades,
            "paper_forward_performance": False,
        }
        for field in ("closed_trades", "wins", "realised_net_pnl_usd",
                      "allocated_cash_costs_usd"):
            lineage[f"/research/periods/{name}/{field}"] = {
                "source_sha256": journal_sha, "source_path": "/day24/metrics/trades",
                "filter": name, "trade_indices": period_trades,
                "derivation": "UTC_closed_trades_subset_sum_or_count",
            }
    return periods, lineage


def build_canonical_report(
    journal: dict, cost: dict, evidence: dict, *,
    as_of_utc: str,
) -> dict:
    """Compose immutable **verified upstream research fixture bundle**.

    A trusted server-side caller must supply native internally recalculated
    receipts. This function refuses inconsistent arithmetic and provenance,
    but user-supplied hashes or booleans are NOT independent attestations.
    """
    anchors = _check_sources(journal, cost, evidence)
    m = journal["metrics"]
    _check_ledger(m)
    as_of = _stamp(as_of_utc)
    if any(_stamp(t["closed_at_utc"]) > as_of for t in m["trades"]):
        raise ValueError("as-of report cannot see future trade closures")
    periods, lineage = _period_views(m, as_of, anchors["day24_sqlite_journal"])
    # Every exposed first-party accounting number names an actual journal.
    ledger_fields = ("initial_capital_usd", "final_cash_usd", "final_equity_usd",
                     "realized_gross_usd", "transaction_costs_usd",
                     "net_profit_usd", "closed_trades", "wins", "losses",
                     "breakeven", "win_rate_percent", "expectancy_net_usd_per_trade",
                     "profit_factor", "max_observed_drawdown_usd",
                     "max_observed_drawdown_percent", "sharpe_annualized")
    accounting = {key: m[key] for key in ledger_fields}
    accounting["profit_factor_status"] = m["profit_factor_status"]
    accounting["sharpe_status"] = m["sharpe_status"]
    accounting["drawdown_basis"] = m["max_drawdown_type"]
    for key in ledger_fields:
        lineage[f"/research/accounting/{key}"] = {
            "source_sha256": anchors["day24_sqlite_journal"],
            "source_path": f"/day24/metrics/{key}", "derivation": "replayed_SQLite_cash_journal",
        }
    trades = m["trades"]
    for i, t in enumerate(trades):
        for field in ("gross_usd", "costs_usd", "net_usd"):
            lineage[f"/research/trades/{i}/{field}"] = {
                "source_sha256": anchors["day24_sqlite_journal"],
                "source_path": f"/day24/metrics/trades/{i}/{field}",
                "derivation": "unmodified_replayed_trade",
            }
    scenarios = cost["benchmark_and_stress"]["scenario_results"]
    for i, row in enumerate(scenarios):
        for field, value in row.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                lineage[f"/research/cost_stress/{i}/{field}"] = {
                    "source_sha256": anchors["day25_cost_policy"],
                    "source_path": f"/day25/benchmark_and_stress/scenario_results/{i}/{field}",
                    "derivation": "pinned_two_Sqlite_journal_replay",
                }
            elif field.endswith("_usd") and isinstance(value, str):
                _number(value)
                lineage[f"/research/cost_stress/{i}/{field}"] = {
                    "source_sha256": anchors["day25_cost_policy"],
                    "source_path": f"/day25/benchmark_and_stress/scenario_results/{i}/{field}",
                    "derivation": "pinned_two_SQLite_journal_replay",
                }
    rating = evidence["rating"]
    for i, (_, weight) in enumerate(rating["factor_weights"]):
        if type(weight) is not int or weight < 1:
            raise ValueError("factor weighting differs from frozen policy")
        lineage[f"/research/evidence_rating/factor_weights/{i}/1"] = {
            "source_sha256": anchors["day28_rating_policy"],
            "source_path": f"/day28/rating/factor_weights/{i}/1",
            "derivation": "frozen_owner_policy",
        }
    for key in ("historical_native_m1", "fully_closed_m5",
                "walkforward_development_decisions", "held_out_final_oos_reused"):
        lineage[f"/research/upstream_counts/{key}"] = {
            "source_sha256": anchors["day26_real_historical_bid"]
            if key in ("historical_native_m1", "fully_closed_m5")
            else anchors["day27_asof_regimes"],
            "source_path": f"/day28/upstream_evidence/{key}",
            "derivation": "original_historical_source_replay",
        }
    # GoldThinker has no named/marketable system or proven forward account yet.
    report = {
        "schema": SCHEMA,
        "identity": {
            "research_engine": "AIDY",
            "customer_brand": "GoldThinker",
            "subject_kind": "laboratory_reference_evidence_bundle",
            "subject_id": "AIDY_DAY29_REFERENCE_ONLY",
            "strategy_id": None,
            "goldthinker_system_name": None,
            "strategy_display_description": None,
            "rule_version": None,
            "originating_customer_rights_qualified": False,
            "publication_allowed": False,
            "customer_can_connect": False,
        },
        "as_of_utc": as_of_utc,
        "lifecycle": {
            "stage": "INTERNAL_RESEARCH_REFERENCE",
            "aidy_research_qualified": False,
            "forward_paper_production_qualified": False,
            "goldthinker_named_system_qualified": False,
            "live_capital_owner_approved": False,
        },
        "account_separation": {
            "research_account": {
                "kind": "historical_synthetic_single_fixture",
                "account_id": "DAY24_INTERNAL_SAMPLE_ONLY",
                "account_balance_is_live": False,
            },
            "dedicated_forward_paper_account": None,
            "goldthinker_elite20_combined_account": None,
            "portfolio_return_is_sum_of_system_balances": False,
        },
        "research": {
            "accounting": accounting, "trades": trades,
            "periods": periods, "cost_stress": scenarios,
            "evidence_rating": {
                "score_out_of_100": rating["score_out_of_100"],
                "status": rating["score_status"],
                "governance": rating["governance"],
                "factor_scores": rating["factor_scores"],
                "factor_weights": rating["factor_weights"],
                "missing_evidence": rating["missing_evidence"],
            },
            "upstream_counts": {
                key: evidence["upstream_evidence"][key]
                for key in ("historical_native_m1", "fully_closed_m5",
                            "walkforward_development_decisions", "held_out_final_oos_reused")
            },
            "synthetic_historical_net_pnl_only": True,
            "independently_qualified_real_strategy_profit": False,
        },
        "production": {
            "paper": {
                "status": "NOT_STARTED", "account_id": None,
                "currency": "USD", "periods": None,
                "real_money_balance": None, "forward_paper_pnl": None,
            },
            "elite20": {
                "status": "NOT_STARTED", "combined_account_id": None,
                "components": None, "periods": None,
                "portfolio_pnl": None,
            },
        },
        "provenance": {
            "source_sha256": anchors,
            "numeric_field_lineage": lineage,
            "source_types": {
                "day24": "INTERNAL_SYNTHETIC_LEDGER",
                "day25": "INTERNAL_SYNTHETIC_BIDASK_COST_STRESS",
                "day26": "REAL_RETROSPECTIVE_BID_M1_DIRECTION_ONLY",
                "day27": "REAL_RETROSPECTIVE_BID_M5_DEVELOPMENT_REGIMES",
                "day28": "GOVERNANCE_POLICY_UNQUALIFIED_TRADE_SCORE",
            },
            "source_claims_are_server_replay_receipts_not_user_attestations": True,
        },
        "output_contract": {
            "pdf": "DAY30_NOT_BUILT",
            "csv": "DAY30_NOT_BUILT",
            "charts": "DAY30_NOT_BUILT",
            "period_basis": "UTC_CLOSED_TRADES",
            "not_a_real_gold_strategy": True,
        },
    }
    report["run_id"] = "aidy-d29-" + _hash({
        "anchors": anchors, "as_of_utc": as_of_utc,
        "subject_id": report["identity"]["subject_id"],
    })[:24]
    report["canonical_result_sha256"] = _hash(report)
    return report


def verify_canonical_report(report: dict) -> None:
    if not isinstance(report, dict):
        raise ValueError("canonical report object required")  # noqa: TRY004
    claimed = report.get("canonical_result_sha256")
    original = {k: v for k, v in report.items() if k != "canonical_result_sha256"}
    if not _digest(claimed) or _hash(original) != claimed:
        raise ValueError("tampered canonical report result hash")
    if report.get("schema") != SCHEMA:
        raise ValueError("unrecognised canonical report schema")
    if report["identity"]["publication_allowed"] or report["identity"]["customer_can_connect"]:
        raise ValueError("reference fixture cannot be published or traded")
