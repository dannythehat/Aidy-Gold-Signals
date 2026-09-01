from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from aidy.volatility_intelligence import (
    J7_J8_FOUNDATION_VERSION,
    VOLATILITY_INTELLIGENCE_VERSION,
    digest,
    verify_j7_j8_foundation,
    verify_volatility_state,
)

RICHER_VOLATILITY_VERSION = "aidy_richer_volatility_regime_v1"
EVENT_IV_KINK_VERSION = "aidy_event_iv_kink_v1"
UNEXPLAINED_SHOCK_VERSION = "aidy_unexplained_market_shock_v1"
DAY43_EXPERIMENT_PLAN_VERSION = "aidy_day43_j7_j8_plan_v1"
J7_RESULT_VERSION = "aidy_j7_iv_rv_regime_test_v1"
J8_RESULT_VERSION = "aidy_j8_jump_instability_test_v1"
MINIMUM_INDEPENDENT_EVALUATION_N = 30


class RicherVolatilityError(ValueError):
    """Raised when Day 43 evidence violates the frozen research contract."""


def _utc(value: datetime | str, *, name: str) -> datetime:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise RicherVolatilityError(f"{name} must be ISO-8601.") from exc
    if parsed.tzinfo is None:
        raise RicherVolatilityError(f"{name} must be timezone-aware.")
    return parsed.astimezone(UTC)


