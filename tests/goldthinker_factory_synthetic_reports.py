"""Synthetic MT5 Strategy Tester fixtures. Not broker output.

The numbers are an authored two-trade book so the extractor has something
shaped like a real tester report. source_kind is SYNTHETIC_FIXTURE.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from xml.sax.saxutils import escape

from aidy.goldthinker_factory_mt5_extract import _drawdown, closed_trades_from_deals

DEPOSIT = Decimal("10000.00")


def _amount(value: Decimal, *, decimal_comma: bool, nbsp: bool) -> str:
    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if quantized < 0 else ""
    whole, frac = format(abs(quantized), "f").split(".")
    chunks: list[str] = []
    while whole:
        chunks.append(whole[-3:])
        whole = whole[:-3]
    body = " ".join(reversed(chunks))
    if nbsp:
        body = body.replace(" ", "\u00a0")
    text = f"{sign}{body}.{frac}"
    return text.replace(".", ",") if decimal_comma else text


def _percent(value: Decimal, *, decimal_comma: bool) -> str:
    text = format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")
    return text.replace(".", ",") if decimal_comma else text


def economics(year: int, extra_last_profit: Decimal = Decimal("0.00")) -> list[dict]:
    """Flat XAUUSD book. extra_last_profit changes only the last closing profit."""
    specs = [
        ("balance", "", None, None, None, Decimal("0.00"), Decimal("0.00"), DEPOSIT, f"{year}-01-02T00:00:00"),
        ("buy", "in", Decimal("0.10"), Decimal("1900.00"), 10, Decimal("-5.00"), Decimal("0.00"), Decimal("0.00"), f"{year}-02-01T10:00:00"),
        ("sell", "out", Decimal("0.10"), Decimal("1891.00"), 11, Decimal("-5.00"), Decimal("0.00"), Decimal("-90.00"), f"{year}-02-01T14:00:00"),
        ("buy", "in", Decimal("0.10"), Decimal("1900.00"), 12, Decimal("-5.00"), Decimal("0.00"), Decimal("0.00"), f"{year}-03-01T10:00:00"),
        ("sell", "out", Decimal("0.10"), Decimal("1926.00"), 13, Decimal("-5.00"), Decimal("0.00"), Decimal("260.00") + extra_last_profit, f"{year}-03-01T16:00:00"),
    ]
    running = Decimal("0.00")
    deals = []
    for index, spec in enumerate(specs, start=1):
        kind, direction, volume, price, order, commission, swap, profit, stamp = spec
        running += profit + commission + swap
        deals.append({
            "time": stamp,
            "deal": index,
            "order": order,
            "symbol": "" if kind == "balance" else "XAUUSD",
            "type": kind,
            "direction": direction,
            "volume": volume,
            "price": price,
            "commission": commission,
            "swap": swap,
            "profit": profit,
            "balance": running,
            "comment": "SYNTHETIC_FIXTURE",
        })
    return deals


def _broker(stamp: str) -> str:
    day, clock = stamp.split("T")
    return day.replace("-", ".") + " " + clock


def report_rows(
    year: int,
    *,
    end: str,
    extra_last_profit: Decimal = Decimal("0.00"),
    decimal_comma: bool = False,
    nbsp: bool = False,
    label_overrides: dict[str, str] | None = None,
    profit_override: str | None = None,
) -> list[list[str]]:
    deals = economics(year, extra_last_profit)
    trades, residual = closed_trades_from_deals(deals)
    if residual != 0:
        raise RuntimeError("synthetic book must be flat")
    net = sum((trade.net_pnl for trade in trades), Decimal(0))
    gross_profit = sum((trade.net_pnl for trade in trades if trade.net_pnl > 0), Decimal(0))
    gross_loss = sum((trade.net_pnl for trade in trades if trade.net_pnl < 0), Decimal(0))
    stats = _drawdown([deal["balance"] for deal in deals], DEPOSIT)
    flags = {"decimal_comma": decimal_comma, "nbsp": nbsp}

    def money(value: Decimal) -> str:
        return _amount(value, **flags)

    def pct(value: Decimal) -> str:
        return _percent(value, decimal_comma=decimal_comma)

    factor = gross_profit / abs(gross_loss)
    labels = {
        "Total Net Profit:": money(net),
        "Gross Profit:": money(gross_profit),
        "Gross Loss:": money(gross_loss),
        "Profit Factor:": _percent(factor, decimal_comma=decimal_comma),
        "Total Trades:": str(len(trades)),
        "Total Deals:": str(len(deals)),
        "Initial Deposit:": money(DEPOSIT),
        "Equity Drawdown Absolute:": money(stats["absolute"]),
        "Equity Drawdown Maximal:": f"{money(stats['maximal_money'])} ({pct(stats['maximal_pct'])}%)",
        "Equity Drawdown Relative:": f"{pct(stats['relative_pct'])}% ({money(stats['relative_money'])})",
        "Balance Drawdown Absolute:": money(stats["absolute"]),
        "Balance Drawdown Maximal:": f"{money(stats['maximal_money'])} ({pct(stats['maximal_pct'])}%)",
        "Balance Drawdown Relative:": f"{pct(stats['relative_pct'])}% ({money(stats['relative_money'])})",
    }
    if label_overrides:
        labels.update(label_overrides)
    rows: list[list[str]] = [
        ["Strategy Tester Report"],
        ["SYNTHETIC_FIXTURE SyntheticBroker-MT5 (Build 0000)"],
        ["Settings"],
        ["Expert:", r"Factory\SyntheticFixture"],
        ["Symbol:", "XAUUSD"],
        ["Period:", f"M15 ({year}.01.01 - {end})"],
        ["Company:", "SYNTHETIC_FIXTURE"],
        ["Currency:", "USD"],
        ["Initial Deposit:", labels["Initial Deposit:"]],
        ["Leverage:", "1:100"],
        ["Results"],
        ["Total Net Profit:", labels["Total Net Profit:"], "Balance Drawdown Absolute:", labels["Balance Drawdown Absolute:"], "Equity Drawdown Absolute:", labels["Equity Drawdown Absolute:"]],
        ["Gross Profit:", labels["Gross Profit:"], "Balance Drawdown Maximal:", labels["Balance Drawdown Maximal:"], "Equity Drawdown Maximal:", labels["Equity Drawdown Maximal:"]],
        ["Gross Loss:", labels["Gross Loss:"], "Balance Drawdown Relative:", labels["Balance Drawdown Relative:"], "Equity Drawdown Relative:", labels["Equity Drawdown Relative:"]],
        ["Profit Factor:", labels["Profit Factor:"], "Expected Payoff:", "0.00", "Margin Level:", "100.00%"],
        ["Total Trades:", labels["Total Trades:"], "Short Trades (won %):", "0 (0.00%)", "Long Trades (won %):", "2 (50.00%)"],
        ["Total Deals:", labels["Total Deals:"]],
        ["Orders"],
        ["Open Time", "Order", "Symbol", "Type", "Volume", "Price", "S / L", "T / P", "Time", "State", "Comment"],
        [_broker(deals[1]["time"]), "10", "XAUUSD", "buy", "0.10", "1900.00", "", "", _broker(deals[1]["time"]), "filled", "SYNTHETIC_FIXTURE"],
        ["Deals"],
        ["Time", "Deal", "Symbol", "Type", "Direction", "Volume", "Price", "Order", "Commission", "Swap", "Profit", "Balance", "Comment"],
    ]
    for deal in deals:
        profit = money(deal["profit"])
        if profit_override is not None and deal["deal"] == 5:
            profit = profit_override
        volume = "" if deal["volume"] is None else _amount(deal["volume"], **flags)
        price = "" if deal["price"] is None else _amount(deal["price"], **flags)
        order = "" if deal["order"] is None else str(deal["order"])
        rows.append([
            _broker(deal["time"]), str(deal["deal"]), deal["symbol"], deal["type"],
            deal["direction"], volume, price, order,
            money(deal["commission"]), money(deal["swap"]), profit, money(deal["balance"]),
            deal["comment"],
        ])
    rows.append([
        "",
        money(sum((deal["commission"] for deal in deals), Decimal(0))),
        money(sum((deal["swap"] for deal in deals), Decimal(0))),
        money(sum((deal["profit"] for deal in deals), Decimal(0)) + (Decimal(0) if profit_override is None else Decimal(0))),
        money(deals[-1]["balance"]),
        "",
    ])
    if profit_override is not None:
        # Keep the authored footer profit in sync with the overridden cell only
        # when the override is a real decimal; ambiguous text is left for the parser to refuse.
        try:
            overridden = Decimal(profit_override)
        except Exception:
            pass
        else:
            base = sum((deal["profit"] for deal in deals if deal["deal"] != 5), Decimal(0))
            rows[-1][3] = money(base + overridden)
    return rows


def rows_to_html(rows: list[list[str]]) -> str:
    body = ["<!DOCTYPE html>", "<html>", "<head>", "<title>Strategy Tester Report</title>",
            "<meta name=\"generator\" content=\"SYNTHETIC_FIXTURE\">", "</head>", "<body>",
            "<div align=\"center\">", "<table cellspacing=\"1\" cellpadding=\"3\" border=\"0\">"]
    for row in rows:
        body.append("<tr>")
        for cell in row:
            body.append(f"<td>{escape(cell)}</td>")
        body.append("</tr>")
    body.extend(["</table>", "</div>", "</body>", "</html>", ""])
    return "\n".join(body)


def rows_to_spreadsheetml(rows: list[list[str]]) -> str:
    lines = [
        '<?xml version="1.0"?>',
        '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">',
        '<Worksheet ss:Name="Strategy Tester Report">',
        "<Table>",
    ]
    for row in rows:
        lines.append("<Row>")
        for cell in row:
            lines.append(f'<Cell><Data ss:Type="String">{escape(cell)}</Data></Cell>')
        lines.append("</Row>")
    lines.extend(["</Table>", "</Worksheet>", "</Workbook>", ""])
    return "\n".join(lines)


def synthetic_report_html(year: int, *, end: str, **kwargs) -> str:
    return rows_to_html(report_rows(year, end=end, **kwargs))


def synthetic_report_xml(year: int, *, end: str, **kwargs) -> str:
    return rows_to_spreadsheetml(report_rows(year, end=end, **kwargs))
