from __future__ import annotations

import io
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from statistics import median
from typing import Any
from urllib.parse import urlparse

import httpx

CME_CONTRACT_INTELLIGENCE_VERSION = "aidy_cme_gold_contract_intelligence_v1"
CME_DAILY_RECORD_VERSION = "aidy_cme_gold_daily_settlement_oi_v1"
CME_CALENDAR_VERSION = "aidy_cme_gold_contract_calendar_v1"
J6_VERSION = "aidy_j6_open_interest_persistence_v1"

CME_BULLETIN_URL = (
    "https://www.cmegroup.com/daily_bulletin/current/"
    "Section62_Metals_Futures_Products.pdf"
)
CME_GOLD_CALENDAR_URL = (
    "https://www.cmegroup.com/markets/metals/precious/gold.calendar.html"
)
CME_GOLD_CALENDAR_DOWNLOAD_URL = (
    "https://www.cmegroup.com/CmeWS/mvc/ProductCalendar/Download.xls?productId=437"
)
CME_GOLD_SETTLEMENTS_URL = (
    "https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/Settlements/437/FUT"
)
CME_GOLD_VOLUME_URL_TEMPLATE = (
    "https://www.cmegroup.com/CmeWS/mvc/Volume/Details/F/437/{trade_date}/P"
)
CME_ALLOWED_HOSTS = ("cmegroup.com", "www.cmegroup.com")
MAX_BULLETIN_BYTES = 8_000_000
MIN_J6_EPISODES_PER_QUADRANT_HORIZON = 30
ROLL_WINDOW_BUSINESS_DAYS = 10

MONTH_CODES = {
    1: "F",
    2: "G",
    3: "H",
    4: "J",
    5: "K",
    6: "M",
    7: "N",
    8: "Q",
    9: "U",
    10: "V",
    11: "X",
    12: "Z",
}
MONTH_NAMES = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}
J6_HORIZONS = (1, 3, 5)
J6_QUADRANTS = (
    "price_up_oi_up",
    "price_down_oi_up",
    "price_up_oi_down",
    "price_down_oi_down",
)


class CmeContractError(RuntimeError):
    pass


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("CME evidence timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _decimal(value: object, *, name: str, positive: bool = False) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{name} must be a finite decimal.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a finite decimal.") from exc
    if not parsed.is_finite() or (positive and parsed <= 0):
        raise ValueError(f"{name} must be a finite{' positive' if positive else ''} decimal.")
    return parsed


def _fmt(value: Decimal | object) -> str:
    parsed = value if isinstance(value, Decimal) else _decimal(value, name="value")
    text = format(parsed, "f").rstrip("0").rstrip(".")
    return text or "0"


def _official_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in CME_ALLOWED_HOSTS:
        raise ValueError("CME source URL is not on the official HTTPS allowlist.")
    return url


def _contract_month(label: str) -> date:
    match = re.fullmatch(r"([A-Z]{3})(\d{2})", label.strip().upper())
    if match is None or match.group(1) not in MONTH_NAMES:
        raise ValueError("Invalid CME contract-month label.")
    return date(2000 + int(match.group(2)), MONTH_NAMES[match.group(1)], 1)


def _contract_code(label: str) -> str:
    month = _contract_month(label)
    return f"GC{MONTH_CODES[month.month]}{str(month.year)[-2:]}"


@dataclass(frozen=True, slots=True)
class CmeGoldBulletinRow:
    contract_label: str
    contract_code: str
    contract_month: date
    settlement: str
    settlement_change: str
    settlement_change_bps: str
    open_interest: int
    open_interest_change: int
    settlement_indicator: str | None


@dataclass(frozen=True, slots=True)
class CmeGoldBulletinSnapshot:
    trade_date: date
    bulletin_number: int | None
    publication_state: str
    official_published_at: datetime | None
    source_url: str
    final_url: str
    first_observed_at: datetime
    source_sha256: str
    extracted_text_sha256: str
    rows: tuple[CmeGoldBulletinRow, ...]

    @property
    def snapshot_digest(self) -> str:
        return digest(
            {
                "trade_date": self.trade_date.isoformat(),
                "bulletin_number": self.bulletin_number,
                "publication_state": self.publication_state,
                "official_published_at": (
                    None
                    if self.official_published_at is None
                    else self.official_published_at.isoformat()
                ),
                "source_url": self.source_url,
                "final_url": self.final_url,
                "first_observed_at": self.first_observed_at.isoformat(),
                "source_sha256": self.source_sha256,
                "extracted_text_sha256": self.extracted_text_sha256,
                "rows": [
                    {
                        "contract_label": row.contract_label,
                        "contract_code": row.contract_code,
                        "contract_month": row.contract_month.isoformat(),
                        "settlement": row.settlement,
                        "settlement_change": row.settlement_change,
                        "settlement_change_bps": row.settlement_change_bps,
                        "open_interest": row.open_interest,
                        "open_interest_change": row.open_interest_change,
                        "settlement_indicator": row.settlement_indicator,
                    }
                    for row in self.rows
                ],
            }
        )