def _finite(value: Any, *, name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise RicherVolatilityError(f"{name} must be a finite decimal.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise RicherVolatilityError(f"{name} must be a finite decimal.") from exc
    if not parsed.is_finite():
        raise RicherVolatilityError(f"{name} must be a finite decimal.")
    return parsed


def _fmt(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value == 0:
        return "0"
    return format(value, "f").rstrip("0").rstrip(".") or "0"


def _verify_day31_contract(state: Mapping[str, Any]) -> None:
    if not verify_volatility_state(state):
        raise RicherVolatilityError("Day 43 requires a valid accepted Day 31 volatility state.")
    if state.get("volatility_intelligence_version") != VOLATILITY_INTELLIGENCE_VERSION:
        raise RicherVolatilityError("Day 31 volatility contract version drifted.")
    gvz = state.get("gvz")
    rv = state.get("realized_volatility")
    iv_rv = state.get("iv_minus_rv")
    jump = state.get("jump_continuous")
    vov = state.get("vol_of_vol")
    if not all(isinstance(item, Mapping) for item in (gvz, rv, iv_rv, jump, vov)):
        raise RicherVolatilityError("Day 31 volatility components are incomplete.")
    if gvz.get("implied_horizon_calendar_days") != 30:
        raise RicherVolatilityError("GVZ implied horizon must remain 30 calendar days.")
    if rv.get("horizons_trading_days") != [5, 10, 21]:
        raise RicherVolatilityError("Realised-volatility horizons must remain 5/10/21 trading days.")
    if iv_rv.get("iv_horizon_calendar_days") != 30 or iv_rv.get("rv_horizon_trading_days") != 21:
        raise RicherVolatilityError("IV-RV comparable horizons drifted.")
    if iv_rv.get("cross_instrument_proxy") is not True:
        raise RicherVolatilityError("GVZ-versus-XAUUSD comparison must retain proxy caveat.")
    if jump.get("estimator") != "realized_variation_minus_bipower_variation":
        raise RicherVolatilityError("Jump/continuous estimator drifted.")
    if vov.get("window_trading_days") != 21:
        raise RicherVolatilityError("Vol-of-vol horizon must remain 21 trading days.")


def build_event_iv_kink(
    *,
    as_of: datetime | str,
    event_at: datetime | str,
    observations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build an ex-ante event IV term-structure kink only from data known before the event."""

    cutoff = _utc(as_of, name="as_of")
    event = _utc(event_at, name="event_at")
    if cutoff >= event:
        raise RicherVolatilityError("Event-kink state must be constructed before the event.")
    eligible: list[dict[str, Any]] = []
    for index, raw in enumerate(observations):
        if not isinstance(raw, Mapping):
            raise RicherVolatilityError(f"event_iv_observations[{index}] must be an object.")
        row = dict(raw)
        observed = _utc(row.get("observed_at_utc"), name="event IV observed_at_utc")
        row_event = _utc(row.get("event_at_utc"), name="event IV event_at_utc")
        if row_event != event:
            continue
        if observed > cutoff:
            continue
        if row.get("pit_reconstructable") is not True:
            continue
        if row.get("source") in {None, "", "unknown"}:
            continue
        near_days = int(row.get("near_expiry_calendar_days") or 0)
        far_days = int(row.get("far_expiry_calendar_days") or 0)
        if near_days <= 0 or far_days <= near_days:
            raise RicherVolatilityError("Event IV expiries must be explicit and increasing.")
        near_iv = _finite(row.get("near_iv_annualized_percent"), name="near event IV")
        far_iv = _finite(row.get("far_iv_annualized_percent"), name="far event IV")
        if near_iv <= 0 or far_iv <= 0:
            raise RicherVolatilityError("Event IV observations must be positive.")
        eligible.append(
            {
                **row,
                "observed_at_utc": observed.isoformat(),
                "event_at_utc": event.isoformat(),
                "near_expiry_calendar_days": near_days,
                "far_expiry_calendar_days": far_days,
                "near_iv_annualized_percent": _fmt(near_iv),
                "far_iv_annualized_percent": _fmt(far_iv),
            }
        )
    selected = max(eligible, key=lambda row: str(row["observed_at_utc"])) if eligible else None
    if selected is None:
        body: dict[str, Any] = {
            "version": EVENT_IV_KINK_VERSION,
            "as_of_utc": cutoff.isoformat(),
            "event_at_utc": event.isoformat(),
            "state": "unavailable_no_pit_options_term_structure",
            "kink_percentage_points": None,
            "source": None,
            "source_observed_at_utc": None,
            "pit_reconstructable": False,
            "ex_ante_only": True,
            "event_outcome_used": False,
        }
    else:
        near_iv = _finite(selected["near_iv_annualized_percent"], name="near event IV")
        far_iv = _finite(selected["far_iv_annualized_percent"], name="far event IV")
        body = {
            "version": EVENT_IV_KINK_VERSION,
            "as_of_utc": cutoff.isoformat(),
            "event_at_utc": event.isoformat(),
            "state": "known",
            "kink_percentage_points": _fmt(near_iv - far_iv),
            "near_expiry_calendar_days": selected["near_expiry_calendar_days"],
            "far_expiry_calendar_days": selected["far_expiry_calendar_days"],
            "source": selected["source"],
            "source_observed_at_utc": selected["observed_at_utc"],
            "source_identity": selected.get("source_identity"),
            "pit_reconstructable": True,
            "ex_ante_only": True,
            "event_outcome_used": False,
        }
    body["kink_digest"] = digest(body)
    return body


def build_unexplained_market_shock(
    *,
    as_of: datetime | str,
    volatility_z: Any,
    volume_z: Any,
    spread_z: Any,
    cross_asset_reaction_z: Any,
    absolute_z_threshold: Any = "2.5",
    minimum_trigger_count: int = 2,
) -> dict[str, Any]:
    """Detect abnormal market reaction without adding a narrative cause or intent label."""

    cutoff = _utc(as_of, name="as_of")
    threshold = _finite(absolute_z_threshold, name="absolute_z_threshold")
    if threshold <= 0:
        raise RicherVolatilityError("Shock z threshold must be positive.")
    if minimum_trigger_count not in {2, 3, 4}:
        raise RicherVolatilityError("Shock minimum trigger count must be between 2 and 4.")
    inputs = {
        "volatility_z": _finite(volatility_z, name="volatility_z"),
        "volume_z": _finite(volume_z, name="volume_z"),
        "spread_z": _finite(spread_z, name="spread_z"),
        "cross_asset_reaction_z": _finite(
            cross_asset_reaction_z, name="cross_asset_reaction_z"
        ),
    }
    triggered = [name for name, value in inputs.items() if abs(value) >= threshold]
    state = "unexplained_market_shock" if len(triggered) >= minimum_trigger_count else "normal_market_reaction"
    body: dict[str, Any] = {
        "version": UNEXPLAINED_SHOCK_VERSION,
        "as_of_utc": cutoff.isoformat(),
        "state": state,
        "inputs": {name: _fmt(value) for name, value in inputs.items()},
        "absolute_z_threshold": _fmt(threshold),
        "minimum_trigger_count": minimum_trigger_count,
        "trigger_count": len(triggered),
        "triggered_metrics": sorted(triggered),
        "market_derived_only": True,
        "news_or_sentiment_input_used": False,
        "geopolitical_label_used": False,
        "narrative_cause": None,
        "intent_label": None,
    }
    body["shock_digest"] = digest(body)
    return body


def build_richer_volatility_regime(
    *,
    day31_state: Mapping[str, Any],
    shock_state: Mapping[str, Any],
    event_kink: Mapping[str, Any],
) -> dict[str, Any]:
    _verify_day31_contract(day31_state)
    if shock_state.get("version") != UNEXPLAINED_SHOCK_VERSION:
        raise RicherVolatilityError("Invalid unexplained-shock contract.")
    shock_body = dict(shock_state)
    supplied_shock = str(shock_body.pop("shock_digest", ""))
    if not supplied_shock or supplied_shock != digest(shock_body):
        raise RicherVolatilityError("Unexplained-shock digest mismatch.")
    if shock_state.get("market_derived_only") is not True:
        raise RicherVolatilityError("Unexplained shock must remain market-derived only.")
    if shock_state.get("narrative_cause") is not None or shock_state.get("intent_label") is not None:
        raise RicherVolatilityError("Narrative or intent labels are forbidden in unexplained shock.")

    if event_kink.get("version") != EVENT_IV_KINK_VERSION:
        raise RicherVolatilityError("Invalid event-kink contract.")
    kink_body = dict(event_kink)
    supplied_kink = str(kink_body.pop("kink_digest", ""))
    if not supplied_kink or supplied_kink != digest(kink_body):
        raise RicherVolatilityError("Event-kink digest mismatch.")
    if event_kink.get("event_outcome_used") is not False:
        raise RicherVolatilityError("Event-kink state cannot use event outcomes.")

    rv = day31_state["realized_volatility"]
    iv_rv = day31_state["iv_minus_rv"]
    jump = day31_state["jump_continuous"]
    vov = day31_state["vol_of_vol"]
    components = {
        "iv_minus_rv_state": iv_rv["state"],
        "realized_term_structure_state": rv["term_structure_state"],
        "jump_state": jump["state"],
        "vol_of_vol_state": vov["state"],
        "event_iv_kink_state": event_kink["state"],
        "unexplained_market_shock_state": shock_state["state"],
    }
    known_count = sum(
        value not in {
            "unknown",
            "unknown_insufficient_daily_history",
            "unknown_insufficient_intraday_coverage",
            "unknown_insufficient_history",
            "unknown_missing_iv_or_comparable_rv",
            "unavailable_no_pit_options_term_structure",
        }
        for value in components.values()
    )
    body: dict[str, Any] = {
        "version": RICHER_VOLATILITY_VERSION,
        "day31_state_digest": day31_state["volatility_state_digest"],
        "source_mode": day31_state["mode"],
        "components": components,
        "known_component_count": known_count,
        "component_count": len(components),
        "gvz_iv_horizon_calendar_days": 30,
        "rv_horizons_trading_days": [5, 10, 21],
        "iv_rv_comparison_horizons": {
            "iv_calendar_days": 30,
            "rv_trading_days": 21,
            "cross_instrument_proxy": True,
        },
        "jump_estimator": "realized_variation_minus_bipower_variation",
        "vol_of_vol_window_trading_days": 21,
        "redundant_volatility_estimators_added": False,
        "cvol_state": "deferred_pending_gvz_evidence_and_owner_approval",
        "features_shadow_only": True,
        "regime_or_abstention_conditioning_promoted": False,
        "decision_input_allowed": False,
        "formal_forward_evidence_created": False,
        "predictive_edge_claimed": False,
        "trading_gate_created": False,
    }
    body["regime_digest"] = digest(body)
    return body


def day43_experiment_plan(*, day31_foundation: Mapping[str, Any]) -> dict[str, Any]:
    if not verify_j7_j8_foundation(day31_foundation):
        raise RicherVolatilityError("Day 43 requires the valid Day 31 J7/J8 foundation.")
    if day31_foundation.get("foundation_version") != J7_J8_FOUNDATION_VERSION:
        raise RicherVolatilityError("Day 31 J7/J8 foundation version drifted.")
    body: dict[str, Any] = {
        "version": DAY43_EXPERIMENT_PLAN_VERSION,
        "day31_foundation_digest": day31_foundation["foundation_digest"],
        "j7_result_version": J7_RESULT_VERSION,
        "j8_result_version": J8_RESULT_VERSION,
        "j7_hypothesis": (
            "Frozen IV-RV and realised-volatility regime state adds incremental information "
            "about outcome dispersion or intelligent restraint after chronological controls."
        ),
        "j7_null_hypothesis": (
            "Frozen IV-RV and realised-volatility regime state adds no incremental information "
            "after chronological controls."
        ),
        "j8_hypothesis": (
            "Frozen jump-versus-continuous and volatility-instability state differentiates "
            "subsequent outcome dispersion after chronological controls."
        ),
        "j8_null_hypothesis": (
            "Frozen jump-versus-continuous and volatility-instability state does not "
            "differentiate subsequent outcome dispersion after chronological controls."
        ),
        "minimum_independent_evaluation_n": MINIMUM_INDEPENDENT_EVALUATION_N,
        "chronological_split_required": True,
        "purge_required": True,
        "embargo_required": True,
        "episode_independence_required": True,
        "day32_trial_registry_required": True,
        "threshold_tuning_on_evaluation_set_allowed": False,
        "null_or_insufficient_result_allowed": True,
        "single_result_can_promote_gate": False,
        "event_kink_requires_pre_event_pit_options_data": True,
        "unexplained_shock_market_derived_only": True,
        "cvol_purchase_authorized": False,
        "features_shadow_only": True,
        "predictive_edge_claimed": False,
    }
    body["plan_digest"] = digest(body)
    return body


def run_day43_experiment(
    *,
    experiment: str,
    rows: Sequence[Mapping[str, Any]],
    split_binding: Mapping[str, Any],
    minimum_independent_n: int = MINIMUM_INDEPENDENT_EVALUATION_N,
) -> dict[str, Any]:
    if experiment not in {"J7", "J8"}:
        raise RicherVolatilityError("Day 43 experiment must be J7 or J8.")
    if minimum_independent_n < 2:
        raise RicherVolatilityError("Minimum independent N must be at least 2.")
    if split_binding.get("manifest_version") != "aidy_chronological_split_manifest_v1":
        raise RicherVolatilityError("Day 43 requires the Day 37 chronological split contract.")
    if split_binding.get("purge_required") is not True or split_binding.get("embargo_required") is not True:
        raise RicherVolatilityError("Day 43 requires purge and embargo.")
    if split_binding.get("holdout_tuning_allowed") is not False:
        raise RicherVolatilityError("Day 43 cannot tune on holdout.")

    seen: set[str] = set()
    statistics: list[Decimal] = []
    for row in rows:
        episode = str(row.get("independent_episode_id") or "")
        raw_stat = row.get("incremental_statistic")
        if not episode or raw_stat is None or episode in seen:
            continue
        seen.add(episode)
        statistics.append(_finite(raw_stat, name="incremental_statistic"))
    effective_n = len(statistics)
    mean = None if not statistics else sum(statistics, Decimal(0)) / Decimal(effective_n)
    if effective_n < minimum_independent_n:
        result_state = "insufficient"
    elif mean == 0:
        result_state = "null"
    else:
        result_state = "descriptive_non_null"
    body: dict[str, Any] = {
        "version": J7_RESULT_VERSION if experiment == "J7" else J8_RESULT_VERSION,
        "experiment": experiment,
        "split_digest": split_binding.get("split_digest"),
        "raw_rows": len(rows),
        "effective_independent_n": effective_n,
        "minimum_independent_evaluation_n": minimum_independent_n,
        "mean_incremental_statistic": _fmt(mean),
        "result_state": result_state,
        "purge_required": True,
        "embargo_required": True,
        "holdout_tuning_allowed": False,
        "threshold_tuning_on_evaluation_set_allowed": False,
        "null_or_insufficient_result_retained": result_state in {"null", "insufficient"},
        "features_shadow_only": True,
        "proposed_trading_gate": None,
        "gate_promoted": False,
        "predictive_edge_claimed": False,
        "formal_forward_evidence_created": False,
    }
    body["result_digest"] = digest(body)
    return body
