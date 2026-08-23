from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from email.utils import parsedate_to_datetime
from hashlib import sha256
from itertools import pairwise
from typing import Any
from urllib.parse import urlparse

import httpx

VOLATILITY_INTELLIGENCE_VERSION = "aidy_gold_volatility_intelligence_v1"
GVZ_RECORD_VERSION = "aidy_cboe_gvz_observation_v1"
J7_J8_FOUNDATION_VERSION = "aidy_j7_j8_volatility_foundation_v1"

CBOE_GVZ_HISTORY_URL = (
    "https://cdn.cboe.com/api/global/us_indices/daily_prices/GVZ_History.csv"
)
CBOE_GVZ_DASHBOARD_URL = "https://www.cboe.com/us/indices/dashboard/gvz/"
CBOE_GVZ_METHODOLOGY_NOTICE_URL = (
    "https://cdn.cboe.com/resources/release_notes/2025/"
    "Modifications-to-the-Strike-Selection-in-Volatility-Index-Calculations.pdf"
)
CBOE_ALLOWED_HOSTS = ("cboe.com", "www.cboe.com", "cdn.cboe.com")

RV_HORIZONS_TRADING_DAYS = (5, 10, 21)
GVZ_HORIZON_CALENDAR_DAYS = 30
VOL_OF_VOL_WINDOW_DAYS = 21
MIN_INTRADAY_RETURNS_PER_DAY = 300
MAX_GVZ_BYTES = 2_000_000

_TRADING_DAYS_PER_YEAR = Decimal(252)
_ONE_HUNDRED = Decimal(100)
_PI_OVER_TWO = Decimal("1.57079632679489661923132169164")
_OUTPUT_SCALE = Decimal("0.000000000001")


class VolatilityIntelligenceError(RuntimeError):
    pass


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Volatility evidence timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _decimal(value: object, *, name: str, positive: bool = False) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{name} must be a finite decimal.")
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a finite decimal.") from exc
    if not parsed.is_finite() or (positive and parsed <= 0):
        raise ValueError(f"{name} must be a finite{' positive' if positive else ''} decimal.")
    return parsed


def _fmt(value: Decimal | None) -> str | None:
    if value is None:
        return None
    with localcontext() as ctx:
        ctx.prec = 50
        rounded = value.quantize(_OUTPUT_SCALE)
    if rounded == 0:
        return "0"
    return format(rounded, "f").rstrip("0").rstrip(".")


def _official_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in CBOE_ALLOWED_HOSTS:
        raise ValueError("Cboe source URL is not on the official HTTPS allowlist.")
    return url


def _parse_date(value: str) -> date:
    raw = value.strip()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        pass
    try:
        return datetime.strptime(raw, "%m/%d/%Y").replace(tzinfo=UTC).date()
    except ValueError:
        pass
    raise VolatilityIntelligenceError("cboe_gvz_invalid_observation_date")


def _record_body(record: Mapping[str, Any]) -> dict[str, Any]:
    body = dict(record)
    body.pop("record_digest", None)
    return body


