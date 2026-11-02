"""Reconcile AIDY trades to the one selected MT5 year.

This does not search other years, does not open tick files, and does not send
orders. A real strategy replay hook is not wired: callers pass an
AidySelectedYearReplay. The built-in adapter reports that gap as
INCONCLUSIVE. MATCH is possible only when an adapter supplied trades and
Danny has approved the tolerance file. UNSET tolerances never match.

Final P&L is reported and is never sufficient. Each paired trade itemises
signal time, entry time, exit time, entry price, exit price, costs and cash.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Protocol

from aidy.goldthinker_factory_contract import (
    FactoryContractError,
    digest,
)
from aidy.goldthinker_factory_metrics import normalise_thresholds
from aidy.goldthinker_factory_mt5_extract import (
    closed_trades_from_deals,
    parse_ledger_csv,
)

RECONCILE_SCHEMA = "goldthinker.factory.aidy_reconciliation.v1"
TRADES_SCHEMA = "goldthinker.factory.aidy_trades.v1"
MANIFEST_SCHEMA = "goldthinker.factory.data_manifest.v1"
SELECTION_KEYS = frozenset({
    "schema", "system_id", "family_id", "source_kind", "mt5_bundle_sha256",
    "selection_policy", "selection_status", "aidy_year", "aidy_expected_net_usd",
    "aidy_expected_ledger_sha256", "historical_edge_verified",
    "real_mt5_evidence_authenticated", "paper_authorised", "cent_authorised",
    "live_authorised", "public_performance_publication_authorised",
    "selection_sha256",
})
COMPARED_FIELDS = (
    "signal_time", "entry_time", "exit_time", "entry_price", "exit_price",
    "cost_usd", "cash_pnl_usd",
)
MISSING_HOOK = (
    "No offline AIDY strategy replay is wired for an arbitrary selected year. "
    "strategy_lab_deterministic_replay.replay_cash_events replays a pre-recorded cash journal; "
    "strategy_lab_order_lifecycle.simulate_order fills one order against a QuoteTape; "
    "strategy_lab_reference_run.run_internal_reference is a frozen 55-bar internal fixture. "
    "None of these accepts a factory strategy plus the selected MT5 year and emits comparable trades. "
    "Pass an explicit AidySelectedYearReplay adapter."
)
_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
_TRADE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")


class AidyReplayUnavailable(Exception):
    """The adapter cannot produce trades for the selected year."""


@dataclass(frozen=True)
class AidyTrade:
    trade_id: str
    signal_time: datetime
    entry_time: datetime
    exit_time: datetime
    side: str
    volume: Decimal
    entry_price: Decimal
    exit_price: Decimal
    commission: Decimal
    swap: Decimal
    profit: Decimal
    net_pnl: Decimal


@dataclass(frozen=True)
class AidyReplayResult:
    adapter: str
    year: int
    trades: tuple[AidyTrade, ...]
    notes: str


class AidySelectedYearReplay(Protocol):
    def replay(self, *, selection: Mapping[str, Any], data_manifest: Mapping[str, Any]) -> AidyReplayResult:
        """Return trades for selection['aidy_year'] only."""


class UnavailableAidyStrategyReplay:
    """Placeholder for the missing offline strategy-to-trade hook."""

    adapter_id = "unavailable_aidy_strategy_replay"

    def replay(self, *, selection: Mapping[str, Any], data_manifest: Mapping[str, Any]) -> AidyReplayResult:
        raise AidyReplayUnavailable(MISSING_HOOK)


class ExplicitTradeListReplay:
    """Caller-supplied trades for one year. Does not open other years."""

    adapter_id = "explicit_trade_list"

    def __init__(self, document: Mapping[str, Any]) -> None:
        self._document = document

    def replay(self, *, selection: Mapping[str, Any], data_manifest: Mapping[str, Any]) -> AidyReplayResult:
        year = selection.get("aidy_year")
        if not isinstance(self._document, Mapping) or self._document.get("year") != year:
            raise AidyReplayUnavailable(
                "explicit AIDY trades are not for the selected year; other years are not searched"
            )
        if self._document.get("system_id") != selection.get("system_id"):
            raise FactoryContractError("AIDY trades are for a different system")
        trades = _aidy_trades(self._document, year)
        return AidyReplayResult(self.adapter_id, year, tuple(trades), "explicit trade list, not a strategy replay")


def _stamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or _STAMP.fullmatch(value) is None:
        raise FactoryContractError(f"{label}: broker-server timestamp required")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
    except ValueError as exc:
        raise FactoryContractError(f"{label}: impossible timestamp") from exc


def _decimal(value: Any, label: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, str):
        raise FactoryContractError(f"{label}: decimal string required")
    try:
        number = Decimal(value)
    except Exception as exc:
        raise FactoryContractError(f"{label}: invalid decimal") from exc
    if not number.is_finite() or (positive and number <= 0):
        raise FactoryContractError(f"{label}: invalid magnitude")
    return number


def _aidy_trades(document: Mapping[str, Any], year: int) -> list[AidyTrade]:
    keys = {
        "schema", "source_kind", "system_id", "year", "trades",
    }
    if set(document) != keys:
        raise FactoryContractError("AIDY trade list: missing or unexpected keys")
    if document["schema"] != TRADES_SCHEMA:
        raise FactoryContractError("unknown AIDY trade schema")
    if document["source_kind"] not in ("SYNTHETIC_FIXTURE", "AIDY_OFFLINE_REPLAY"):
        raise FactoryContractError("unsupported AIDY trade source")
    if not isinstance(document["trades"], list):
        raise FactoryContractError("AIDY trades must be a list")
    trades: list[AidyTrade] = []
    seen: set[str] = set()
    for raw in document["trades"]:
        if not isinstance(raw, dict) or set(raw) != {
            "trade_id", "signal_time", "entry_time", "exit_time", "side",
            "volume", "entry_price", "exit_price", "commission", "swap",
            "profit", "net_pnl",
        }:
            raise FactoryContractError("AIDY trade: missing or unexpected keys")
        trade_id = raw["trade_id"]
        if not isinstance(trade_id, str) or _TRADE_ID.fullmatch(trade_id) is None or trade_id in seen:
            raise FactoryContractError("AIDY trade id is missing or duplicated")
        seen.add(trade_id)
        if raw["side"] not in ("buy", "sell"):
            raise FactoryContractError("AIDY trade side must be buy or sell")
        signal = _stamp(raw["signal_time"], "signal_time")
        entry = _stamp(raw["entry_time"], "entry_time")
        exit_at = _stamp(raw["exit_time"], "exit_time")
        if signal.year != year or entry.year != year or exit_at.year != year:
            raise FactoryContractError("AIDY trade timestamp is outside the selected year")
        if exit_at < entry:
            raise FactoryContractError("AIDY trade exits before it enters")
        profit = _decimal(raw["profit"], "profit")
        commission = _decimal(raw["commission"], "commission")
        swap = _decimal(raw["swap"], "swap")
        net = _decimal(raw["net_pnl"], "net_pnl")
        if profit + commission + swap != net:
            raise FactoryContractError("AIDY trade net is not profit plus commission plus swap")
        trades.append(AidyTrade(
            trade_id, signal, entry, exit_at, raw["side"],
            _decimal(raw["volume"], "volume", positive=True),
            _decimal(raw["entry_price"], "entry_price", positive=True),
            _decimal(raw["exit_price"], "exit_price", positive=True),
            commission, swap, profit, net,
        ))
    return trades


def _manifest(payload: Mapping[str, Any], system_id: str, year: int) -> None:
    if not isinstance(payload, dict) or set(payload) != {"schema", "system_id", "years"}:
        raise FactoryContractError("data manifest: missing or unexpected keys")
    if payload["schema"] != MANIFEST_SCHEMA or payload["system_id"] != system_id:
        raise FactoryContractError("data manifest identity does not match the selection")
    if not isinstance(payload["years"], list):
        raise FactoryContractError("data manifest years must be a list")
    found = False
    seen: set[int] = set()
    for row in payload["years"]:
        if not isinstance(row, dict) or set(row) != {"year", "dataset_id", "coverage"}:
            raise FactoryContractError("data manifest year: missing or unexpected keys")
        if type(row["year"]) is not int or row["year"] in seen or row["year"] not in range(2021, 2027):
            raise FactoryContractError("data manifest year is invalid")
        seen.add(row["year"])
        if row["coverage"] not in ("FIXTURE", "NOT_ATTACHED", "VERIFIED_TICKS"):
            raise FactoryContractError("data manifest coverage is invalid")
        dataset = row["dataset_id"]
        if not isinstance(dataset, str) or not dataset.strip() or dataset != dataset.strip():
            raise FactoryContractError("dataset_id is required and is not opened")
        if row["year"] == year:
            found = True
    if not found:
        raise FactoryContractError("DATA_MANIFEST_YEAR_MISSING")


def _text(value: Decimal) -> str:
    return format(value, "f")


def _seconds(left: datetime, right: datetime) -> str:
    return str(int((left - right).total_seconds()))


def _receipt(body: dict[str, Any]) -> dict[str, Any]:
    body["receipt_sha256"] = digest(body)
    return body


def _base(
    *,
    status: str,
    reasons: list[str],
    selection: Mapping[str, Any] | None,
    adapter: str,
    notes: str,
    thresholds: Mapping[str, Any] | None,
    manifest_sha: str | None,
    ledger_sha: str | None,
    replay_kind: str,
) -> dict[str, Any]:
    approval = None if thresholds is None else thresholds["approval_status"]
    tolerances = None if thresholds is None else thresholds["tolerances"]
    return {
        "schema": RECONCILE_SCHEMA,
        "status": status,
        "reasons": sorted(set(reasons)),
        "research_packaging_allowed": status == "MATCH",
        "system_id": None if selection is None else selection.get("system_id"),
        "source_kind": None if selection is None else selection.get("source_kind"),
        "aidy_year": None if selection is None else selection.get("aidy_year"),
        "selection_sha256": None if selection is None else selection.get("selection_sha256"),
        "ledger_sha256": ledger_sha,
        "data_manifest_sha256": manifest_sha,
        "replay_adapter": adapter,
        "replay_notes": notes,
        "tolerances_approval": approval,
        "tolerances": tolerances,
        "compared_fields": list(COMPARED_FIELDS),
        "final_pnl_only": False,
        "mt5_trade_count": None,
        "aidy_trade_count": None,
        "matched_count": None,
        "unmatched_mt5": [],
        "unmatched_aidy": [],
        "differences": [],
        "mt5_net_pnl_usd": None,
        "aidy_net_pnl_usd": None,
        "explained_pnl_gap_usd": None,
        "unexplained_residual_usd": None,
        "historical_edge_verified": False,
        "real_mt5_evidence_authenticated": False,
        "paper_authorised": False,
        "cent_authorised": False,
        "live_authorised": False,
        "public_performance_publication_authorised": False,
        "broker_credentials_used": False,
        "orders_sent": False,
        "tick_data_opened": False,
        "aidy_strategy_replay": replay_kind,
    }


def reconcile_selected_year(
    *,
    selection: Mapping[str, Any],
    ledger_dir: Path,
    data_manifest: Mapping[str, Any],
    replay: AidySelectedYearReplay,
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare one selected year. Never lists or opens a different year's ledger."""
    config = normalise_thresholds(dict(thresholds))
    adapter = getattr(replay, "adapter_id", "custom")
    replay_kind = {
        "unavailable_aidy_strategy_replay": "NOT_AVAILABLE",
        "explicit_trade_list": "EXPLICIT_INTERFACE",
    }.get(adapter, "CUSTOM")
    if not isinstance(selection, Mapping) or set(selection) != SELECTION_KEYS:
        return _receipt(_base(
            status="INCONCLUSIVE", reasons=["MALFORMED_SELECTION"], selection=None,
            adapter=adapter, notes="", thresholds=config, manifest_sha=None,
            ledger_sha=None, replay_kind=replay_kind,
        ))
    body = {key: selection[key] for key in selection if key != "selection_sha256"}
    if digest(body) != selection["selection_sha256"]:
        return _receipt(_base(
            status="INCONCLUSIVE", reasons=["TAMPERED_SELECTION"], selection=selection,
            adapter=adapter, notes="", thresholds=config, manifest_sha=None,
            ledger_sha=None, replay_kind=replay_kind,
        ))
    if selection["aidy_year"] is None:
        return _receipt(_base(
            status="INCONCLUSIVE", reasons=["NO_SELECTED_YEAR"], selection=selection,
            adapter=adapter, notes="no completed profitable year was selected",
            thresholds=config, manifest_sha=digest(dict(data_manifest)) if isinstance(data_manifest, dict) else None,
            ledger_sha=None, replay_kind=replay_kind,
        ))
    year = selection["aidy_year"]
    try:
        _manifest(data_manifest, selection["system_id"], year)
    except FactoryContractError as exc:
        reason = str(exc)
        code = reason if reason.startswith("DATA_MANIFEST") else "MALFORMED_MANIFEST"
        return _receipt(_base(
            status="INCONCLUSIVE", reasons=[code], selection=selection, adapter=adapter,
            notes=reason, thresholds=config,
            manifest_sha=digest(dict(data_manifest)) if isinstance(data_manifest, dict) else None,
            ledger_sha=None, replay_kind=replay_kind,
        ))
    manifest_sha = digest(dict(data_manifest))
    # The only ledger path consulted. A sibling year file is not discovered.
    ledger_path = Path(ledger_dir) / f"{selection['system_id']}_{year}_deals.csv"
    if not ledger_path.is_file():
        return _receipt(_base(
            status="INCONCLUSIVE", reasons=["LEDGER_MISSING"], selection=selection,
            adapter=adapter, notes=f"selected-year ledger {ledger_path.name} is absent",
            thresholds=config, manifest_sha=manifest_sha, ledger_sha=None,
            replay_kind=replay_kind,
        ))
    csv_text = ledger_path.read_text(encoding="utf-8")
    ledger_sha = hashlib.sha256(csv_text.encode("utf-8")).hexdigest()
    if ledger_sha != selection["aidy_expected_ledger_sha256"]:
        return _receipt(_base(
            status="INCONCLUSIVE", reasons=["LEDGER_HASH_MISMATCH"], selection=selection,
            adapter=adapter, notes="ledger bytes are not the selected year's expected ledger",
            thresholds=config, manifest_sha=manifest_sha, ledger_sha=ledger_sha,
            replay_kind=replay_kind,
        ))
    try:
        deals = parse_ledger_csv(csv_text)
        mt5_trades, residual = closed_trades_from_deals(deals)
    except (FactoryContractError, ValueError) as exc:
        return _receipt(_base(
            status="INCONCLUSIVE", reasons=["LEDGER_NOT_PAIRABLE"], selection=selection,
            adapter=adapter, notes=str(exc), thresholds=config, manifest_sha=manifest_sha,
            ledger_sha=ledger_sha, replay_kind=replay_kind,
        ))
    if residual != 0:
        return _receipt(_base(
            status="INCONCLUSIVE", reasons=["LEDGER_NOT_PAIRABLE"], selection=selection,
            adapter=adapter, notes="selected ledger is not flat", thresholds=config,
            manifest_sha=manifest_sha, ledger_sha=ledger_sha, replay_kind=replay_kind,
        ))
    mt5_net = sum((trade.net_pnl for trade in mt5_trades), Decimal(0))
    if Decimal(selection["aidy_expected_net_usd"]) != mt5_net:
        return _receipt(_base(
            status="INCONCLUSIVE", reasons=["LEDGER_NET_MISMATCH"], selection=selection,
            adapter=adapter, notes="selected net does not equal the ledger's closed-trade net",
            thresholds=config, manifest_sha=manifest_sha, ledger_sha=ledger_sha,
            replay_kind=replay_kind,
        ))
    try:
        produced = replay.replay(selection=selection, data_manifest=data_manifest)
    except AidyReplayUnavailable as exc:
        return _receipt(_base(
            status="INCONCLUSIVE", reasons=["AIDY_REPLAY_UNAVAILABLE"], selection=selection,
            adapter=adapter, notes=str(exc), thresholds=config, manifest_sha=manifest_sha,
            ledger_sha=ledger_sha, replay_kind=replay_kind,
        ))
    except FactoryContractError as exc:
        return _receipt(_base(
            status="INCONCLUSIVE", reasons=["MALFORMED_AIDY_TRADES"], selection=selection,
            adapter=adapter, notes=str(exc), thresholds=config, manifest_sha=manifest_sha,
            ledger_sha=ledger_sha, replay_kind=replay_kind,
        ))
    if produced.year != year:
        return _receipt(_base(
            status="INCONCLUSIVE", reasons=["AIDY_REPLAY_WRONG_YEAR"], selection=selection,
            adapter=produced.adapter, notes="adapter returned a year other than the selection",
            thresholds=config, manifest_sha=manifest_sha, ledger_sha=ledger_sha,
            replay_kind=replay_kind,
        ))
    return _compare(
        selection=selection, config=config, adapter=produced.adapter, notes=produced.notes,
        manifest_sha=manifest_sha, ledger_sha=ledger_sha, replay_kind=replay_kind,
        mt5_trades=mt5_trades, aidy_trades=list(produced.trades), mt5_net=mt5_net,
    )


