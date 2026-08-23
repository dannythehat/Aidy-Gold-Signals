from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx

DAY28_VERSION = "aidy_macro_vintages_v1"
RATES_DECOMPOSITION_VERSION = "aidy_us_rates_decomposition_v1"
REVISION_INTELLIGENCE_VERSION = "aidy_macro_revision_intelligence_v1"
SOURCE_ALFRED = "fred_alfred"
ALFRED_BASE = "https://alfred.stlouisfed.org/graph/alfredgraph.csv"

SERIES_DGS2 = "DGS2"
SERIES_DGS10 = "DGS10"
SERIES_DFII10 = "DFII10"
SERIES_T10YIE = "T10YIE"
SERIES_CPI = "CPIAUCSL"
SERIES = (SERIES_DGS2, SERIES_DGS10, SERIES_DFII10, SERIES_T10YIE, SERIES_CPI)

SERIES_ROLES = {
    SERIES_DGS2: "nominal_2y",
    SERIES_DGS10: "nominal_10y",
    SERIES_DFII10: "real_10y",
    SERIES_T10YIE: "official_breakeven_reference_only",
    SERIES_CPI: "inflation_revision_series",
}

PUBLICATION_TIME_PRECISION = "date_only"
EVIDENCE_FAMILY = "us_rates_decomposition"
REAL_YIELD_ROLE = "context_regime_only"
REAL_YIELD_DIRECTIONAL_INFLUENCE = "provisional_unvalidated_j12"

_MAX_SOURCE_BYTES = 2_000_000
_ALLOWED_HOST = "alfred.stlouisfed.org"