def parse_gvz_history_csv(
    payload: bytes,
    *,
    first_observed_at: datetime | str,
    source_url: str = CBOE_GVZ_HISTORY_URL,
    final_url: str | None = None,
    source_last_modified_at: datetime | str | None = None,
) -> list[dict[str, Any]]:
    if not payload or len(payload) > MAX_GVZ_BYTES:
        raise VolatilityIntelligenceError("cboe_gvz_invalid_payload_size")
    observed = _utc(first_observed_at)
    requested_url = _official_url(source_url)
    resolved_url = _official_url(final_url or source_url)
    modified = None if source_last_modified_at is None else _utc(source_last_modified_at)
    snapshot_sha = sha256(payload).hexdigest()
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise VolatilityIntelligenceError("cboe_gvz_csv_not_utf8") from exc
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise VolatilityIntelligenceError("cboe_gvz_csv_header_missing")
    names = {str(name).strip().upper(): str(name) for name in reader.fieldnames}
    if "DATE" not in names or "GVZ" not in names:
        raise VolatilityIntelligenceError("cboe_gvz_csv_required_columns_missing")
    rows: list[dict[str, Any]] = []
    seen: set[date] = set()
    for raw in reader:
        if not any(str(value or "").strip() for value in raw.values()):
            continue
        observed_date = _parse_date(str(raw.get(names["DATE"]) or ""))
        if observed_date in seen:
            raise VolatilityIntelligenceError("cboe_gvz_duplicate_observation_date")
        seen.add(observed_date)
        value = _decimal(raw.get(names["GVZ"]), name="GVZ value", positive=True)
        record: dict[str, Any] = {
            "gvz_record_version": GVZ_RECORD_VERSION,
            "index_symbol": "GVZ",
            "index_name": "Cboe Gold ETF Volatility Index",
            "underlying_proxy": "SPDR_Gold_Shares_ETF_GLD",
            "implied_horizon_calendar_days": GVZ_HORIZON_CALENDAR_DAYS,
            "unit": "annualized_percent",
            "observation_date": observed_date.isoformat(),
            "value": _fmt(value),
            "source_url": requested_url,
            "final_url": resolved_url,
            "source_snapshot_sha256": snapshot_sha,
            "source_last_modified_at": None if modified is None else modified.isoformat(),
            "first_observed_at": observed.isoformat(),
            "historical_release_time_known": False,
            "pit_reconstructable_from": observed.isoformat(),
            "pit_reconstructable": True,
            "official_source": True,
            "authentication_required": False,
            "paid_api_used": False,
        }
        record["record_digest"] = digest(record)
        rows.append(record)
    rows.sort(key=lambda item: str(item["observation_date"]))
    if not rows:
        raise VolatilityIntelligenceError("cboe_gvz_csv_no_rows")
    return rows


def verify_gvz_record(record: Mapping[str, Any]) -> bool:
    try:
        if record.get("gvz_record_version") != GVZ_RECORD_VERSION:
            return False
        if record.get("index_symbol") != "GVZ":
            return False
        if record.get("underlying_proxy") != "SPDR_Gold_Shares_ETF_GLD":
            return False
        if record.get("implied_horizon_calendar_days") != GVZ_HORIZON_CALENDAR_DAYS:
            return False
        if record.get("historical_release_time_known") is not False:
            return False
        if record.get("pit_reconstructable") is not True:
            return False
        if record.get("authentication_required") is not False:
            return False
        if record.get("paid_api_used") is not False:
            return False
        _official_url(str(record["source_url"]))
        _official_url(str(record["final_url"]))
        date.fromisoformat(str(record["observation_date"]))
        observed = _utc(str(record["first_observed_at"]))
        if _utc(str(record["pit_reconstructable_from"])) != observed:
            return False
        _decimal(record["value"], name="GVZ value", positive=True)
        supplied = str(record.get("record_digest") or "")
        return bool(supplied) and supplied == digest(_record_body(record))
    except (KeyError, TypeError, ValueError):
        return False


def select_gvz_as_of(
    records: Iterable[Mapping[str, Any]], *, as_of: datetime | str
) -> dict[str, Any] | None:
    cutoff = _utc(as_of)
    eligible: list[Mapping[str, Any]] = []
    for record in records:
        if not verify_gvz_record(record):
            raise ValueError("Invalid GVZ record entered point-in-time selection.")
        if _utc(str(record["first_observed_at"])) > cutoff:
            continue
        if date.fromisoformat(str(record["observation_date"])) > cutoff.date():
            continue
        eligible.append(record)
    if not eligible:
        return None
    selected = max(
        eligible,
        key=lambda item: (
            str(item["observation_date"]),
            str(item["first_observed_at"]),
            str(item["record_digest"]),
        ),
    )
    return dict(selected)


