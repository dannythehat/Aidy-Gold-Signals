"""Build 13: Volatility / Jump Expert for AIDY Gold.

The expert classifies volatility conditions that change the usefulness of other
experts. It is context-only: volatility never creates a directional BUY/SELL
forecast here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from itertools import pairwise
from typing import Any

from aidy.feature_engine import Candle, normalize_candles
from aidy.gold_expert_gate_contract import build_expert_gate_packet, verify_expert_gate_packet
from aidy.gold_expert_trust import (
    build_trust_envelope,
    build_trust_scopes,
    select_conditional_trust,
)
from aidy.gold_price_expert_math import verify_price_expert_math_packet

VOLATILITY_JUMP_EXPERT_VERSION = "aidy_gold_volatility_jump_expert_v1"
VOLATILITY_JUMP_GATE_ID = "volatility_jump_expert"
VOLATILITY_TARGET_HORIZON_MINUTES = 15
CLOCK_BASELINE_MINIMUM_N = 20

VOLATILITY_TRUST_REDUCED_CONTEXTS = (
    {
        "name": "clock_volatility",
        "mini_dimensions": [
            "utc_clock_bucket_15m",
            "clock_vol_percentile_band",
            "transition_state",
        ],
        "global_dimensions": [],
        "minimum_sample_n": 12,
    },
    {
        "name": "jump_regime",
        "mini_dimensions": [
            "jump_regime",
            "event_timing_state",
            "vol_of_vol_state",
        ],
        "global_dimensions": [],
        "minimum_sample_n": 10,
    },
    {
        "name": "volatility_regime",
        "mini_dimensions": [
            "rich_regime",
            "simple_atr_band",
            "iv_rv_state",
        ],
        "global_dimensions": [],
        "minimum_sample_n": 8,
    },
)


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("volatility timestamps must be timezone-aware")
    return parsed.astimezone(UTC)


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _fmt(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal("0.000001")), "f")


def _completed_m1(
    rows: Sequence[Mapping[str, Any]],
    *,
    as_of: datetime,
    mode: str,
) -> list[Candle]:
    grouped = normalize_candles(rows, as_of=as_of, symbol="XAUUSD", mode=mode)
    return [
        candle
        for candle in grouped["M1"]
        if candle.open_time_utc + timedelta(minutes=1) <= as_of
    ]


def _contiguous_tail(candles: Sequence[Candle], required: int = 31) -> list[Candle]:
    sample = list(candles[-required:])
    if len(sample) < required:
        return []
    if any(
        right.open_time_utc - left.open_time_utc != timedelta(minutes=1)
        for left, right in pairwise(sample)
    ):
        return []
    return sample


def _rms_return_bps(candles: Sequence[Candle]) -> Decimal | None:
    if len(candles) < 2:
        return None
    returns: list[Decimal] = []
    for left, right in pairwise(candles):
        if left.close == 0:
            return None
        with localcontext() as ctx:
            ctx.prec = 40
            returns.append((right.close / left.close - Decimal(1)) * Decimal(10000))
    if not returns:
        return None
    with localcontext() as ctx:
        ctx.prec = 40
        mean_square = sum((item * item for item in returns), Decimal(0)) / Decimal(
            len(returns)
        )
        return mean_square.sqrt()


def _clock_bucket(timestamp: datetime) -> str:
    minute = (timestamp.minute // 15) * 15
    return f"{timestamp.hour:02d}:{minute:02d}"


def _clock_history_values(
    rows: Sequence[Mapping[str, Any]],
    *,
    bucket: str,
    as_of: datetime,
) -> list[Decimal]:
    values: list[Decimal] = []
    for row in rows:
        if str(row.get("utc_clock_bucket_15m") or "") != bucket:
            continue
        observed = row.get("observed_at_utc")
        if observed is None:
            continue
        try:
            observed_at = _utc(str(observed))
        except ValueError:
            continue
        if observed_at >= as_of:
            continue
        value = _decimal(row.get("realized_vol_bps"))
        if value is None or value < 0:
            continue
        values.append(value)
    return values


def _percentile(value: Decimal | None, history: Sequence[Decimal]) -> Decimal | None:
    if value is None or len(history) < CLOCK_BASELINE_MINIMUM_N:
        return None
    rank = sum(item <= value for item in history)
    return Decimal(rank) / Decimal(len(history))


def _percentile_band(value: Decimal | None) -> str:
    if value is None:
        return "unknown"
    if value <= Decimal("0.20"):
        return "compression"
    if value >= Decimal("0.95"):
        return "extreme_expansion"
    if value >= Decimal("0.80"):
        return "expansion"
    return "normal"


def _clock_normalised(
    candles: Sequence[Candle],
    *,
    as_of: datetime,
    history_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    sample = _contiguous_tail(candles)
    if not sample:
        return {
            "state": "unknown_insufficient_contiguous_m1",
            "current_15m_rv_bps": None,
            "prior_15m_rv_bps": None,
            "current_clock_bucket_15m": _clock_bucket(as_of - timedelta(minutes=1)),
            "prior_clock_bucket_15m": _clock_bucket(as_of - timedelta(minutes=16)),
            "current_clock_sample_n": 0,
            "prior_clock_sample_n": 0,
            "current_clock_percentile": None,
            "prior_clock_percentile": None,
        }

    current = sample[-16:]
    prior = sample[-31:-15]
    current_rv = _rms_return_bps(current)
    prior_rv = _rms_return_bps(prior)
    current_bucket = _clock_bucket(as_of - timedelta(minutes=1))
    prior_bucket = _clock_bucket(as_of - timedelta(minutes=16))
    current_history = _clock_history_values(
        history_rows,
        bucket=current_bucket,
        as_of=as_of,
    )
    prior_history = _clock_history_values(
        history_rows,
        bucket=prior_bucket,
        as_of=as_of,
    )
    current_percentile = _percentile(current_rv, current_history)
    prior_percentile = _percentile(prior_rv, prior_history)
    return {
        "state": (
            "known"
            if current_percentile is not None and prior_percentile is not None
            else "unknown_insufficient_clock_baseline"
        ),
        "current_15m_rv_bps": _fmt(current_rv),
        "prior_15m_rv_bps": _fmt(prior_rv),
        "current_clock_bucket_15m": current_bucket,
        "prior_clock_bucket_15m": prior_bucket,
        "current_clock_sample_n": len(current_history),
        "prior_clock_sample_n": len(prior_history),
        "current_clock_percentile": _fmt(current_percentile),
        "prior_clock_percentile": _fmt(prior_percentile),
        "current_clock_percentile_band": _percentile_band(current_percentile),
        "prior_clock_percentile_band": _percentile_band(prior_percentile),
    }


def _transition(clock_state: Mapping[str, Any]) -> str:
    current = _decimal(clock_state.get("current_clock_percentile"))
    prior = _decimal(clock_state.get("prior_clock_percentile"))
    if current is None or prior is None:
        return "unknown"
    if prior <= Decimal("0.25") and current >= Decimal("0.80"):
        return "compression_to_expansion"
    if prior >= Decimal("0.80") and current <= Decimal("0.30"):
        return "expansion_to_compression"
    if current >= Decimal("0.80"):
        return "expansion_persistent"
    if current <= Decimal("0.20"):
        return "compression_persistent"
    return "stable_normal"


def _simple_atr_band(price_math_packet: Mapping[str, Any]) -> dict[str, Any]:
    payload = price_math_packet["timeframes"]["M15"]
    if payload.get("state") != "known":
        return {
            "state": "unknown",
            "atr_14_bps": None,
            "realized_vol_20_bps": None,
            "rv_to_atr_ratio": None,
            "band": "unknown",
        }
    normal = payload["primitives"]["atr_rv_normalisation"]
    atr = _decimal(normal.get("atr_14_bps"))
    rv = _decimal(normal.get("realized_vol_20_bps"))
    ratio = None if atr in {None, Decimal(0)} or rv is None else rv / atr
    if ratio is None:
        band = "unknown"
    elif ratio <= Decimal("0.60"):
        band = "low"
    elif ratio >= Decimal("1.40"):
        band = "high"
    else:
        band = "normal"
    return {
        "state": "known" if ratio is not None else "unknown",
        "atr_14_bps": _fmt(atr),
        "realized_vol_20_bps": _fmt(rv),
        "rv_to_atr_ratio": _fmt(ratio),
        "band": band,
    }


def _qualified_external_state(
    raw: Mapping[str, Any] | None,
    *,
    as_of: datetime,
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return {
            "state": "unavailable",
            "qualified": False,
            "reason": "missing",
            "jump_continuous": {"state": "unknown"},
            "vol_of_vol": {"state": "unknown"},
            "gvz": {"state": "unknown"},
            "iv_minus_rv": {"state": "unknown"},
        }

    mode = str(raw.get("mode") or "")
    observed = raw.get("as_of_utc")
    try:
        observed_at = _utc(str(observed)) if observed else None
    except ValueError:
        observed_at = None
    pit_ok = mode == "pit" and raw.get("pit_reconstructable") is True
    time_ok = observed_at is not None and observed_at <= as_of
    qualified = pit_ok and time_ok
    reason = "qualified" if qualified else "not_pit_qualified"
    result = {
        "state": str(raw.get("state") or "unknown") if qualified else "unavailable",
        "qualified": qualified,
        "reason": reason,
        "source_as_of_utc": observed_at.isoformat() if observed_at else None,
    }
    for key in ("jump_continuous", "vol_of_vol", "gvz", "iv_minus_rv", "realized_volatility"):
        payload = raw.get(key)
        if qualified and isinstance(payload, Mapping):
            result[key] = dict(payload)
        else:
            result[key] = {"state": "unknown"}
    return result


def _jump_regime(
    *,
    external: Mapping[str, Any],
    transition_state: str,
    event_timing_state: str,
) -> dict[str, Any]:
    jump = external.get("jump_continuous")
    jump = jump if isinstance(jump, Mapping) else {}
    jump_state = str(jump.get("state") or "unknown")
    near_event = event_timing_state in {
        "inside_event_window",
        "near_event_window",
        "inside_near_event_window",
        "event_imminent",
    }
    if jump_state == "jump_dominant" and near_event:
        regime = "event_proximate_jump"
    elif jump_state == "jump_dominant":
        regime = "jump_dominant"
    elif jump_state == "continuous_dominant" and transition_state in {
        "compression_to_expansion",
        "expansion_persistent",
    }:
        regime = "continuous_volatility_expansion"
    elif jump_state == "continuous_dominant":
        regime = "continuous_dominant"
    else:
        regime = "unknown"
    return {
        "state": regime,
        "source_jump_state": jump_state,
        "event_timing_state": event_timing_state,
        "event_proximity_used": near_event,
        "event_causal_claim": False,
        "jump_share": jump.get("jump_share"),
        "estimator": jump.get("estimator"),
    }


def _optional_external_components(external: Mapping[str, Any]) -> dict[str, Any]:
    gvz = external.get("gvz")
    gvz = gvz if isinstance(gvz, Mapping) else {}
    iv_rv = external.get("iv_minus_rv")
    iv_rv = iv_rv if isinstance(iv_rv, Mapping) else {}
    vov = external.get("vol_of_vol")
    vov = vov if isinstance(vov, Mapping) else {}

    gvz_known = str(gvz.get("state") or "unknown") == "known"
    iv_state = str(iv_rv.get("state") or "unknown")
    iv_known = iv_state in {"implied_above_realized", "implied_below_realized", "near_realized"}
    vov_known = str(vov.get("state") or "unknown") == "known"

    return {
        "gvz": {
            "state": "known" if gvz_known else "unknown",
            "value_annualized_percent": gvz.get("value_annualized_percent") if gvz_known else None,
            "underlying_proxy": gvz.get("underlying_proxy") if gvz_known else None,
            "proxy_not_direct_xau_options_iv": True,
        },
        "iv_rv": {
            "state": iv_state if iv_known else "unknown",
            "spread_percentage_points": iv_rv.get("spread_percentage_points") if iv_known else None,
            "cross_instrument_proxy": True,
        },
        "vol_of_vol": {
            "state": "known" if vov_known else "unknown",
            "annualized_vol_dispersion_percent": (
                vov.get("annualized_vol_dispersion_percent") if vov_known else None
            ),
            "window_trading_days": vov.get("window_trading_days") if vov_known else None,
        },
    }


def _rich_regime(
    *,
    clock_state: Mapping[str, Any],
    transition_state: str,
    jump: Mapping[str, Any],
    optional: Mapping[str, Any],
) -> str:
    percentile_band = str(clock_state.get("current_clock_percentile_band") or "unknown")
    jump_state = str(jump.get("state") or "unknown")
    vov = optional["vol_of_vol"]
    vov_state = str(vov.get("state") or "unknown")
    if jump_state == "event_proximate_jump":
        return "event_proximate_jump"
    if jump_state == "jump_dominant":
        return "jump_dominant"
    if transition_state == "compression_to_expansion":
        return "compression_breaking_to_expansion"
    if percentile_band in {"expansion", "extreme_expansion"} and vov_state == "known":
        return "high_volatility_with_known_instability"
    if percentile_band in {"expansion", "extreme_expansion"}:
        return "high_volatility"
    if percentile_band == "compression":
        return "compressed"
    if percentile_band == "normal":
        return "normal"
    return "unknown"


def _context_calculator(
    *,
    calculator_id: str,
    dependency_family: str,
    evidence_ref: str,
    state: str,
    observation: Mapping[str, Any],
    explanation: str,
) -> dict[str, Any]:
    known = state == "known"
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


def summarise_volatility_regime_ablation(
    cases: Sequence[Mapping[str, Any]],
    *,
    minimum_sample_n: int = 20,
) -> dict[str, Any]:
    """Compare simple ATR-band context with richer volatility-regime context."""

    usable = [
        row
        for row in cases
        if row.get("simple_atr_correct") in {0, 1}
        and row.get("rich_regime_correct") in {0, 1}
    ]
    n = len(usable)
    simple = sum(int(row["simple_atr_correct"]) for row in usable)
    rich = sum(int(row["rich_regime_correct"]) for row in usable)
    simple_accuracy = Decimal(simple) / Decimal(n) if n else None
    rich_accuracy = Decimal(rich) / Decimal(n) if n else None
    delta = (
        rich_accuracy - simple_accuracy
        if simple_accuracy is not None and rich_accuracy is not None
        else None
    )
    return {
        "sample_n": n,
        "minimum_sample_n": minimum_sample_n,
        "simple_atr_accuracy": _fmt(simple_accuracy),
        "rich_regime_accuracy": _fmt(rich_accuracy),
        "rich_minus_simple_accuracy": _fmt(delta),
        "richer_regime_incremental_value_proven": (
            n >= minimum_sample_n and delta is not None and delta > Decimal(0)
        ),
        "complexity_grants_no_weight": True,
        "directional_authority": False,
        "research_only": True,
    }


def build_volatility_jump_expert(
    *,
    global_environment: Mapping[str, Any],
    price_math_packet: Mapping[str, Any],
    m1_candle_rows: Sequence[Mapping[str, Any]],
    clock_volatility_history: Sequence[Mapping[str, Any]],
    qualified_volatility_state: Mapping[str, Any] | None = None,
    trust_score_rows_by_subject: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Build one frozen direction-neutral volatility/jump context packet."""

    if not verify_price_expert_math_packet(price_math_packet):
        raise ValueError("price_math_packet must satisfy Build-4 verification")
    as_of = _utc(str(price_math_packet["as_of_utc"]))
    exact = global_environment.get("exact_facts")
    exact = exact if isinstance(exact, Mapping) else {}
    if _utc(str(exact.get("as_of_utc"))) != as_of:
        raise ValueError("volatility expert requires price math and environment at same as-of")

    mode = str(price_math_packet["mode"])
    candles = _completed_m1(m1_candle_rows, as_of=as_of, mode=mode)
    clock_state = _clock_normalised(
        candles,
        as_of=as_of,
        history_rows=clock_volatility_history,
    )
    transition_state = _transition(clock_state)
    simple_atr = _simple_atr_band(price_math_packet)
    external = _qualified_external_state(qualified_volatility_state, as_of=as_of)
    event = exact.get("scheduled_event")
    event = event if isinstance(event, Mapping) else {}
    event_timing = str(event.get("timing_state") or "unknown")
    jump = _jump_regime(
        external=external,
        transition_state=transition_state,
        event_timing_state=event_timing,
    )
    optional = _optional_external_components(external)
    rich_regime = _rich_regime(
        clock_state=clock_state,
        transition_state=transition_state,
        jump=jump,
        optional=optional,
    )

    evidence_inputs = [
        {
            "evidence_id": "volatility_clock_evidence",
            "source": "completed_m1_plus_clock_baseline",
            "path": "volatility.clock_normalised",
            "observed_at_utc": as_of,
            "state": "known" if clock_state["state"] == "known" else "unknown",
            "value": clock_state if clock_state["state"] == "known" else None,
            "provenance": {
                "completed_bars_only": True,
                "future_values_used": False,
                "clock_baseline_minimum_n": CLOCK_BASELINE_MINIMUM_N,
            },
        },
        {
            "evidence_id": "volatility_simple_atr_evidence",
            "source": "aidy_gold_price_expert_math_v1",
            "path": "timeframes.M15.primitives.atr_rv_normalisation",
            "observed_at_utc": as_of,
            "state": "known" if simple_atr["state"] == "known" else "unknown",
            "value": simple_atr if simple_atr["state"] == "known" else None,
            "provenance": {
                "price_math_packet_digest": price_math_packet["packet_digest"],
                "completed_bars_only": True,
                "future_values_used": False,
            },
        },
        {
            "evidence_id": "volatility_jump_evidence",
            "source": "qualified_volatility_intelligence",
            "path": "jump_continuous",
            "observed_at_utc": as_of,
            "state": "known" if jump["state"] != "unknown" else "unknown",
            "value": jump if jump["state"] != "unknown" else None,
            "provenance": {
                "qualified_pit_state": external["qualified"],
                "future_values_used": False,
                "event_causal_claim": False,
            },
        },
        {
            "evidence_id": "volatility_optional_iv_evidence",
            "source": "qualified_volatility_intelligence",
            "path": "gvz_iv_rv_vol_of_vol",
            "observed_at_utc": as_of,
            "state": (
                "known"
                if any(
                    optional[key]["state"] != "unknown"
                    for key in ("gvz", "iv_rv", "vol_of_vol")
                )
                else "unknown"
            ),
            "value": optional,
            "provenance": {
                "qualified_pit_state": external["qualified"],
                "gvz_cross_instrument_proxy": True,
                "future_values_used": False,
            },
        },
    ]

    calculators = [
        _context_calculator(
            calculator_id="volatility_clock_percentile",
            dependency_family="volatility",
            evidence_ref="volatility_clock_evidence",
            state="known" if clock_state["state"] == "known" else "unknown",
            observation=clock_state,
            explanation=(
                "Current 15-minute realised volatility is ranked against prior observations "
                "from the same UTC clock bucket."
            ),
        ),
        _context_calculator(
            calculator_id="volatility_transition",
            dependency_family="volatility",
            evidence_ref="volatility_clock_evidence",
            state="known" if transition_state != "unknown" else "unknown",
            observation={"transition_state": transition_state},
            explanation=f"Volatility transition state={transition_state}.",
        ),
        _context_calculator(
            calculator_id="volatility_jump_continuous",
            dependency_family="volatility",
            evidence_ref="volatility_jump_evidence",
            state="known" if jump["state"] != "unknown" else "unknown",
            observation=jump,
            explanation=(
                f"Jump/continuous regime={jump['state']}. Event proximity is descriptive "
                "only and does not assert causation."
            ),
        ),
        _context_calculator(
            calculator_id="volatility_vol_of_vol",
            dependency_family="volatility",
            evidence_ref="volatility_optional_iv_evidence",
            state="known" if optional["vol_of_vol"]["state"] == "known" else "unknown",
            observation=optional["vol_of_vol"],
            explanation="Vol-of-vol is used only when qualified PIT evidence is available.",
        ),
        _context_calculator(
            calculator_id="volatility_iv_rv_context",
            dependency_family="volatility",
            evidence_ref="volatility_optional_iv_evidence",
            state=(
                "known"
                if optional["gvz"]["state"] == "known"
                or optional["iv_rv"]["state"] != "unknown"
                else "unknown"
            ),
            observation={
                "gvz": optional["gvz"],
                "iv_rv": optional["iv_rv"],
            },
            explanation=(
                "GVZ/IV-RV context remains UNKNOWN when sparse or unqualified and retains "
                "the GLD/XAUUSD cross-instrument proxy caveat."
            ),
        ),
        _context_calculator(
            calculator_id="volatility_simple_atr_baseline",
            dependency_family="volatility",
            evidence_ref="volatility_simple_atr_evidence",
            state="known" if simple_atr["state"] == "known" else "unknown",
            observation=simple_atr,
            explanation=(
                "Simple M15 ATR/RV band is retained as the ablation baseline; richer "
                "complexity receives no automatic extra influence."
            ),
        ),
    ]

    dimensions = global_environment["learning_dimensions"]
    mini_environment = {
        "session": dimensions["session"],
        "session_phase": dimensions["session_phase"],
        "utc_clock_bucket_15m": dimensions["utc_clock_bucket_15m"],
        "clock_vol_percentile_band": str(
            clock_state.get("current_clock_percentile_band") or "unknown"
        ),
        "transition_state": transition_state,
        "jump_regime": jump["state"],
        "event_timing_state": event_timing,
        "vol_of_vol_state": optional["vol_of_vol"]["state"],
        "rich_regime": rich_regime,
        "simple_atr_band": simple_atr["band"],
        "iv_rv_state": optional["iv_rv"]["state"],
    }

    explanation_parts = [
        {
            "text": (
                f"Volatility regime={rich_regime}; clock percentile band="
                f"{clock_state.get('current_clock_percentile_band')}; "
                f"transition={transition_state}; jump state={jump['state']}."
            ),
            "source_refs": [
                "calc:volatility_clock_percentile",
                "calc:volatility_transition",
                "calc:volatility_jump_continuous",
            ],
        },
        {
            "text": (
                "Build 13 is direction-neutral. Volatility changes context and expert "
                "reliability but cannot create a BUY/SELL forecast."
            ),
            "source_refs": ["calc:volatility_simple_atr_baseline"],
        },
    ]

    packet = build_expert_gate_packet(
        gate_id=VOLATILITY_JUMP_GATE_ID,
        gate_version=VOLATILITY_JUMP_EXPERT_VERSION,
        gate_mode="context_only",
        dependency_family="volatility",
        target_horizon_minutes=VOLATILITY_TARGET_HORIZON_MINUTES,
        as_of_utc=as_of,
        global_environment=global_environment,
        mini_environment=mini_environment,
        evidence_inputs=evidence_inputs,
        subcalculators=calculators,
        conclusion="context_only",
        internal_conviction=None,
        explanation_parts=explanation_parts,
        contradictions=(),
    )
    if not verify_expert_gate_packet(packet):
        raise ValueError("constructed Volatility/Jump packet failed Build-2 verification")

    scopes = build_trust_scopes(
        packet=packet,
        reduced_contexts=VOLATILITY_TRUST_REDUCED_CONTEXTS,
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
        "expert_version": VOLATILITY_JUMP_EXPERT_VERSION,
        "expert_packet": packet,
        "clock_normalised": clock_state,
        "transition_state": transition_state,
        "jump_regime": jump,
        "optional_components": optional,
        "simple_atr_baseline": simple_atr,
        "rich_regime": rich_regime,
        "qualified_external_state": {
            "qualified": external["qualified"],
            "reason": external["reason"],
            "source_as_of_utc": external.get("source_as_of_utc"),
        },
        "trust_scopes": scopes,
        "trust_envelope": trust_envelope,
        "direction_policy": {
            "directional_vote_allowed": False,
            "volatility_alone_creates_direction": False,
            "event_proximity_is_causal_claim": False,
        },
        "research_only": True,
        "future_values_used": False,
        "live_money_execution_allowed": False,
    }


__all__ = [
    "CLOCK_BASELINE_MINIMUM_N",
    "VOLATILITY_JUMP_EXPERT_VERSION",
    "VOLATILITY_JUMP_GATE_ID",
    "VOLATILITY_TARGET_HORIZON_MINUTES",
    "VOLATILITY_TRUST_REDUCED_CONTEXTS",
    "build_volatility_jump_expert",
    "summarise_volatility_regime_ablation",
]