class MacroVintageError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Day 28 timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _decimal(value: Any, *, name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a finite decimal.") from exc
    if not parsed.is_finite():
        raise ValueError(f"{name} must be a finite decimal.")
    return parsed


def _fmt(value: Decimal | float | None) -> str | None:
    if value is None:
        return None
    dec = value if isinstance(value, Decimal) else Decimal(str(value))
    with localcontext() as ctx:
        ctx.prec = 34
        quantized = dec.quantize(Decimal("0.000001"))
    text = format(quantized, "f").rstrip("0").rstrip(".")
    return text or "0"


def conservative_available_after(vintage_date: date) -> datetime:
    return datetime.combine(vintage_date + timedelta(days=1), datetime.min.time(), tzinfo=UTC)


def alfred_url(
    *,
    series_id: str,
    vintage_date: date,
    observation_start: date,
    observation_end: date,
) -> str:
    if series_id not in SERIES:
        raise ValueError(f"Unsupported Day 28 series: {series_id}")
    if observation_end < observation_start:
        raise ValueError("observation_end must not precede observation_start.")
    query = urlencode(
        {
            "id": series_id,
            "vintage_date": vintage_date.isoformat(),
            "cosd": observation_start.isoformat(),
            "coed": observation_end.isoformat(),
        }
    )
    return f"{ALFRED_BASE}?{query}"


@dataclass(frozen=True, slots=True)
class AlfredSnapshot:
    series_id: str
    vintage_date: date
    observation_start: date
    observation_end: date
    values: tuple[tuple[date, str | None], ...]
    source_url: str
    source_sha256: str

    @property
    def snapshot_digest(self) -> str:
        return _digest(
            {
                "series_id": self.series_id,
                "vintage_date": self.vintage_date.isoformat(),
                "observation_start": self.observation_start.isoformat(),
                "observation_end": self.observation_end.isoformat(),
                "values": [(day.isoformat(), value) for day, value in self.values],
                "source_url": self.source_url,
                "source_sha256": self.source_sha256,
            }
        )

    def value_map(self) -> dict[date, str | None]:
        return dict(self.values)


def parse_alfred_csv(
    raw: bytes,
    *,
    series_id: str,
    vintage_date: date,
    observation_start: date,
    observation_end: date,
    source_url: str,
) -> AlfredSnapshot:
    if series_id not in SERIES:
        raise ValueError(f"Unsupported Day 28 series: {series_id}")
    if not raw or len(raw) > _MAX_SOURCE_BYTES:
        raise MacroVintageError("alfred_payload_size")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise MacroVintageError("alfred_invalid_utf8") from exc
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise MacroVintageError("alfred_empty_csv") from exc
    if len(header) < 2 or header[0].strip().lower() not in {"observation_date", "date"}:
        raise MacroVintageError("alfred_unexpected_header")

    rows: list[tuple[date, str | None]] = []
    for line_number, row in enumerate(reader, start=2):
        if not row:
            continue
        if len(row) < 2:
            raise MacroVintageError(f"alfred_short_row_{line_number}")
        try:
            observation_date = date.fromisoformat(row[0].strip())
        except ValueError as exc:
            raise MacroVintageError(f"alfred_invalid_date_{line_number}") from exc
        if observation_date < observation_start or observation_date > observation_end:
            continue
        raw_value = row[1].strip()
        if raw_value in {"", "."}:
            value = None
        else:
            value = _fmt(_decimal(raw_value, name="ALFRED value"))
        rows.append((observation_date, value))
    rows.sort(key=lambda item: item[0])
    return AlfredSnapshot(
        series_id=series_id,
        vintage_date=vintage_date,
        observation_start=observation_start,
        observation_end=observation_end,
        values=tuple(rows),
        source_url=source_url,
        source_sha256=sha256(raw).hexdigest(),
    )


class AlfredGateway:
    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        self._timeout = httpx.Timeout(timeout_seconds)

    def fetch_snapshot(
        self,
        *,
        series_id: str,
        vintage_date: date,
        observation_start: date,
        observation_end: date,
        client: httpx.Client | None = None,
    ) -> AlfredSnapshot:
        url = alfred_url(
            series_id=series_id,
            vintage_date=vintage_date,
            observation_start=observation_start,
            observation_end=observation_end,
        )
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != _ALLOWED_HOST:
            raise MacroVintageError("alfred_source_not_allowed")
        owns_client = client is None
        if client is None:
            client = httpx.Client(
                timeout=self._timeout,
                follow_redirects=False,
                headers={"User-Agent": "AIDY-Gold-Macro-Vintage-Research/1.0"},
            )
        try:
            response = client.get(url)
            if response.status_code != 200:
                raise MacroVintageError(f"alfred_http_{response.status_code}")
            if len(response.content) > _MAX_SOURCE_BYTES:
                raise MacroVintageError("alfred_payload_size")
            return parse_alfred_csv(
                response.content,
                series_id=series_id,
                vintage_date=vintage_date,
                observation_start=observation_start,
                observation_end=observation_end,
                source_url=url,
            )
        except MacroVintageError:
            raise
        except httpx.TimeoutException as exc:
            raise MacroVintageError("alfred_timeout") from exc
        except httpx.HTTPError as exc:
            raise MacroVintageError("alfred_http_error") from exc
        finally:
            if owns_client:
                client.close()


def build_version_history(snapshots: Iterable[AlfredSnapshot]) -> list[dict[str, Any]]:
    grouped: dict[str, list[AlfredSnapshot]] = defaultdict(list)
    for snapshot in snapshots:
        if snapshot.series_id not in SERIES:
            continue
        grouped[snapshot.series_id].append(snapshot)

    output: list[dict[str, Any]] = []
    for series_id, series_snapshots in sorted(grouped.items()):
        ordered = sorted(series_snapshots, key=lambda item: (item.vintage_date, item.snapshot_digest))
        if len({item.vintage_date for item in ordered}) != len(ordered):
            raise ValueError(f"Duplicate ALFRED vintage date for {series_id}.")
        previous_map: dict[date, str | None] | None = None
        current_value: dict[date, str | None] = {}
        revision_index: dict[date, int] = {}
        first_print_state: dict[date, str] = {}

        for snapshot_index, snapshot in enumerate(ordered):
            value_map = snapshot.value_map()
            observation_dates = sorted(set(value_map) | set(current_value))
            for observation_date in observation_dates:
                new_present = observation_date in value_map
                new_value = value_map.get(observation_date)
                old_known = observation_date in current_value
                old_value = current_value.get(observation_date)

                if snapshot_index == 0 and new_present:
                    current_value[observation_date] = new_value
                    revision_index[observation_date] = 0
                    first_print_state[observation_date] = "pre_window_unknown"
                    output.append(
                        _version_record(
                            series_id=series_id,
                            observation_date=observation_date,
                            value=new_value,
                            previous_value=None,
                            revision_index=0,
                            revision_type="captured_existing",
                            first_print_state="pre_window_unknown",
                            snapshot=snapshot,
                        )
                    )
                    continue

                if not new_present:
                    continue
                if not old_known:
                    current_value[observation_date] = new_value
                    revision_index[observation_date] = 0
                    first_print_state[observation_date] = "known"
                    output.append(
                        _version_record(
                            series_id=series_id,
                            observation_date=observation_date,
                            value=new_value,
                            previous_value=None,
                            revision_index=0,
                            revision_type="first_print" if new_value is not None else "first_print_missing",
                            first_print_state="known",
                            snapshot=snapshot,
                        )
                    )
                    continue
                if new_value == old_value:
                    continue

                next_index = revision_index[observation_date] + 1
                revision_index[observation_date] = next_index
                current_value[observation_date] = new_value
                output.append(
                    _version_record(
                        series_id=series_id,
                        observation_date=observation_date,
                        value=new_value,
                        previous_value=old_value,
                        revision_index=next_index,
                        revision_type="revision_to_missing" if new_value is None else "revision",
                        first_print_state=first_print_state[observation_date],
                        snapshot=snapshot,
                    )
                )
            previous_map = value_map
        if previous_map is None:
            raise ValueError(f"No snapshots supplied for {series_id}.")

    output.sort(
        key=lambda item: (
            item["series_id"],
            item["observation_date"],
            item["vintage_date"],
            item["revision_index"],
        )
    )
    return output


def _version_record(
    *,
    series_id: str,
    observation_date: date,
    value: str | None,
    previous_value: str | None,
    revision_index: int,
    revision_type: str,
    first_print_state: str,
    snapshot: AlfredSnapshot,
) -> dict[str, Any]:
    delta: str | None = None
    if value is not None and previous_value is not None:
        delta = _fmt(_decimal(value, name="value") - _decimal(previous_value, name="previous_value"))
    available_after = conservative_available_after(snapshot.vintage_date)
    record: dict[str, Any] = {
        "version": DAY28_VERSION,
        "source": SOURCE_ALFRED,
        "series_id": series_id,
        "series_role": SERIES_ROLES[series_id],
        "observation_date": observation_date.isoformat(),
        "value": value,
        "publication_date": snapshot.vintage_date.isoformat(),
        "vintage_date": snapshot.vintage_date.isoformat(),
        "publication_time_precision": PUBLICATION_TIME_PRECISION,
        "pit_available_after_utc": available_after.isoformat(),
        "pit_reconstructable": True,
        "revision_index": revision_index,
        "revision_type": revision_type,
        "first_print_state": first_print_state,
        "previous_value": previous_value,
        "revision_delta": delta,
        "source_url": snapshot.source_url,
        "source_sha256": snapshot.source_sha256,
        "snapshot_digest": snapshot.snapshot_digest,
    }
    record["version_identity"] = _digest(record)
    return record


def verify_version_record(record: Mapping[str, Any]) -> bool:
    body = dict(record)
    supplied = str(body.pop("version_identity", ""))
    if not supplied or supplied != _digest(body):
        return False
    if body.get("series_id") not in SERIES or body.get("source") != SOURCE_ALFRED:
        return False
    if body.get("publication_time_precision") != PUBLICATION_TIME_PRECISION:
        return False
    if body.get("pit_reconstructable") is not True:
        return False
    try:
        vintage = date.fromisoformat(str(body["vintage_date"]))
        available = _utc(str(body["pit_available_after_utc"]))
    except (KeyError, ValueError):
        return False
    return available == conservative_available_after(vintage)


def reconstruct_series_as_of(
    records: Iterable[Mapping[str, Any]],
    *,
    series_id: str,
    as_of: datetime | str,
) -> dict[str, Any]:
    if series_id not in SERIES:
        raise ValueError(f"Unsupported Day 28 series: {series_id}")
    cutoff = _utc(as_of)
    latest_versions: dict[date, Mapping[str, Any]] = {}
    for record in records:
        if record.get("series_id") != series_id or not verify_version_record(record):
            continue
        observation_date = date.fromisoformat(str(record["observation_date"]))
        if observation_date > cutoff.date():
            continue
        available_after = _utc(str(record["pit_available_after_utc"]))
        if available_after > cutoff:
            continue
        current = latest_versions.get(observation_date)
        sort_key = (available_after, int(record["revision_index"]), str(record["version_identity"]))
        if current is None:
            latest_versions[observation_date] = record
            continue
        current_key = (
            _utc(str(current["pit_available_after_utc"])),
            int(current["revision_index"]),
            str(current["version_identity"]),
        )
        if sort_key > current_key:
            latest_versions[observation_date] = record

    known = [record for record in latest_versions.values() if record.get("value") is not None]
    if not known:
        return {
            "state": "unknown",
            "series_id": series_id,
            "series_role": SERIES_ROLES[series_id],
            "as_of_utc": cutoff.isoformat(),
            "fact": None,
        }
    selected = max(
        known,
        key=lambda item: (
            date.fromisoformat(str(item["observation_date"])),
            _utc(str(item["pit_available_after_utc"])),
            int(item["revision_index"]),
        ),
    )
    return {
        "state": "known",
        "series_id": series_id,
        "series_role": SERIES_ROLES[series_id],
        "as_of_utc": cutoff.isoformat(),
        "observation_age_days": (
            cutoff.date() - date.fromisoformat(str(selected["observation_date"]))
        ).days,
        "fact": dict(selected),
    }


def _same_date_value(left: Mapping[str, Any], right: Mapping[str, Any]) -> tuple[date, Decimal, Decimal] | None:
    if left.get("state") != "known" or right.get("state") != "known":
        return None
    left_fact = left.get("fact")
    right_fact = right.get("fact")
    if not isinstance(left_fact, Mapping) or not isinstance(right_fact, Mapping):
        return None
    left_date = date.fromisoformat(str(left_fact["observation_date"]))
    right_date = date.fromisoformat(str(right_fact["observation_date"]))
    if left_date != right_date:
        return None
    return (
        left_date,
        _decimal(left_fact["value"], name="left value"),
        _decimal(right_fact["value"], name="right value"),
    )


def build_rates_macro_state(
    records: Iterable[Mapping[str, Any]],
    *,
    as_of: datetime | str,
) -> dict[str, Any]:
    cutoff = _utc(as_of)
    materialized = list(records)
    selected = {
        series_id: reconstruct_series_as_of(materialized, series_id=series_id, as_of=cutoff)
        for series_id in SERIES
    }

    nominal_real = _same_date_value(selected[SERIES_DGS10], selected[SERIES_DFII10])
    nominal_curve = _same_date_value(selected[SERIES_DGS10], selected[SERIES_DGS2])
    derived_breakeven: dict[str, Any]
    if nominal_real is None:
        derived_breakeven = {"state": "unknown", "value": None, "observation_date": None}
    else:
        day, nominal_10y, real_10y = nominal_real
        derived_breakeven = {
            "state": "known",
            "value": _fmt(nominal_10y - real_10y),
            "observation_date": day.isoformat(),
            "formula": "DGS10-DFII10",
        }

    slope: dict[str, Any]
    if nominal_curve is None:
        slope = {"state": "unknown", "value": None, "observation_date": None}
    else:
        day, nominal_10y, nominal_2y = nominal_curve
        slope = {
            "state": "known",
            "value": _fmt(nominal_10y - nominal_2y),
            "observation_date": day.isoformat(),
            "formula": "DGS10-DGS2",
        }

    official_reference = selected[SERIES_T10YIE]
    validation_delta: str | None = None
    if derived_breakeven["state"] == "known" and official_reference.get("state") == "known":
        fact = official_reference.get("fact")
        if isinstance(fact, Mapping) and fact.get("observation_date") == derived_breakeven["observation_date"]:
            validation_delta = _fmt(
                _decimal(derived_breakeven["value"], name="derived breakeven")
                - _decimal(fact["value"], name="official breakeven")
            )

    state: dict[str, Any] = {
        "rates_decomposition_version": RATES_DECOMPOSITION_VERSION,
        "revision_intelligence_version": REVISION_INTELLIGENCE_VERSION,
        "as_of_utc": cutoff.isoformat(),
        "pit_reconstructable": all(
            item.get("state") == "unknown"
            or (
                isinstance(item.get("fact"), Mapping)
                and item["fact"].get("pit_reconstructable") is True
                and _utc(str(item["fact"]["pit_available_after_utc"])) <= cutoff
            )
            for item in selected.values()
        ),
        "evidence_family": EVIDENCE_FAMILY,
        "independent_confirmation_units": 1,
        "components_not_independent": True,
        "confirmation_policy": "single_family_decomposition_not_independent_votes",
        "real_yield_role": REAL_YIELD_ROLE,
        "directional_influence": REAL_YIELD_DIRECTIONAL_INFLUENCE,
        "series": selected,
        "derived": {
            "breakeven_10y": derived_breakeven,
            "slope_2s10s": slope,
        },
        "official_breakeven_reference": {
            "series_id": SERIES_T10YIE,
            "role": "validation_reference_only_zero_confirmation_weight",
            "state": official_reference.get("state"),
            "derived_minus_official": validation_delta,
        },
        "inflation_revision_context": selected[SERIES_CPI],
        "predictive_edge_claimed": False,
        "trading_gate_created": False,
    }
    state["state_digest"] = _digest(state)
    return state


def verify_rates_macro_state(state: Mapping[str, Any]) -> bool:
    body = dict(state)
    supplied = str(body.pop("state_digest", ""))
    if not supplied or supplied != _digest(body):
        return False
    if body.get("rates_decomposition_version") != RATES_DECOMPOSITION_VERSION:
        return False
    if body.get("evidence_family") != EVIDENCE_FAMILY:
        return False
    if body.get("independent_confirmation_units") != 1:
        return False
    if body.get("components_not_independent") is not True:
        return False
    if body.get("real_yield_role") != REAL_YIELD_ROLE:
        return False
    if body.get("directional_influence") != REAL_YIELD_DIRECTIONAL_INFLUENCE:
        return False
    if body.get("predictive_edge_claimed") is not False or body.get("trading_gate_created") is not False:
        return False
    return True
