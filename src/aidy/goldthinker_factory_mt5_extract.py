"""Extract a strict annual bundle from MT5 Strategy Tester reports.

Offline and fail-closed. Reads report bytes only. Does not launch MT5, open a
socket, or read broker credentials. A year whose ledger disagrees with the
report summary is FAILED and its bundle result fields stay null.

report_sha256 is the SHA-256 of the raw file bytes.
ledger_sha256 is the SHA-256 of the canonical ledger CSV (also written for
archive). Those archive hashes are recorded on the extraction receipt even
when the year is not admissible. The bundle carries them only for an admitted
year.

Times in the ledger are the broker-server clock printed by MT5. Reconciliation
converts them to UTC only when an explicit server clock is supplied.
2026 is always PARTIAL. Equity drawdown is taken from the report's equity
figures. It is not required to be at least the balance-path drawdown,
because MT5 computes the two curves separately. Balance drawdown is
recomputed from the ledger and cross-checked against the report's
balance-drawdown lines. Advancement stays blocked while equity drawdown
is EQUITY_DD_UNVERIFIED.
A REAL_MT5_TESTER label is not self-authenticating. Selection accepts it
only when the extractor receipt binds the bundle digest, source_kind and
the archived report and ledger hashes, and those files contain no
SYNTHETIC_FIXTURE marker. That binding is still not proof a terminal wrote
the file.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping
from xml.etree import ElementTree

from aidy.goldthinker_factory_contract import (
    ALL_YEARS,
    IDENTIFIER,
    FactoryContractError,
    canonical_json,
    digest,
    validate_mt5_bundle,
)

DEAL_HEADER_NO_FEE = (
    "time", "deal", "symbol", "type", "direction", "volume", "price",
    "order", "commission", "swap", "profit", "balance", "comment",
)
DEAL_HEADER_WITH_FEE = (
    "time", "deal", "symbol", "type", "direction", "volume", "price",
    "order", "commission", "fee", "swap", "profit", "balance", "comment",
)
LEDGER_COLUMNS = (
    "time", "deal", "order", "symbol", "type", "direction", "volume",
    "price", "commission", "fee", "swap", "profit", "balance", "comment",
)
CASHFLOW_TYPES = frozenset({"balance", "credit", "charge", "correction", "bonus"})
TRADE_TYPES = frozenset({"buy", "sell"})
CLOSE_DIRECTIONS = frozenset({"out"})
OPEN_DIRECTIONS = frozenset({"in"})
SYNTHETIC_MARKER = "SYNTHETIC_FIXTURE"
_SPACE = re.compile(r"[\u00a0\u202f\u2009 ]+")
_TIME = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2}) (\d{2}):(\d{2}):(\d{2})$")
_PERIOD = re.compile(
    r"(\d{4})\.(\d{2})\.(\d{2})\s*-\s*(\d{4})\.(\d{2})\.(\d{2})"
)
_LABELS = (
    "Total Net Profit:",
    "Total Trades:",
    "Equity Drawdown Absolute:",
    "Equity Drawdown Maximal:",
    "Equity Drawdown Relative:",
    "Balance Drawdown Absolute:",
    "Balance Drawdown Maximal:",
    "Balance Drawdown Relative:",
    "Period:",
    "Symbol:",
    "Currency:",
    "Initial Deposit:",
)


def _sha(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def decode_mt5_report_text(raw: bytes) -> str:
    """Decode MT5 report bytes. UTF-16 with BOM is the common tester encoding."""
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        raise FactoryContractError("empty report")
    blob = bytes(raw)
    if blob.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return blob.decode("utf-16")
        except UnicodeError as exc:
            raise FactoryContractError("undecodable UTF-16 report") from exc
    if blob.startswith(b"\xef\xbb\xbf"):
        try:
            return blob.decode("utf-8-sig")
        except UnicodeError as exc:
            raise FactoryContractError("undecodable UTF-8 report") from exc
    sample = blob[:256]
    if b"\x00" in sample:
        odd_nul = all(sample[i] == 0 for i in range(1, len(sample), 2))
        even_nul = all(sample[i] == 0 for i in range(0, len(sample), 2))
        if odd_nul and not even_nul:
            encoding = "utf-16-le"
        elif even_nul and not odd_nul:
            encoding = "utf-16-be"
        else:
            raise FactoryContractError("ambiguous report encoding")
        try:
            return blob.decode(encoding)
        except UnicodeError as exc:
            raise FactoryContractError("undecodable UTF-16 report") from exc
    try:
        return blob.decode("utf-8")
    except UnicodeError as exc:
        raise FactoryContractError("undecodable report bytes") from exc


def parse_decimal(raw: str, label: str) -> Decimal:
    """Parse an MT5 number. Fail closed when thousands and decimals are ambiguous."""
    if not isinstance(raw, str):
        raise FactoryContractError(f"{label}: number required")
    text = raw.strip().replace("\u00a0", " ").replace("\u202f", " ").replace("\u2009", " ")
    if not text or any(ch.isalpha() or ch in "$€£¥%" for ch in text):
        raise FactoryContractError(f"{label}: not a plain decimal")
    negative = False
    if text[0] == "-":
        negative = True
        text = text[1:].strip()
    if not text or text[0] == "-" or " " in text.strip() and text.strip() != text:
        raise FactoryContractError(f"{label}: malformed sign")
    if any(ch not in "0123456789., " for ch in text):
        raise FactoryContractError(f"{label}: unsupported numeric glyph")
    dot, comma, space = "." in text, "," in text, " " in text

    def grouped(body: str, sep: str) -> bool:
        parts = body.split(sep) if sep else [body]
        if any(not part.isdigit() for part in parts):
            return False
        if len(parts) == 1:
            return True
        return 1 <= len(parts[0]) <= 3 and all(len(part) == 3 for part in parts[1:])

    if dot and comma:
        decimal_sep = "." if text.rfind(".") > text.rfind(",") else ","
        thousands = "," if decimal_sep == "." else "."
        if space:
            raise FactoryContractError(f"{label}: mixed separators")
        body, frac = text.rsplit(decimal_sep, 1)
        if not frac.isdigit() or not grouped(body, thousands):
            raise FactoryContractError(f"{label}: malformed grouped decimal")
        digits = body.replace(thousands, "") + "." + frac
    elif space and (dot or comma):
        decimal_sep = "." if dot else ","
        if text.count(decimal_sep) != 1:
            raise FactoryContractError(f"{label}: malformed grouped decimal")
        body, frac = text.split(decimal_sep)
        if not frac.isdigit() or not grouped(body, " "):
            raise FactoryContractError(f"{label}: malformed spaced decimal")
        digits = body.replace(" ", "") + "." + frac
    elif space:
        if not grouped(text, " "):
            raise FactoryContractError(f"{label}: malformed thousands")
        digits = text.replace(" ", "")
    elif dot or comma:
        sep = "." if dot else ","
        parts = text.split(sep)
        if len(parts) > 2:
            if not grouped(text, sep):
                raise FactoryContractError(f"{label}: malformed thousands")
            digits = text.replace(sep, "")
        else:
            body, frac = parts
            if not body.isdigit() or not frac.isdigit():
                raise FactoryContractError(f"{label}: malformed decimal")
            # A single group of exactly three digits is both a thousands
            # separator and a decimal ("1.234"). Do not guess.
            if len(frac) == 3:
                raise FactoryContractError(f"{label}: ambiguous thousands or decimal separator")
            digits = body + "." + frac
    else:
        if not text.isdigit():
            raise FactoryContractError(f"{label}: malformed integer")
        digits = text
    try:
        value = Decimal(digits)
    except InvalidOperation as exc:
        raise FactoryContractError(f"{label}: invalid decimal") from exc
    if not value.is_finite():
        raise FactoryContractError(f"{label}: non-finite decimal")
    return -value if negative else value


def _cell(text: str) -> str:
    return " ".join(text.replace("\u00a0", " ").split())


class _HTMLRows(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._skip = 0
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        if name in ("script", "style"):
            self._skip += 1
            return
        if self._skip:
            return
        if name == "tr":
            self._row = []
        elif name in ("td", "th") and self._row is not None:
            self._cell = []
        elif name == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name in ("script", "style") and self._skip:
            self._skip -= 1
            return
        if self._skip:
            return
        if name in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(_cell("".join(self._cell)))
            self._cell = None
        elif name == "tr" and self._row is not None:
            if any(self._row):
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._skip == 0 and self._cell is not None:
            self._cell.append(data)


def _html_rows(text: str) -> list[list[str]]:
    parser = _HTMLRows()
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:
        raise FactoryContractError("HTML report could not be read") from exc
    return parser.rows


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _spreadsheet_rows(text: str) -> list[list[str]]:
    if "<!ENTITY" in text or "<!DOCTYPE" in text.upper() and "SYSTEM" in text.upper():
        raise FactoryContractError("SpreadsheetML with external entities is refused")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise FactoryContractError("SpreadsheetML report could not be read") from exc
    rows: list[list[str]] = []
    for worksheet in root.iter():
        if _local(worksheet.tag) != "Worksheet":
            continue
        for table in worksheet:
            if _local(table.tag) != "Table":
                continue
            for row in table:
                if _local(row.tag) != "Row":
                    continue
                cells: list[str] = []
                column = 1
                for cell in row:
                    if _local(cell.tag) != "Cell":
                        continue
                    index = None
                    for key, value in cell.attrib.items():
                        if _local(key) == "Index":
                            index = value
                    if index is not None:
                        try:
                            target = int(index)
                        except ValueError as exc:
                            raise FactoryContractError("SpreadsheetML cell index is not an integer") from exc
                        if target < column:
                            raise FactoryContractError("SpreadsheetML cell index moved backwards")
                        while column < target:
                            cells.append("")
                            column += 1
                    parts: list[str] = []
                    for node in cell.iter():
                        if _local(node.tag) == "Data" and node.text:
                            parts.append(node.text)
                    cells.append(_cell(" ".join(parts)))
                    column += 1
                if any(cells):
                    rows.append(cells)
    if not rows:
        raise FactoryContractError("SpreadsheetML report has no rows")
    return rows


def _rows_from_text(text: str) -> list[list[str]]:
    if "Strategy Tester Report" not in text:
        raise FactoryContractError("document is not an MT5 Strategy Tester report")
    head = text.lstrip("\ufeff \t\r\n")[:300].lower()
    if head.startswith("<?xml") or head.startswith("<workbook"):
        return _spreadsheet_rows(text)
    if "<html" in head or head.startswith("<!doctype") or "<table" in text[:4000].lower():
        return _html_rows(text)
    raise FactoryContractError("report is neither HTML nor SpreadsheetML")


def _label_map(rows: list[list[str]], stop: int) -> dict[str, str]:
    found: dict[str, str] = {}
    wanted = set(_LABELS) | {
        "Gross Profit:", "Gross Loss:", "Total Deals:", "Profit Factor:",
        "Balance Drawdown Absolute:", "Balance Drawdown Maximal:",
        "Balance Drawdown Relative:",
    }
    for row in rows[:stop]:
        for index, cell in enumerate(row):
            if cell not in wanted:
                continue
            if cell in found:
                raise FactoryContractError(f"duplicate report label {cell}")
            if index + 1 >= len(row) or not row[index + 1]:
                raise FactoryContractError(f"missing value for {cell}")
            found[cell] = row[index + 1]
    return found


def _canonical_time(raw: str) -> str:
    match = _TIME.fullmatch(raw.strip())
    if match is None:
        raise FactoryContractError("deal time is not broker-server YYYY.MM.DD HH:MM:SS")
    year, month, day, hour, minute, second = (int(part) for part in match.groups())
    try:
        stamped = datetime(year, month, day, hour, minute, second)
    except ValueError as exc:
        raise FactoryContractError("deal time is not a real calendar timestamp") from exc
    return stamped.strftime("%Y-%m-%dT%H:%M:%S")


def _optional_decimal(raw: str, label: str) -> Decimal | None:
    if raw == "":
        return None
    return parse_decimal(raw, label)


def _header_for_width(width: int) -> tuple[str, ...] | None:
    if width == len(DEAL_HEADER_WITH_FEE):
        return DEAL_HEADER_WITH_FEE
    if width == len(DEAL_HEADER_NO_FEE):
        return DEAL_HEADER_NO_FEE
    return None


def _fee_of(deal: dict[str, Any]) -> Decimal:
    return deal.get("fee", Decimal(0))


def _deal_from_cells(cells: list[str]) -> dict[str, Any]:
    header = _header_for_width(len(cells))
    if header is None:
        raise FactoryContractError("deal row does not have the 13 or 14 MT5 columns")
    mapped = dict(zip(header, cells, strict=True))
    if "fee" not in mapped:
        mapped["fee"] = "0.00"
    kind = mapped["type"].strip().lower()
    direction = mapped["direction"].strip().lower()
    if kind not in CASHFLOW_TYPES | TRADE_TYPES:
        raise FactoryContractError(f"unsupported deal type {mapped['type']!r}")
    if direction not in ("", "in", "out", "in/out", "out/in", "out by"):
        raise FactoryContractError(f"unsupported deal direction {mapped['direction']!r}")
    try:
        deal_id = int(mapped["deal"])
    except ValueError as exc:
        raise FactoryContractError("deal id is not an integer") from exc
    if deal_id <= 0:
        raise FactoryContractError("deal id must be positive")
    order_raw = mapped["order"].strip()
    if order_raw == "":
        order_id = None
    else:
        try:
            order_id = int(order_raw)
        except ValueError as exc:
            raise FactoryContractError("order id is not an integer") from exc
        if order_id <= 0:
            raise FactoryContractError("order id must be positive")
    comment = mapped["comment"].strip()
    if len(comment) > 200 or any(ch in comment for ch in "\r\n\""):
        raise FactoryContractError("deal comment is empty-of-quotes and single-line only")
    return {
        "time": _canonical_time(mapped["time"]),
        "deal": deal_id,
        "order": order_id,
        "symbol": mapped["symbol"].strip(),
        "type": kind,
        "direction": direction,
        "volume": _optional_decimal(mapped["volume"], "volume"),
        "price": _optional_decimal(mapped["price"], "price"),
        "commission": parse_decimal(mapped["commission"], "commission"),
        "fee": parse_decimal(mapped["fee"], "fee"),
        "swap": parse_decimal(mapped["swap"], "swap"),
        "profit": parse_decimal(mapped["profit"], "profit"),
        "balance": parse_decimal(mapped["balance"], "balance"),
        "comment": comment,
    }


def _decimal_text(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value, "f")


def canonical_ledger_csv(deals: list[dict[str, Any]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(LEDGER_COLUMNS)
    for deal in deals:
        writer.writerow([
            deal["time"],
            str(deal["deal"]),
            "" if deal["order"] is None else str(deal["order"]),
            deal["symbol"],
            deal["type"],
            deal["direction"],
            _decimal_text(deal["volume"]),
            _decimal_text(deal["price"]),
            _decimal_text(deal["commission"]),
            _decimal_text(deal["fee"]),
            _decimal_text(deal["swap"]),
            _decimal_text(deal["profit"]),
            _decimal_text(deal["balance"]),
            deal["comment"],
        ])
    return buffer.getvalue()


def parse_ledger_csv(text: str) -> list[dict[str, Any]]:
    if not text.endswith("\n"):
        raise FactoryContractError("ledger CSV must end with a newline")
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise FactoryContractError("empty ledger") from exc
    if tuple(header) != LEDGER_COLUMNS:
        raise FactoryContractError("ledger CSV header is not the canonical column set")
    deals = []
    for cells in reader:
        if len(cells) != len(LEDGER_COLUMNS):
            raise FactoryContractError("ledger CSV row width mismatch")
        raw = dict(zip(LEDGER_COLUMNS, cells, strict=True))
        deals.append({
            "time": raw["time"],
            "deal": int(raw["deal"]),
            "order": None if raw["order"] == "" else int(raw["order"]),
            "symbol": raw["symbol"],
            "type": raw["type"],
            "direction": raw["direction"],
            "volume": None if raw["volume"] == "" else Decimal(raw["volume"]),
            "price": None if raw["price"] == "" else Decimal(raw["price"]),
            "commission": Decimal(raw["commission"]),
            "fee": Decimal(raw["fee"]),
            "swap": Decimal(raw["swap"]),
            "profit": Decimal(raw["profit"]),
            "balance": Decimal(raw["balance"]),
            "comment": raw["comment"],
        })
    rendered = canonical_ledger_csv(deals)
    if rendered != text:
        raise FactoryContractError("ledger CSV is not in canonical form")
    return deals


@dataclass(frozen=True)
class ClosedTrade:
    trade_id: str
    side: str
    signal_time: str
    entry_time: str
    exit_time: str
    entry_price: Decimal
    exit_price: Decimal
    volume: Decimal
    commission: Decimal
    fee: Decimal
    swap: Decimal
    profit: Decimal
    net_pnl: Decimal
    entry_deal: int
    exit_deal: int


@dataclass
class _Lot:
    time: str
    deal: int
    side: str
    price: Decimal
    volume: Decimal
    commission_left: Decimal
    fee_left: Decimal
    swap_left: Decimal


def closed_trades_from_deals(deals: list[dict[str, Any]]) -> tuple[list[ClosedTrade], Decimal]:
    """FIFO netting. Returns closed trades and residual open volume.

    `in/out`, `out by`, and a close that spans two different entry prices are
    refused. Those reports do not identify which position was closed.
    """
    open_lots: list[_Lot] = []
    trades: list[ClosedTrade] = []
    for deal in deals:
        if deal["type"] in CASHFLOW_TYPES:
            if deal["direction"] or deal["symbol"] or deal["volume"] is not None or deal["price"] is not None or deal["order"] is not None:
                raise FactoryContractError("cashflow deal carries trade fields")
            if deal["commission"] != 0 or deal["swap"] != 0 or _fee_of(deal) != 0:
                raise FactoryContractError("cashflow deal has commission, fee or swap")
            continue
        if deal["direction"] not in ("in", "out"):
            raise FactoryContractError(
                "in/out and out-by deals are ambiguous without a position id"
            )
        if deal["volume"] is None or deal["price"] is None or deal["order"] is None or not deal["symbol"]:
            raise FactoryContractError("trade deal is missing symbol, volume, price or order")
        if deal["volume"] <= 0 or deal["price"] <= 0:
            raise FactoryContractError("trade volume and price must be positive")
        if deal["direction"] == "in":
            open_lots.append(_Lot(
                deal["time"], deal["deal"], deal["type"], deal["price"], deal["volume"],
                deal["commission"], _fee_of(deal), deal["swap"],
            ))
            continue
        remaining = deal["volume"]
        if not open_lots:
            raise FactoryContractError("close without an open position")
        if any(lot.side == deal["type"] for lot in open_lots):
            raise FactoryContractError("close side does not reduce the open net position")
        if len({lot.side for lot in open_lots}) != 1:
            raise FactoryContractError("mixed open sides are ambiguous")
        pieces: list[tuple[_Lot, Decimal, Decimal, Decimal, Decimal]] = []
        while remaining > 0:
            if not open_lots:
                raise FactoryContractError("close volume exceeds the open position")
            lot = open_lots[0]
            take = lot.volume if lot.volume <= remaining else remaining
            if take == lot.volume:
                commission = lot.commission_left
                fee = lot.fee_left
                swap = lot.swap_left
            else:
                commission = (lot.commission_left * take) / lot.volume
                fee = (lot.fee_left * take) / lot.volume
                swap = (lot.swap_left * take) / lot.volume
            lot.commission_left -= commission
            lot.fee_left -= fee
            lot.swap_left -= swap
            lot.volume -= take
            remaining -= take
            pieces.append((lot, take, commission, fee, swap))
            if lot.volume == 0:
                open_lots.pop(0)
        if len({piece[0].price for piece in pieces}) != 1 or len({piece[0].time for piece in pieces}) != 1:
            raise FactoryContractError("one close spans different entry prices; refusing to invent an entry")
        entry = pieces[0][0]
        volume = sum((piece[1] for piece in pieces), Decimal(0))
        entry_commission = sum((piece[2] for piece in pieces), Decimal(0))
        entry_fee = sum((piece[3] for piece in pieces), Decimal(0))
        entry_swap = sum((piece[4] for piece in pieces), Decimal(0))
        close_fraction = volume / deal["volume"]
        profit = deal["profit"] * close_fraction
        commission = entry_commission + deal["commission"] * close_fraction
        fee = entry_fee + _fee_of(deal) * close_fraction
        swap = entry_swap + deal["swap"] * close_fraction
        trades.append(ClosedTrade(
            trade_id=f"mt5-{deal['deal']}",
            side=entry.side,
            signal_time=entry.time,
            entry_time=entry.time,
            exit_time=deal["time"],
            entry_price=entry.price,
            exit_price=deal["price"],
            volume=volume,
            commission=commission,
            fee=fee,
            swap=swap,
            profit=profit,
            net_pnl=profit + commission + fee + swap,
            entry_deal=entry.deal,
            exit_deal=deal["deal"],
        ))
    residual = sum((lot.volume for lot in open_lots), Decimal(0))
    return trades, residual


def _money_pair(raw: str, label: str) -> tuple[Decimal, Decimal]:
    match = re.fullmatch(r"(.+?)\s*\((.+)\)", raw.strip())
    if match is None:
        raise FactoryContractError(f"{label}: expected money (percent) or percent (money)")
    left, right = match.group(1).strip(), match.group(2).strip()
    if left.endswith("%") and not right.endswith("%"):
        percent = parse_decimal(left[:-1].strip(), label)
        money = parse_decimal(right, label)
    elif right.endswith("%") and not left.endswith("%"):
        money = parse_decimal(left, label)
        percent = parse_decimal(right[:-1].strip(), label)
    else:
        raise FactoryContractError(f"{label}: drawdown pair is ambiguous")
    if percent < 0 or money < 0:
        raise FactoryContractError(f"{label}: negative drawdown")
    return money, percent


def _agrees(exact: Decimal, shown: Decimal) -> bool:
    exponent = shown.as_tuple().exponent
    if not isinstance(exponent, int) or exponent > 0:
        return False
    quantum = Decimal(1).scaleb(exponent)
    return exact.quantize(quantum, rounding=ROUND_HALF_UP) == shown


def _drawdown(balances: list[Decimal], deposit: Decimal) -> dict[str, Decimal]:
    if deposit <= 0:
        raise FactoryContractError("deposit must be positive")
    trough = min(balances)
    absolute = deposit - trough
    if absolute < 0:
        absolute = Decimal(0)
    peak = balances[0]
    max_money = Decimal(0)
    max_money_pct = Decimal(0)
    max_pct = Decimal(0)
    max_pct_money = Decimal(0)
    for balance in balances:
        if balance > peak:
            peak = balance
        if peak <= 0:
            raise FactoryContractError("non-positive balance peak")
        money = peak - balance
        percent = money / peak * Decimal(100)
        if money > max_money or (money == max_money and percent > max_money_pct):
            max_money = money
            max_money_pct = percent
        if percent > max_pct or (percent == max_pct and money > max_pct_money):
            max_pct = percent
            max_pct_money = money
    return {
        "absolute": absolute,
        "maximal_money": max_money,
        "maximal_pct": max_money_pct,
        "relative_pct": max_pct,
        "relative_money": max_pct_money,
    }


def _claim_text(value: Decimal, places: int = 4) -> str:
    quantum = Decimal(1).scaleb(-places)
    if value != value.quantize(quantum):
        raise FactoryContractError("ledger value does not fit 4 decimal places")
    return format(value, "f")


def parse_mt5_report(raw: bytes) -> dict[str, Any]:
    text = decode_mt5_report_text(raw)
    rows = _rows_from_text(text)
    headers = [
        index for index, row in enumerate(rows)
        if tuple(cell.lower() for cell in row) in (DEAL_HEADER_NO_FEE, DEAL_HEADER_WITH_FEE)
    ]
    if len(headers) != 1:
        raise FactoryContractError("report must contain exactly one Deals header")
    header_at = headers[0]
    header = tuple(cell.lower() for cell in rows[header_at])
    has_fee = header == DEAL_HEADER_WITH_FEE
    width = len(header)
    deals: list[dict[str, Any]] = []
    footer = None
    end = header_at + 1
    while end < len(rows) and len(rows[end]) == width:
        deals.append(_deal_from_cells(rows[end]))
        end += 1
    footer_width = 7 if has_fee else 6
    if end < len(rows) and len(rows[end]) == footer_width:
        candidate = rows[end]
        try:
            if has_fee:
                footer = {
                    "commission": parse_decimal(candidate[1], "footer commission"),
                    "fee": parse_decimal(candidate[2], "footer fee"),
                    "swap": parse_decimal(candidate[3], "footer swap"),
                    "profit": parse_decimal(candidate[4], "footer profit"),
                    "balance": parse_decimal(candidate[5], "footer balance"),
                }
            else:
                footer = {
                    "commission": parse_decimal(candidate[1], "footer commission"),
                    "swap": parse_decimal(candidate[2], "footer swap"),
                    "profit": parse_decimal(candidate[3], "footer profit"),
                    "balance": parse_decimal(candidate[4], "footer balance"),
                }
        except FactoryContractError:
            footer = None
        else:
            end += 1
    for row in rows[end:]:
        if len(row) == width or (row and _TIME.fullmatch(row[0])):
            raise FactoryContractError("deals table ended before a later deal-like row")
    if not deals:
        raise FactoryContractError("deals table is empty")
    seen: set[int] = set()
    previous = 0
    running = Decimal(0)
    for deal in deals:
        if deal["deal"] in seen or deal["deal"] <= previous:
            raise FactoryContractError("deal ids must be unique and increasing")
        seen.add(deal["deal"])
        previous = deal["deal"]
        running += deal["profit"] + deal["commission"] + deal["fee"] + deal["swap"]
        if running != deal["balance"]:
            raise FactoryContractError("balance column does not chain from deal profit, commission, fee and swap")
    labels = _label_map(rows, header_at)
    missing = [name for name in _LABELS if name not in labels]
    if missing:
        raise FactoryContractError("report summary is missing " + ", ".join(missing))
    return {
        "text": text,
        "labels": labels,
        "deals": deals,
        "footer": footer,
    }


def _period_bounds(period: str, year: int, as_of: datetime) -> None:
    match = _PERIOD.search(period)
    if match is None:
        raise FactoryContractError("report period is missing or ambiguous")
    start = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    end = date(int(match.group(4)), int(match.group(5)), int(match.group(6)))
    if start != date(year, 1, 1):
        raise FactoryContractError("report does not start on 1 January of the tested year")
    if year < 2026:
        if end not in (date(year, 12, 31), date(year + 1, 1, 1)):
            raise FactoryContractError("completed-year report is not bounded to that calendar year")
    else:
        as_of_day = as_of.date()
        if end.year != 2026 or end <= date(2026, 1, 1) or end > as_of_day:
            raise FactoryContractError("2026 report is not a partial window inside the as-of date")


def analyse_report(raw: bytes, *, year: int, as_of: datetime, source_kind: str) -> dict[str, Any]:
    """Parse one report and decide whether its numbers may enter the bundle."""
    if year not in ALL_YEARS:
        raise FactoryContractError("year is outside 2021-2026")
    if source_kind not in ("REAL_MT5_TESTER", "SYNTHETIC_FIXTURE"):
        raise FactoryContractError("unsupported source kind")
    report_hash = _sha(bytes(raw))
    try:
        parsed = parse_mt5_report(raw)
    except FactoryContractError as exc:
        return {
            "admitted": False,
            "parse_error": str(exc),
            "report_sha256": report_hash,
            "ledger_csv": None,
            "discrepancies": ["unreadable_or_ambiguous_report"],
        }
    text = parsed["text"]
    if source_kind == "SYNTHETIC_FIXTURE" and SYNTHETIC_MARKER not in text:
        return _rejected(report_hash, parsed, ["synthetic report is not labelled SYNTHETIC_FIXTURE"])
    if source_kind == "REAL_MT5_TESTER" and SYNTHETIC_MARKER in text:
        return _rejected(report_hash, parsed, ["synthetic marker present on a real-labelled report"])
    issues: list[str] = []
    labels = parsed["labels"]
    deals = parsed["deals"]
    try:
        _period_bounds(labels["Period:"], year, as_of)
    except FactoryContractError as exc:
        issues.append(str(exc))
    if labels["Currency:"] != "USD":
        issues.append("account currency is not USD")
    symbol = labels["Symbol:"]
    trade_symbols = {deal["symbol"] for deal in deals if deal["type"] in TRADE_TYPES}
    if len(trade_symbols) > 1 or (trade_symbols and symbol not in trade_symbols):
        issues.append("deal symbols disagree with the report symbol")
    try:
        deposit = parse_decimal(labels["Initial Deposit:"], "Initial Deposit")
    except FactoryContractError as exc:
        issues.append(str(exc))
        deposit = None
    if deposit is not None:
        first = deals[0]
        if first["type"] != "balance" or first["profit"] != deposit or first["balance"] != deposit:
            issues.append("initial deposit does not match the opening balance deal")
    try:
        reported_net = parse_decimal(labels["Total Net Profit:"], "Total Net Profit")
        reported_trades = parse_decimal(labels["Total Trades:"], "Total Trades")
        equity_abs = parse_decimal(labels["Equity Drawdown Absolute:"], "Equity Drawdown Absolute")
        equity_max_money, equity_max_pct = _money_pair(
            labels["Equity Drawdown Maximal:"], "Equity Drawdown Maximal"
        )
        equity_rel_money, equity_rel_pct = _money_pair(
            labels["Equity Drawdown Relative:"], "Equity Drawdown Relative"
        )
    except FactoryContractError as exc:
        return _rejected(report_hash, parsed, issues + [str(exc)])
    if reported_trades != reported_trades.to_integral_value() or reported_trades < 0:
        issues.append("total trades is not a nonnegative integer")
    ledger_net = sum(
        (deal["profit"] + deal["commission"] + deal["fee"] + deal["swap"]
         for deal in deals if deal["type"] not in CASHFLOW_TYPES),
        Decimal(0),
    )
    if not _agrees(ledger_net, reported_net):
        issues.append("net profit disagrees with the deal ledger")
    try:
        trades, residual = closed_trades_from_deals(deals)
    except FactoryContractError as exc:
        return _rejected(report_hash, parsed, issues + [str(exc)])
    if residual != 0:
        issues.append("position is not flat at the end of the report")
    if len(trades) != int(reported_trades):
        issues.append("closed trades disagree with Total Trades")
    trade_net = sum((trade.net_pnl for trade in trades), Decimal(0))
    if trade_net != ledger_net:
        issues.append("closed-trade net does not equal deal-ledger net")
    gross_profit = sum((trade.net_pnl for trade in trades if trade.net_pnl > 0), Decimal(0))
    gross_loss = sum((trade.net_pnl for trade in trades if trade.net_pnl < 0), Decimal(0))
    if "Gross Profit:" in labels:
        try:
            if not _agrees(gross_profit, parse_decimal(labels["Gross Profit:"], "Gross Profit")):
                issues.append("gross profit disagrees with closed trades")
        except FactoryContractError as exc:
            issues.append(str(exc))
    if "Gross Loss:" in labels:
        try:
            if not _agrees(gross_loss, parse_decimal(labels["Gross Loss:"], "Gross Loss")):
                issues.append("gross loss disagrees with closed trades")
        except FactoryContractError as exc:
            issues.append(str(exc))
    if "Profit Factor:" in labels:
        try:
            shown_factor = parse_decimal(labels["Profit Factor:"], "Profit Factor")
        except FactoryContractError as exc:
            issues.append(str(exc))
        else:
            if gross_loss == 0:
                issues.append("profit factor is printed but the ledger has no losing trades")
            elif not _agrees(gross_profit / abs(gross_loss), shown_factor):
                issues.append("profit factor disagrees with closed trades")
    if "Total Deals:" in labels:
        try:
            shown = parse_decimal(labels["Total Deals:"], "Total Deals")
            if shown != Decimal(len(deals)):
                issues.append("total deals disagrees with the deals table")
        except FactoryContractError as exc:
            issues.append(str(exc))
    footer = parsed["footer"]
    if footer is not None:
        if footer["commission"] != sum((deal["commission"] for deal in deals), Decimal(0)):
            issues.append("deals footer commission disagrees")
        if footer["swap"] != sum((deal["swap"] for deal in deals), Decimal(0)):
            issues.append("deals footer swap disagrees")
        if "fee" in footer and footer["fee"] != sum((deal["fee"] for deal in deals), Decimal(0)):
            issues.append("deals footer fee disagrees")
        if footer["profit"] != sum((deal["profit"] for deal in deals), Decimal(0)):
            issues.append("deals footer profit disagrees")
        if footer["balance"] != deals[-1]["balance"]:
            issues.append("deals footer balance disagrees")
    if deposit is None:
        stats = None
    else:
        try:
            stats = _drawdown([deal["balance"] for deal in deals], deposit)
        except FactoryContractError as exc:
            issues.append(str(exc))
            stats = None
    if stats is not None:
        # Balance drawdown is the ledger path. Equity drawdown is whatever the
        # report printed and is not required to equal the balance path.
        for prefix, money_key, pct_key in (
            ("Balance Drawdown Absolute:", "absolute", None),
            ("Balance Drawdown Maximal:", "maximal_money", "maximal_pct"),
            ("Balance Drawdown Relative:", "relative_money", "relative_pct"),
        ):
            try:
                if pct_key is None:
                    shown_money = parse_decimal(labels[prefix], prefix)
                    shown_pct = None
                else:
                    shown_money, shown_pct = _money_pair(labels[prefix], prefix)
            except FactoryContractError as exc:
                issues.append(str(exc))
                continue
            if not _agrees(stats[money_key], shown_money):
                issues.append("balance drawdown disagrees with the ledger balance path")
            if shown_pct is not None and pct_key == "maximal_pct" and not _agrees(stats["maximal_pct"], shown_pct):
                issues.append("balance drawdown maximal percent disagrees with the ledger balance path")
            if shown_pct is not None and pct_key == "relative_pct" and not _agrees(stats["relative_pct"], shown_pct):
                issues.append("balance drawdown relative percent disagrees with the ledger balance path")
        if equity_abs < 0 or equity_max_money < 0 or equity_rel_money < 0:
            issues.append("equity drawdown money is negative")
    claims = None
    if not issues and stats is not None:
        try:
            equity_percent = equity_rel_pct.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            if not _agrees(equity_percent, equity_rel_pct):
                issues.append("equity drawdown percent does not fit 4 decimal places")
            else:
                claims = {
                    "net_profit_usd": _claim_text(ledger_net),
                    "closed_trades": len(trades),
                    "max_equity_drawdown_pct": format(equity_percent, "f"),
                    "trades": trades,
                }
        except FactoryContractError as exc:
            issues.append(str(exc))
    csv_text = canonical_ledger_csv(deals)
    return {
        "admitted": not issues and claims is not None,
        "parse_error": None,
        "report_sha256": report_hash,
        "ledger_csv": csv_text,
        "ledger_sha256": _sha(csv_text.encode("utf-8")),
        "discrepancies": issues,
        "claims": claims,
        "ledger_net": format(ledger_net, "f"),
        "reported_net": format(reported_net, "f"),
        "closed_trade_count": len(trades),
    }


def _rejected(report_hash: str, parsed: dict[str, Any], issues: list[str]) -> dict[str, Any]:
    csv_text = canonical_ledger_csv(parsed["deals"])
    return {
        "admitted": False,
        "parse_error": None,
        "report_sha256": report_hash,
        "ledger_csv": csv_text,
        "ledger_sha256": _sha(csv_text.encode("utf-8")),
        "discrepancies": issues,
        "claims": None,
    }


def _empty_result(year: int, coverage: str, status: str) -> dict[str, Any]:
    return {
        "year": year,
        "coverage": coverage,
        "test_status": status,
        "net_profit_usd": None,
        "closed_trades": None,
        "max_equity_drawdown_pct": None,
        "report_sha256": None,
        "ledger_sha256": None,
    }


def _as_of(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise FactoryContractError("as_of_utc must use UTC Z")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FactoryContractError("invalid as_of_utc") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise FactoryContractError("as_of_utc must be UTC")
    return parsed


def build_annual_bundle(
    *,
    system_id: str,
    family_id: str,
    source_kind: str,
    strategy_version_sha256: str,
    ea_sha256: str,
    broker_profile_sha256: str,
    test_config_sha256: str,
    data_manifest_sha256: str,
    tester_build: str,
    as_of_utc: str,
    reports: dict[int, tuple[str, bytes] | None],
    ledger_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a v1 bundle. Writes a canonical ledger CSV for every parsed year.

    `reports` must contain each year 2021-2026. None means the file is missing.
    A tuple is (filename, raw bytes). Synthetic inputs must carry the marker in
    the filename or a `synthetic` path segment.
    """
    if set(reports) != set(ALL_YEARS):
        raise FactoryContractError("reports must cover 2021-2026 exactly once")
    if not IDENTIFIER.fullmatch(system_id):
        raise FactoryContractError("invalid system_id")
    as_of = _as_of(as_of_utc)
    ledger_dir.mkdir(parents=True, exist_ok=True)
    results = []
    receipt_years = []
    for year in ALL_YEARS:
        item = reports[year]
        if item is None:
            results.append(_empty_result(year, "MISSING", "BLOCKED"))
            receipt_years.append({
                "year": year,
                "admission": "MISSING",
                "archive_report_sha256": None,
                "archive_ledger_sha256": None,
                "ledger_file": None,
                "discrepancies": ["report_file_missing"],
                "admitted_to_bundle": False,
            })
            continue
        filename, raw = item
        if source_kind == "SYNTHETIC_FIXTURE":
            lowered = filename.replace("\\", "/").lower()
            if "synthetic" not in lowered.split("/"):
                # Also accept a filename token, e.g. synthetic_GT_2023_real_ticks.htm.
                parts = re.split(r"[^a-z0-9]+", lowered)
                if "synthetic" not in parts:
                    raise FactoryContractError("synthetic report path is not marked synthetic")
        analysis = analyse_report(raw, year=year, as_of=as_of, source_kind=source_kind)
        ledger_name = None
        if analysis.get("ledger_csv") is not None:
            ledger_name = f"{system_id}_{year}_deals.csv"
            destination = ledger_dir / ledger_name
            if destination.exists():
                raise FactoryContractError(f"refusing overwrite of ledger {destination.name}")
            destination.write_bytes(analysis["ledger_csv"].encode("utf-8"))
        if analysis["admitted"]:
            claims = analysis["claims"]
            status = "PARTIAL" if year == 2026 else "COMPLETED"
            results.append({
                "year": year,
                "coverage": "VERIFIED",
                "test_status": status,
                "net_profit_usd": claims["net_profit_usd"],
                "closed_trades": claims["closed_trades"],
                "max_equity_drawdown_pct": claims["max_equity_drawdown_pct"],
                "report_sha256": analysis["report_sha256"],
                "ledger_sha256": analysis["ledger_sha256"],
            })
            admission = "ADMITTED_PARTIAL" if year == 2026 else "ADMITTED"
        elif analysis.get("parse_error"):
            results.append(_empty_result(year, "INCOMPLETE", "FAILED"))
            admission = "UNREADABLE"
        else:
            results.append(_empty_result(year, "VERIFIED", "FAILED"))
            admission = "CROSSCHECK_FAILED"
        receipt_years.append({
            "year": year,
            "admission": admission,
            "archive_report_sha256": analysis["report_sha256"],
            "archive_ledger_sha256": analysis.get("ledger_sha256"),
            "ledger_file": ledger_name,
            "discrepancies": list(analysis["discrepancies"]),
            "admitted_to_bundle": bool(analysis["admitted"]),
            "parse_error": analysis.get("parse_error"),
        })
    bundle = {
        "schema": "goldthinker.factory.mt5_bundle.v1",
        "source_kind": source_kind,
        "system_id": system_id,
        "family_id": family_id,
        "strategy_version_sha256": strategy_version_sha256,
        "ea_sha256": ea_sha256,
        "broker_profile_sha256": broker_profile_sha256,
        "test_config_sha256": test_config_sha256,
        "data_manifest_sha256": data_manifest_sha256,
        "tester_build": tester_build,
        "as_of_utc": as_of_utc,
        "account_currency": "USD",
        "results": results,
    }
    validate_mt5_bundle(bundle)
    receipt = {
        "schema": "goldthinker.factory.mt5_extraction.v1",
        "source_kind": source_kind,
        "system_id": system_id,
        "as_of_utc": as_of_utc,
        "bundle_sha256": digest(bundle),
        "execution_performed": False,
        "broker_credentials_used": False,
        "tick_coverage_verified": False,
        "equity_series_in_deals": False,
        "real_mt5_evidence_authenticated": False,
        "time_basis": "BROKER_SERVER_CLOCK_NOT_UTC",
        "years": receipt_years,
    }
    receipt["receipt_sha256"] = digest(receipt)
    return bundle, receipt