def _parse_bulletin_header(text: str) -> tuple[date, int, str]:
    bulletin = re.search(r"PG62\s*BULLETIN\s+#\s*(\d+)@", text, flags=re.IGNORECASE)
    dated = re.search(
        r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s*([A-Z][a-z]{2}),?\s+"
        r"(\d{1,2}),?\s+(\d{4})",
        text,
        flags=re.IGNORECASE,
    )
    if bulletin is None or dated is None:
        raise CmeContractError("cme_bulletin_header_missing")
    trade_date = datetime.strptime(
        f"{dated.group(1)} {dated.group(2)} {dated.group(3)}", "%b %d %Y"
    ).replace(tzinfo=UTC).date()
    upper = text.upper()
    publication_state = "final" if re.search(r"\bFINAL\b", upper) else "preliminary"
    if "PRELIMINARY" not in upper and publication_state != "final":
        raise CmeContractError("cme_bulletin_publication_state_missing")
    return trade_date, int(bulletin.group(1)), publication_state


def _parse_signed_tail(tokens: list[str]) -> tuple[int, int]:
    if not tokens:
        raise CmeContractError("cme_gc_row_open_interest_missing")
    if tokens[-1].upper() == "UNCH":
        if len(tokens) < 2 or not tokens[-2].isdigit():
            raise CmeContractError("cme_gc_row_open_interest_invalid")
        return int(tokens[-2]), 0
    if len(tokens) >= 3 and tokens[-2] in {"+", "-"} and tokens[-3].isdigit():
        change = int(tokens[-1]) * (1 if tokens[-2] == "+" else -1)
        return int(tokens[-3]), change
    compact = re.fullmatch(r"([+-])(\d+)", tokens[-1])
    if compact is not None and len(tokens) >= 2 and tokens[-2].isdigit():
        change = int(compact.group(2)) * (1 if compact.group(1) == "+" else -1)
        return int(tokens[-2]), change
    raise CmeContractError("cme_gc_row_open_interest_change_invalid")


def _parse_gc_line(line: str) -> CmeGoldBulletinRow | None:
    tokens = line.replace("/", " /").split()
    if not tokens or re.fullmatch(r"[A-Z]{3}\d{2}", tokens[0]) is None:
        return None
    label = tokens[0]
    settlement_index: int | None = None
    for index in range(1, len(tokens) - 1):
        if tokens[index + 1] in {"+", "-", "UNCH"}:
            settlement_index = index
            break
    if settlement_index is None:
        return None
    raw_settlement = tokens[settlement_index]
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([ABNP])?", raw_settlement)
    if match is None:
        raise CmeContractError("cme_gc_row_settlement_invalid")
    settlement = _fmt(_decimal(match.group(1), name="settlement", positive=True))
    change_token = tokens[settlement_index + 1].upper()
    if change_token == "UNCH":
        settlement_change = Decimal(0)
        tail_start = settlement_index + 2
    else:
        if settlement_index + 2 >= len(tokens):
            raise CmeContractError("cme_gc_row_settlement_change_missing")
        settlement_change = _decimal(
            tokens[settlement_index + 2], name="settlement change"
        ) * (Decimal(1) if change_token == "+" else Decimal(-1))
        tail_start = settlement_index + 3
    prior_settlement = Decimal(settlement) - settlement_change
    if prior_settlement <= 0:
        raise CmeContractError("cme_gc_row_prior_settlement_invalid")
    settlement_change_bps = settlement_change / prior_settlement * Decimal(10_000)
    open_interest, open_interest_change = _parse_signed_tail(tokens[tail_start:])
    return CmeGoldBulletinRow(
        contract_label=label,
        contract_code=_contract_code(label),
        contract_month=_contract_month(label),
        settlement=settlement,
        settlement_change=_fmt(settlement_change),
        settlement_change_bps=_fmt(settlement_change_bps),
        open_interest=open_interest,
        open_interest_change=open_interest_change,
        settlement_indicator=match.group(2),
    )


def parse_cme_gold_bulletin_text(
    text: str,
    *,
    source_bytes: bytes,
    first_observed_at: datetime | str,
    source_url: str = CME_BULLETIN_URL,
    final_url: str = CME_BULLETIN_URL,
) -> CmeGoldBulletinSnapshot:
    _official_url(source_url)
    _official_url(final_url)
    if not source_bytes or len(source_bytes) > MAX_BULLETIN_BYTES:
        raise CmeContractError("cme_bulletin_payload_size")
    if "GC FUT COMEX GOLD FUTURES" not in " ".join(text.upper().split()):
        raise CmeContractError("cme_gc_section_missing")
    trade_date, bulletin_number, publication_state = _parse_bulletin_header(text)
    in_gc = False
    rows: list[CmeGoldBulletinRow] = []
    for raw_line in text.splitlines():
        line = " ".join(raw_line.replace("\x00", " ").split())
        upper = line.upper()
        if "GC FUT COMEX GOLD FUTURES" in upper:
            in_gc = True
            continue
        if in_gc and upper.startswith("TOTAL GC FUT"):
            break
        if in_gc:
            parsed = _parse_gc_line(line)
            if parsed is not None:
                rows.append(parsed)
    if not rows:
        raise CmeContractError("cme_gc_contract_rows_missing")
    if len({row.contract_code for row in rows}) != len(rows):
        raise CmeContractError("cme_gc_duplicate_contract_month")
    return CmeGoldBulletinSnapshot(
        trade_date=trade_date,
        bulletin_number=bulletin_number,
        publication_state=publication_state,
        official_published_at=None,
        source_url=source_url,
        final_url=final_url,
        first_observed_at=_utc(first_observed_at),
        source_sha256=sha256(source_bytes).hexdigest(),
        extracted_text_sha256=sha256(text.encode()).hexdigest(),
        rows=tuple(sorted(rows, key=lambda row: row.contract_month)),
    )


