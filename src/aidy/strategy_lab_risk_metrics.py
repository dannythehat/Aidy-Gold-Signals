"""Day24: measured trade and risk statistics from Day17's verified SQLite journal.

Only one sequential flat-to-flat instrument position at a time is admitted for
per-trade cost attribution. All events are SHA-chain verified by the EXISTING
ledger before independent metric calculations. Observed-event equity drawdown
is not an intrabar maximum; no native-broker or profitable-edge claims.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from urllib.parse import quote

from aidy.strategy_lab_cash_ledger import CashJournal, _money, _stamp

MAX_EVENTS = 1500
COST_KINDS = frozenset({"commission", "slippage", "swap"})


@dataclass(frozen=True)
class CompletedTrade:
    position_id: str
    opened_at_utc: str
    closed_at_utc: str
    direction: str
    gross_usd: Decimal
    costs_usd: Decimal
    net_usd: Decimal


@dataclass(frozen=True)
class MonthlyMetrics:
    month_utc: str
    closed_trades: int
    net_usd: Decimal


@dataclass(frozen=True)
class RiskMetrics:
    schema: str
    broker_source_sha256: str
    verified_journal_tip_sha256: str
    journal_event_count: int
    initial_capital_usd: Decimal
    final_cash_usd: Decimal
    final_equity_usd: Decimal
    realized_gross_usd: Decimal
    transaction_costs_usd: Decimal
    net_profit_usd: Decimal
    closed_trades: int
    wins: int
    losses: int
    breakeven: int
    win_rate_percent: Decimal | None
    expectancy_net_usd_per_trade: Decimal | None
    profit_factor: Decimal | None
    profit_factor_status: str
    max_observed_drawdown_usd: Decimal
    max_observed_drawdown_percent: Decimal
    max_drawdown_type: str
    sharpe_annualized: Decimal | None
    sharpe_status: str
    monthly: tuple[MonthlyMetrics, ...]
    trades: tuple[CompletedTrade, ...]
    input_type: str = "verified_sqlite_research_journal"
    original_broker_trades_verified: bool = False
    historical_strategy_profitability_qualified: bool = False

    def to_wire(self) -> dict:
        def decimal(value: Decimal | None) -> str | None:
            return None if value is None else format(value, "f")

        return {
            "schema": self.schema, "broker_source_sha256": self.broker_source_sha256,
            "verified_journal_tip_sha256": self.verified_journal_tip_sha256,
            "journal_event_count": self.journal_event_count,
            "initial_capital_usd": decimal(self.initial_capital_usd),
            "final_cash_usd": decimal(self.final_cash_usd),
            "final_equity_usd": decimal(self.final_equity_usd),
            "realized_gross_usd": decimal(self.realized_gross_usd),
            "transaction_costs_usd": decimal(self.transaction_costs_usd),
            "net_profit_usd": decimal(self.net_profit_usd),
            "closed_trades": self.closed_trades,
            "wins": self.wins, "losses": self.losses, "breakeven": self.breakeven,
            "win_rate_percent": decimal(self.win_rate_percent),
            "expectancy_net_usd_per_trade": decimal(self.expectancy_net_usd_per_trade),
            "profit_factor": decimal(self.profit_factor),
            "profit_factor_status": self.profit_factor_status,
            "max_observed_drawdown_usd": decimal(self.max_observed_drawdown_usd),
            "max_observed_drawdown_percent": decimal(self.max_observed_drawdown_percent),
            "max_drawdown_type": self.max_drawdown_type,
            "sharpe_annualized": decimal(self.sharpe_annualized),
            "sharpe_status": self.sharpe_status,
            "monthly": [
                {"month_utc": x.month_utc, "closed_trades": x.closed_trades,
                 "net_usd": decimal(x.net_usd)} for x in self.monthly
            ],
            "trades": [
                {"position_id": t.position_id, "opened_at_utc": t.opened_at_utc,
                 "closed_at_utc": t.closed_at_utc, "direction": t.direction,
                 "gross_usd": decimal(t.gross_usd), "costs_usd": decimal(t.costs_usd),
                 "net_usd": decimal(t.net_usd)} for t in self.trades
            ],
            "input_type": self.input_type,
            "original_broker_trades_verified": False,
            "historical_strategy_profitability_qualified": False,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_wire(), sort_keys=True, separators=(",", ":"))


def qualified_daily_sharpe(
    daily_excess_returns: tuple[Decimal, ...], *,
    session_calendar_independently_verified: bool,
    periods_per_year: int = 252,
) -> Decimal | None:
    """Optional diagnostic only for independently qualified complete daily marks.

    Values must ALREADY be daily risk-free-adjusted account returns. Their
    provenance/calendar is an external precondition. No backfilling weekends,
    interpolating missing marks or annualising individual trade returns.
    """
    if not session_calendar_independently_verified or len(daily_excess_returns) < 30:
        return None
    if (periods_per_year != 252
            or any(not isinstance(x, Decimal) or not x.is_finite()
                   for x in daily_excess_returns)):
        raise ValueError("Sharpe requires finite daily excess returns and frozen 252-day basis")
    n = Decimal(len(daily_excess_returns))
    mean = sum(daily_excess_returns, Decimal(0)) / n
    variance = sum(((x - mean) ** 2 for x in daily_excess_returns), Decimal(0)) / (n - 1)
    if variance == 0:
        return None
    return mean / variance.sqrt() * Decimal(periods_per_year).sqrt()


def _replay_verified_rows(
    journal_path: Path, *, source_sha256: str, ounces_per_lot: Decimal,
    expected_tip_sha256: str,
) -> tuple[CashJournal, list[sqlite3.Row]]:
    if not isinstance(journal_path, Path) or not journal_path.is_file():
        raise ValueError("existing on-disk verified SQLite journal required")
    if (not isinstance(expected_tip_sha256, str) or len(expected_tip_sha256) != 64
            or any(x not in "0123456789abcdef" for x in expected_tip_sha256)):
        raise ValueError("frozen exact journal tip SHA256 required")
    journal = CashJournal(journal_path, source_sha256=source_sha256,
                          ounces_per_lot=ounces_per_lot)
    uri = "file:" + quote(str(journal_path.resolve()), safe="/") + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")  # keep the verified and measured rows in ONE snapshot
        records = journal._events(db)
        if not 0 < len(records) <= MAX_EVENTS:
            raise ValueError("journal outside Day24 bounded measurement size")
        verified = journal._rebuild(records)
        if verified.tip_sha256 != expected_tip_sha256:
            raise ValueError("frozen SQLite journal tip mismatch")
        db.commit()
    return journal, records


def compute_ledger_metrics(
    journal_path: Path, *, source_sha256: str, ounces_per_lot: Decimal,
    expected_tip_sha256: str,
) -> RiskMetrics:
    """Compute net expectancy, PF, observed equity MDD and monthly realised P&L.

    Fail closed when fee ownership is ambiguous, capital flows repeat,
    simultaneous trades overlap, or the journal ends with an open position.
    These limitations are deliberate rather than manufacturing trade P&L.
    """
    journal, records = _replay_verified_rows(
        journal_path, source_sha256=source_sha256,
        ounces_per_lot=ounces_per_lot, expected_tip_sha256=expected_tip_sha256,
    )
    first = records[0]
    if first["kind"] != "deposit":
        raise ValueError("first journal event must be initial capital deposit")
    starting = Decimal(json.loads(first["payload_json"])["usd"])
    if starting <= 0:
        raise ValueError("invalid research starting capital")

    trade: dict | None = None
    pending: dict | None = None
    closed: list[CompletedTrade] = []
    equity_peak = starting
    max_dd_usd = Decimal("0.00")
    max_dd_pct = Decimal(0)
    last_view = None

    def finalize_pending() -> None:
        nonlocal pending
        if pending is not None:
            gross = pending["gross"]
            cost = pending["costs"]
            closed.append(CompletedTrade(
                pending["id"], pending["open_at"], pending["close_at"],
                pending["direction"], gross, cost, gross + cost,
            ))
            pending = None

    for i, record in enumerate(records):
        kind = record["kind"]
        when = record["at_utc"]
        data = json.loads(record["payload_json"])
        if pending is not None and when != pending["close_at"]:
            finalize_pending()
        if i != 0 and kind in ("deposit", "withdrawal"):
            raise ValueError("external funding after initial deposit makes raw returns ambiguous")
        if kind == "open":
            if trade is not None:
                raise ValueError("overlapping positions cannot safely allocate costs")
            finalize_pending()
            trade = {
                "id": data["id"], "open_at": when, "direction": data["direction"],
                "entry": Decimal(data["price"]), "remaining": Decimal(data["lots"]),
                "gross": Decimal("0.00"), "costs": Decimal("0.00"),
            }
        elif kind in COST_KINDS:
            if trade is not None:
                trade["costs"] += Decimal(data["usd"])
            elif pending is not None and pending["close_at"] == when:
                pending["costs"] += Decimal(data["usd"])
            else:
                raise ValueError("unattributed commission/slippage/swap event")
        elif kind == "close":
            if trade is None or data["id"] != trade["id"]:
                raise ValueError("close event has no unique active position")
            lots = Decimal(data["lots"])
            exit_price = Decimal(data["price"])
            sign = Decimal(1) if trade["direction"] == "long" else Decimal(-1)
            trade["gross"] += _money(
                (exit_price - trade["entry"]) * sign * lots * ounces_per_lot
            )
            trade["remaining"] -= lots
            if trade["remaining"] == 0:
                trade["close_at"] = when
                pending = trade
                trade = None

        # Every account equity observation is independently rebuilt from the
        # pre-existing verified Day17 chain. This includes unrealised marks,
        # transaction costs, and partial close cash effects.
        v = journal._rebuild(records[:i+1])
        last_view = v
        if i > 0:
            if v.equity_usd > equity_peak:
                equity_peak = v.equity_usd
            dd = equity_peak - v.equity_usd
            pct = dd / equity_peak * Decimal(100)
            if dd > max_dd_usd:
                max_dd_usd = dd
            if pct > max_dd_pct:
                max_dd_pct = pct

    finalize_pending()
    if last_view is None or trade is not None or last_view.open_positions:
        raise ValueError("end-of-period open positions require marked open-risk report")
    gross = sum((x.gross_usd for x in closed), Decimal("0.00"))
    costs = sum((x.costs_usd for x in closed), Decimal("0.00"))
    net = sum((x.net_usd for x in closed), Decimal("0.00"))
    if (last_view.cash_usd != starting + net
            or last_view.realized_usd != gross
            or last_view.equity_usd != last_view.cash_usd):
        raise ValueError("independent trade aggregation differs from verified cash journal")

    winners = [x.net_usd for x in closed if x.net_usd > 0]
    losers = [x.net_usd for x in closed if x.net_usd < 0]
    win_sum = sum(winners, Decimal(0))
    loss_abs = -sum(losers, Decimal(0))
    pf = win_sum / loss_abs if loss_abs else None
    status = ("NO_TRADES" if not closed else
              "UNDEFINED_NO_LOSSES" if not loss_abs else "DEFINED")
    months: dict[str, list[Decimal]] = {}
    for t in closed:
        month = _stamp(t.closed_at_utc).strftime("%Y-%m")
        months.setdefault(month, []).append(t.net_usd)
    monthly = tuple(MonthlyMetrics(k, len(months[k]), sum(months[k], Decimal(0)))
                    for k in sorted(months))
    return RiskMetrics(
        "aidy.strategy_lab.risk_metrics.v1",
        source_sha256, expected_tip_sha256, len(records), starting,
        last_view.cash_usd, last_view.equity_usd, gross, costs, net,
        len(closed), len(winners), len(losers),
        len(closed) - len(winners) - len(losers),
        Decimal(len(winners)) / Decimal(len(closed)) * 100 if closed else None,
        net / Decimal(len(closed)) if closed else None,
        pf, status, max_dd_usd, max_dd_pct,
        "EVENT_SAMPLED_MARK_TO_MARKET_NOT_INTRABAR",
        None,
        "UNAVAILABLE_NO_QUALIFIED_COMPLETE_DAILY_RETURNS_AND_SESSION_CALENDAR",
        monthly, tuple(closed),
    )
