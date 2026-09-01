from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256
from typing import Any

from .macro_vintages import (
    RATES_DECOMPOSITION_VERSION,
    REAL_YIELD_DIRECTIONAL_INFLUENCE,
    REAL_YIELD_ROLE,
)

DAY44_VERSION = "aidy_policy_cross_asset_v1"
SOURCE_CONTRACT_VERSION = "aidy_day44_source_contract_v1"
OBSERVATION_VERSION = "aidy_day44_cross_asset_observation_v1"
MECHANISM_STATE_VERSION = "aidy_day44_mechanism_state_v1"
EXPERIMENT_PLAN_VERSION = "aidy_day44_j11_j14_plan_v1"
EXPERIMENT_RESULT_VERSION = "aidy_day44_mechanism_experiment_v1"
REAL_YIELD_POLICY_VERSION = "aidy_day44_real_yield_policy_v1"

MIN_INDEPENDENT_EVALUATION_N = 50
MIN_J12_REGIME_N = 20
NULL_EFFECT_THRESHOLD = Decimal("0.02")
MAX_INTRADAY_SKEW = timedelta(minutes=15)

SERIES_ZQ = "ZQ_FUT"
SERIES_SR3 = "SR3_FUT"
SERIES_ZN = "ZN_FUT"
SERIES_GC = "GC_FUT"
SERIES_SI = "SI_FUT"
SERIES_EURUSD = "EURUSD_SPOT"
SERIES_USDJPY = "USDJPY_SPOT"
SERIES_VIX = "VIX_INDEX"
SERIES_ES = "ES_FUT"
SERIES_BROAD_USD = "DTWEXBGS"
SERIES_REAL10Y = "DFII10"

PROHIBITED_GOLD_PROXIES = ("CL", "HG", "BTC")


class Day44Error(ValueError):
    """Raised when Day 44 research-integrity invariants are violated."""


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: object) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise Day44Error("Day 44 timestamps must be timezone-aware.")
    return parsed.astimezone(UTC)