def _integer(value: object, *, name: str) -> int:
    text = str(value).replace(",", "").strip()
    if not re.fullmatch(r"[+-]?\d+", text):
        raise CmeContractError(f"cme_json_{name}_invalid")
    return int(text)


def parse_cme_gold_official_json(
    settlements_payload: Mapping[str, Any],
    volume_payload: Mapping[str, Any],
    *,
    first_observed_at: datetime | str,
    settlements_url: str,
    volume_url: str,
) -> CmeGoldBulletinSnapshot:
    _official_url(settlements_url)
    _official_url(volume_url)
    settlement_trade_date = datetime.strptime(
        str(settlements_payload.get("tradeDate") or ""), "%m/%d/%Y"
    ).replace(tzinfo=UTC).date()
    volume_trade_date = datetime.strptime(
        str(volume_payload.get("tradeDate") or ""), "%Y%m%d"
    ).replace(tzinfo=UTC).date()
    if settlement_trade_date != volume_trade_date:
        raise CmeContractError("cme_json_trade_date_disagreement")
    if settlements_payload.get("empty") is True or volume_payload.get("empty") is True:
        raise CmeContractError("cme_json_empty")
    if str(settlements_payload.get("reportType") or "").lower() != "final":
        raise CmeContractError("cme_json_report_not_final")
    published_at = _utc(str(volume_payload.get("updateTime") or ""))

    volume_by_label: dict[str, Mapping[str, Any]] = {}
    for raw in volume_payload.get("monthData") or []:
        item = dict(raw)
        match = re.fullmatch(r"([A-Z]{3})\s+(\d{4})", str(item.get("month") or ""))
        if match is None:
            continue
        label = f"{match.group(1)}{match.group(2)[-2:]}"
        volume_by_label[label] = item

    rows: list[CmeGoldBulletinRow] = []
    for raw in settlements_payload.get("settlements") or []:
        item = dict(raw)
        match = re.fullmatch(r"([A-Z]{3})\s+(\d{2})", str(item.get("month") or ""))
        if match is None:
            continue
        label = f"{match.group(1)}{match.group(2)}"
        volume = volume_by_label.get(label)
        if volume is None:
            continue
        raw_settlement = str(item.get("settle") or "").strip()
        settle_match = re.fullmatch(r"(\d+(?:\.\d+)?)([ABNP])?", raw_settlement)
        if settle_match is None:
            raise CmeContractError("cme_json_settlement_invalid")
        settlement = _decimal(settle_match.group(1), name="settlement", positive=True)
        settlement_change = _decimal(
            str(item.get("change") or "").replace(",", ""), name="settlement change"
        )
        prior_settlement = settlement - settlement_change
        if prior_settlement <= 0:
            raise CmeContractError("cme_json_prior_settlement_invalid")
        rows.append(
            CmeGoldBulletinRow(
                contract_label=label,
                contract_code=_contract_code(label),
                contract_month=_contract_month(label),
                settlement=_fmt(settlement),
                settlement_change=_fmt(settlement_change),
                settlement_change_bps=_fmt(
                    settlement_change / prior_settlement * Decimal(10_000)
                ),
                open_interest=_integer(volume.get("atClose"), name="open_interest"),
                open_interest_change=_integer(
                    volume.get("change"), name="open_interest_change"
                ),
                settlement_indicator=settle_match.group(2),
            )
        )
    if not rows:
        raise CmeContractError("cme_json_gc_contract_rows_missing")
    canonical_payload = canonical_json(
        {"settlements": settlements_payload, "volume_open_interest": volume_payload}
    ).encode()
    return CmeGoldBulletinSnapshot(
        trade_date=settlement_trade_date,
        bulletin_number=None,
        publication_state="final",
        official_published_at=published_at,
        source_url=settlements_url,
        final_url=volume_url,
        first_observed_at=_utc(first_observed_at),
        source_sha256=sha256(canonical_payload).hexdigest(),
        extracted_text_sha256=sha256(canonical_payload).hexdigest(),
        rows=tuple(sorted(rows, key=lambda row: row.contract_month)),
    )


