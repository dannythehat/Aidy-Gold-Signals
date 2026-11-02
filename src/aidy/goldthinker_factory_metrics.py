"""Ledger-computed v2 metrics. The deal ledger is the only source of truth.

v1 validation is unchanged. A v2 bundle adds a broker cost profile and a
metrics object. Validation recomputes every metric from the canonical ledger
CSV and rejects the bundle on any difference.

Quoted round-trip cost for a trade is:

    (spread_price * contract_size + commission_usd_per_lot_round_turn) * volume

Doubled-cost stress net is the ledger net minus that quoted cost once more
(a second full spread plus a second full round-turn commission). It is not a
broker attestation.

Threshold checks read config/goldthinker_factory_thresholds.json. While
approval_status is UNSET, every check is UNSET. UNSET is not a pass.
"""
from __future__ import annotations

import json
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from typing import Any, Mapping

from aidy.goldthinker_factory_contract import (
    COMPLETE_YEARS,
    ROOT_KEYS,
    SCHEMA,
    FactoryContractError,
    digest,
    validate_mt5_bundle,
)
from aidy.goldthinker_factory_mt5_extract import (
    _claim_text,
    _drawdown,
    closed_trades_from_deals,
    parse_ledger_csv,
)

V2_SCHEMA = "goldthinker.factory.mt5_bundle.v2"
METRICS_SCHEMA = "goldthinker.factory.ledger_metrics.v2"
COST_SCHEMA = "goldthinker.factory.broker_costs.v1"
THRESHOLD_SCHEMA = "goldthinker.factory.thresholds.v1"
V2_ROOT = ROOT_KEYS | {"broker_cost_profile", "metrics"}
COST_KEYS = frozenset({
    "schema", "symbol", "spread_price", "contract_size",
    "commission_usd_per_lot_round_turn", "cost_basis",
})
THRESHOLD_KEYS = frozenset({
    "schema", "approval_status", "approved_by", "note",
    "tolerances", "metric_thresholds",
})
TOLERANCE_KEYS = (
    "signal_time_seconds", "entry_time_seconds", "exit_time_seconds",
    "price_abs", "cost_usd", "cash_pnl_usd",
)
METRIC_THRESHOLD_KEYS = (
    "profit_factor_overall_min",
    "worst_trade_share_of_net_min",
    "average_profit_vs_round_trip_cost_min_usd",
    "doubled_cost_stress_net_min_usd",
)
YEAR_METRIC_KEYS = frozenset({
    "year", "profit_factor", "profit_factor_defined", "worst_trade_net_usd",
    "worst_trade_share_of_net", "worst_trade_share_defined",
    "average_profit_per_trade_usd", "average_round_trip_quoted_cost_usd",
    "average_profit_vs_round_trip_cost_usd", "doubled_cost_stress_net_usd",
    "closed_trades",
})
METRIC_KEYS = frozenset({
    "schema", "profit_factor_overall", "profit_factor_overall_defined",
    "profit_factor_scope", "threshold_approval", "threshold_checks", "years",
})
CHECK_KEYS = frozenset({"metric", "status", "actual", "limit"})
FOUR = Decimal("0.0001")


def _q(value: Decimal) -> str:
    return format(value.quantize(FOUR, rounding=ROUND_HALF_UP), "f")


def _money(value: Any, label: str) -> Decimal:
    if not isinstance(value, str) or not value.strip():
        raise FactoryContractError(f"{label}: decimal string required")
    try:
        number = Decimal(value)
    except Exception as exc:
        raise FactoryContractError(f"{label}: invalid decimal") from exc
    if not number.is_finite() or number < 0:
        raise FactoryContractError(f"{label}: nonnegative decimal required")
    return number