def _limit(config: Mapping[str, Any], name: str) -> Decimal | None:
    if config["approval_status"] != "APPROVED":
        return None
    return Decimal(config["tolerances"][name])


def _compare(
    *,
    selection: Mapping[str, Any],
    config: Mapping[str, Any],
    adapter: str,
    notes: str,
    manifest_sha: str,
    ledger_sha: str,
    replay_kind: str,
    mt5_trades: list[Any],
    aidy_trades: list[AidyTrade],
    mt5_net: Decimal,
) -> dict[str, Any]:
    approved = config["approval_status"] == "APPROVED"
    entry_limit = _limit(config, "entry_time_seconds")
    unused = set(range(len(mt5_trades)))
    pairs: list[tuple[Any, AidyTrade]] = []
    unmatched_aidy: list[AidyTrade] = []
    ambiguous = False
    for aidy in sorted(aidy_trades, key=lambda trade: (trade.entry_time, trade.exit_time, trade.trade_id)):
        candidates: list[tuple[int, str, int]] = []
        for index in unused:
            mt5 = mt5_trades[index]
            if mt5.side != aidy.side or mt5.volume != aidy.volume:
                continue
            entry_delta = abs(int((aidy.entry_time - _stamp(mt5.entry_time, "mt5 entry")).total_seconds()))
            exit_delta = abs(int((aidy.exit_time - _stamp(mt5.exit_time, "mt5 exit")).total_seconds()))
            if approved:
                if entry_delta <= int(entry_limit or 0):
                    candidates.append((entry_delta, mt5.trade_id, index))
            elif entry_delta == 0 and exit_delta == 0:
                candidates.append((0, mt5.trade_id, index))
        if not candidates:
            unmatched_aidy.append(aidy)
            continue
        candidates.sort()
        if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
            ambiguous = True
            break
        chosen = candidates[0][2]
        unused.remove(chosen)
        pairs.append((mt5_trades[chosen], aidy))
    if ambiguous:
        return _receipt(_base(
            status="INCONCLUSIVE", reasons=["AMBIGUOUS_MATCH"], selection=selection,
            adapter=adapter, notes=notes, thresholds=config, manifest_sha=manifest_sha,
            ledger_sha=ledger_sha, replay_kind=replay_kind,
        ))
    differences = []
    explained = Decimal(0)
    field_difference = False
    for mt5, aidy in pairs:
        mt5_entry = _stamp(mt5.entry_time, "mt5 entry")
        mt5_exit = _stamp(mt5.exit_time, "mt5 exit")
        item = {
            "mt5_trade_id": mt5.trade_id,
            "aidy_trade_id": aidy.trade_id,
            "signal_time_seconds": _seconds(aidy.signal_time, mt5_entry),
            "entry_time_seconds": _seconds(aidy.entry_time, mt5_entry),
            "exit_time_seconds": _seconds(aidy.exit_time, mt5_exit),
            "entry_price": _text(aidy.entry_price - mt5.entry_price),
            "exit_price": _text(aidy.exit_price - mt5.exit_price),
            "cost_usd": _text((aidy.commission + aidy.swap) - (mt5.commission + mt5.swap)),
            "cash_pnl_usd": _text(aidy.net_pnl - mt5.net_pnl),
        }
        differences.append(item)
        explained += mt5.net_pnl - aidy.net_pnl
        checks = {
            "signal_time_seconds": ("signal_time_seconds", item["signal_time_seconds"]),
            "entry_time_seconds": ("entry_time_seconds", item["entry_time_seconds"]),
            "exit_time_seconds": ("exit_time_seconds", item["exit_time_seconds"]),
            "entry_price": ("price_abs", item["entry_price"]),
            "exit_price": ("price_abs", item["exit_price"]),
            "cost_usd": ("cost_usd", item["cost_usd"]),
            "cash_pnl_usd": ("cash_pnl_usd", item["cash_pnl_usd"]),
        }
        for _name, (gate, raw) in checks.items():
            delta = abs(Decimal(raw))
            if not approved:
                if delta != 0:
                    field_difference = True
            else:
                allowed = Decimal(config["tolerances"][gate])
                if delta > allowed:
                    field_difference = True
    unmatched_mt5 = [mt5_trades[index] for index in sorted(unused)]
    for trade in unmatched_mt5:
        explained += trade.net_pnl
    for trade in unmatched_aidy:
        explained -= trade.net_pnl
    aidy_net = sum((trade.net_pnl for trade in aidy_trades), Decimal(0))
    residual = (mt5_net - aidy_net) - explained
    reasons = []
    if residual != 0:
        status = "INCONCLUSIVE"
        reasons.append("UNEXPLAINED_RESIDUAL")
    elif unmatched_mt5 or unmatched_aidy or field_difference:
        status = "MISMATCH"
        if unmatched_mt5 or unmatched_aidy:
            reasons.append("UNMATCHED_TRADE")
        if field_difference:
            reasons.append("FIELD_DIFFERENCE")
    elif not approved:
        status = "INCONCLUSIVE"
        reasons.append("TOLERANCES_UNSET")
    else:
        status = "MATCH"
        reasons.append("WITHIN_APPROVED_TOLERANCES")
    body = _base(
        status=status, reasons=reasons, selection=selection, adapter=adapter, notes=notes,
        thresholds=config, manifest_sha=manifest_sha, ledger_sha=ledger_sha, replay_kind=replay_kind,
    )
    body.update({
        "mt5_trade_count": len(mt5_trades),
        "aidy_trade_count": len(aidy_trades),
        "matched_count": len(pairs),
        "unmatched_mt5": [trade.trade_id for trade in unmatched_mt5],
        "unmatched_aidy": [trade.trade_id for trade in unmatched_aidy],
        "differences": differences,
        "mt5_net_pnl_usd": _text(mt5_net),
        "aidy_net_pnl_usd": _text(aidy_net),
        "explained_pnl_gap_usd": _text(explained),
        "unexplained_residual_usd": _text(residual),
    })
    return _receipt(body)


def load_trade_document(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FactoryContractError("AIDY trade file is not JSON") from exc
    if not isinstance(payload, dict):
        raise FactoryContractError("AIDY trade file must be an object")
    return payload
