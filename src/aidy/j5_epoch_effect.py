from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from hashlib import sha256
from itertools import combinations
from typing import Any

from aidy.historical_cases import verify_historical_case_digest
from aidy.market_structure_context import market_structure_epoch_at

J5_VERSION = "aidy_j5_market_structure_epoch_effect_v1"
J5_MIN_PAIR_COUNT = 10
J5_MIN_NEW_EPOCH_INDEPENDENT_CASES = 10
J5_HORIZON_MINUTES = 240
J5_OUTCOME_FIELD = "path_stats.terminal_return_bps"
NEW_24X7_EPOCH = "post_1oz_24x7"


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("J5 timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _decimal(value: Any) -> Decimal:
    if value is None or isinstance(value, bool):
        raise TypeError("J5 outcome must be a finite decimal.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("J5 outcome must be a finite decimal.") from exc
    if not parsed.is_finite():
        raise ValueError("J5 outcome must be a finite decimal.")
    return parsed


def _q(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def _quantile(values: list[Decimal], probability: Decimal) -> Decimal:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = probability * Decimal(len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - Decimal(lower))


def _distribution(values: list[Decimal]) -> dict[str, Any]:
    if not values:
        return {
            "n": 0,
            "min": None,
            "p25": None,
            "median": None,
            "mean": None,
            "p75": None,
            "max": None,
        }
    ordered = sorted(values)
    mean = sum(ordered, Decimal(0)) / Decimal(len(ordered))
    return {
        "n": len(ordered),
        "min": _q(ordered[0]),
        "p25": _q(_quantile(ordered, Decimal("0.25"))),
        "median": _q(_quantile(ordered, Decimal("0.50"))),
        "mean": _q(mean),
        "p75": _q(_quantile(ordered, Decimal("0.75"))),
        "max": _q(ordered[-1]),
    }


def _move_240(case: Mapping[str, Any]) -> Mapping[str, Any] | None:
    future = case.get("future_evaluation")
    bundle = future.get("move_bundle") if isinstance(future, Mapping) else None
    labels = bundle.get("labels") if isinstance(bundle, Mapping) else None
    if not isinstance(labels, list):
        return None
    for item in labels:
        if (
            isinstance(item, Mapping)
            and int(item.get("horizon_minutes", -1)) == J5_HORIZON_MINUTES
            and item.get("coverage_state") == "complete"
        ):
            return item
    return None


def _stratum(case: Mapping[str, Any]) -> tuple[str, str, tuple[str, ...]] | None:
    boundary = case.get("input_boundary")
    if not isinstance(boundary, Mapping):
        return None
    regime = boundary.get("regime")
    setup = boundary.get("setup")
    labels = regime.get("labels") if isinstance(regime, Mapping) else None
    if not isinstance(labels, Mapping) or not isinstance(setup, Mapping):
        return None
    trend = str(labels.get("trend_structure") or "").strip()
    volatility = str(labels.get("volatility_band") or "").strip()
    setup_ids = setup.get("candidate_setup_ids")
    if not trend or not volatility or not isinstance(setup_ids, list):
        return None
    return trend, volatility, tuple(sorted(str(value) for value in setup_ids))


def _eligible_record(case: Mapping[str, Any]) -> dict[str, Any] | None:
    if not verify_historical_case_digest(case):
        raise ValueError("J5 cohort contains an invalid historical case.")
    stratum = _stratum(case)
    label = _move_240(case)
    if stratum is None or label is None:
        return None
    anchor = _utc(str(label.get("anchor_time_utc") or ""))
    end = _utc(str(label.get("horizon_end_utc") or ""))
    if end <= anchor:
        raise ValueError("J5 complete 240-minute label has an invalid outcome window.")
    stats = label.get("path_stats")
    if not isinstance(stats, Mapping):
        raise TypeError("J5 complete label requires path_stats.")
    terminal = _decimal(stats.get("terminal_return_bps"))
    case_time = _utc(str(case.get("as_of_utc") or ""))
    return {
        "case_id": str(case["case_id"]),
        "stratum": stratum,
        "epoch": market_structure_epoch_at(case_time)["market_structure_epoch"],
        "window_start": anchor,
        "window_end": end,
        "terminal_return_bps": terminal,
    }


def _episode_representatives(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(records, key=lambda item: (item["window_start"], item["case_id"]))
    components: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_end: datetime | None = None
    for record in ordered:
        if current_end is None or record["window_start"] >= current_end:
            if current:
                components.append(current)
            current = [record]
            current_end = record["window_end"]
        else:
            current.append(record)
            current_end = max(current_end, record["window_end"])
    if current:
        components.append(current)
    return [min(component, key=lambda item: item["case_id"]) for component in components]


def run_j5_epoch_effect(cases: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    source_cases = list(cases)
    raw_epoch_counts: Counter[str] = Counter()
    complete_epoch_counts: Counter[str] = Counter()
    eligible_by_stratum: dict[tuple[str, str, tuple[str, ...]], list[dict[str, Any]]] = defaultdict(list)

    for case in source_cases:
        if not verify_historical_case_digest(case):
            raise ValueError("J5 cohort contains an invalid historical case.")
        epoch = str(market_structure_epoch_at(str(case["as_of_utc"]))["market_structure_epoch"])
        raw_epoch_counts[epoch] += 1
        record = _eligible_record(case)
        if record is None:
            continue
        complete_epoch_counts[record["epoch"]] += 1
        eligible_by_stratum[record["stratum"]].append(record)

    representatives: list[dict[str, Any]] = []
    stratum_rows: list[dict[str, Any]] = []
    for stratum in sorted(eligible_by_stratum):
        raw = eligible_by_stratum[stratum]
        independent = _episode_representatives(raw)
        representatives.extend(independent)
        stratum_rows.append(
            {
                "trend_structure": stratum[0],
                "volatility_band": stratum[1],
                "candidate_setup_ids": list(stratum[2]),
                "raw_complete_case_count": len(raw),
                "independent_episode_count": len(independent),
                "representative_case_ids": sorted(item["case_id"] for item in independent),
            }
        )

    independent_epoch_counts = Counter(item["epoch"] for item in representatives)
    same_epoch_differences: list[Decimal] = []
    cross_epoch_differences: list[Decimal] = []
    same_pair_count_by_stratum: Counter[str] = Counter()
    cross_pair_count_by_stratum: Counter[str] = Counter()

    for row in stratum_rows:
        key = (
            row["trend_structure"],
            row["volatility_band"],
            tuple(row["candidate_setup_ids"]),
        )
        independent = _episode_representatives(eligible_by_stratum[key])
        stratum_id = _digest(
            {
                "trend_structure": key[0],
                "volatility_band": key[1],
                "candidate_setup_ids": list(key[2]),
            }
        )
        for left, right in combinations(independent, 2):
            difference = abs(left["terminal_return_bps"] - right["terminal_return_bps"])
            if left["epoch"] == right["epoch"]:
                same_epoch_differences.append(difference)
                same_pair_count_by_stratum[stratum_id] += 1
            else:
                cross_epoch_differences.append(difference)
                cross_pair_count_by_stratum[stratum_id] += 1

    same = _distribution(same_epoch_differences)
    cross = _distribution(cross_epoch_differences)
    if same["n"] < J5_MIN_PAIR_COUNT or cross["n"] < J5_MIN_PAIR_COUNT:
        conclusion = "INSUFFICIENT"
    elif Decimal(str(same["median"])) < Decimal(str(cross["median"])):
        conclusion = "SUPPORTS_LOWER_SAME_EPOCH_DISPERSION"
    else:
        conclusion = "DOES_NOT_SUPPORT_LOWER_SAME_EPOCH_DISPERSION"

    new_epoch_n = int(independent_epoch_counts[NEW_24X7_EPOCH])
    new_epoch_conclusion = (
        "SUFFICIENT_FOR_DESCRIPTIVE_COMPARISON"
        if new_epoch_n >= J5_MIN_NEW_EPOCH_INDEPENDENT_CASES
        else "INSUFFICIENT"
    )

    result: dict[str, Any] = {
        "j5_version": J5_VERSION,
        "hypothesis": "same_epoch_analogues_have_lower_240m_outcome_dispersion",
        "descriptive_only": True,
        "causal_claim": False,
        "outcome_used_for_epoch_assignment": False,
        "outcome_used_for_stratum_assignment": False,
        "outcome_used_for_episode_representative_selection": False,
        "outcome_field": J5_OUTCOME_FIELD,
        "horizon_minutes": J5_HORIZON_MINUTES,
        "matching_fields": [
            "regime.trend_structure",
            "regime.volatility_band",
            "candidate_setup_ids",
        ],
        "episode_rule": "connected_overlapping_240m_windows_lowest_case_id_representative",
        "minimum_pair_count_per_class": J5_MIN_PAIR_COUNT,
        "new_24x7_minimum_independent_cases": J5_MIN_NEW_EPOCH_INDEPENDENT_CASES,
        "source_case_count": len(source_cases),
        "raw_case_counts_by_epoch": dict(sorted(raw_epoch_counts.items())),
        "complete_240m_case_counts_by_epoch": dict(sorted(complete_epoch_counts.items())),
        "independent_case_counts_by_epoch": dict(sorted(independent_epoch_counts.items())),
        "matching_stratum_count": len(stratum_rows),
        "matching_strata": stratum_rows,
        "same_epoch_abs_terminal_return_difference_bps": same,
        "cross_epoch_abs_terminal_return_difference_bps": cross,
        "same_epoch_pair_count_by_stratum": dict(sorted(same_pair_count_by_stratum.items())),
        "cross_epoch_pair_count_by_stratum": dict(sorted(cross_pair_count_by_stratum.items())),
        "j5_conclusion": conclusion,
        "new_24x7_epoch_independent_case_count": new_epoch_n,
        "new_24x7_epoch_conclusion": new_epoch_conclusion,
    }
    result["j5_digest"] = _digest(result)
    return result


def verify_j5_digest(value: Mapping[str, Any]) -> bool:
    body = dict(value)
    supplied = str(body.pop("j5_digest", ""))
    return bool(supplied) and supplied == _digest(body)
