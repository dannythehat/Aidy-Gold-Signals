"""GoldThinker factory v1: validate MT5 receipts and select AIDY's ONE replay year.

Pure, offline and fail-closed. No MT5, broker, website, or network interactions.
A self-reported hash is *not* an independently authenticated result.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

SCHEMA = "goldthinker.factory.mt5_bundle.v1"
SELECTION_SCHEMA = "goldthinker.factory.best_year_selection.v1"
HEX = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{2,79}$")
COMPLETE_YEARS = tuple(range(2021, 2026))
ALL_YEARS = tuple(range(2021, 2027))
ROW_KEYS = frozenset({
    "year", "coverage", "test_status", "net_profit_usd", "closed_trades",
    "max_equity_drawdown_pct", "report_sha256", "ledger_sha256",
})
ROOT_KEYS = frozenset({
    "schema", "source_kind", "system_id", "family_id", "strategy_version_sha256",
    "ea_sha256", "broker_profile_sha256", "test_config_sha256",
    "data_manifest_sha256", "tester_build", "as_of_utc", "account_currency",
    "results",
})


class FactoryContractError(ValueError):
    """Invalid or materially incomplete evidence: do not advance the candidate."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _exact(obj: Any, names: frozenset[str], label: str) -> dict:
    if type(obj) is not dict or obj.keys() != names:
        raise FactoryContractError(f"{label}: missing or unexpected keys")
    return obj