def select_gvz_research_anchor(
    records: Iterable[Mapping[str, Any]], *, anchor_date: date | str
) -> dict[str, Any] | None:
    anchor = date.fromisoformat(anchor_date) if isinstance(anchor_date, str) else anchor_date
    eligible = []
    for record in records:
        if not verify_gvz_record(record):
            raise ValueError("Invalid GVZ record entered research selection.")
        if date.fromisoformat(str(record["observation_date"])) <= anchor:
            eligible.append(record)
    if not eligible:
        return None
    return dict(max(eligible, key=lambda item: str(item["observation_date"])))


class CboeGvzGateway:
    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport

    def fetch_history(
        self, *, first_observed_at: datetime | str
    ) -> list[dict[str, Any]]:
        headers = {
            "accept": "text/csv,*/*;q=0.8",
            "user-agent": "AIDY-Signals/1.0 public-research-contact",
        }
        try:
            with httpx.Client(
                follow_redirects=True,
                timeout=httpx.Timeout(30.0),
                transport=self._transport,
            ) as client:
                response = client.get(CBOE_GVZ_HISTORY_URL, headers=headers)
        except httpx.TimeoutException as exc:
            raise VolatilityIntelligenceError("cboe_gvz_timeout") from exc
        except httpx.HTTPError as exc:
            raise VolatilityIntelligenceError("cboe_gvz_transport_error") from exc
        if response.status_code != 200:
            raise VolatilityIntelligenceError(f"cboe_gvz_http_{response.status_code}")
        _official_url(str(response.url))
        declared = response.headers.get("content-length", "").strip()
        if declared.isdigit() and int(declared) > MAX_GVZ_BYTES:
            raise VolatilityIntelligenceError("cboe_gvz_payload_too_large")
        body = response.content
        if len(body) > MAX_GVZ_BYTES:
            raise VolatilityIntelligenceError("cboe_gvz_payload_too_large")
        modified = None
        raw_modified = response.headers.get("last-modified")
        if raw_modified:
            try:
                modified = parsedate_to_datetime(raw_modified)
            except (TypeError, ValueError) as exc:
                raise VolatilityIntelligenceError("cboe_gvz_invalid_last_modified") from exc
            if modified.tzinfo is None:
                modified = modified.replace(tzinfo=UTC)
        return parse_gvz_history_csv(
            body,
            first_observed_at=first_observed_at,
            source_url=CBOE_GVZ_HISTORY_URL,
            final_url=str(response.url),
            source_last_modified_at=modified,
        )


def _candle_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    timeframe: str,
    anchor: date,
    mode: str,
) -> list[tuple[datetime, Decimal]]:
    result: list[tuple[datetime, Decimal]] = []
    seen: set[datetime] = set()
    for row in rows:
        if str(row.get("symbol") or "") != "XAUUSD":
            continue
        if str(row.get("timeframe") or "").upper() != timeframe:
            continue
        if mode == "retrospective_research":
            if row.get("pit_eligible") is not False:
                raise ValueError("Retrospective volatility rows must be pit_eligible=false.")
            if str(row.get("provenance_class") or "") != "retrospective_history":
                raise ValueError("Retrospective volatility rows require retrospective provenance.")
        elif mode == "pit":
            if row.get("pit_eligible") is False or str(row.get("provenance_class")) == (
                "retrospective_history"
            ):
                raise ValueError("Retrospective candles cannot enter PIT volatility state.")
        else:
            raise ValueError("Volatility mode must be pit or retrospective_research.")
        timestamp = _utc(str(row["open_time_utc"]))
        if timestamp.date() > anchor:
            continue
        if timestamp in seen:
            raise ValueError("Duplicate logical candles entered volatility state.")
        seen.add(timestamp)
        result.append((timestamp, _decimal(row["close"], name="candle close", positive=True)))
    result.sort(key=lambda item: item[0])
    return result