def normalise_broker_costs(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != COST_KEYS:
        raise FactoryContractError("broker cost profile: missing or unexpected keys")
    if payload["schema"] != COST_SCHEMA:
        raise FactoryContractError("unknown broker cost schema")
    if payload["cost_basis"] != "QUOTED_INPUT_NOT_BROKER_ATTESTED":
        raise FactoryContractError("broker costs must be labelled as an unattested quoted input")
    symbol = payload["symbol"]
    if not isinstance(symbol, str) or not symbol.isascii() or not symbol.isalnum() or not symbol.isupper():
        raise FactoryContractError("broker cost symbol must be uppercase ASCII")
    if not 2 <= len(symbol) <= 32:
        raise FactoryContractError("broker cost symbol length is invalid")
    _money(payload["spread_price"], "spread_price")
    contract = _money(payload["contract_size"], "contract_size")
    if contract <= 0:
        raise FactoryContractError("contract_size must be positive")
    _money(payload["commission_usd_per_lot_round_turn"], "commission")
    return payload


def normalise_thresholds(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != THRESHOLD_KEYS:
        raise FactoryContractError("threshold config: missing or unexpected keys")
    if payload["schema"] != THRESHOLD_SCHEMA:
        raise FactoryContractError("unknown threshold schema")
    if payload["approval_status"] not in ("UNSET", "APPROVED"):
        raise FactoryContractError("threshold approval_status must be UNSET or APPROVED")
    if payload["approval_status"] == "APPROVED":
        if not isinstance(payload["approved_by"], str) or not payload["approved_by"].strip():
            raise FactoryContractError("APPROVED thresholds require approved_by")
    elif payload["approved_by"] is not None:
        raise FactoryContractError("UNSET thresholds cannot name an approver")
    if not isinstance(payload["note"], str) or "UNSET" not in payload["note"]:
        raise FactoryContractError("threshold note must say that UNSET is not a pass")
    tolerances = payload["tolerances"]
    metrics = payload["metric_thresholds"]
    if not isinstance(tolerances, dict) or set(tolerances) != set(TOLERANCE_KEYS):
        raise FactoryContractError("tolerances: missing or unexpected keys")
    if not isinstance(metrics, dict) or set(metrics) != set(METRIC_THRESHOLD_KEYS):
        raise FactoryContractError("metric thresholds: missing or unexpected keys")
    approved = payload["approval_status"] == "APPROVED"
    signed_gates = {
        "worst_trade_share_of_net_min",
        "average_profit_vs_round_trip_cost_min_usd",
        "doubled_cost_stress_net_min_usd",
    }
    for name, value in {**tolerances, **metrics}.items():
        if approved:
            if not isinstance(value, str):
                raise FactoryContractError(f"{name}: approved gate needs an exact decimal string")
            number = _signed(value, name) if name in signed_gates else _money(value, name)
            if name.endswith("_seconds") and number != number.to_integral_value():
                raise FactoryContractError(f"{name}: whole seconds required")
        elif value is not None:
            raise FactoryContractError(f"{name}: UNSET config must keep this gate null")
    return payload


def _signed(value: str, label: str) -> Decimal:
    try:
        number = Decimal(value)
    except Exception as exc:
        raise FactoryContractError(f"{label}: invalid decimal") from exc
    if not number.is_finite():
        raise FactoryContractError(f"{label}: non-finite")
    return number


def load_thresholds(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FactoryContractError("threshold config is not JSON") from exc
    return normalise_thresholds(payload)


def _empty_year(year: int) -> dict[str, Any]:
    return {
        "year": year,
        "profit_factor": None,
        "profit_factor_defined": False,
        "worst_trade_net_usd": None,
        "worst_trade_share_of_net": None,
        "worst_trade_share_defined": False,
        "average_profit_per_trade_usd": None,
        "average_round_trip_quoted_cost_usd": None,
        "average_profit_vs_round_trip_cost_usd": None,
        "doubled_cost_stress_net_usd": None,
        "closed_trades": None,
    }


def _quoted_cost(trade_volume: Decimal, spread: Decimal, contract: Decimal, commission: Decimal) -> Decimal:
    return (spread * contract + commission) * trade_volume


def metrics_from_deals(
    deals: list[dict[str, Any]], costs: Mapping[str, Any]
) -> dict[str, Any]:
    trades, residual = closed_trades_from_deals(deals)
    if residual != 0:
        raise FactoryContractError("metrics require a flat deal ledger")
    year_net = sum((trade.net_pnl for trade in trades), Decimal(0))
    wins = sum((trade.net_pnl for trade in trades if trade.net_pnl > 0), Decimal(0))
    losses = sum((trade.net_pnl for trade in trades if trade.net_pnl < 0), Decimal(0))
    defined = losses != 0
    factor = None if not defined else _q(wins / abs(losses))
    spread = Decimal(costs["spread_price"])
    contract = Decimal(costs["contract_size"])
    commission = Decimal(costs["commission_usd_per_lot_round_turn"])
    count = len(trades)
    if count == 0:
        return {
            "profit_factor": None,
            "profit_factor_defined": False,
            "worst_trade_net_usd": None,
            "worst_trade_share_of_net": None,
            "worst_trade_share_defined": False,
            "average_profit_per_trade_usd": None,
            "average_round_trip_quoted_cost_usd": None,
            "average_profit_vs_round_trip_cost_usd": None,
            "doubled_cost_stress_net_usd": _q(year_net),
            "closed_trades": 0,
            "year_net": year_net,
            "wins": wins,
            "losses": losses,
        }
    worst = min(trades, key=lambda trade: (trade.net_pnl, trade.exit_time, trade.trade_id))
    share_defined = year_net != 0
    quoted = [
        _quoted_cost(trade.volume, spread, contract, commission) for trade in trades
    ]
    quoted_sum = sum(quoted, Decimal(0))
    average_profit = year_net / Decimal(count)
    average_quoted = quoted_sum / Decimal(count)
    return {
        "profit_factor": factor,
        "profit_factor_defined": defined,
        "worst_trade_net_usd": _q(worst.net_pnl),
        "worst_trade_share_of_net": None if not share_defined else _q(worst.net_pnl / year_net),
        "worst_trade_share_defined": share_defined,
        "average_profit_per_trade_usd": _q(average_profit),
        "average_round_trip_quoted_cost_usd": _q(average_quoted),
        "average_profit_vs_round_trip_cost_usd": _q(average_profit - average_quoted),
        "doubled_cost_stress_net_usd": _q(year_net - quoted_sum),
        "closed_trades": count,
        "year_net": year_net,
        "wins": wins,
        "losses": losses,
    }


def _gate(actual: str | None, limit: str | None, approval: str, *, signed: bool = False) -> str:
    if approval != "APPROVED" or limit is None:
        return "UNSET"
    if actual is None:
        return "FAIL"
    left = _signed(actual, "actual") if signed else _money(actual, "actual")
    right = _signed(limit, "limit") if signed else _money(limit, "limit")
    return "PASS" if left >= right else "FAIL"


def _min_text(values: list[str | None]) -> str | None:
    if not values or any(value is None for value in values):
        return None
    return _q(min(Decimal(value) for value in values if value is not None))


def compute_v2_metrics(
    bundle_v1: Mapping[str, Any],
    ledgers: Mapping[int, str],
    costs: Mapping[str, Any],
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    validate_mt5_bundle(dict(bundle_v1))
    costs = normalise_broker_costs(dict(costs))
    thresholds = normalise_thresholds(dict(thresholds))
    if digest(costs) != bundle_v1["broker_profile_sha256"]:
        raise FactoryContractError("broker_profile_sha256 is not the cost-profile digest")
    by_year = {row["year"]: row for row in bundle_v1["results"]}
    if set(ledgers) != {
        year for year, row in by_year.items() if row["ledger_sha256"] is not None
    }:
        raise FactoryContractError("ledgers must be exactly the admitted years")
    computed: dict[int, dict[str, Any]] = {}
    wins = Decimal(0)
    losses = Decimal(0)
    completed_ready = True
    for year in COMPLETE_YEARS:
        row = by_year[year]
        if row["test_status"] != "COMPLETED" or row["ledger_sha256"] is None:
            completed_ready = False
            continue
        detail = _require_ledger(year, row, ledgers[year], costs)
        computed[year] = detail
        wins += detail["wins"]
        losses += detail["losses"]
    partial = by_year[2026]
    if partial["ledger_sha256"] is not None:
        if partial["test_status"] != "PARTIAL":
            raise FactoryContractError("2026 ledger is present but the year is not PARTIAL")
        computed[2026] = _require_ledger(2026, partial, ledgers[2026], costs)
    if completed_ready and losses != 0:
        overall = _q(wins / abs(losses))
        overall_defined = True
        scope = "COMPLETED_2021_2025"
    else:
        overall = None
        overall_defined = False
        scope = "INCOMPLETE" if not completed_ready else "NO_LOSING_TRADES"
    ordered_years = []
    for year in range(2021, 2027):
        if year not in computed:
            ordered_years.append(_empty_year(year))
            continue
        detail = computed[year]
        ordered_years.append({
            "year": year,
            "profit_factor": detail["profit_factor"],
            "profit_factor_defined": detail["profit_factor_defined"],
            "worst_trade_net_usd": detail["worst_trade_net_usd"],
            "worst_trade_share_of_net": detail["worst_trade_share_of_net"],
            "worst_trade_share_defined": detail["worst_trade_share_defined"],
            "average_profit_per_trade_usd": detail["average_profit_per_trade_usd"],
            "average_round_trip_quoted_cost_usd": detail["average_round_trip_quoted_cost_usd"],
            "average_profit_vs_round_trip_cost_usd": detail["average_profit_vs_round_trip_cost_usd"],
            "doubled_cost_stress_net_usd": detail["doubled_cost_stress_net_usd"],
            "closed_trades": detail["closed_trades"],
        })
    approval = thresholds["approval_status"]
    limits = thresholds["metric_thresholds"]
    completed_rows = [row for row in ordered_years if 2021 <= row["year"] <= 2025 and row["closed_trades"] is not None]
    if not completed_ready:
        completed_rows = []
    checks = [
        ("profit_factor_overall_min", overall, False),
        ("worst_trade_share_of_net_min", _min_text([
            row["worst_trade_share_of_net"] for row in completed_rows
        ]) if completed_rows else None, True),
        ("average_profit_vs_round_trip_cost_min_usd", _min_text([
            row["average_profit_vs_round_trip_cost_usd"] for row in completed_rows
        ]) if completed_rows else None, True),
        ("doubled_cost_stress_net_min_usd", _min_text([
            row["doubled_cost_stress_net_usd"] for row in completed_rows
        ]) if completed_rows else None, True),
    ]
    return {
        "schema": METRICS_SCHEMA,
        "profit_factor_overall": overall,
        "profit_factor_overall_defined": overall_defined,
        "profit_factor_scope": scope,
        "threshold_approval": approval,
        "threshold_checks": [
            {
                "metric": name,
                "status": _gate(actual, limits[name], approval, signed=signed),
                "actual": actual,
                "limit": limits[name],
            }
            for name, actual, signed in checks
        ],
        "years": ordered_years,
    }


def _require_ledger(year: int, row: Mapping[str, Any], csv_text: str, costs: Mapping[str, Any]) -> dict[str, Any]:
    if sha256(csv_text.encode("utf-8")).hexdigest() != row["ledger_sha256"]:
        raise FactoryContractError(f"{year} ledger_sha256 does not match the ledger bytes")
    deals = parse_ledger_csv(csv_text)
    detail = metrics_from_deals(deals, costs)
    if detail["closed_trades"] != row["closed_trades"]:
        raise FactoryContractError(f"{year} closed trades do not match the ledger")
    if _claim_text(detail["year_net"]) != row["net_profit_usd"]:
        raise FactoryContractError(f"{year} net profit does not match the ledger")
    deposit = deals[0]["balance"]
    stats = _drawdown([deal["balance"] for deal in deals], deposit)
    percent = format(stats["relative_pct"].quantize(FOUR, rounding=ROUND_HALF_UP), "f")
    if percent != row["max_equity_drawdown_pct"]:
        raise FactoryContractError(f"{year} drawdown percent does not match the ledger balance path")
    return detail


def v1_view(payload: Mapping[str, Any]) -> dict[str, Any]:
    view = {key: payload[key] for key in ROOT_KEYS}
    view["schema"] = SCHEMA
    return view


def validate_mt5_bundle_v2(
    payload: Any,
    ledgers: Mapping[int, str],
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != V2_ROOT:
        raise FactoryContractError("MT5 bundle v2: missing or unexpected keys")
    if payload["schema"] != V2_SCHEMA:
        raise FactoryContractError("unknown MT5 v2 schema")
    view = v1_view(payload)
    validate_mt5_bundle(view)
    expected = compute_v2_metrics(view, ledgers, payload["broker_cost_profile"], thresholds)
    if payload["metrics"] != expected:
        raise FactoryContractError("v2 metrics do not match recomputation from the deal ledger")
    for row in payload["metrics"]["years"]:
        if set(row) != YEAR_METRIC_KEYS:
            raise FactoryContractError("year metrics: missing or unexpected keys")
    if set(payload["metrics"]) != METRIC_KEYS:
        raise FactoryContractError("metrics: missing or unexpected keys")
    for check in payload["metrics"]["threshold_checks"]:
        if set(check) != CHECK_KEYS or check["status"] not in ("UNSET", "PASS", "FAIL"):
            raise FactoryContractError("threshold check shape is invalid")
        if thresholds["approval_status"] != "APPROVED" and check["status"] != "UNSET":
            raise FactoryContractError("UNSET thresholds cannot produce PASS or FAIL")
    return payload


def attach_v2(
    bundle_v1: Mapping[str, Any],
    ledgers: Mapping[int, str],
    costs: Mapping[str, Any],
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    view = dict(bundle_v1)
    if view.get("schema") != SCHEMA:
        raise FactoryContractError("attach_v2 starts from a v1 bundle")
    profile = normalise_broker_costs(dict(costs))
    view["broker_profile_sha256"] = digest(profile)
    metrics = compute_v2_metrics(view, ledgers, profile, thresholds)
    payload = dict(view)
    payload["schema"] = V2_SCHEMA
    payload["broker_cost_profile"] = profile
    payload["metrics"] = metrics
    return validate_mt5_bundle_v2(payload, ledgers, thresholds)