def _str(value: Any, label: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise FactoryContractError(f"{label}: nonempty string required")
    return value


def _hash(value: Any, label: str) -> None:
    if type(value) is not str or not HEX.fullmatch(value):
        raise FactoryContractError(f"{label}: SHA256 required")


def _money(value: Any, label: str, *, nonnegative: bool = False) -> Decimal:
    if type(value) is not str or not re.fullmatch(r"-?\d+(?:\.\d{1,4})?", value):
        raise FactoryContractError(f"{label}: fixed-point decimal string required")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise FactoryContractError(f"{label}: invalid decimal") from exc
    if not result.is_finite() or (nonnegative and result < 0):
        raise FactoryContractError(f"{label}: invalid money or risk value")
    return result


def _utc(value: Any) -> datetime:
    raw = _str(value, "as_of_utc")
    if not raw.endswith("Z"):
        raise FactoryContractError("as_of_utc must use UTC Z")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FactoryContractError("invalid as_of_utc") from exc
    if parsed.utcoffset().total_seconds() != 0:
        raise FactoryContractError("as_of_utc must be UTC")
    return parsed


def validate_mt5_bundle(payload: Any) -> dict:
    """Schema/coverage checks only; does NOT authenticate MT5 or financial results."""
    root = _exact(payload, ROOT_KEYS, "MT5 bundle")
    if root["schema"] != SCHEMA:
        raise FactoryContractError("unknown MT5 schema")
    if root["source_kind"] not in ("REAL_MT5_TESTER", "SYNTHETIC_FIXTURE"):
        raise FactoryContractError("unsupported source kind")
    for name in ("system_id", "family_id"):
        if not IDENTIFIER.fullmatch(_str(root[name], name)):
            raise FactoryContractError(f"invalid {name}")
    for name in (
        "strategy_version_sha256", "ea_sha256", "broker_profile_sha256",
        "test_config_sha256", "data_manifest_sha256",
    ):
        _hash(root[name], name)
    _str(root["tester_build"], "tester_build")
    if root["account_currency"] != "USD":
        raise FactoryContractError("v1 supports only explicitly USD-accounted results")
    as_of = _utc(root["as_of_utc"])
    if not isinstance(root["results"], list) or len(root["results"]) != len(ALL_YEARS):
        raise FactoryContractError("one independent year-scoped result is required per year")
    seen: set[int] = set()
    for row in root["results"]:
        yr = _exact(row, ROW_KEYS, "year result")["year"]
        if type(yr) is not int or yr not in ALL_YEARS or yr in seen:
            raise FactoryContractError("duplicate, invalid or missing calendar year")
        seen.add(yr)
        if row["coverage"] not in ("VERIFIED", "MISSING", "INCOMPLETE"):
            raise FactoryContractError("invalid coverage")
        if row["test_status"] not in ("COMPLETED", "BLOCKED", "FAILED", "PARTIAL"):
            raise FactoryContractError("invalid test status")
        # Positive/negative test values are allowed, but absent results must stay null.
        complete = row["coverage"] == "VERIFIED" and row["test_status"] == "COMPLETED"
        if yr == 2026 and as_of.year == 2026 and complete:
            raise FactoryContractError("2026 cannot be a completed calendar year in 2026")
        reportable_partial = (
            yr == 2026 and as_of.year == 2026
            and row["coverage"] == "VERIFIED" and row["test_status"] == "PARTIAL"
        )
        if complete or reportable_partial:
            _money(row["net_profit_usd"], "net_profit_usd")
            _money(row["max_equity_drawdown_pct"], "drawdown", nonnegative=True)
            if Decimal(row["max_equity_drawdown_pct"]) > 100:
                raise FactoryContractError("drawdown exceeds 100%")
            if type(row["closed_trades"]) is not int or row["closed_trades"] < 0:
                raise FactoryContractError("closed_trades must be nonnegative integer")
            _hash(row["report_sha256"], "report_sha256")
            _hash(row["ledger_sha256"], "ledger_sha256")
        else:
            if any(row[name] is not None for name in (
                "net_profit_usd", "closed_trades", "max_equity_drawdown_pct",
                "report_sha256", "ledger_sha256"
            )):
                raise FactoryContractError("unfinished year cannot contain claimed results")
    if seen != set(ALL_YEARS):
        raise FactoryContractError("2021-2026 coverage rows must be present")
    if as_of.year < 2026:
        raise FactoryContractError("unsupported bundle as-of date")
    return root


def select_best_completed_year(payload: Any) -> dict:
    """Select exactly one best profitable year once ALL completed years have evidence.

    Never imply this constitutes out-of-sample validation or an actual verified MT5 run.
    2026 year-to-date is deliberately excluded from selection in 2026.
    """
    root = validate_mt5_bundle(payload)
    years = {r["year"]: r for r in root["results"]}
    completed = all(
        years[y]["coverage"] == "VERIFIED" and years[y]["test_status"] == "COMPLETED"
        for y in COMPLETE_YEARS
    )
    candidates = [years[y] for y in COMPLETE_YEARS] if completed else []
    top = max(
        candidates, key=lambda r: (Decimal(r["net_profit_usd"]), -r["year"])
    ) if candidates else None
    # A profitable year is NOT sufficient for qualification. Six-year policy is separate.
    profitable = top is not None and Decimal(top["net_profit_usd"]) > 0
    selected = top if profitable else None
    outcome = {
        "schema": SELECTION_SCHEMA,
        "system_id": root["system_id"],
        "family_id": root["family_id"],
        "source_kind": root["source_kind"],
        "mt5_bundle_sha256": digest(root),
        "selection_policy": "highest_positive_net_usd_2021_2025_completed_only_v1",
        "selection_status": (
            "RESEARCH_FIXTURE_ONLY" if root["source_kind"] == "SYNTHETIC_FIXTURE"
            else "SELECTED_PENDING_INDEPENDENT_EVIDENCE" if selected is not None
            else "BLOCKED_INCOMPLETE_YEARS" if not completed
            else "NO_PROFITABLE_COMPLETED_YEAR"
        ),
        "aidy_year": selected["year"] if selected else None,
        "aidy_expected_net_usd": selected["net_profit_usd"] if selected else None,
        "aidy_expected_ledger_sha256": selected["ledger_sha256"] if selected else None,
        "historical_edge_verified": False,
        "real_mt5_evidence_authenticated": False,
        "paper_authorised": False,
        "cent_authorised": False,
        "live_authorised": False,
        "public_performance_publication_authorised": False,
    }
    outcome["selection_sha256"] = digest(outcome)
    return outcome