def _log_return(right: Decimal, left: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 50
        return (right / left).ln()


def _annualized_rv(returns: list[Decimal]) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 50
        mean_square = sum((item * item for item in returns), Decimal(0)) / Decimal(
            len(returns)
        )
        return (mean_square * _TRADING_DAYS_PER_YEAR).sqrt() * _ONE_HUNDRED


def _realized_term_structure(
    daily: list[tuple[datetime, Decimal]],
) -> dict[int, Decimal | None]:
    result: dict[int, Decimal | None] = {}
    for horizon in RV_HORIZONS_TRADING_DAYS:
        if len(daily) < horizon + 1:
            result[horizon] = None
            continue
        sample = daily[-(horizon + 1) :]
        returns = [_log_return(right[1], left[1]) for left, right in pairwise(sample)]
        result[horizon] = _annualized_rv(returns)
    return result


def _daily_intraday_variation(
    intraday: list[tuple[datetime, Decimal]],
) -> list[dict[str, Any]]:
    grouped: dict[date, list[tuple[datetime, Decimal]]] = defaultdict(list)
    for item in intraday:
        grouped[item[0].date()].append(item)
    result: list[dict[str, Any]] = []
    for day in sorted(grouped):
        sample = sorted(grouped[day], key=lambda item: item[0])
        returns = [
            _log_return(right[1], left[1])
            for left, right in pairwise(sample)
            if right[0] - left[0] <= timedelta(seconds=90)
        ]
        if len(returns) < MIN_INTRADAY_RETURNS_PER_DAY:
            continue
        with localcontext() as ctx:
            ctx.prec = 50
            realized = sum((item * item for item in returns), Decimal(0))
            bipower = _PI_OVER_TWO * sum(
                (abs(left) * abs(right) for left, right in pairwise(returns)), Decimal(0)
            )
            continuous = min(realized, bipower)
            jump = max(realized - continuous, Decimal(0))
            jump_share = None if realized == 0 else jump / realized
            annualized = (realized * _TRADING_DAYS_PER_YEAR).sqrt() * _ONE_HUNDRED
        result.append(
            {
                "observation_date": day.isoformat(),
                "return_count": len(returns),
                "realized_variation": realized,
                "continuous_variation": continuous,
                "jump_variation": jump,
                "jump_share": jump_share,
                "annualized_realized_vol_percent": annualized,
            }
        )
    return result


def _sample_std(values: list[Decimal]) -> Decimal | None:
    if len(values) < 2:
        return None
    with localcontext() as ctx:
        ctx.prec = 50
        mean = sum(values, Decimal(0)) / Decimal(len(values))
        variance = sum(((item - mean) ** 2 for item in values), Decimal(0)) / Decimal(
            len(values) - 1
        )
        return variance.sqrt()


def _state_body(state: Mapping[str, Any]) -> dict[str, Any]:
    body = dict(state)
    body.pop("volatility_state_digest", None)
    return body


def build_volatility_state(
    *,
    as_of: datetime | str,
    gvz_record: Mapping[str, Any] | None,
    daily_candles: Iterable[Mapping[str, Any]],
    intraday_candles: Iterable[Mapping[str, Any]],
    mode: str,
    anchor_date: date | str | None = None,
) -> dict[str, Any]:
    cutoff = _utc(as_of)
    anchor = (
        cutoff.date()
        if anchor_date is None
        else (date.fromisoformat(anchor_date) if isinstance(anchor_date, str) else anchor_date)
    )
    if mode not in {"pit", "retrospective_research"}:
        raise ValueError("Volatility mode must be pit or retrospective_research.")
    if gvz_record is not None:
        if not verify_gvz_record(gvz_record):
            raise ValueError("Invalid GVZ record entered volatility state.")
        if mode == "pit" and _utc(str(gvz_record["first_observed_at"])) > cutoff:
            raise ValueError("GVZ record was not known at the requested point in time.")
        if date.fromisoformat(str(gvz_record["observation_date"])) > anchor:
            raise ValueError("GVZ observation is after the volatility anchor date.")
    daily = _candle_rows(daily_candles, timeframe="D1", anchor=anchor, mode=mode)
    intraday = _candle_rows(intraday_candles, timeframe="M1", anchor=anchor, mode=mode)
    term = _realized_term_structure(daily)
    variations = _daily_intraday_variation(intraday)
    latest_variation = variations[-1] if variations else None
    vov_values = [
        item["annualized_realized_vol_percent"]
        for item in variations[-VOL_OF_VOL_WINDOW_DAYS:]
    ]
    vol_of_vol = (
        _sample_std(vov_values)
        if len(vov_values) == VOL_OF_VOL_WINDOW_DAYS
        else None
    )
    gvz_value = None if gvz_record is None else _decimal(
        gvz_record["value"], name="GVZ value", positive=True
    )
    comparable_rv = term[21]
    spread = None if gvz_value is None or comparable_rv is None else gvz_value - comparable_rv
    if spread is None:
        spread_state = "unknown_missing_iv_or_comparable_rv"
    elif spread > 0:
        spread_state = "implied_above_realized"
    elif spread < 0:
        spread_state = "implied_below_realized"
    else:
        spread_state = "implied_equal_realized"
    if term[5] is None or term[21] is None:
        term_state = "unknown_insufficient_daily_history"
    elif term[5] > term[21]:
        term_state = "short_above_long"
    elif term[5] < term[21]:
        term_state = "short_below_long"
    else:
        term_state = "flat"
    jump_share = None if latest_variation is None else latest_variation["jump_share"]
    if jump_share is None:
        jump_state = "unknown_insufficient_intraday_coverage"
    elif jump_share >= Decimal("0.5"):
        jump_state = "jump_dominant"
    else:
        jump_state = "continuous_dominant"
    known_components = sum(
        (
            gvz_record is not None,
            comparable_rv is not None,
            latest_variation is not None,
            vol_of_vol is not None,
        )
    )
    overall = "known" if known_components == 4 else ("partial" if known_components else "unknown")
    evaluation_only = mode == "retrospective_research"
    state: dict[str, Any] = {
        "volatility_intelligence_version": VOLATILITY_INTELLIGENCE_VERSION,
        "as_of_utc": cutoff.isoformat(),
        "anchor_date": anchor.isoformat(),
        "mode": mode,
        "state": overall,
        "gvz": {
            "state": "known" if gvz_record is not None else "unknown",
            "record_digest": None if gvz_record is None else gvz_record["record_digest"],
            "observation_date": None if gvz_record is None else gvz_record["observation_date"],
            "value_annualized_percent": _fmt(gvz_value),
            "implied_horizon_calendar_days": GVZ_HORIZON_CALENDAR_DAYS,
            "underlying_proxy": "SPDR_Gold_Shares_ETF_GLD",
        },
        "realized_volatility": {
            "state": "known" if comparable_rv is not None else "unknown_insufficient_daily_history",
            "annualization_trading_days": 252,
            "estimator": "root_mean_square_log_returns",
            "horizons_trading_days": list(RV_HORIZONS_TRADING_DAYS),
            "annualized_percent": {str(key): _fmt(value) for key, value in term.items()},
            "term_structure_state": term_state,
        },
        "iv_minus_rv": {
            "state": spread_state,
            "spread_percentage_points": _fmt(spread),
            "iv_horizon_calendar_days": GVZ_HORIZON_CALENDAR_DAYS,
            "rv_horizon_trading_days": 21,
            "cross_instrument_proxy": True,
            "iv_underlying": "GLD",
            "rv_underlying": "XAUUSD",
            "comparable_with_caveats": True,
        },
        "jump_continuous": {
            "state": jump_state,
            "estimator": "realized_variation_minus_bipower_variation",
            "minimum_intraday_returns_per_day": MIN_INTRADAY_RETURNS_PER_DAY,
            "known_daily_decomposition_count": len(variations),
            "latest_observation_date": (
                None if latest_variation is None else latest_variation["observation_date"]
            ),
            "latest_return_count": (
                None if latest_variation is None else latest_variation["return_count"]
            ),
            "realized_variation": (
                None if latest_variation is None else _fmt(latest_variation["realized_variation"])
            ),
            "continuous_variation": (
                None
                if latest_variation is None
                else _fmt(latest_variation["continuous_variation"])
            ),
            "jump_variation": (
                None if latest_variation is None else _fmt(latest_variation["jump_variation"])
            ),
            "jump_share": _fmt(jump_share),
        },
        "vol_of_vol": {
            "state": "known" if vol_of_vol is not None else "unknown_insufficient_history",
            "window_trading_days": VOL_OF_VOL_WINDOW_DAYS,
            "estimator": "sample_std_of_annualized_daily_realized_vol_percent",
            "annualized_vol_dispersion_percent": _fmt(vol_of_vol),
        },
        "evaluation_only": evaluation_only,
        "decision_input_allowed": not evaluation_only,
        "pit_reconstructable": not evaluation_only,
        "retrospective_history_included": evaluation_only,
        "gvz_proxy_not_direct_gold_options_iv": True,
        "cme_cvol_state": "deferred_pending_evidence_and_owner_approval",
        "formal_j7_j8_test_run": False,
        "predictive_edge_claimed": False,
        "trading_gate_created": False,
        "super_signals_modified": False,
    }
    state["volatility_state_digest"] = digest(state)
    return state


def verify_volatility_state(state: Mapping[str, Any]) -> bool:
    try:
        if state.get("volatility_intelligence_version") != VOLATILITY_INTELLIGENCE_VERSION:
            return False
        if state.get("mode") not in {"pit", "retrospective_research"}:
            return False
        evaluation_only = state.get("mode") == "retrospective_research"
        if state.get("evaluation_only") is not evaluation_only:
            return False
        if state.get("decision_input_allowed") is not (not evaluation_only):
            return False
        if state.get("pit_reconstructable") is not (not evaluation_only):
            return False
        if state.get("formal_j7_j8_test_run") is not False:
            return False
        if state.get("predictive_edge_claimed") is not False:
            return False
        if state.get("trading_gate_created") is not False:
            return False
        if state.get("super_signals_modified") is not False:
            return False
        iv_rv = state["iv_minus_rv"]
        if iv_rv.get("cross_instrument_proxy") is not True:
            return False
        if iv_rv.get("iv_horizon_calendar_days") != 30:
            return False
        if iv_rv.get("rv_horizon_trading_days") != 21:
            return False
        supplied = str(state.get("volatility_state_digest") or "")
        return bool(supplied) and supplied == digest(_state_body(state))
    except (KeyError, TypeError, ValueError):
        return False


def build_j7_j8_foundation() -> dict[str, Any]:
    foundation: dict[str, Any] = {
        "foundation_version": J7_J8_FOUNDATION_VERSION,
        "status": "data_foundation_only",
        "formal_test_day": 43,
        "j7": {
            "name": "implied_volatility_regime_value",
            "null_hypothesis": (
                "GVZ state adds no outcome-dispersion information beyond the frozen realized-"
                "volatility state."
            ),
            "inputs_frozen": ["gvz_30_calendar_day_gld_proxy", "xauusd_rv_21_trading_day"],
            "formal_test_run": False,
        },
        "j8": {
            "name": "jump_vs_continuous_volatility",
            "null_hypothesis": (
                "Jump-dominant and continuous-dominant states do not differ in subsequent "
                "outcome dispersion after frozen controls."
            ),
            "inputs_frozen": ["realized_variation", "bipower_variation", "jump_share"],
            "formal_test_run": False,
        },
        "episode_independence_required": True,
        "chronological_split_required": True,
        "insufficient_or_null_result_allowed": True,
        "threshold_tuning_on_evaluation_set_allowed": False,
        "predictive_edge_claimed": False,
        "trading_gate_created": False,
    }
    foundation["foundation_digest"] = digest(foundation)
    return foundation


def verify_j7_j8_foundation(foundation: Mapping[str, Any]) -> bool:
    body = dict(foundation)
    supplied = str(body.pop("foundation_digest", ""))
    return bool(supplied) and supplied == digest(body) and all(
        (
            foundation.get("foundation_version") == J7_J8_FOUNDATION_VERSION,
            foundation.get("status") == "data_foundation_only",
            foundation.get("predictive_edge_claimed") is False,
            foundation.get("trading_gate_created") is False,
            foundation.get("threshold_tuning_on_evaluation_set_allowed") is False,
        )
    )