class CmePublicBulletinGateway:
    def __init__(self, *, timeout_seconds: float = 45.0) -> None:
        self._timeout = httpx.Timeout(timeout_seconds)

    def fetch_current(
        self,
        *,
        first_observed_at: datetime | str,
        client: httpx.Client | None = None,
    ) -> CmeGoldBulletinSnapshot:
        owns_client = client is None
        if client is None:
            client = httpx.Client(
                timeout=self._timeout,
                follow_redirects=True,
                headers={"User-Agent": "AIDY-Gold-Signals/Day30 official CME evidence"},
            )
        try:
            json_snapshot = self._fetch_official_json(
                first_observed_at=first_observed_at, client=client
            )
            if json_snapshot is not None:
                return json_snapshot
            response = client.get(CME_BULLETIN_URL)
            if response.status_code != 200:
                raise CmeContractError(f"cme_bulletin_http_{response.status_code}")
            _official_url(str(response.url))
            body = response.content
            if not body.startswith(b"%PDF") or len(body) > MAX_BULLETIN_BYTES:
                raise CmeContractError("cme_bulletin_invalid_pdf")
            try:
                import pdfplumber

                with pdfplumber.open(io.BytesIO(body)) as document:
                    text = "\n".join(
                        page.extract_text(layout=True) or "" for page in document.pages
                    )
            except Exception as exc:
                raise CmeContractError("cme_bulletin_pdf_extract_failed") from exc
            return parse_cme_gold_bulletin_text(
                text,
                source_bytes=body,
                first_observed_at=first_observed_at,
                final_url=str(response.url),
            )
        finally:
            if owns_client:
                client.close()

    def _fetch_official_json(
        self,
        *,
        first_observed_at: datetime | str,
        client: httpx.Client,
    ) -> CmeGoldBulletinSnapshot | None:
        observed = _utc(first_observed_at)
        headers = {
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://www.cmegroup.com/markets/metals/precious/gold.html",
        }
        for offset in range(11):
            candidate = observed.date() - timedelta(days=offset)
            compact = candidate.strftime("%Y%m%d")
            volume_url = CME_GOLD_VOLUME_URL_TEMPLATE.format(trade_date=compact)
            response = client.get(volume_url, headers=headers)
            if response.status_code in {400, 404}:
                continue
            if response.status_code != 200:
                return None
            try:
                volume_payload = response.json()
            except ValueError:
                return None
            if volume_payload.get("empty") is True or not volume_payload.get("monthData"):
                continue
            settlements_url = f"{CME_GOLD_SETTLEMENTS_URL}?tradeDate={candidate:%m/%d/%Y}"
            settlement_response = client.get(settlements_url, headers=headers)
            if settlement_response.status_code != 200:
                return None
            try:
                settlements_payload = settlement_response.json()
            except ValueError:
                return None
            return parse_cme_gold_official_json(
                settlements_payload,
                volume_payload,
                first_observed_at=observed,
                settlements_url=settlements_url,
                volume_url=volume_url,
            )
        return None


def build_daily_contract_records(snapshot: CmeGoldBulletinSnapshot) -> list[dict[str, Any]]:
    revision_index = 1 if snapshot.publication_state == "final" else 0
    records = []
    for row in snapshot.rows:
        record: dict[str, Any] = {
            "record_version": CME_DAILY_RECORD_VERSION,
            "source": "cme_group_public_daily_contract_evidence",
            "source_url": snapshot.source_url,
            "final_url": snapshot.final_url,
            "source_sha256": snapshot.source_sha256,
            "extracted_text_sha256": snapshot.extracted_text_sha256,
            "snapshot_digest": snapshot.snapshot_digest,
            "bulletin_number": snapshot.bulletin_number,
            "publication_state": snapshot.publication_state,
            "official_published_at": (
                None
                if snapshot.official_published_at is None
                else snapshot.official_published_at.isoformat()
            ),
            "first_observed_at": snapshot.first_observed_at.isoformat(),
            "trade_date": snapshot.trade_date.isoformat(),
            "contract_label": row.contract_label,
            "contract_code": row.contract_code,
            "contract_month": row.contract_month.isoformat(),
            "settlement": row.settlement,
            "settlement_change": row.settlement_change,
            "settlement_change_bps": row.settlement_change_bps,
            "settlement_unit": "usd_per_troy_ounce",
            "settlement_indicator": row.settlement_indicator,
            "open_interest": row.open_interest,
            "open_interest_change": row.open_interest_change,
            "open_interest_unit": "contracts",
            "open_interest_frequency": "daily_t_plus_1",
            "revision_index": revision_index,
            "pit_reconstructable": True,
            "intraday_open_interest_inferred": False,
            "tas_reference_state": "unknown_not_ingested",
            "future_derived": False,
            "decision_input_allowed": True,
        }
        record["fact_key"] = digest(
            {
                "record_version": CME_DAILY_RECORD_VERSION,
                "trade_date": record["trade_date"],
                "contract_code": record["contract_code"],
            }
        )
        record["record_digest"] = digest(record)
        records.append(record)
    return records


def verify_daily_contract_record(record: Mapping[str, Any]) -> bool:
    body = dict(record)
    supplied = str(body.pop("record_digest", ""))
    if not supplied or supplied != digest(body):
        return False
    try:
        _official_url(str(body["source_url"]))
        _official_url(str(body["final_url"]))
        _utc(str(body["first_observed_at"]))
        if body.get("official_published_at") is not None:
            _utc(str(body["official_published_at"]))
        date.fromisoformat(str(body["trade_date"]))
        date.fromisoformat(str(body["contract_month"]))
        _decimal(body["settlement"], name="settlement", positive=True)
        _decimal(body["settlement_change"], name="settlement change")
        _decimal(body["settlement_change_bps"], name="settlement change bps")
        int(body["open_interest"])
        int(body["open_interest_change"])
    except (KeyError, TypeError, ValueError):
        return False
    expected_fact_key = digest(
        {
            "record_version": CME_DAILY_RECORD_VERSION,
            "trade_date": body.get("trade_date"),
            "contract_code": body.get("contract_code"),
        }
    )
    return (
        body.get("record_version") == CME_DAILY_RECORD_VERSION
        and body.get("fact_key") == expected_fact_key
        and body.get("open_interest_frequency") == "daily_t_plus_1"
        and body.get("intraday_open_interest_inferred") is False
        and body.get("future_derived") is False
        and body.get("decision_input_allowed") is True
    )


