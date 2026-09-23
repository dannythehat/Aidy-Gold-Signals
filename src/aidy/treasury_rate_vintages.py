"""Turn the Treasury yield curve we already store into records the rates expert reads.

AIDY has been fetching the US Treasury daily yield curve since 2026-08-18 and writing it
to `cross_market_observations` as UST_NOMINAL_2Y, UST_NOMINAL_10Y and UST_REAL_10Y. On
2026-09-23 those rows were fresh to the previous evening - and **nothing read them**.
Only `ENABLED_SERIES`, a config list, was imported anywhere.

Meanwhile `gold_rates_usd_cross_asset_expert` asks for the FRED identifiers DGS2, DGS10,
DFII10 and T10YIE through `macro_vintages`, and no FRED data has ever been stored. So the
expert reported `unknown` for the entire rates block on every cycle, not because the data
was missing but because the two halves were never connected.

This module is that connection. It is a pure transformation over rows - no network, no
database - so the point-in-time claims it makes can be tested directly.

POINT-IN-TIME

Each record's availability is `max(conservative_available_after(D), first_observed_at)`:

  * `conservative_available_after(D)` is midnight UTC on D+1. Treasury publishes the
    curve for date D on D itself, around 19:30-22:00 UTC, so this is already 2-4.5 hours
    later than the real publication. It is a bound, not an estimate.
  * `first_observed_at` is when the row entered our database. Ingest is daily and
    per-row, and it sometimes lags: the 2026-09-11 curve was not ours until
    2026-09-13T07:00Z, and 2026-08-18's not until 2026-08-19T16:02Z. Treating those as
    available on D+1 would let a replay read a value we did not yet hold.

    So the rule does real work in both directions. On 2026-09-22 (ingested 20:01Z) the
    conservative bound is later and wins; on 2026-09-11 the ingest time is later and
    wins.

Taking the later of the two is conservative under both readings at once. Moving
availability later can only withhold evidence the system might have used; it can never
manufacture knowledge the system did not have. That asymmetry is the whole argument, and
it is why `verify_version_record` accepts `>=` for a Treasury record rather than `==`.

THE DERIVED BREAKEVEN

T10YIE has no Treasury series of its own - FRED defines it as DGS10 - DFII10, which is
exactly `macro_vintages` line 517's own formula. It is emitted here as a derived record,
marked as such in `series_role` and `derivation`, and never described as the official
series.

Deriving it does not smuggle in false independence. The expert already places all four
of these in one `rates_curve` dependency group with `independent_confirmation_units: 1`
and `same_mechanism_components_not_independent: True`, so the curve counts once however
many of its components are present. The derived record lets the rates block reach
`known` instead of `partial`; it does not let it count twice.

A derived record is only emitted when both inputs are present for that date AND both are
already available, and it inherits the LATER of their two availabilities. A value cannot
be known before everything it is computed from is known.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from aidy.macro_vintages import (
    DAY28_VERSION,
    PUBLICATION_TIME_PRECISION,
    SERIES_DFII10,
    SERIES_DGS2,
    SERIES_DGS10,
    SERIES_T10YIE,
    SOURCE_US_TREASURY,
    _digest,
    _fmt,
    conservative_available_after,
)

TREASURY_RATE_VINTAGES_VERSION = "aidy_treasury_rate_vintages_v1"

#: Treasury's own series id -> the FRED identifier the rates expert asks for. The two
#: measure the same published number; only the naming differs.
TREASURY_TO_FRED = {
    "UST_NOMINAL_2Y": SERIES_DGS2,
    "UST_NOMINAL_10Y": SERIES_DGS10,
    "UST_REAL_10Y": SERIES_DFII10,
}

#: Roles for what this module emits. The breakeven is explicitly NOT the official series.
DERIVED_BREAKEVEN_ROLE = "derived_breakeven_reference_only"
BREAKEVEN_DERIVATION = "UST_NOMINAL_10Y-UST_REAL_10Y"

_DIRECT_ROLES = {
    SERIES_DGS2: "nominal_2y",
    SERIES_DGS10: "nominal_10y",
    SERIES_DFII10: "real_10y",
}


def _as_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _as_decimal(value: Any) -> Decimal | None:
    text = str(value if value is not None else "").strip()
    if not text:
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _record(
    *,
    series_id: str,
    series_role: str,
    observation_date: date,
    value: Decimal,
    available_after: datetime,
    revision_index: int,
    source_url: str,
    source_digest: str,
    derivation: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "version": DAY28_VERSION,
        "adapter_version": TREASURY_RATE_VINTAGES_VERSION,
        "source": SOURCE_US_TREASURY,
        "series_id": series_id,
        "series_role": series_role,
        "observation_date": observation_date.isoformat(),
        "value": _fmt(value),
        "publication_date": observation_date.isoformat(),
        "vintage_date": observation_date.isoformat(),
        "publication_time_precision": PUBLICATION_TIME_PRECISION,
        "pit_available_after_utc": available_after.isoformat(),
        "pit_reconstructable": True,
        "revision_index": revision_index,
        "revision_type": "first_print" if revision_index <= 1 else "revision",
        "first_print_state": "known",
        "previous_value": None,
        "revision_delta": None,
        "source_url": source_url,
        "source_sha256": source_digest,
        "snapshot_digest": source_digest,
    }
    if derivation is not None:
        record["derivation"] = derivation
    record["version_identity"] = _digest(record)
    return record


def build_treasury_rate_records(
    rows: Iterable[Mapping[str, Any]],
    *,
    include_derived_breakeven: bool = True,
) -> list[dict[str, Any]]:
    """Convert `cross_market_observations` Treasury rows into version records.

    A row is used only when it is a Treasury row for a mapped series carrying a finite
    value and a usable observation date. Anything else is skipped rather than guessed at:
    a malformed row is not evidence, and inventing a value here would be indistinguishable
    from inventing one anywhere else.

    Where several rows describe the same series and date, the highest `revision_index`
    wins, which is how a later Treasury correction supersedes an earlier print.
    """
    direct: dict[tuple[str, date], dict[str, Any]] = {}
    for row in rows:
        if str(row.get("source") or "") != SOURCE_US_TREASURY:
            continue
        fred_id = TREASURY_TO_FRED.get(str(row.get("series_id") or ""))
        if fred_id is None:
            continue
        value = _as_decimal(row.get("value"))
        if value is None:
            continue
        try:
            observed = date.fromisoformat(str(row.get("observation_date") or ""))
        except ValueError:
            continue

        ingested = _as_utc(row.get("first_observed_at"))
        conservative = conservative_available_after(observed)
        available = max(conservative, ingested) if ingested else conservative
        revision_index = int(row.get("revision_index") or 0)

        key = (fred_id, observed)
        current = direct.get(key)
        if current is not None and int(current["revision_index"]) >= revision_index:
            continue
        direct[key] = _record(
            series_id=fred_id,
            series_role=_DIRECT_ROLES[fred_id],
            observation_date=observed,
            value=value,
            available_after=available,
            revision_index=revision_index,
            source_url=str(row.get("source_url") or ""),
            source_digest=str(row.get("source_document_digest") or ""),
        )

    records = list(direct.values())
    if include_derived_breakeven:
        records.extend(_derived_breakevens(direct))
    records.sort(key=lambda item: (item["series_id"], item["observation_date"]))
    return records


def _derived_breakevens(
    direct: Mapping[tuple[str, date], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """10-year breakeven = nominal 10y - real 10y, for dates carrying both.

    The record inherits the LATER of the two inputs' availabilities: a derived value
    cannot be known before every input it is computed from is known.
    """
    out: list[dict[str, Any]] = []
    for (series_id, observed), nominal in direct.items():
        if series_id != SERIES_DGS10:
            continue
        real = direct.get((SERIES_DFII10, observed))
        if real is None:
            continue
        nominal_value = _as_decimal(nominal["value"])
        real_value = _as_decimal(real["value"])
        if nominal_value is None or real_value is None:
            continue
        available = max(
            datetime.fromisoformat(str(nominal["pit_available_after_utc"])),
            datetime.fromisoformat(str(real["pit_available_after_utc"])),
        )
        out.append(
            _record(
                series_id=SERIES_T10YIE,
                series_role=DERIVED_BREAKEVEN_ROLE,
                observation_date=observed,
                value=nominal_value - real_value,
                available_after=available,
                revision_index=max(
                    int(nominal["revision_index"]), int(real["revision_index"])
                ),
                source_url=str(nominal["source_url"]),
                source_digest=str(nominal["source_sha256"]),
                derivation=BREAKEVEN_DERIVATION,
            )
        )
    return out


__all__ = [
    "BREAKEVEN_DERIVATION",
    "DERIVED_BREAKEVEN_ROLE",
    "TREASURY_RATE_VINTAGES_VERSION",
    "TREASURY_TO_FRED",
    "build_treasury_rate_records",
]
