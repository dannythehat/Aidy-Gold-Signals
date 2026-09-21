"""Build 16: Rates / USD / Cross-Asset Expert for AIDY Gold.

Models Gold's opportunity-cost and cross-asset mechanisms without permanent
sign assumptions. Daily cash-rate series remain daily context and can never
masquerade as an intraday reaction signal.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from aidy.gold_expert_gate_contract import build_expert_gate_packet, verify_expert_gate_packet
from aidy.gold_expert_trust import (
    build_trust_envelope,
    build_trust_scopes,
    select_conditional_trust,
)
from aidy.macro_vintages import (
    SERIES_DFII10,
    SERIES_DGS10,
    SERIES_DGS2,
    SERIES_T10YIE,
    verify_version_record,
)
from aidy.policy_cross_asset import (
    SERIES_BROAD_USD,
    SERIES_ES,
    SERIES_EURUSD,
    SERIES_GC,
    SERIES_REAL10Y,
    SERIES_SI,
    SERIES_SR3,
    SERIES_USDJPY,
    SERIES_VIX,
    SERIES_ZN,
    SERIES_ZQ,
    verify_observation,
)

RATES_CROSS_ASSET_EXPERT_VERSION = "aidy_gold_rates_usd_cross_asset_expert_v1"
RATES_CROSS_ASSET_GATE_ID = "rates_usd_cross_asset_expert"
RATES_CROSS_ASSET_TARGET_HORIZON_MINUTES = 15
RELATIONSHIP_MINIMUM_N = 20
RELATIONSHIP_WINDOW_N = 60

DAILY_RATE_SERIES = (SERIES_DGS2, SERIES_DGS10, SERIES_DFII10, SERIES_T10YIE)
INTRADAY_MARKET_SERIES = (SERIES_ZQ, SERIES_SR3, SERIES_ZN, SERIES_GC, SERIES_SI, SERIES_ES)
DAILY_CONTEXT_MARKET_SERIES = (
    SERIES_BROAD_USD,
    SERIES_EURUSD,
    SERIES_USDJPY,
    SERIES_VIX,
    SERIES_REAL10Y,
)
SUPPORTED_CROSS_SERIES = INTRADAY_MARKET_SERIES + DAILY_CONTEXT_MARKET_SERIES

DEPENDENCY_GROUPS = {
    SERIES_DGS2: "rates_curve",
    SERIES_DGS10: "rates_curve",
    SERIES_DFII10: "rates_curve",
    SERIES_T10YIE: "rates_curve",
    SERIES_REAL10Y: "rates_curve",
    SERIES_ZN: "rates_intraday_proxy",
    SERIES_ZQ: "policy_path",
    SERIES_SR3: "policy_path",
    SERIES_BROAD_USD: "usd_mechanism",
    SERIES_EURUSD: "usd_mechanism",
    SERIES_USDJPY: "usd_mechanism",
    SERIES_SI: "precious_complex",
    SERIES_ES: "risk_state",
    SERIES_VIX: "risk_state",
    SERIES_GC: "gold_baseline",
}

RATES_CROSS_ASSET_TRUST_REDUCED_CONTEXTS = (
    {
        "name": "relationship_regime",
        "mini_dimensions": [
            "regime",
            "relationship_state",
            "breadth_state",
        ],
        "global_dimensions": [],
        "minimum_sample_n": 12,
    },
    {
        "name": "rates_usd_context",
        "mini_dimensions": [
            "rates_state",
            "usd_state",
            "divergence_state",
        ],
        "global_dimensions": ["volatility_state"],
        "minimum_sample_n": 10,
    },
    {
        "name": "cross_asset_context",
        "mini_dimensions": [
            "cross_asset_state",
            "breadth_state",
            "relationship_state",
        ],
        "global_dimensions": [],
        "minimum_sample_n": 8,
    },
)


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("rates/cross-asset timestamps must be timezone-aware")
    return parsed.astimezone(UTC)


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _fmt(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal("0.000001")), "f")


def _mean(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, Decimal(0)) / Decimal(len(values))


def _covariance(left: Sequence[Decimal], right: Sequence[Decimal]) -> Decimal | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = _mean(left)
    right_mean = _mean(right)
    assert left_mean is not None and right_mean is not None
    return sum(
        (lval - left_mean) * (rval - right_mean)
        for lval, rval in zip(left, right, strict=True)
    ) / Decimal(len(left) - 1)


def _sample_std(values: Sequence[Decimal]) -> Decimal | None:
    if len(values) < 2:
        return None
    mean = _mean(values)
    assert mean is not None
    variance = sum((value - mean) ** 2 for value in values) / Decimal(len(values) - 1)
    with localcontext() as ctx:
        ctx.prec = 40
        return variance.sqrt()


def _corr_beta(x_values: Sequence[Decimal], gold_values: Sequence[Decimal]) -> dict[str, Any]:
    if len(x_values) != len(gold_values) or len(x_values) < 2:
        return {"correlation": None, "beta": None}
    covariance = _covariance(x_values, gold_values)
    x_std = _sample_std(x_values)
    gold_std = _sample_std(gold_values)
    if covariance is None or x_std in {None, Decimal(0)} or gold_std in {None, Decimal(0)}:
        return {"correlation": None, "beta": None}
    variance_x = x_std * x_std
    correlation = covariance / (x_std * gold_std)
    beta = covariance / variance_x
    return {
        "correlation": _fmt(correlation),
        "beta": _fmt(beta),
    }


def _latest_rate_history(
    records: Sequence[Mapping[str, Any]],
    *,
    series_id: str,
    as_of: datetime,
) -> list[tuple[date, Decimal, datetime]]:
    by_date: dict[date, tuple[datetime, int, str, Decimal]] = {}
    for record in records:
        if record.get("series_id") != series_id or not verify_version_record(record):
            continue
        available = _utc(str(record["pit_available_after_utc"]))
        if available > as_of:
            continue
        value = _decimal(record.get("value"))
        if value is None:
            continue
        observed_date = date.fromisoformat(str(record["observation_date"]))
        key = (
            available,
            int(record.get("revision_index") or 0),
            str(record.get("version_identity") or ""),
            value,
        )
        current = by_date.get(observed_date)
        if current is None or key[:3] > current[:3]:
            by_date[observed_date] = key
    return [
        (day, payload[3], payload[0])
        for day, payload in sorted(by_date.items())
    ]


def _rate_change(history: Sequence[tuple[date, Decimal, datetime]], lag: int) -> str | None:
    if len(history) <= lag:
        return None
    latest = history[-1][1]
    previous = history[-1 - lag][1]
    return _fmt((latest - previous) * Decimal(100))


def _daily_rates_context(
    records: Sequence[Mapping[str, Any]],
    *,
    as_of: datetime,
) -> dict[str, Any]:
    series: dict[str, Any] = {}
    for series_id in DAILY_RATE_SERIES:
        history = _latest_rate_history(records, series_id=series_id, as_of=as_of)
        if not history:
            series[series_id] = {
                "state": "unknown",
                "dependency_group": DEPENDENCY_GROUPS[series_id],
                "intraday_reaction_allowed": False,
                "source_frequency": "daily",
            }
            continue
        observed_date, value, available = history[-1]
        age_days = (as_of.date() - observed_date).days
        series[series_id] = {
            "state": "known",
            "value_percent": _fmt(value),
            "observation_date": observed_date.isoformat(),
            "pit_available_after_utc": available.isoformat(),
            "observation_age_days": age_days,
            "change_1obs_bps": _rate_change(history, 1),
            "change_5obs_bps": _rate_change(history, 5),
            "change_20obs_bps": _rate_change(history, 20),
            "intraday_change_15m": None,
            "intraday_change_60m": None,
            "intraday_reaction_allowed": False,
            "intraday_unavailable_reason": "daily_cash_series_not_intraday",
            "source_frequency": "daily",
            "dependency_group": DEPENDENCY_GROUPS[series_id],
        }

    known_count = sum(item["state"] == "known" for item in series.values())
    return {
        "state": "known" if known_count == len(DAILY_RATE_SERIES) else "partial" if known_count else "unknown",
        "series": series,
        "dependency_policy": {
            "independent_confirmation_units": 1 if known_count else 0,
            "same_mechanism_components_not_independent": True,
            "group": "rates_curve",
        },
        "stale_daily_cannot_be_intraday_reaction": True,
    }


def _eligible_cross_observations(
    observations: Sequence[Mapping[str, Any]],
    *,
    as_of: datetime,
) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in observations:
        if not verify_observation(record):
            continue
        series_id = str(record.get("series_id") or "")
        if series_id not in SUPPORTED_CROSS_SERIES:
            continue
        first_seen = _utc(str(record["first_observed_at_utc"]))
        observed = _utc(str(record["observed_at_utc"]))
        if first_seen > as_of or observed > as_of:
            continue
        if record.get("pit_reconstructable") is not True:
            continue
        grouped[series_id].append(record)
    for rows in grouped.values():
        rows.sort(
            key=lambda row: (
                _utc(str(row["observed_at_utc"])),
                _utc(str(row["first_observed_at_utc"])),
            )
        )
    return grouped


def _previous_at_or_before(
    rows: Sequence[Mapping[str, Any]],
    cutoff: datetime,
) -> Mapping[str, Any] | None:
    eligible = [row for row in rows if _utc(str(row["observed_at_utc"])) <= cutoff]
    return eligible[-1] if eligible else None


def _price_change_bps(
    latest: Mapping[str, Any],
    previous: Mapping[str, Any] | None,
) -> str | None:
    if previous is None:
        return None
    latest_value = _decimal(latest.get("value"))
    previous_value = _decimal(previous.get("value"))
    if latest_value is None or previous_value in {None, Decimal(0)}:
        return None
    return _fmt((latest_value / previous_value - Decimal(1)) * Decimal(10000))


def _cross_asset_context(
    observations: Sequence[Mapping[str, Any]],
    *,
    as_of: datetime,
) -> dict[str, Any]:
    grouped = _eligible_cross_observations(observations, as_of=as_of)
    output: dict[str, Any] = {}
    for series_id in SUPPORTED_CROSS_SERIES:
        rows = grouped.get(series_id, [])
        dependency_group = DEPENDENCY_GROUPS[series_id]
        source_frequency = (
            "intraday"
            if series_id in INTRADAY_MARKET_SERIES
            else "daily_or_official_fix"
        )
        if not rows:
            output[series_id] = {
                "state": "unknown",
                "dependency_group": dependency_group,
                "source_frequency": source_frequency,
                "intraday_reaction_allowed": series_id in INTRADAY_MARKET_SERIES,
            }
            continue
        latest = rows[-1]
        latest_time = _utc(str(latest["observed_at_utc"]))
        fresh = str(latest.get("staleness_state") or "").startswith("fresh")
        decision_eligible = latest.get("decision_input_allowed") is True
        intraday_allowed = (
            series_id in INTRADAY_MARKET_SERIES
            and fresh
            and decision_eligible
        )
        item = {
            "state": "known",
            "value": latest.get("value"),
            "observed_at_utc": latest_time.isoformat(),
            "first_observed_at_utc": latest.get("first_observed_at_utc"),
            "age_minutes": _fmt(
                Decimal(str((as_of - latest_time).total_seconds() / 60))
            ),
            "staleness_state": latest.get("staleness_state"),
            "decision_input_allowed": decision_eligible,
            "qualification": (
                "decision_eligible"
                if decision_eligible
                else "retrospective_research_only"
            ),
            "source_frequency": source_frequency,
            "intraday_reaction_allowed": intraday_allowed,
            "dependency_group": dependency_group,
            "change_15m_bps": None,
            "change_60m_bps": None,
            "change_1d_bps": None,
        }
        if intraday_allowed:
            item["change_15m_bps"] = _price_change_bps(
                latest,
                _previous_at_or_before(rows, as_of - timedelta(minutes=15)),
            )
            item["change_60m_bps"] = _price_change_bps(
                latest,
                _previous_at_or_before(rows, as_of - timedelta(minutes=60)),
            )
        else:
            item["intraday_unavailable_reason"] = (
                "official_daily_context_not_intraday"
                if series_id in DAILY_CONTEXT_MARKET_SERIES
                else "stale_or_unqualified_intraday_observation"
            )
        item["change_1d_bps"] = _price_change_bps(
            latest,
            _previous_at_or_before(rows, as_of - timedelta(days=1)),
        )
        output[series_id] = item

    known = sum(item["state"] == "known" for item in output.values())
    return {
        "state": "known" if known == len(SUPPORTED_CROSS_SERIES) else "partial" if known else "unknown",
        "series": output,
        "dependency_groups": {
            group: sorted(
                series_id
                for series_id, candidate_group in DEPENDENCY_GROUPS.items()
                if candidate_group == group and series_id in SUPPORTED_CROSS_SERIES
            )
            for group in sorted(set(DEPENDENCY_GROUPS.values()))
        },
        "same_mechanism_series_not_independent_votes": True,
    }


def _relationship_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    as_of: datetime,
    regime: str,
    series_id: str,
) -> list[tuple[Decimal, Decimal]]:
    eligible: list[tuple[datetime, str, Decimal, Decimal]] = []
    seen: set[str] = set()
    for row in rows:
        if row.get("pit_reconstructable") is not True:
            continue
        if str(row.get("regime") or "") != regime:
            continue
        stamp_raw = row.get("first_observed_at")
        if stamp_raw is None:
            continue
        stamp = _utc(str(stamp_raw))
        if stamp >= as_of:
            continue
        episode_id = str(row.get("independent_episode_id") or "")
        if not episode_id or episode_id in seen:
            continue
        changes = row.get("series_changes_bps")
        if not isinstance(changes, Mapping):
            continue
        x_value = _decimal(changes.get(series_id))
        gold_value = _decimal(row.get("gold_return_bps"))
        if x_value is None or gold_value is None:
            continue
        seen.add(episode_id)
        eligible.append((stamp, episode_id, x_value, gold_value))
    eligible.sort(key=lambda item: (item[0], item[1]))
    return [(item[2], item[3]) for item in eligible[-RELATIONSHIP_WINDOW_N:]]


def _relationship_state(
    rows: Sequence[Mapping[str, Any]],
    *,
    as_of: datetime,
    regime: str,
    series_id: str,
) -> dict[str, Any]:
    pairs = _relationship_rows(rows, as_of=as_of, regime=regime, series_id=series_id)
    if len(pairs) < RELATIONSHIP_MINIMUM_N:
        return {
            "state": "unknown_insufficient_regime_history",
            "sample_n": len(pairs),
            "minimum_sample_n": RELATIONSHIP_MINIMUM_N,
            "correlation": None,
            "beta": None,
            "relationship_sign": "unknown",
            "stability_state": "unknown",
            "hardcoded_sign_used": False,
            "dependency_group": DEPENDENCY_GROUPS.get(series_id, "other"),
        }

    x_values = [item[0] for item in pairs]
    gold_values = [item[1] for item in pairs]
    stats = _corr_beta(x_values, gold_values)
    corr = _decimal(stats["correlation"])
    beta = _decimal(stats["beta"])
    midpoint = len(pairs) // 2
    first_stats = _corr_beta(x_values[:midpoint], gold_values[:midpoint])
    second_stats = _corr_beta(x_values[midpoint:], gold_values[midpoint:])
    first_corr = _decimal(first_stats["correlation"])
    second_corr = _decimal(second_stats["correlation"])

    if corr is None or beta is None:
        sign = "unknown"
    elif corr >= Decimal("0.20"):
        sign = "positive"
    elif corr <= Decimal("-0.20"):
        sign = "negative"
    else:
        sign = "weak"

    if first_corr is None or second_corr is None:
        stability = "unknown"
    elif first_corr >= Decimal("0.20") and second_corr >= Decimal("0.20"):
        stability = "stable_positive"
    elif first_corr <= Decimal("-0.20") and second_corr <= Decimal("-0.20"):
        stability = "stable_negative"
    elif (
        first_corr >= Decimal("0.20") and second_corr <= Decimal("-0.20")
    ) or (
        first_corr <= Decimal("-0.20") and second_corr >= Decimal("0.20")
    ):
        stability = "sign_flip"
    else:
        stability = "weak_or_unstable"

    return {
        "state": "known",
        "sample_n": len(pairs),
        "minimum_sample_n": RELATIONSHIP_MINIMUM_N,
        "correlation": stats["correlation"],
        "beta": stats["beta"],
        "relationship_sign": sign,
        "stability_state": stability,
        "first_half_correlation": first_stats["correlation"],
        "second_half_correlation": second_stats["correlation"],
        "hardcoded_sign_used": False,
        "dependency_group": DEPENDENCY_GROUPS.get(series_id, "other"),
    }


def _relationship_map(
    rows: Sequence[Mapping[str, Any]],
    *,
    as_of: datetime,
    regime: str,
) -> dict[str, Any]:
    series_ids = [
        SERIES_DGS2,
        SERIES_DGS10,
        SERIES_DFII10,
        SERIES_T10YIE,
        SERIES_BROAD_USD,
        SERIES_EURUSD,
        SERIES_USDJPY,
        SERIES_ZN,
        SERIES_ZQ,
        SERIES_SR3,
        SERIES_SI,
        SERIES_ES,
        SERIES_VIX,
    ]
    relationships = {
        series_id: _relationship_state(
            rows,
            as_of=as_of,
            regime=regime,
            series_id=series_id,
        )
        for series_id in series_ids
    }
    known = [item for item in relationships.values() if item["state"] == "known"]
    stable = [
        item
        for item in known
        if item["stability_state"] in {"stable_positive", "stable_negative"}
    ]
    state = (
        "stable_relationships_present"
        if stable
        else "known_but_unstable"
        if known
        else "unknown"
    )
    return {
        "state": state,
        "regime": regime,
        "relationships": relationships,
        "hardcoded_forever_signs": False,
    }


def _current_series_change(
    *,
    series_id: str,
    rates: Mapping[str, Any],
    cross: Mapping[str, Any],
) -> tuple[str | None, str | None]:
    if series_id in DAILY_RATE_SERIES:
        item = rates["series"].get(series_id, {})
        return item.get("change_1obs_bps"), "daily"
    item = cross["series"].get(series_id, {})
    if item.get("intraday_reaction_allowed") is True and item.get("change_60m_bps") is not None:
        return item.get("change_60m_bps"), "60m"
    return item.get("change_1d_bps"), "daily"


def _divergence_and_breadth(
    *,
    relationships: Mapping[str, Any],
    rates: Mapping[str, Any],
    cross: Mapping[str, Any],
    current_gold_return_bps: Decimal | None,
) -> dict[str, Any]:
    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    divergences: list[dict[str, Any]] = []

    for series_id, relation in relationships["relationships"].items():
        if relation.get("state") != "known":
            continue
        beta = _decimal(relation.get("beta"))
        corr = _decimal(relation.get("correlation"))
        if beta is None or corr is None or abs(corr) < Decimal("0.20"):
            continue
        raw_change, horizon = _current_series_change(
            series_id=series_id,
            rates=rates,
            cross=cross,
        )
        change = _decimal(raw_change)
        if change is None:
            continue
        expected_gold = beta * change
        group = str(relation["dependency_group"])
        row = {
            "series_id": series_id,
            "dependency_group": group,
            "horizon": horizon,
            "series_change": _fmt(change),
            "beta": _fmt(beta),
            "correlation": _fmt(corr),
            "expected_gold_return_bps": _fmt(expected_gold),
            "implied_gold_sign": (
                "up" if expected_gold > 0 else "down" if expected_gold < 0 else "flat"
            ),
        }
        by_group[group].append(row)
        if (
            current_gold_return_bps is not None
            and abs(expected_gold) >= Decimal(1)
            and abs(current_gold_return_bps) >= Decimal(1)
            and expected_gold * current_gold_return_bps < 0
        ):
            divergences.append(
                {
                    **row,
                    "actual_gold_return_bps": _fmt(current_gold_return_bps),
                    "state": "opposite_to_learned_relationship",
                }
            )

    group_representatives: list[dict[str, Any]] = []
    for group, rows in sorted(by_group.items()):
        representative = max(
            rows,
            key=lambda row: abs(_decimal(row["correlation"]) or Decimal(0)),
        )
        group_representatives.append(representative)

    up = sum(item["implied_gold_sign"] == "up" for item in group_representatives)
    down = sum(item["implied_gold_sign"] == "down" for item in group_representatives)
    if up and not down:
        breadth = "all_groups_imply_gold_up"
    elif down and not up:
        breadth = "all_groups_imply_gold_down"
    elif up and down:
        breadth = "mixed_cross_asset_implications"
    else:
        breadth = "unknown"

    return {
        "breadth_state": breadth,
        "independent_dependency_group_count": len(group_representatives),
        "group_representatives": group_representatives,
        "same_group_components_count_once": True,
        "divergence_state": "present" if divergences else "none",
        "divergences": divergences,
    }


def _context_calculator(
    *,
    calculator_id: str,
    dependency_family: str,
    evidence_ref: str,
    known: bool,
    observation: Mapping[str, Any],
    explanation: str,
) -> dict[str, Any]:
    return {
        "calculator_id": calculator_id,
        "version": f"{calculator_id}_v1",
        "role": "context_only",
        "dependency_family": dependency_family,
        "state": "known" if known else "insufficient",
        "vote": "context_only" if known else "unknown",
        "evidence_refs": [evidence_ref],
        "observation": dict(observation),
        "explanation": explanation,
    }


def _subject_keys(packet: Mapping[str, Any]) -> list[str]:
    keys = [f"gate:{packet['gate_id']}"]
    keys.extend(
        f"subcalculator:{item['calculator_id']}"
        for item in packet["subcalculators"]
    )
    return keys


def build_rates_usd_cross_asset_expert(
    *,
    global_environment: Mapping[str, Any],
    rates_version_records: Sequence[Mapping[str, Any]],
    cross_asset_observations: Sequence[Mapping[str, Any]],
    relationship_history_rows: Sequence[Mapping[str, Any]],
    current_gold_return_bps: Any = None,
    trust_score_rows_by_subject: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Build one frozen rates/USD/cross-asset context packet."""

    exact = global_environment.get("exact_facts")
    exact = exact if isinstance(exact, Mapping) else {}
    as_of = _utc(str(exact.get("as_of_utc")))
    dimensions = global_environment["learning_dimensions"]
    regime = str(dimensions.get("compound_regime") or "unknown")

    rates = _daily_rates_context(rates_version_records, as_of=as_of)
    cross = _cross_asset_context(cross_asset_observations, as_of=as_of)
    relationships = _relationship_map(
        relationship_history_rows,
        as_of=as_of,
        regime=regime,
    )
    gold_return = _decimal(current_gold_return_bps)
    divergence = _divergence_and_breadth(
        relationships=relationships,
        rates=rates,
        cross=cross,
        current_gold_return_bps=gold_return,
    )

    usd_series = [
        cross["series"][SERIES_BROAD_USD],
        cross["series"][SERIES_EURUSD],
        cross["series"][SERIES_USDJPY],
    ]
    usd_known = sum(item["state"] == "known" for item in usd_series)
    usd_state = "known" if usd_known == 3 else "partial" if usd_known else "unknown"

    cross_known = sum(
        item["state"] == "known"
        for series_id, item in cross["series"].items()
        if series_id not in {SERIES_GC}
    )
    cross_state = "known" if cross_known else "unknown"

    evidence_inputs = [
        {
            "evidence_id": "rates_cash_evidence",
            "source": "aidy_macro_vintages_v1",
            "path": "rates_usd_cross_asset.daily_rates",
            "observed_at_utc": as_of,
            "state": "known" if rates["state"] != "unknown" else "unknown",
            "value": rates,
            "provenance": {
                "pit_vintage_verified": True,
                "daily_cash_series": True,
                "intraday_reaction_allowed": False,
                "future_values_used": False,
            },
        },
        {
            "evidence_id": "cross_asset_current_evidence",
            "source": "aidy_policy_cross_asset_v1",
            "path": "rates_usd_cross_asset.cross_asset_current",
            "observed_at_utc": as_of,
            "state": "known" if cross["state"] != "unknown" else "unknown",
            "value": cross,
            "provenance": {
                "pit_observations_verified": True,
                "same_mechanism_series_not_independent_votes": True,
                "future_values_used": False,
            },
        },
        {
            "evidence_id": "rolling_relationship_evidence",
            "source": "build16_regime_relationship_history",
            "path": "rates_usd_cross_asset.relationships",
            "observed_at_utc": as_of,
            "state": "known" if relationships["state"] != "unknown" else "unknown",
            "value": relationships,
            "provenance": {
                "pit_history_only": True,
                "independent_episode_ids_required": True,
                "hardcoded_forever_signs": False,
                "future_values_used": False,
            },
        },
        {
            "evidence_id": "cross_asset_divergence_evidence",
            "source": "build16_relationship_application",
            "path": "rates_usd_cross_asset.divergence_breadth",
            "observed_at_utc": as_of,
            "state": "known" if divergence["independent_dependency_group_count"] else "unknown",
            "value": divergence,
            "provenance": {
                "one_representative_per_dependency_group": True,
                "hardcoded_forever_signs": False,
                "future_values_used": False,
            },
        },
    ]

    calculators = [
        _context_calculator(
            calculator_id="rates_cash_context",
            dependency_family="rates_usd",
            evidence_ref="rates_cash_evidence",
            known=rates["state"] != "unknown",
            observation=rates,
            explanation=(
                "DGS2/DGS10/DFII10/T10YIE are PIT-vintaged daily context. "
                "They are one dependency family and cannot masquerade as 15m/60m reactions."
            ),
        ),
        _context_calculator(
            calculator_id="usd_cross_asset_current",
            dependency_family="cross_market",
            evidence_ref="cross_asset_current_evidence",
            known=cross["state"] != "unknown",
            observation=cross,
            explanation=(
                "Current USD/policy/precious/risk observations retain their source cadence "
                "and mechanism dependency tags; same-mechanism series are not independent votes."
            ),
        ),
        _context_calculator(
            calculator_id="rolling_gold_relationships",
            dependency_family="cross_market",
            evidence_ref="rolling_relationship_evidence",
            known=relationships["state"] != "unknown",
            observation=relationships,
            explanation=(
                "Rolling Gold beta/correlation is learned separately inside the current regime. "
                "Positive, negative, weak and sign-flipping relationships are all representable."
            ),
        ),
        _context_calculator(
            calculator_id="cross_asset_divergence_breadth",
            dependency_family="cross_market",
            evidence_ref="cross_asset_divergence_evidence",
            known=divergence["independent_dependency_group_count"] > 0,
            observation=divergence,
            explanation=(
                "Divergence and breadth apply the learned relationship sign and count only one "
                "representative per dependency group. No forever-sign is imposed."
            ),
        ),
    ]

    mini_environment = {
        "regime": regime,
        "rates_state": rates["state"],
        "usd_state": usd_state,
        "cross_asset_state": cross_state,
        "relationship_state": relationships["state"],
        "breadth_state": divergence["breadth_state"],
        "divergence_state": divergence["divergence_state"],
        "volatility_state": dimensions["volatility_state"],
    }

    packet = build_expert_gate_packet(
        gate_id=RATES_CROSS_ASSET_GATE_ID,
        gate_version=RATES_CROSS_ASSET_EXPERT_VERSION,
        gate_mode="context_only",
        dependency_family="cross_market",
        target_horizon_minutes=RATES_CROSS_ASSET_TARGET_HORIZON_MINUTES,
        as_of_utc=as_of,
        global_environment=global_environment,
        mini_environment=mini_environment,
        evidence_inputs=evidence_inputs,
        subcalculators=calculators,
        conclusion="context_only",
        internal_conviction=None,
        explanation_parts=(
            {
                "text": (
                    f"Rates state={rates['state']}; USD state={usd_state}; "
                    f"relationship state={relationships['state']}; "
                    f"breadth={divergence['breadth_state']}."
                ),
                "source_refs": [
                    "calc:rates_cash_context",
                    "calc:usd_cross_asset_current",
                    "calc:rolling_gold_relationships",
                    "calc:cross_asset_divergence_breadth",
                ],
            },
            {
                "text": (
                    "Build 16 has no permanent Gold/USD, Gold/real-yield or cross-asset sign. "
                    "Relationships are empirical, regime-specific context only."
                ),
                "source_refs": ["calc:rolling_gold_relationships"],
            },
        ),
        contradictions=(),
    )
    if not verify_expert_gate_packet(packet):
        raise ValueError("constructed Rates/USD/Cross-Asset packet failed Build-2 verification")

    scopes = build_trust_scopes(
        packet=packet,
        reduced_contexts=RATES_CROSS_ASSET_TRUST_REDUCED_CONTEXTS,
    )
    rows_by_subject = trust_score_rows_by_subject or {}
    profiles = {
        key: select_conditional_trust(
            score_rows=rows_by_subject.get(key, ()),
            scopes=scopes,
        )
        for key in _subject_keys(packet)
    }
    trust_envelope = build_trust_envelope(packet=packet, profiles_by_subject=profiles)

    return {
        "expert_version": RATES_CROSS_ASSET_EXPERT_VERSION,
        "expert_packet": packet,
        "daily_rates": rates,
        "cross_asset_current": cross,
        "relationships": relationships,
        "divergence_breadth": divergence,
        "trust_scopes": scopes,
        "trust_envelope": trust_envelope,
        "sign_policy": {
            "hardcoded_forever_signs": False,
            "gold_usd_fixed_inverse": False,
            "gold_real_yield_fixed_inverse": False,
            "regime_specific_signs_allowed": True,
            "sign_flip_state_allowed": True,
        },
        "frequency_policy": {
            "daily_cash_rates_are_intraday_reaction": False,
            "daily_official_fx_usd_vix_are_intraday_reaction": False,
            "exchange_timestamped_futures_can_be_intraday_when_fresh": True,
        },
        "research_only": True,
        "future_values_used": False,
        "live_money_execution_allowed": False,
    }


__all__ = [
    "DAILY_CONTEXT_MARKET_SERIES",
    "DAILY_RATE_SERIES",
    "DEPENDENCY_GROUPS",
    "INTRADAY_MARKET_SERIES",
    "RELATIONSHIP_MINIMUM_N",
    "RELATIONSHIP_WINDOW_N",
    "RATES_CROSS_ASSET_EXPERT_VERSION",
    "RATES_CROSS_ASSET_GATE_ID",
    "RATES_CROSS_ASSET_TARGET_HORIZON_MINUTES",
    "RATES_CROSS_ASSET_TRUST_REDUCED_CONTEXTS",
    "build_rates_usd_cross_asset_expert",
]