def select_daily_contract_records_as_of(
    records: Iterable[Mapping[str, Any]], *, as_of: datetime | str
) -> list[dict[str, Any]]:
    cutoff = _utc(as_of)
    latest: dict[str, dict[str, Any]] = {}
    for raw in records:
        record = dict(raw)
        if not verify_daily_contract_record(record):
            raise ValueError("Invalid CME daily contract record.")
        observed = _utc(str(record["first_observed_at"]))
        if observed > cutoff:
            continue
        key = str(record["fact_key"])
        current = latest.get(key)
        rank = (int(record["revision_index"]), observed, str(record["record_digest"]))
        if current is None:
            latest[key] = record
            continue
        current_rank = (
            int(current["revision_index"]),
            _utc(str(current["first_observed_at"])),
            str(current["record_digest"]),
        )
        if rank > current_rank:
            latest[key] = record
    if not latest:
        return []
    latest_trade_date = max(date.fromisoformat(str(item["trade_date"])) for item in latest.values())
    return sorted(
        (
            item
            for item in latest.values()
            if date.fromisoformat(str(item["trade_date"])) == latest_trade_date
        ),
        key=lambda item: str(item["contract_month"]),
    )


def build_contract_calendar_observation(
    *,
    contract_code: str,
    contract_month: date | str,
    first_notice_date: date | str,
    last_trade_date: date | str,
    first_delivery_date: date | str | None,
    last_delivery_date: date | str | None,
    first_observed_at: datetime | str,
    source_document_sha256: str,
    source_url: str = CME_GOLD_CALENDAR_URL,
) -> dict[str, Any]:
    _official_url(source_url)
    month = contract_month if isinstance(contract_month, date) else date.fromisoformat(contract_month)
    first_notice = (
        first_notice_date
        if isinstance(first_notice_date, date)
        else date.fromisoformat(first_notice_date)
    )
    last_trade = (
        last_trade_date
        if isinstance(last_trade_date, date)
        else date.fromisoformat(last_trade_date)
    )
    first_delivery = (
        first_delivery_date
        if isinstance(first_delivery_date, date) or first_delivery_date is None
        else date.fromisoformat(first_delivery_date)
    )
    last_delivery = (
        last_delivery_date
        if isinstance(last_delivery_date, date) or last_delivery_date is None
        else date.fromisoformat(last_delivery_date)
    )
    if not re.fullmatch(r"GC[FGHJKMNQUVXZ]\d{2}", contract_code):
        raise ValueError("Unsupported GC contract code.")
    if contract_code != f"GC{MONTH_CODES[month.month]}{str(month.year)[-2:]}":
        raise ValueError("GC contract code and contract month disagree.")
    if not re.fullmatch(r"[0-9a-f]{64}", source_document_sha256):
        raise ValueError("CME calendar source digest must be SHA-256.")
    record: dict[str, Any] = {
        "calendar_version": CME_CALENDAR_VERSION,
        "source": "cme_group_gold_contract_calendar",
        "source_url": source_url,
        "source_document_sha256": source_document_sha256,
        "first_observed_at": _utc(first_observed_at).isoformat(),
        "contract_code": contract_code,
        "contract_month": month.isoformat(),
        "first_notice_date": first_notice.isoformat(),
        "last_trade_date": last_trade.isoformat(),
        "first_delivery_date": None if first_delivery is None else first_delivery.isoformat(),
        "last_delivery_date": None if last_delivery is None else last_delivery.isoformat(),
        "pit_reconstructable": True,
        "future_derived": False,
    }
    record["calendar_digest"] = digest(record)
    return record