def _decimal(value: object, *, name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise Day44Error(f"{name} must be a finite decimal.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise Day44Error(f"{name} must be a finite decimal.") from exc
    if not parsed.is_finite():
        raise Day44Error(f"{name} must be a finite decimal.")
    return parsed


def _fmt(value: Decimal) -> str:
    with localcontext() as ctx:
        ctx.prec = 40
        quantized = value.quantize(Decimal("0.000000001"))
    text = format(quantized, "f").rstrip("0").rstrip(".")
    return text or "0"


def _contract(
    *,
    series_id: str,
    label: str,
    mechanism_family: str,
    provider: str,
    authority: str,
    source_locator: str,
    timestamp_semantics: str,
    unit: str,
    provenance_policy: str,
    decision_role: str = "shadow_context_only",
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "source_contract_version": SOURCE_CONTRACT_VERSION,
        "series_id": series_id,
        "label": label,
        "mechanism_family": mechanism_family,
        "provider": provider,
        "source_authority": authority,
        "source_locator": source_locator,
        "timestamp_semantics": timestamp_semantics,
        "unit": unit,
        "provenance_policy": provenance_policy,
        "pit_attestation_required": True,
        "first_observed_at_required": True,
        "quality_state_required": True,
        "staleness_state_required": True,
        "decision_role": decision_role,
        "mandatory_for_trade": False,
        "independent_vote": False,
    }
    record["contract_digest"] = digest(record)
    return record


def day44_source_contracts() -> dict[str, dict[str, Any]]:
    contracts = {
        SERIES_ZQ: _contract(
            series_id=SERIES_ZQ,
            label="30-Day Federal Funds futures",
            mechanism_family="policy_path",
            provider="Databento",
            authority="CME_Group",
            source_locator="GLBX.MDP3:ZQ.n.0",
            timestamp_semantics="exchange_event_time_utc",
            unit="futures_price_100_minus_implied_rate",
            provenance_policy="historical_or_delayed_shadow_only_without_paid_live_activation",
        ),
        SERIES_SR3: _contract(
            series_id=SERIES_SR3,
            label="Three-Month SOFR futures",
            mechanism_family="policy_path",
            provider="Databento",
            authority="CME_Group",
            source_locator="GLBX.MDP3:SR3.n.0",
            timestamp_semantics="exchange_event_time_utc",
            unit="futures_price_100_minus_contract_rate",
            provenance_policy="historical_or_delayed_shadow_only_without_paid_live_activation",
        ),
        SERIES_ZN: _contract(
            series_id=SERIES_ZN,
            label="10-Year Treasury Note futures",
            mechanism_family="treasury_intraday_proxy",
            provider="Databento",
            authority="CME_Group",
            source_locator="GLBX.MDP3:ZN.n.0",
            timestamp_semantics="exchange_event_time_utc",
            unit="futures_price",
            provenance_policy="historical_or_delayed_shadow_only_without_paid_live_activation",
        ),
        SERIES_GC: _contract(
            series_id=SERIES_GC,
            label="COMEX Gold futures accepted observation spine",
            mechanism_family="precious_complex_baseline",
            provider="Databento",
            authority="CME_Group_COMEX",
            source_locator="GLBX.MDP3:GC.n.0",
            timestamp_semantics="exchange_event_time_utc",
            unit="usd_per_troy_ounce",
            provenance_policy="reuse_accepted_day41_day42_gc_shadow_contract",
        ),
        SERIES_SI: _contract(
            series_id=SERIES_SI,
            label="COMEX Silver futures",
            mechanism_family="precious_complex",
            provider="Databento",
            authority="CME_Group_COMEX",
            source_locator="GLBX.MDP3:SI.n.0",
            timestamp_semantics="exchange_event_time_utc",
            unit="usd_per_troy_ounce",
            provenance_policy="historical_or_delayed_shadow_only_without_paid_live_activation",
        ),
        SERIES_EURUSD: _contract(
            series_id=SERIES_EURUSD,
            label="EURUSD Federal Reserve H10",
            mechanism_family="usd_composition",
            provider="Federal_Reserve_H10",
            authority="Federal_Reserve_Board",
            source_locator="H10:DEXUSEU",
            timestamp_semantics="official_observation_date_plus_first_observed_capture",
            unit="usd_per_eur",
            provenance_policy="official_first_observed_capture_or_explicit_retrospective_research",
        ),
        SERIES_USDJPY: _contract(
            series_id=SERIES_USDJPY,
            label="USDJPY Federal Reserve H10",
            mechanism_family="usd_composition",
            provider="Federal_Reserve_H10",
            authority="Federal_Reserve_Board",
            source_locator="H10:DEXJPUS",
            timestamp_semantics="official_observation_date_plus_first_observed_capture",
            unit="jpy_per_usd",
            provenance_policy="official_first_observed_capture_or_explicit_retrospective_research",
        ),
        SERIES_VIX: _contract(
            series_id=SERIES_VIX,
            label="Cboe Volatility Index",
            mechanism_family="risk_state",
            provider="Cboe",
            authority="Cboe_Global_Markets",
            source_locator="CBOE:VIX_History.csv",
            timestamp_semantics="official_observation_date_plus_first_observed_capture",
            unit="index_points",
            provenance_policy="official_first_observed_capture_or_explicit_retrospective_research",
        ),
        SERIES_ES: _contract(
            series_id=SERIES_ES,
            label="E-mini S&P 500 futures",
            mechanism_family="risk_state",
            provider="Databento",
            authority="CME_Group",
            source_locator="GLBX.MDP3:ES.n.0",
            timestamp_semantics="exchange_event_time_utc",
            unit="futures_index_points",
            provenance_policy="historical_or_delayed_shadow_only_without_paid_live_activation",
        ),
        SERIES_BROAD_USD: _contract(
            series_id=SERIES_BROAD_USD,
            label="Broad trade-weighted U.S. dollar index",
            mechanism_family="usd_baseline",
            provider="Federal_Reserve_H10",
            authority="Federal_Reserve_Board",
            source_locator="H10:DTWEXBGS",
            timestamp_semantics="official_observation_date_plus_first_observed_capture",
            unit="index_jan_2006_100",
            provenance_policy="reuse_accepted_day9_cross_market_contract",
        ),
        SERIES_REAL10Y: _contract(
            series_id=SERIES_REAL10Y,
            label="10-Year real Treasury yield",
            mechanism_family="us_rates_decomposition",
            provider="FRED_ALFRED",
            authority="Federal_Reserve_Bank_of_St_Louis",
            source_locator="ALFRED:DFII10",
            timestamp_semantics="vintage_date_with_conservative_available_after",
            unit="percent",
            provenance_policy="reuse_accepted_day28_vintage_contract",
            decision_role="context_regime_only",
        ),
    }
    return contracts


def verify_source_contract(contract: Mapping[str, Any]) -> bool:
    body = dict(contract)
    supplied = str(body.pop("contract_digest", ""))
    required = (
        "source_contract_version",
        "series_id",
        "mechanism_family",
        "provider",
        "source_authority",
        "source_locator",
        "timestamp_semantics",
        "unit",
        "provenance_policy",
    )
    return bool(supplied) and all(body.get(key) for key in required) and all(
        (
            body.get("source_contract_version") == SOURCE_CONTRACT_VERSION,
            body.get("pit_attestation_required") is True,
            body.get("first_observed_at_required") is True,
            body.get("quality_state_required") is True,
            body.get("staleness_state_required") is True,
            body.get("mandatory_for_trade") is False,
            body.get("independent_vote") is False,
            supplied == digest(body),
        )
    )


def build_observation(
    *,
    series_id: str,
    value: object,
    observed_at: datetime | str,
    first_observed_at: datetime | str,
    source_snapshot_digest: str,
    provenance_class: str,
    pit_reconstructable: bool,
    quality_state: str = "known",
    staleness_state: str = "fresh_for_declared_horizon",
) -> dict[str, Any]:
    contracts = day44_source_contracts()
    contract = contracts.get(series_id)
    if contract is None:
        raise Day44Error(f"Unsupported Day 44 series: {series_id}")
    if provenance_class not in {"first_observed_capture", "retrospective_history"}:
        raise Day44Error("Invalid Day 44 provenance class.")
    if quality_state != "known":
        raise Day44Error("Known observations must use quality_state='known'.")
    observed = _utc(observed_at)
    first_seen = _utc(first_observed_at)
    if first_seen < observed:
        raise Day44Error("first_observed_at cannot precede the market/official observation time.")
    snapshot = source_snapshot_digest.strip()
    if len(snapshot) != 64 or any(char not in "0123456789abcdef" for char in snapshot.lower()):
        raise Day44Error("source_snapshot_digest must be a SHA-256 hex digest.")
    decimal_value = _decimal(value, name=f"{series_id} value")
    decision_input_allowed = provenance_class == "first_observed_capture" and pit_reconstructable
    record: dict[str, Any] = {
        "observation_version": OBSERVATION_VERSION,
        "series_id": series_id,
        "contract_digest": contract["contract_digest"],
        "mechanism_family": contract["mechanism_family"],
        "value": _fmt(decimal_value),
        "unit": contract["unit"],
        "observed_at_utc": observed.isoformat(),
        "first_observed_at_utc": first_seen.isoformat(),
        "source_snapshot_digest": snapshot.lower(),
        "provenance_class": provenance_class,
        "pit_reconstructable": bool(pit_reconstructable),
        "quality_state": quality_state,
        "staleness_state": staleness_state,
        "decision_input_allowed": decision_input_allowed,
        "evaluation_only": not decision_input_allowed,
        "mandatory_for_trade": False,
    }
    record["observation_digest"] = digest(record)
    return record


def verify_observation(record: Mapping[str, Any]) -> bool:
    try:
        body = dict(record)
        supplied = str(body.pop("observation_digest", ""))
        contracts = day44_source_contracts()
        contract = contracts[str(body["series_id"])]
        if not verify_source_contract(contract):
            return False
        if body.get("observation_version") != OBSERVATION_VERSION:
            return False
        if body.get("contract_digest") != contract["contract_digest"]:
            return False
        if body.get("unit") != contract["unit"]:
            return False
        observed = _utc(str(body["observed_at_utc"]))
        first_seen = _utc(str(body["first_observed_at_utc"]))
        if first_seen < observed:
            return False
        _decimal(body["value"], name="observation value")
        provenance = body.get("provenance_class")
        if provenance not in {"first_observed_capture", "retrospective_history"}:
            return False
        expected_decision = provenance == "first_observed_capture" and body.get(
            "pit_reconstructable"
        ) is True
        if body.get("decision_input_allowed") is not expected_decision:
            return False
        if body.get("evaluation_only") is not (not expected_decision):
            return False
        if body.get("mandatory_for_trade") is not False:
            return False
        return bool(supplied) and supplied == digest(body)
    except (KeyError, TypeError, ValueError):
        return False


def _validated_value(record: Mapping[str, Any], expected_series: str) -> Decimal:
    if not verify_observation(record):
        raise Day44Error("Invalid Day 44 observation entered mechanism state.")
    if record.get("series_id") != expected_series:
        raise Day44Error(f"Expected {expected_series} observation.")
    return _decimal(record["value"], name=f"{expected_series} value")


def build_policy_path_state(
    *,
    zq: Mapping[str, Any] | None,
    sr3: Mapping[str, Any] | None,
) -> dict[str, Any]:
    zq_rate = None if zq is None else Decimal(100) - _validated_value(zq, SERIES_ZQ)
    sr3_rate = None if sr3 is None else Decimal(100) - _validated_value(sr3, SERIES_SR3)
    state = "known" if zq_rate is not None and sr3_rate is not None else "partial_or_unknown"
    result: dict[str, Any] = {
        "mechanism_state_version": MECHANISM_STATE_VERSION,
        "mechanism_family": "policy_path",
        "state": state,
        "zq_implied_average_policy_rate_percent": None if zq_rate is None else _fmt(zq_rate),
        "sr3_implied_contract_rate_percent": None if sr3_rate is None else _fmt(sr3_rate),
        "component_count": 2,
        "independent_confirmation_units": 1,
        "components_not_independent": True,
        "confirmation_policy": "single_policy_path_family_not_independent_votes",
        "mandatory_for_trade": False,
    }
    result["state_digest"] = digest(result)
    return result


def build_gold_silver_state(
    *,
    gold: Mapping[str, Any] | None,
    silver: Mapping[str, Any] | None,
) -> dict[str, Any]:
    ratio: Decimal | None = None
    state = "unknown_missing_gold_or_silver"
    if gold is not None and silver is not None:
        gold_value = _validated_value(gold, SERIES_GC)
        silver_value = _validated_value(silver, SERIES_SI)
        gold_time = _utc(str(gold["observed_at_utc"]))
        silver_time = _utc(str(silver["observed_at_utc"]))
        if abs(gold_time - silver_time) > MAX_INTRADAY_SKEW:
            state = "unknown_clock_mismatch"
        elif silver_value <= 0 or gold_value <= 0:
            raise Day44Error("Gold and silver prices must be positive.")
        else:
            ratio = gold_value / silver_value
            state = "known"
    result: dict[str, Any] = {
        "mechanism_state_version": MECHANISM_STATE_VERSION,
        "mechanism_family": "precious_complex",
        "state": state,
        "gold_silver_ratio": None if ratio is None else _fmt(ratio),
        "maximum_clock_skew_minutes": int(MAX_INTRADAY_SKEW.total_seconds() // 60),
        "j11_required_before_incremental_use": True,
        "mandatory_for_trade": False,
        "predictive_edge_claimed": False,
    }
    result["state_digest"] = digest(result)
    return result


def build_usd_composition_state(
    *,
    broad_usd: Mapping[str, Any] | None,
    eurusd: Mapping[str, Any] | None,
    usdjpy: Mapping[str, Any] | None,
) -> dict[str, Any]:
    values: dict[str, str | None] = {}
    for key, expected, record in (
        ("broad_usd", SERIES_BROAD_USD, broad_usd),
        ("eurusd", SERIES_EURUSD, eurusd),
        ("usdjpy", SERIES_USDJPY, usdjpy),
    ):
        values[key] = None if record is None else _fmt(_validated_value(record, expected))
    known = sum(value is not None for value in values.values())
    result: dict[str, Any] = {
        "mechanism_state_version": MECHANISM_STATE_VERSION,
        "mechanism_family": "usd_composition",
        "state": "known" if known == 3 else ("partial" if known else "unknown"),
        **values,
        "broad_usd_is_baseline_not_a_vote": True,
        "j14_tests_incremental_composition_only": True,
        "mandatory_for_trade": False,
        "predictive_edge_claimed": False,
    }
    result["state_digest"] = digest(result)
    return result


def build_risk_state(
    *,
    vix: Mapping[str, Any] | None,
    es: Mapping[str, Any] | None,
) -> dict[str, Any]:
    vix_value = None if vix is None else _fmt(_validated_value(vix, SERIES_VIX))
    es_value = None if es is None else _fmt(_validated_value(es, SERIES_ES))
    known = sum(value is not None for value in (vix_value, es_value))
    result: dict[str, Any] = {
        "mechanism_state_version": MECHANISM_STATE_VERSION,
        "mechanism_family": "risk_state",
        "state": "known" if known == 2 else ("partial" if known else "unknown"),
        "vix": vix_value,
        "es": es_value,
        "risk_state_is_context_not_gold_proxy": True,
        "mandatory_for_trade": False,
        "predictive_edge_claimed": False,
    }
    result["state_digest"] = digest(result)
    return result


def day44_experiment_plan() -> dict[str, Any]:
    contracts = day44_source_contracts()
    plan: dict[str, Any] = {
        "experiment_plan_version": EXPERIMENT_PLAN_VERSION,
        "day44_version": DAY44_VERSION,
        "minimum_independent_evaluation_n": MIN_INDEPENDENT_EVALUATION_N,
        "minimum_j12_regime_n": MIN_J12_REGIME_N,
        "null_effect_threshold": _fmt(NULL_EFFECT_THRESHOLD),
        "chronological_split_required": True,
        "purge_required": True,
        "embargo_required": True,
        "episode_independence_required": True,
        "threshold_tuning_on_evaluation_set_allowed": False,
        "correlation_mining_allowed": False,
        "multiple_unregistered_predictor_search_allowed": False,
        "single_result_can_promote_mandatory_feature": False,
        "j11": {
            "name": "gold_silver_mechanism",
            "hypothesis": "Silver and gold/silver add incremental information beyond the Gold baseline.",
            "null_hypothesis": "The precious-complex additions do not add incremental information beyond Gold.",
            "frozen_predictors": [SERIES_SI, "gold_silver_ratio"],
            "required_baseline": SERIES_GC,
            "effect_field": "precious_incremental_effect",
        },
        "j12": {
            "name": "real_yield_regime_dependence",
            "hypothesis": "The Gold/real-yield relationship varies materially across predeclared regimes.",
            "null_hypothesis": "No material regime-dependent real-yield directional relationship is demonstrated.",
            "frozen_predictors": [SERIES_REAL10Y],
            "rates_decomposition_version": RATES_DECOMPOSITION_VERSION,
            "existing_real_yield_role": REAL_YIELD_ROLE,
            "existing_directional_influence": REAL_YIELD_DIRECTIONAL_INFLUENCE,
            "effect_field": "real_yield_directional_effect",
        },
        "j13": {
            "name": "intraday_zn_vs_daily_yields",
            "hypothesis": "Intraday ZN adds timely rate-path information beyond daily cash-yield context.",
            "null_hypothesis": "ZN adds no incremental information beyond the existing daily rates decomposition.",
            "frozen_predictors": [SERIES_ZN],
            "required_baseline": RATES_DECOMPOSITION_VERSION,
            "effect_field": "zn_incremental_effect",
        },
        "j14": {
            "name": "usd_composition_beyond_broad_dollar",
            "hypothesis": "EURUSD and USDJPY composition adds information beyond the broad-dollar baseline.",
            "null_hypothesis": "FX composition adds no incremental information beyond the broad-dollar baseline.",
            "frozen_predictors": [SERIES_EURUSD, SERIES_USDJPY],
            "required_baseline": SERIES_BROAD_USD,
            "effect_field": "usd_composition_incremental_effect",
        },
        "source_contract_digests": {
            series: contract["contract_digest"] for series, contract in sorted(contracts.items())
        },
        "prohibited_gold_proxies": list(PROHIBITED_GOLD_PROXIES),
        "features_shadow_only": True,
        "trading_gate_created": False,
        "predictive_edge_claimed": False,
    }
    plan["plan_digest"] = digest(plan)
    return plan


def _validate_split_binding(split_binding: Mapping[str, Any]) -> None:
    required_true = ("purge_required", "embargo_required", "cpcv_pre_holdout_only")
    if any(split_binding.get(key) is not True for key in required_true):
        raise Day44Error("Day 44 experiments require Day 37 purge/embargo pre-holdout semantics.")
    if split_binding.get("holdout_tuning_allowed") is not False:
        raise Day44Error("Day 44 holdout tuning is forbidden.")
    if not str(split_binding.get("split_digest") or ""):
        raise Day44Error("Day 44 split binding requires an immutable digest.")


def run_day44_experiment(
    *,
    experiment: str,
    rows: Iterable[Mapping[str, Any]],
    split_binding: Mapping[str, Any],
) -> dict[str, Any]:
    _validate_split_binding(split_binding)
    plan = day44_experiment_plan()
    key = experiment.lower()
    if key not in {"j11", "j12", "j13", "j14"}:
        raise Day44Error("Experiment must be one of J11, J12, J13 or J14.")
    spec = plan[key]
    metric = str(spec["effect_field"])
    unique: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        episode = str(row.get("episode_id") or "").strip()
        if not episode:
            raise Day44Error("Every Day 44 evaluation row requires episode_id.")
        if episode in unique:
            raise Day44Error("Duplicate independent episode entered Day 44 evaluation.")
        unique[episode] = row
    effective_n = len(unique)
    state = "insufficient"
    mean_effect: Decimal | None = None
    regime_counts: dict[str, int] = {}
    if effective_n >= MIN_INDEPENDENT_EVALUATION_N:
        effects: list[Decimal] = []
        for row in unique.values():
            effects.append(_decimal(row.get(metric), name=metric))
            if key == "j12":
                regime = str(row.get("regime") or "").strip()
                if not regime:
                    raise Day44Error("J12 requires a preregistered regime label on every row.")
                regime_counts[regime] = regime_counts.get(regime, 0) + 1
        if key == "j12" and (
            len(regime_counts) < 2 or min(regime_counts.values(), default=0) < MIN_J12_REGIME_N
        ):
            state = "insufficient"
        else:
            mean_effect = sum(effects, Decimal(0)) / Decimal(len(effects))
            state = (
                "null"
                if abs(mean_effect) < NULL_EFFECT_THRESHOLD
                else "descriptive_non_null"
            )
    result: dict[str, Any] = {
        "experiment_result_version": EXPERIMENT_RESULT_VERSION,
        "experiment": experiment.upper(),
        "name": spec["name"],
        "plan_digest": plan["plan_digest"],
        "split_digest": split_binding["split_digest"],
        "effective_independent_n": effective_n,
        "minimum_independent_evaluation_n": MIN_INDEPENDENT_EVALUATION_N,
        "result_state": state,
        "effect_field": metric,
        "mean_effect": None if mean_effect is None else _fmt(mean_effect),
        "regime_counts": regime_counts,
        "threshold_tuning_on_evaluation_set_allowed": False,
        "features_shadow_only": True,
        "mandatory_feature_promoted": False,
        "trading_gate_created": False,
        "predictive_edge_claimed": False,
    }
    result["result_digest"] = digest(result)
    return result


def real_yield_policy_after_j12(j12_result: Mapping[str, Any]) -> dict[str, Any]:
    if j12_result.get("experiment") != "J12":
        raise Day44Error("Real-yield policy requires a J12 result.")
    state = str(j12_result.get("result_state") or "")
    effective_n = int(j12_result.get("effective_independent_n") or 0)
    if state == "null" and effective_n >= MIN_INDEPENDENT_EVALUATION_N:
        directional = "demoted_disabled_after_sufficient_j12_null"
        role = "context_regime_only"
        demoted = True
    elif state == "descriptive_non_null":
        directional = "provisional_requires_separate_followup_before_any_promotion"
        role = "context_regime_only"
        demoted = False
    else:
        directional = REAL_YIELD_DIRECTIONAL_INFLUENCE
        role = REAL_YIELD_ROLE
        demoted = False
    policy: dict[str, Any] = {
        "real_yield_policy_version": REAL_YIELD_POLICY_VERSION,
        "j12_result_digest": j12_result.get("result_digest"),
        "j12_result_state": state,
        "effective_independent_n": effective_n,
        "real_yield_role": role,
        "directional_influence": directional,
        "directional_use_demoted": demoted,
        "directional_use_promoted": False,
        "rates_independent_confirmation_units": 1,
        "rates_components_not_independent": True,
    }
    policy["policy_digest"] = digest(policy)
    return policy


def day44_manifest() -> dict[str, Any]:
    contracts = day44_source_contracts()
    plan = day44_experiment_plan()
    manifest: dict[str, Any] = {
        "day44_version": DAY44_VERSION,
        "source_contract_count": len(contracts),
        "source_contracts_valid": all(verify_source_contract(item) for item in contracts.values()),
        "required_added_series": [
            SERIES_ZQ,
            SERIES_SR3,
            SERIES_ZN,
            SERIES_SI,
            SERIES_EURUSD,
            SERIES_USDJPY,
            SERIES_VIX,
            SERIES_ES,
        ],
        "reused_baseline_series": [SERIES_GC, SERIES_BROAD_USD, SERIES_REAL10Y],
        "policy_path_components_not_independent": True,
        "rates_decomposition_components_not_independent": True,
        "rates_independent_confirmation_units": 1,
        "cross_asset_features_mandatory": [],
        "prohibited_gold_proxies": list(PROHIBITED_GOLD_PROXIES),
        "correlation_mining_allowed": False,
        "retrospective_history_can_be_live_decision_input": False,
        "formal_forward_evidence_created": False,
        "paid_live_market_data_activation_performed": False,
        "cvol_purchase_authorized": False,
        "trading_gate_created": False,
        "predictive_edge_claimed": False,
        "super_signals_modified": False,
        "experiment_plan_digest": plan["plan_digest"],
    }
    manifest["manifest_digest"] = digest(manifest)
    return manifest