def _marker_in_bytes(raw: bytes) -> bool:
    if SYNTHETIC_MARKER.encode("utf-8") in raw:
        return True
    if SYNTHETIC_MARKER.encode("utf-16-le") in raw or SYNTHETIC_MARKER.encode("utf-16-be") in raw:
        return True
    try:
        return SYNTHETIC_MARKER in decode_mt5_report_text(raw)
    except FactoryContractError:
        return False


def synthetic_content_block(
    bundle: Mapping[str, Any],
    reports: Mapping[int, bytes] | None,
    ledgers: Mapping[int, str],
) -> str | None:
    """Reject synthetic bytes even when a signature claims the run is real.

    Looks at the bundle document and the archived report and ledger bytes.
    Claimed source_kind is not enough.
    """
    if SYNTHETIC_MARKER in canonical_json(bundle):
        return "BLOCKED_SYNTHETIC_MARKER"
    for text in ledgers.values():
        if isinstance(text, str) and SYNTHETIC_MARKER in text:
            return "BLOCKED_SYNTHETIC_MARKER"
    for raw in (reports or {}).values():
        if isinstance(raw, (bytes, bytearray)) and _marker_in_bytes(bytes(raw)):
            return "BLOCKED_SYNTHETIC_MARKER"
    return None


def real_evidence_block_reason(
    bundle_v1: Mapping[str, Any],
    receipt: Mapping[str, Any] | None,
    reports: Mapping[int, bytes] | None,
    ledgers: Mapping[int, str],
) -> str | None:
    """Return a block status, or None when the extractor binding holds.

    A matching receipt only shows these bytes were hashed together. It does
    not authenticate that MetaTrader wrote them.
    """
    if not isinstance(receipt, Mapping) or not isinstance(reports, Mapping):
        return "BLOCKED_EVIDENCE_RECEIPT_MISSING"
    if "receipt_sha256" not in receipt or receipt.get("schema") != "goldthinker.factory.mt5_extraction.v1":
        return "BLOCKED_EVIDENCE_RECEIPT_MISSING"
    body = {key: receipt[key] for key in receipt if key != "receipt_sha256"}
    if digest(body) != receipt.get("receipt_sha256"):
        return "BLOCKED_EVIDENCE_HASH_MISMATCH"
    if receipt.get("source_kind") != "REAL_MT5_TESTER" or bundle_v1.get("source_kind") != "REAL_MT5_TESTER":
        return "BLOCKED_EVIDENCE_HASH_MISMATCH"
    if not isinstance(bundle_v1, Mapping) or "results" not in bundle_v1:
        return "BLOCKED_EVIDENCE_RECEIPT_MISSING"
    if receipt.get("bundle_sha256") != digest(dict(bundle_v1)):
        return "BLOCKED_EVIDENCE_HASH_MISMATCH"
    if receipt.get("system_id") != bundle_v1.get("system_id"):
        return "BLOCKED_EVIDENCE_HASH_MISMATCH"
    by_receipt = {}
    for row in receipt.get("years") or []:
        if not isinstance(row, dict) or "year" not in row:
            return "BLOCKED_EVIDENCE_HASH_MISMATCH"
        by_receipt[row["year"]] = row
    for row in bundle_v1["results"]:
        year = row["year"]
        recorded = by_receipt.get(year)
        if recorded is None:
            return "BLOCKED_EVIDENCE_HASH_MISMATCH"
        if recorded.get("archive_report_sha256") is None and row["report_sha256"] is None:
            continue
        raw = reports.get(year)
        ledger = ledgers.get(year)
        if isinstance(raw, (bytes, bytearray)) and _marker_in_bytes(bytes(raw)):
            return "BLOCKED_SYNTHETIC_MARKER"
        if isinstance(ledger, str) and SYNTHETIC_MARKER in ledger:
            return "BLOCKED_SYNTHETIC_MARKER"
        if not isinstance(raw, (bytes, bytearray)) or not isinstance(ledger, str):
            return "BLOCKED_EVIDENCE_HASH_MISMATCH"
        report_hash = sha256(bytes(raw)).hexdigest()
        ledger_hash = sha256(ledger.encode("utf-8")).hexdigest()
        if report_hash != recorded.get("archive_report_sha256") or ledger_hash != recorded.get("archive_ledger_sha256"):
            return "BLOCKED_EVIDENCE_HASH_MISMATCH"
        if row["report_sha256"] not in (None, report_hash) or row["ledger_sha256"] not in (None, ledger_hash):
            return "BLOCKED_EVIDENCE_HASH_MISMATCH"
        if _marker_in_bytes(bytes(raw)) or SYNTHETIC_MARKER in ledger:
            return "BLOCKED_SYNTHETIC_MARKER"
    return None


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