def _calendar_date(value: object) -> date | None:
    if value is None or value == "" or str(value).strip() in {"-", "N/A"}:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = " ".join(str(value).split())
    for pattern in ("%Y-%m-%d", "%d %b %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=UTC).date()
        except ValueError:
            pass
    raise CmeContractError(f"cme_calendar_date_invalid:{text}")


def parse_gold_calendar_table(
    table: Iterable[Iterable[object]],
    *,
    first_observed_at: datetime | str,
    source_document_sha256: str,
    source_url: str = CME_GOLD_CALENDAR_DOWNLOAD_URL,
) -> list[dict[str, Any]]:
    rows = [list(row) for row in table]
    header_index: int | None = None
    headers: list[str] = []
    for index, row in enumerate(rows):
        normalized = [" ".join(str(value).split()).lower() for value in row]
        if "product code" in normalized and "first notice" in normalized:
            header_index = index
            headers = normalized
            break
    if header_index is None:
        raise CmeContractError("cme_calendar_header_missing")
    aliases = {
        "product code": "product_code",
        "last trade": "last_trade",
        "first notice": "first_notice",
        "first delivery": "first_delivery",
        "last delivery": "last_delivery",
    }
    columns = {target: headers.index(source) for source, target in aliases.items() if source in headers}
    if {"product_code", "last_trade", "first_notice"} - columns.keys():
        raise CmeContractError("cme_calendar_required_columns_missing")
    observations: list[dict[str, Any]] = []
    for row in rows[header_index + 1 :]:
        if len(row) <= max(columns.values()):
            continue
        code = str(row[columns["product_code"]]).strip().upper()
        if re.fullmatch(r"GC[FGHJKMNQUVXZ]\d{2}", code) is None:
            continue
        month_number = next(
            month for month, month_code in MONTH_CODES.items() if month_code == code[2]
        )
        contract_month = date(2000 + int(code[-2:]), month_number, 1)
        first_notice = _calendar_date(row[columns["first_notice"]])
        last_trade = _calendar_date(row[columns["last_trade"]])
        if first_notice is None or last_trade is None:
            raise CmeContractError("cme_calendar_required_date_missing")
        observations.append(
            build_contract_calendar_observation(
                contract_code=code,
                contract_month=contract_month,
                first_notice_date=first_notice,
                last_trade_date=last_trade,
                first_delivery_date=(
                    _calendar_date(row[columns["first_delivery"]])
                    if "first_delivery" in columns
                    else None
                ),
                last_delivery_date=(
                    _calendar_date(row[columns["last_delivery"]])
                    if "last_delivery" in columns
                    else None
                ),
                first_observed_at=first_observed_at,
                source_document_sha256=source_document_sha256,
                source_url=source_url,
            )
        )
    if not observations:
        raise CmeContractError("cme_calendar_gc_rows_missing")
    return sorted(observations, key=lambda item: str(item["contract_month"]))


class CmePublicCalendarGateway:
    def __init__(self, *, timeout_seconds: float = 45.0) -> None:
        self._timeout = httpx.Timeout(timeout_seconds)

    def fetch_current(
        self,
        *,
        first_observed_at: datetime | str,
        client: httpx.Client | None = None,
    ) -> list[dict[str, Any]]:
        owns_client = client is None
        if client is None:
            client = httpx.Client(
                timeout=self._timeout,
                follow_redirects=True,
                headers={"User-Agent": "AIDY-Gold-Signals/Day30 official CME calendar"},
            )
        try:
            response = client.get(CME_GOLD_CALENDAR_DOWNLOAD_URL)
            if response.status_code != 200:
                raise CmeContractError(f"cme_calendar_http_{response.status_code}")
            _official_url(str(response.url))
            body = response.content
            if not body or len(body) > MAX_BULLETIN_BYTES:
                raise CmeContractError("cme_calendar_payload_size")
            try:
                import xlrd

                workbook = xlrd.open_workbook(file_contents=body)
                sheet = workbook.sheet_by_index(0)
                table: list[list[object]] = []
                for row_index in range(sheet.nrows):
                    values: list[object] = []
                    for column_index in range(sheet.ncols):
                        cell = sheet.cell(row_index, column_index)
                        if cell.ctype == xlrd.XL_CELL_DATE:
                            value: object = xlrd.xldate_as_datetime(
                                cell.value, workbook.datemode
                            )
                        else:
                            value = cell.value
                        values.append(value)
                    table.append(values)
            except Exception as exc:
                raise CmeContractError("cme_calendar_xls_extract_failed") from exc
            return parse_gold_calendar_table(
                table,
                first_observed_at=first_observed_at,
                source_document_sha256=sha256(body).hexdigest(),
                source_url=str(response.url),
            )
        finally:
            if owns_client:
                client.close()


def verify_contract_calendar_observation(record: Mapping[str, Any]) -> bool:
    body = dict(record)
    supplied = str(body.pop("calendar_digest", ""))
    if not supplied or supplied != digest(body):
        return False
    try:
        _official_url(str(body["source_url"]))
        _utc(str(body["first_observed_at"]))
        month = date.fromisoformat(str(body["contract_month"]))
        date.fromisoformat(str(body["first_notice_date"]))
        date.fromisoformat(str(body["last_trade_date"]))
    except (KeyError, TypeError, ValueError):
        return False
    return (
        body.get("calendar_version") == CME_CALENDAR_VERSION
        and body.get("contract_code")
        == f"GC{MONTH_CODES[month.month]}{str(month.year)[-2:]}"
        and re.fullmatch(r"[0-9a-f]{64}", str(body.get("source_document_sha256") or ""))
        is not None
        and body.get("pit_reconstructable") is True
        and body.get("future_derived") is False
    )


def _business_days_between(start: date, end: date) -> int:
    if end <= start:
        return 0
    days = 0
    cursor = start
    while cursor < end:
        cursor = date.fromordinal(cursor.toordinal() + 1)
        if cursor.weekday() < 5:
            days += 1
    return days


def build_contract_roll_state(
    *,
    as_of: datetime | str,
    daily_records: Iterable[Mapping[str, Any]],
    calendar_records: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    cutoff = _utc(as_of)
    selected = select_daily_contract_records_as_of(daily_records, as_of=cutoff)
    if not selected:
        result: dict[str, Any] = {
            "contract_intelligence_version": CME_CONTRACT_INTELLIGENCE_VERSION,
            "as_of_utc": cutoff.isoformat(),
            "state": "unknown_no_daily_bulletin",
            "pit_reconstructable": False,
            "intraday_open_interest_inferred": False,
            "tas_reference_state": "unknown_not_ingested",
            "predictive_edge_claimed": False,
            "trading_gate_created": False,
        }
        result["contract_state_digest"] = digest(result)
        return result

    calendars: dict[str, dict[str, Any]] = {}
    for raw in calendar_records:
        record = dict(raw)
        if not verify_contract_calendar_observation(record):
            raise ValueError("Invalid CME contract calendar observation.")
        observed = _utc(str(record["first_observed_at"]))
        if observed > cutoff:
            continue
        code = str(record["contract_code"])
        current = calendars.get(code)
        if current is None or _utc(str(current["first_observed_at"])) < observed:
            calendars[code] = record

    trade_date = date.fromisoformat(str(selected[0]["trade_date"]))
    nearest = min(selected, key=lambda item: str(item["contract_month"]))
    later_than_nearest = [
        item for item in selected if str(item["contract_month"]) > str(nearest["contract_month"])
    ]
    second = None if not later_than_nearest else min(
        later_than_nearest, key=lambda item: str(item["contract_month"])
    )
    leader = max(
        selected,
        key=lambda item: (int(item["open_interest"]), str(item["contract_month"])),
    )
    calendar = calendars.get(str(nearest["contract_code"]))
    ratio: str | None = None
    basis_bps: str | None = None
    if second is not None and int(nearest["open_interest"]) > 0:
        ratio = _fmt(
            Decimal(int(second["open_interest"])) / Decimal(int(nearest["open_interest"]))
        )
        basis_bps = _fmt(
            (_decimal(second["settlement"], name="second settlement")
             / _decimal(nearest["settlement"], name="nearest settlement")
             - Decimal(1))
            * Decimal(10_000)
        )

    days_to_first_notice: int | None = None
    if calendar is None:
        roll_state = "unknown_contract_calendar"
    else:
        first_notice = date.fromisoformat(str(calendar["first_notice_date"]))
        days_to_first_notice = _business_days_between(trade_date, first_notice)
        ratio_value = None if ratio is None else Decimal(ratio)
        near_notice = first_notice <= trade_date or days_to_first_notice <= ROLL_WINDOW_BUSINESS_DAYS
        leader_shifted = str(leader["contract_code"]) != str(nearest["contract_code"])
        immediate_transition = ratio_value is not None and ratio_value >= Decimal("0.8")
        if first_notice <= trade_date and leader_shifted:
            roll_state = "post_first_notice_active_shifted"
        elif first_notice <= trade_date:
            roll_state = "delivery_month_after_first_notice"
        elif near_notice and (leader_shifted or immediate_transition):
            roll_state = "calendar_and_liquidity_roll_window"
        elif near_notice:
            roll_state = "calendar_roll_window"
        elif leader_shifted or immediate_transition:
            roll_state = "liquidity_lead_shifted"
        else:
            roll_state = "clear"

    result = {
        "contract_intelligence_version": CME_CONTRACT_INTELLIGENCE_VERSION,
        "daily_record_version": CME_DAILY_RECORD_VERSION,
        "calendar_version": CME_CALENDAR_VERSION,
        "as_of_utc": cutoff.isoformat(),
        "state": "known" if calendar is not None else "partial_unknown_calendar",
        "trade_date": trade_date.isoformat(),
        "open_interest_frequency": "daily_t_plus_1",
        "intraday_open_interest_inferred": False,
        "nearest_delivery_contract": str(nearest["contract_code"]),
        "front_month_contract": str(nearest["contract_code"]),
        "second_listed_contract": None if second is None else str(second["contract_code"]),
        "open_interest_lead_contract": str(leader["contract_code"]),
        "active_contract": str(leader["contract_code"]),
        "active_contract_rule": "maximum_daily_open_interest_then_later_contract_tiebreak",
        "leader_open_interest": int(leader["open_interest"]),
        "front_month_open_interest": int(nearest["open_interest"]),
        "second_listed_open_interest": None if second is None else int(second["open_interest"]),
        "second_to_front_oi_ratio": ratio,
        "second_minus_front_settlement_bps": basis_bps,
        "days_to_first_notice_business": days_to_first_notice,
        "roll_state": roll_state,
        "roll_window_business_days": ROLL_WINDOW_BUSINESS_DAYS,
        "record_digests": sorted(str(item["record_digest"]) for item in selected),
        "calendar_digest": None if calendar is None else calendar["calendar_digest"],
        "pit_reconstructable": calendar is not None,
        "tas_reference_state": "unknown_not_ingested",
        "trader_intent_inferred": False,
        "predictive_edge_claimed": False,
        "trading_gate_created": False,
    }
    result["contract_state_digest"] = digest(result)
    return result


def verify_contract_roll_state(state: Mapping[str, Any]) -> bool:
    body = dict(state)
    supplied = str(body.pop("contract_state_digest", ""))
    return (
        bool(supplied)
        and supplied == digest(body)
        and body.get("contract_intelligence_version") == CME_CONTRACT_INTELLIGENCE_VERSION
        and body.get("intraday_open_interest_inferred") is False
        and body.get("predictive_edge_claimed") is False
        and body.get("trading_gate_created") is False
    )


def _distribution(values: list[Decimal]) -> dict[str, str | None]:
    if not values:
        return {"min": None, "median": None, "max": None}
    ordered = sorted(values)
    return {
        "min": _fmt(ordered[0]),
        "median": _fmt(median(ordered)),
        "max": _fmt(ordered[-1]),
    }


def _quadrant(price_change: Decimal, oi_change: int) -> str | None:
    if price_change == 0 or oi_change == 0:
        return None
    if price_change > 0 and oi_change > 0:
        return "price_up_oi_up"
    if price_change < 0 and oi_change > 0:
        return "price_down_oi_up"
    if price_change > 0 and oi_change < 0:
        return "price_up_oi_down"
    return "price_down_oi_down"


def _j6_horizon_summary(rows: list[dict[str, Any]], horizon: int) -> dict[str, Any]:
    known = [
        (item, Decimal(str(item["next_return_bps"][str(horizon)])))
        for item in rows
        if item["next_return_bps"][str(horizon)] is not None
    ]
    persistence = [
        value
        for item, value in known
        if (Decimal(item["price_change_bps"]) > 0 and value > 0)
        or (Decimal(item["price_change_bps"]) < 0 and value < 0)
    ]
    return {
        "known_n": len(known),
        "state": (
            "descriptive"
            if len(known) >= MIN_J6_EPISODES_PER_QUADRANT_HORIZON
            else "insufficient"
        ),
        "return_bps_distribution": _distribution([value for _, value in known]),
        "directional_persistence_n": len(persistence),
        "directional_persistence_rate": (
            None if not known else _fmt(Decimal(len(persistence)) / Decimal(len(known)))
        ),
    }


def run_j6_descriptive(episodes: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    forbidden = {"pnl", "profit", "loss", "win_rate", "trade_result", "trader_intent"}
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    neutral_excluded = 0
    for raw in episodes:
        if forbidden.intersection(raw):
            raise ValueError("J6 cannot use trade P/L, win/loss or inferred trader intent.")
        item = dict(raw)
        trade_date = date.fromisoformat(str(item["trade_date"]))
        contract_code = str(item["contract_code"])
        price_change = _decimal(item["price_change_bps"], name="price change")
        oi_change = int(item["open_interest_change"])
        trend_state = str(item.get("trend_state") or "")
        epoch = str(item.get("market_structure_epoch") or "")
        roll_state = str(item.get("roll_state") or "")
        if not trend_state or not epoch or not roll_state:
            raise ValueError("J6 requires trend, market-structure epoch and roll state.")
        horizon_returns = dict(item.get("next_return_bps") or {})
        normalized_returns: dict[str, str | None] = {}
        for horizon in J6_HORIZONS:
            value = horizon_returns.get(str(horizon), horizon_returns.get(horizon))
            normalized_returns[str(horizon)] = (
                None if value is None else _fmt(_decimal(value, name="future return"))
            )
        normalized = {
            "trade_date": trade_date.isoformat(),
            "contract_code": contract_code,
            "price_change_bps": _fmt(price_change),
            "open_interest_change": oi_change,
            "trend_state": trend_state,
            "market_structure_epoch": epoch,
            "roll_state": roll_state,
            "next_return_bps": normalized_returns,
        }
        key = (trade_date.isoformat(), contract_code)
        if key in unique and unique[key] != normalized:
            raise ValueError("Conflicting rows share a J6 independent daily episode identity.")
        unique[key] = normalized

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in unique.values():
        quadrant = _quadrant(Decimal(item["price_change_bps"]), int(item["open_interest_change"]))
        if quadrant is None:
            neutral_excluded += 1
            continue
        grouped[quadrant].append(item)

    results: dict[str, Any] = {}
    for quadrant in J6_QUADRANTS:
        rows = sorted(grouped[quadrant], key=lambda item: (item["trade_date"], item["contract_code"]))
        by_horizon = {
            str(horizon): _j6_horizon_summary(rows, horizon) for horizon in J6_HORIZONS
        }
        trend_counts: dict[str, int] = defaultdict(int)
        roll_counts: dict[str, int] = defaultdict(int)
        epoch_counts: dict[str, int] = defaultdict(int)
        for item in rows:
            trend_counts[item["trend_state"]] += 1
            roll_counts[item["roll_state"]] += 1
            epoch_counts[item["market_structure_epoch"]] += 1
        trend_strata = {
            trend_state: {
                "independent_daily_episode_n": sum(
                    item["trend_state"] == trend_state for item in rows
                ),
                "horizons": {
                    str(horizon): _j6_horizon_summary(
                        [item for item in rows if item["trend_state"] == trend_state], horizon
                    )
                    for horizon in J6_HORIZONS
                },
            }
            for trend_state in sorted(trend_counts)
        }
        results[quadrant] = {
            "independent_daily_episode_n": len(rows),
            "trend_state_counts": dict(sorted(trend_counts.items())),
            "roll_state_counts": dict(sorted(roll_counts.items())),
            "market_structure_epoch_counts": dict(sorted(epoch_counts.items())),
            "trend_strata": trend_strata,
            "horizons": by_horizon,
        }

    study: dict[str, Any] = {
        "study_version": J6_VERSION,
        "descriptive_only": True,
        "independent_unit": "trade_date_x_contract_code",
        "quadrants": list(J6_QUADRANTS),
        "horizons_trading_days": list(J6_HORIZONS),
        "preregistered_min_n_per_quadrant_horizon": MIN_J6_EPISODES_PER_QUADRANT_HORIZON,
        "independent_daily_episode_count": len(unique),
        "neutral_episode_count_excluded": neutral_excluded,
        "quadrant_results": results,
        "trend_control_reported": True,
        "roll_state_reported": True,
        "market_structure_epoch_reported": True,
        "trade_pnl_used": False,
        "trader_intent_inferred": False,
        "predictive_edge_claimed": False,
        "trading_gate_created": False,
        "null_or_insufficient_result_allowed": True,
    }
    study["study_digest"] = digest(study)
    return study


def verify_j6_study(study: Mapping[str, Any]) -> bool:
    body = dict(study)
    supplied = str(body.pop("study_digest", ""))
    return (
        bool(supplied)
        and supplied == digest(body)
        and body.get("study_version") == J6_VERSION
        and body.get("descriptive_only") is True
        and body.get("trade_pnl_used") is False
        and body.get("predictive_edge_claimed") is False
        and body.get("trading_gate_created") is False
    )
