"""Build 24: prospective Gold expert shadow runtime and permanent scorecard.

The runtime attaches the Build 5-22 expert stack to the already-frozen 15-minute
Gold cycle. It is strictly prospective: activation is persisted before eligible
cycles, pre-outcome bundles are immutable, and scoring happens only after the
existing cycle outcome resolver has written a later outcome.

No function in this module grants formal-forward or live-money authority.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy.gold_analogue_episode_expert import (
    ANALOGUE_EPISODE_EXPERT_VERSION,
    ANALOGUE_EPISODE_GATE_ID,
)
from aidy.gold_cycle_environment import verify_cycle_environment
from aidy.gold_d1_context_expert import D1_GATE_ID, build_d1_context_expert
from aidy.gold_environment_gate_selector import (
    build_environment_aware_gate_selector,
    build_gate_selector_input,
)
from aidy.gold_evidence_dependency import (
    build_evidence_dependency_engine,
    extract_dependency_signals,
)
from aidy.gold_expert_gate_contract import (
    build_expert_gate_packet,
    verify_expert_gate_packet,
)
from aidy.gold_expert_trust import (
    aggregate_context_rows,
    build_trust_envelope,
    build_trust_scopes,
    score_directional_outcome,
    score_expert_packet,
    select_conditional_trust,
)
from aidy.gold_futures_microstructure_expert import (
    FUTURES_MICROSTRUCTURE_EXPERT_VERSION,
    FUTURES_MICROSTRUCTURE_GATE_ID,
)
from aidy.gold_h1_price_structure_expert import (
    H1_GATE_ID,
    build_h1_price_structure_expert,
)
from aidy.gold_h4_price_structure_expert import (
    H4_GATE_ID,
    build_h4_price_structure_expert,
)
from aidy.gold_liquidity_reclaim_expert import (
    LIQUIDITY_RECLAIM_GATE_ID,
    build_liquidity_reclaim_expert,
)
from aidy.gold_m15_price_structure_expert import (
    M15_GATE_ID,
    build_m15_price_structure_expert,
)
from aidy.gold_m5_price_structure_expert import (
    M5_GATE_ID,
    build_m5_price_structure_expert,
)
from aidy.gold_macro_event_expert import (
    MACRO_EVENT_EXPERT_VERSION,
    MACRO_EVENT_GATE_ID,
)
from aidy.gold_meta_direction import build_meta_direction_view
from aidy.gold_momentum_impulse_expert import (
    MOMENTUM_IMPULSE_GATE_ID,
    build_momentum_impulse_expert,
)
from aidy.gold_news_movement_mechanism_expert import (
    NEWS_MOVEMENT_MECHANISM_EXPERT_VERSION,
    NEWS_MOVEMENT_MECHANISM_GATE_ID,
)
from aidy.gold_price_expert_math import build_price_expert_math_packet
from aidy.gold_price_location_expert import (
    PRICE_LOCATION_GATE_ID,
    build_price_location_expert,
)
from aidy.gold_rates_usd_cross_asset_expert import (
    RATES_CROSS_ASSET_EXPERT_VERSION,
    RATES_CROSS_ASSET_GATE_ID,
)
from aidy.gold_session_participation_expert import (
    SESSION_PARTICIPATION_GATE_ID,
    build_session_participation_expert,
)
from aidy.gold_volatility_jump_expert import (
    VOLATILITY_JUMP_GATE_ID,
    build_volatility_jump_expert,
)
from aidy.private_forward_context import load_private_forward_snapshot_bundle

GOLD_EXPERT_SHADOW_VERSION = "aidy_gold_expert_shadow_v1"
GOLD_EXPERT_SCORECARD_VERSION = "aidy_gold_expert_scorecard_v1"
SHADOW_HORIZON_MINUTES = 15
DEPENDENCY_LOOKBACK_CYCLES = 120

EXPECTED_GATES = (
    M5_GATE_ID,
    M15_GATE_ID,
    H1_GATE_ID,
    H4_GATE_ID,
    D1_GATE_ID,
    PRICE_LOCATION_GATE_ID,
    MOMENTUM_IMPULSE_GATE_ID,
    LIQUIDITY_RECLAIM_GATE_ID,
    VOLATILITY_JUMP_GATE_ID,
    SESSION_PARTICIPATION_GATE_ID,
    MACRO_EVENT_GATE_ID,
    RATES_CROSS_ASSET_GATE_ID,
    FUTURES_MICROSTRUCTURE_GATE_ID,
    NEWS_MOVEMENT_MECHANISM_GATE_ID,
    ANALOGUE_EPISODE_GATE_ID,
)

_DISCONNECTED_CONTEXT_GATES = {
    MACRO_EVENT_GATE_ID: (MACRO_EVENT_EXPERT_VERSION, "event"),
    RATES_CROSS_ASSET_GATE_ID: (
        RATES_CROSS_ASSET_EXPERT_VERSION,
        "rates_usd",
    ),
    FUTURES_MICROSTRUCTURE_GATE_ID: (
        FUTURES_MICROSTRUCTURE_EXPERT_VERSION,
        "futures_microstructure",
    ),
    NEWS_MOVEMENT_MECHANISM_GATE_ID: (
        NEWS_MOVEMENT_MECHANISM_EXPERT_VERSION,
        "news_mechanism",
    ),
    ANALOGUE_EPISODE_GATE_ID: (
        ANALOGUE_EPISODE_EXPERT_VERSION,
        "analogue",
    ),
}


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str, *, name: str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _decimal(value: Any, *, name: str, default: Decimal | None = None) -> Decimal:
    if value is None and default is not None:
        return default
    if isinstance(value, bool):
        raise TypeError(f"{name} must be numeric")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not parsed.is_finite():
        raise ValueError(f"{name} must be finite")
    return parsed


def _fmt(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN), "f")


def _row(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    try:
        return dict(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise TypeError("Unexpected D1 row shape") from exc


def _results(value: object) -> list[dict[str, Any]]:
    rows = getattr(value, "results", None)
    if rows is None and isinstance(value, dict):
        rows = value.get("results")
    if rows is None:
        return []
    return [row for item in rows if (row := _row(item)) is not None]


def _json(value: Any, *, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (json.JSONDecodeError, TypeError, ValueError):
        return default


def _gate_subject_specs(packet: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    subjects = [
        ("gate", str(packet["gate_id"]), str(packet["gate_version"])),
    ]
    subjects.extend(
        (
            "subcalculator",
            str(item["calculator_id"]),
            str(item["version"]),
        )
        for item in packet["subcalculators"]
    )
    return subjects


def _gate_profile(trust: Mapping[str, Any], gate_id: str) -> dict[str, Any]:
    for row in trust.get("subject_profiles") or []:
        if (
            isinstance(row, Mapping)
            and str(row.get("subject_type")) == "gate"
            and str(row.get("subject_id")) == gate_id
        ):
            profile = row.get("profile")
            return dict(profile) if isinstance(profile, Mapping) else {}
    return {}


def _availability(packet: Mapping[str, Any]) -> str:
    return (
        "available"
        if any(
            isinstance(item, Mapping) and str(item.get("state")) == "known"
            for item in packet.get("subcalculators") or []
        )
        else "explicit_unknown"
    )


def _unknown_context_result(
    *,
    gate_id: str,
    gate_version: str,
    dependency_family: str,
    global_environment: Mapping[str, Any],
    trust_rows_by_subject: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    as_of = str(global_environment["exact_facts"]["as_of_utc"])
    evidence_id = f"{gate_id}_runtime_availability"
    calculator_id = f"{gate_id}_availability"
    packet = build_expert_gate_packet(
        gate_id=gate_id,
        gate_version=gate_version,
        gate_mode="context_only",
        dependency_family=dependency_family,
        target_horizon_minutes=SHADOW_HORIZON_MINUTES,
        as_of_utc=as_of,
        global_environment=global_environment,
        mini_environment={
            "runtime_availability": "explicit_unknown",
            "reason": "source_not_live_connected_to_build24_shadow",
        },
        evidence_inputs=[
            {
                "evidence_id": evidence_id,
                "source": "aidy_gold_expert_shadow_v1",
                "path": f"runtime_availability.{gate_id}",
                "observed_at_utc": as_of,
                "state": "unavailable",
                "value": None,
                "provenance": {
                    "prospective_only": True,
                    "unknown_stays_unknown": True,
                },
            }
        ],
        subcalculators=[
            {
                "calculator_id": calculator_id,
                "version": f"{calculator_id}_v1",
                "role": "context_only",
                "dependency_family": dependency_family,
                "state": "unavailable",
                "vote": "unknown",
                "evidence_refs": [evidence_id],
                "observation": {
                    "availability": "explicit_unknown",
                    "source_connected": False,
                },
                "explanation": (
                    f"{gate_id} is retained as an explicit UNKNOWN because its "
                    "source is not live-connected to the Build-24 PIT cycle."
                ),
            }
        ],
        conclusion="context_only",
        internal_conviction=None,
        explanation_parts=[
            {
                "text": (
                    f"{gate_id} is present but unavailable; no directional "
                    "evidence is invented."
                ),
                "source_refs": [f"calc:{calculator_id}"],
            }
        ],
        contradictions=[],
    )
    scopes = build_trust_scopes(packet=packet)
    rows_by_subject = trust_rows_by_subject or {}
    profiles = {}
    for subject_type, subject_id, _ in _gate_subject_specs(packet):
        key = f"{subject_type}:{subject_id}"
        profiles[key] = select_conditional_trust(
            score_rows=rows_by_subject.get(key, ()),
            scopes=scopes,
        )
    trust = build_trust_envelope(packet=packet, profiles_by_subject=profiles)
    return {
        "expert_version": gate_version,
        "expert_packet": packet,
        "trust_scopes": scopes,
        "trust_envelope": trust,
        "dependency_metadata": {
            calculator_id: {
                "correlation_group": f"{gate_id}_unavailable",
                "later_penalty_tag": "explicit_unknown_no_weight",
            }
        },
        "runtime_availability": "explicit_unknown",
        "research_only": True,
        "future_values_used": False,
        "live_money_execution_allowed": False,
    }


class D1GoldExpertShadowStore:
    def __init__(self, d1: Any) -> None:
        self._d1 = d1

    async def ensure_activation(self, *, now_utc: datetime) -> datetime:
        now = _utc(now_utc, name="now_utc")
        await self._d1.prepare(
            """
            INSERT INTO aidy_gold_expert_shadow_runtime_state (
                singleton_id,activated_at_utc,runtime_version
            ) VALUES (1,?,?)
            ON CONFLICT(singleton_id) DO NOTHING
            """
        ).bind(now.isoformat(), GOLD_EXPERT_SHADOW_VERSION).run()
        row = _row(
            await self._d1.prepare(
                """
                SELECT activated_at_utc
                FROM aidy_gold_expert_shadow_runtime_state
                WHERE singleton_id=1
                """
            ).first()
        )
        if row is None:
            raise RuntimeError("Build 24 activation state was not persisted")
        return _utc(str(row["activated_at_utc"]), name="activated_at_utc")

    async def _environment_for_cycle(
        self,
        *,
        cycle_view_id: str,
    ) -> dict[str, Any]:
        row = _row(
            await self._d1.prepare(
                """
                SELECT environment_json
                FROM aidy_gold_cycle_environments
                WHERE cycle_view_id=?
                LIMIT 1
                """
            ).bind(cycle_view_id).first()
        )
        if row is None:
            raise RuntimeError("Build 24 requires the frozen cycle environment")
        value = _json(row.get("environment_json"), default={})
        if not isinstance(value, dict):
            raise TypeError("stored cycle environment is invalid")
        # The cycle store adds toolbox_coverage after the verified environment
        # digest is created. Remove that additive display field before contract
        # verification; the immutable environment itself is unchanged.
        value.pop("toolbox_coverage", None)
        if not verify_cycle_environment(value):
            raise RuntimeError("stored cycle environment failed verification")
        return value

    async def _logical_history_results(
        self,
        *,
        gate_id: str,
        as_of: datetime,
    ) -> list[dict[str, Any]]:
        result = await self._d1.prepare(
            """
            SELECT result_id,packet_digest,gate_id,gate_version,subject_type,
                   subject_id,subject_version,target_horizon_minutes,
                   scope_key,resolved_at_utc,realised_direction,
                   realised_return_bps,score,correct,impact_class,result_digest
            FROM aidy_gold_expert_outcome_ledger
            WHERE gate_id=? AND resolved_at_utc<?
            ORDER BY resolved_at_utc,result_id,scope_key
            """
        ).bind(gate_id, as_of.isoformat()).all()
        grouped: dict[str, dict[str, Any]] = {}
        for row in _results(result):
            result_id = str(row["result_id"])
            logical = grouped.get(result_id)
            if logical is None:
                logical = {
                    key: row.get(key)
                    for key in (
                        "result_id",
                        "packet_digest",
                        "gate_id",
                        "gate_version",
                        "subject_type",
                        "subject_id",
                        "subject_version",
                        "target_horizon_minutes",
                        "resolved_at_utc",
                        "realised_direction",
                        "realised_return_bps",
                        "score",
                        "correct",
                        "impact_class",
                        "result_digest",
                    )
                }
                logical["scope_keys"] = []
                grouped[result_id] = logical
            logical["scope_keys"].append(str(row["scope_key"]))
        return list(grouped.values())

    async def _trust_rows_for_result(
        self,
        *,
        expert_result: Mapping[str, Any],
        as_of: datetime,
    ) -> dict[str, list[dict[str, Any]]]:
        packet = expert_result["expert_packet"]
        scopes = expert_result["trust_scopes"]
        history = await self._logical_history_results(
            gate_id=str(packet["gate_id"]),
            as_of=as_of,
        )
        output: dict[str, list[dict[str, Any]]] = {}
        for subject_type, subject_id, subject_version in _gate_subject_specs(packet):
            key = f"{subject_type}:{subject_id}"
            output[key] = aggregate_context_rows(
                results=history,
                scopes=scopes,
                subject_type=subject_type,
                subject_id=subject_id,
                subject_version=subject_version,
                as_of_utc=as_of,
            )
        return output

    async def _build_with_history(
        self,
        *,
        builder: Callable[..., dict[str, Any]],
        kwargs: Mapping[str, Any],
        as_of: datetime,
    ) -> dict[str, Any]:
        provisional = builder(**kwargs)
        rows = await self._trust_rows_for_result(
            expert_result=provisional,
            as_of=as_of,
        )
        final_kwargs = dict(kwargs)
        final_kwargs["trust_score_rows_by_subject"] = rows
        final = builder(**final_kwargs)
        if (
            final["expert_packet"]["packet_digest"]
            != provisional["expert_packet"]["packet_digest"]
        ):
            raise RuntimeError("trust history rewrote immutable expert packet")
        return final

    async def _build_unknown_with_history(
        self,
        *,
        gate_id: str,
        gate_version: str,
        dependency_family: str,
        global_environment: Mapping[str, Any],
        as_of: datetime,
    ) -> dict[str, Any]:
        provisional = _unknown_context_result(
            gate_id=gate_id,
            gate_version=gate_version,
            dependency_family=dependency_family,
            global_environment=global_environment,
        )
        rows = await self._trust_rows_for_result(
            expert_result=provisional,
            as_of=as_of,
        )
        return _unknown_context_result(
            gate_id=gate_id,
            gate_version=gate_version,
            dependency_family=dependency_family,
            global_environment=global_environment,
            trust_rows_by_subject=rows,
        )

    async def _build_experts(
        self,
        *,
        environment: Mapping[str, Any],
        snapshot_id: str,
    ) -> list[dict[str, Any]]:
        as_of = _utc(
            str(environment["exact_facts"]["as_of_utc"]),
            name="environment.as_of_utc",
        )
        bundle = await load_private_forward_snapshot_bundle(
            d1=self._d1,
            snapshot_id=snapshot_id,
        )
        snapshot_at = _utc(str(bundle["as_of_utc"]), name="snapshot.as_of_utc")
        if snapshot_at > as_of:
            raise RuntimeError("Build 24 snapshot is later than frozen environment")
        candles = [dict(item) for item in bundle["candles"]]
        price_math = build_price_expert_math_packet(
            as_of=as_of,
            symbol="XAUUSD",
            candle_rows=candles,
            mode="pit",
        )
        m1_rows = [
            item
            for item in candles
            if str(item.get("timeframe") or "").upper() == "M1"
        ]

        common = {
            "global_environment": environment,
            "price_math_packet": price_math,
        }
        results: list[dict[str, Any]] = []
        for builder in (
            build_m5_price_structure_expert,
            build_m15_price_structure_expert,
            build_h1_price_structure_expert,
            build_h4_price_structure_expert,
            build_d1_context_expert,
            build_price_location_expert,
        ):
            results.append(
                await self._build_with_history(
                    builder=builder,
                    kwargs=common,
                    as_of=as_of,
                )
            )

        price_location = next(
            item
            for item in results
            if item["expert_packet"]["gate_id"] == PRICE_LOCATION_GATE_ID
        )
        results.append(
            await self._build_with_history(
                builder=build_momentum_impulse_expert,
                kwargs={
                    **common,
                    "m1_candle_rows": m1_rows,
                },
                as_of=as_of,
            )
        )
        results.append(
            await self._build_with_history(
                builder=build_liquidity_reclaim_expert,
                kwargs={
                    **common,
                    "price_location_result": price_location,
                    "m1_candle_rows": m1_rows,
                    "retrospective_gc_flow_rows": (),
                },
                as_of=as_of,
            )
        )
        results.append(
            await self._build_with_history(
                builder=build_volatility_jump_expert,
                kwargs={
                    **common,
                    "m1_candle_rows": m1_rows,
                    "clock_volatility_history": (),
                    "qualified_volatility_state": None,
                },
                as_of=as_of,
            )
        )
        results.append(
            await self._build_with_history(
                builder=build_session_participation_expert,
                kwargs={
                    "global_environment": environment,
                    "m1_candle_rows": m1_rows,
                    "weekday_clock_history": (),
                    "gc_activity_context": None,
                },
                as_of=as_of,
            )
        )

        for gate_id, (version, family) in _DISCONNECTED_CONTEXT_GATES.items():
            results.append(
                await self._build_unknown_with_history(
                    gate_id=gate_id,
                    gate_version=version,
                    dependency_family=family,
                    global_environment=environment,
                    as_of=as_of,
                )
            )

        by_gate = {
            str(item["expert_packet"]["gate_id"]): item
            for item in results
        }
        if set(by_gate) != set(EXPECTED_GATES):
            missing = sorted(set(EXPECTED_GATES) - set(by_gate))
            extra = sorted(set(by_gate) - set(EXPECTED_GATES))
            raise RuntimeError(
                f"Build 24 gate registry mismatch: missing={missing} extra={extra}"
            )
        return [by_gate[gate_id] for gate_id in EXPECTED_GATES]

    async def _dependency_history(
        self,
        *,
        as_of: datetime,
    ) -> list[dict[str, Any]]:
        result = await self._d1.prepare(
            """
            WITH recent AS (
                SELECT cycle_view_id,decided_at_utc
                FROM aidy_gold_expert_shadow_cycles
                WHERE decided_at_utc<?
                ORDER BY decided_at_utc DESC
                LIMIT ?
            )
            SELECT r.cycle_view_id,r.decided_at_utc,
                   s.gate_id,s.calculator_id,s.vote
            FROM recent r
            JOIN aidy_gold_expert_subcalculator_snapshots s
              ON s.cycle_view_id=r.cycle_view_id
            ORDER BY r.decided_at_utc,r.cycle_view_id,s.gate_id,s.calculator_id
            """
        ).bind(as_of.isoformat(), DEPENDENCY_LOOKBACK_CYCLES).all()
        grouped: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
        for row in _results(result):
            key = (str(row["cycle_view_id"]), str(row["decided_at_utc"]))
            signal_id = f"{row['gate_id']}:{row['calculator_id']}"
            grouped[key][signal_id] = str(row["vote"])
        return [
            {
                "observed_at_utc": decided_at,
                "signals": dict(sorted(signals.items())),
            }
            for (_, decided_at), signals in sorted(
                grouped.items(),
                key=lambda item: item[0][1],
            )
        ]

    async def _build_shadow_bundle(
        self,
        *,
        cycle: Mapping[str, Any],
    ) -> dict[str, Any]:
        cycle_view_id = str(cycle["cycle_view_id"])
        environment = await self._environment_for_cycle(
            cycle_view_id=cycle_view_id,
        )
        as_of = _utc(str(cycle["decided_at_utc"]), name="decided_at_utc")
        environment_as_of = _utc(
            str(environment["exact_facts"]["as_of_utc"]),
            name="environment.as_of_utc",
        )
        if environment_as_of != as_of:
            raise RuntimeError("cycle and environment as-of mismatch")

        experts = await self._build_experts(
            environment=environment,
            snapshot_id=str(cycle["source_snapshot_id"]),
        )
        signals = extract_dependency_signals(experts)
        dependency = build_evidence_dependency_engine(
            signals=signals,
            historical_rows=await self._dependency_history(as_of=as_of),
            as_of_utc=as_of,
        )
        selector = build_environment_aware_gate_selector(
            global_environment=environment,
            expected_gate_ids=EXPECTED_GATES,
            gate_inputs=[build_gate_selector_input(item) for item in experts],
            dependency_engine=dependency,
            calibration_rows=(),
        )
        meta_view = build_meta_direction_view(
            global_environment=environment,
            selector=selector,
            expert_results=experts,
            meta_calibration_rows=(),
        )
        body = {
            "shadow_version": GOLD_EXPERT_SHADOW_VERSION,
            "cycle_view_id": cycle_view_id,
            "source_snapshot_id": str(cycle["source_snapshot_id"]),
            "decided_at_utc": as_of.isoformat(),
            "window_start_utc": str(cycle["window_start_utc"]),
            "window_end_utc": str(cycle["window_end_utc"]),
            "environment_key": str(environment["environment_key"]),
            "environment_version": str(environment["environment_version"]),
            "expert_packet_digests": {
                str(item["expert_packet"]["gate_id"]): str(
                    item["expert_packet"]["packet_digest"]
                )
                for item in experts
            },
            "dependency_digest": dependency["engine_digest"],
            "selector_digest": selector["selector_digest"],
            "meta_view_digest": meta_view["view_digest"],
            "expected_gate_n": len(EXPECTED_GATES),
            "future_values_used": False,
            "research_only": True,
            "formal_forward_authority": False,
            "live_money_execution_allowed": False,
        }
        body["bundle_digest"] = _digest(body)
        return {
            "identity": body,
            "environment": environment,
            "experts": experts,
            "dependency": dependency,
            "selector": selector,
            "meta_view": meta_view,
        }

    async def _store_shadow_bundle(
        self,
        *,
        bundle: Mapping[str, Any],
        created_at: datetime,
    ) -> None:
        identity = bundle["identity"]
        experts = bundle["experts"]
        selector = bundle["selector"]
        dependency = bundle["dependency"]
        meta_view = bundle["meta_view"]
        selector_by_gate = {
            str(item["gate_id"]): item
            for item in selector["all_gates"]
        }
        known_gate_n = sum(
            _availability(item["expert_packet"]) == "available"
            for item in experts
        )
        unknown_gate_n = len(EXPECTED_GATES) - known_gate_n

        await self._d1.prepare(
            """
            INSERT INTO aidy_gold_expert_shadow_cycles (
                cycle_view_id,source_snapshot_id,decided_at_utc,window_start_utc,
                window_end_utc,environment_key,environment_version,
                expected_gate_n,known_gate_n,explicit_unknown_gate_n,
                dependency_json,dependency_digest,selector_json,selector_digest,
                meta_view_json,meta_view_digest,bundle_digest,created_at_utc
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(cycle_view_id) DO NOTHING
            """
        ).bind(
            identity["cycle_view_id"],
            identity["source_snapshot_id"],
            identity["decided_at_utc"],
            identity["window_start_utc"],
            identity["window_end_utc"],
            identity["environment_key"],
            identity["environment_version"],
            len(EXPECTED_GATES),
            known_gate_n,
            unknown_gate_n,
            _canonical_json(dependency),
            dependency["engine_digest"],
            _canonical_json(selector),
            selector["selector_digest"],
            _canonical_json(meta_view),
            meta_view["view_digest"],
            identity["bundle_digest"],
            created_at.isoformat(),
        ).run()

        for expert in experts:
            packet = expert["expert_packet"]
            trust = expert["trust_envelope"]
            scopes = expert["trust_scopes"]
            gate_id = str(packet["gate_id"])
            selected = selector_by_gate[gate_id]
            await self._d1.prepare(
                """
                INSERT INTO aidy_gold_expert_gate_snapshots (
                    cycle_view_id,gate_id,gate_version,gate_mode,dependency_family,
                    conclusion,gate_scoreable,availability_state,packet_json,
                    packet_digest,trust_json,trust_digest,trust_scopes_json,
                    selector_classification,trust_score,observation_weight,
                    directional_authority_weight,mini_environment_digest,
                    mini_environment_json,decided_at_utc
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(cycle_view_id,gate_id) DO NOTHING
                """
            ).bind(
                identity["cycle_view_id"],
                gate_id,
                str(packet["gate_version"]),
                str(packet["gate_mode"]),
                str(packet["dependency_family"]),
                str(packet["conclusion"]),
                int(bool(packet["gate_scoreable"])),
                _availability(packet),
                _canonical_json(packet),
                str(packet["packet_digest"]),
                _canonical_json(trust),
                str(trust["trust_digest"]),
                _canonical_json(scopes),
                str(selected["classification"]),
                str(selected["trust_score"]),
                str(selected["observation_weight"]),
                str(selected["directional_authority_weight"]),
                str(packet["mini_environment"]["mini_environment_digest"]),
                _canonical_json(packet["mini_environment"]),
                identity["decided_at_utc"],
            ).run()

            for calculator in packet["subcalculators"]:
                await self._d1.prepare(
                    """
                    INSERT INTO aidy_gold_expert_subcalculator_snapshots (
                        cycle_view_id,gate_id,calculator_id,calculator_version,
                        role,dependency_family,state,vote,strength,scoreable,
                        observation_json,evidence_refs_json,explanation,
                        calculator_digest,decided_at_utc
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(cycle_view_id,gate_id,calculator_id) DO NOTHING
                    """
                ).bind(
                    identity["cycle_view_id"],
                    gate_id,
                    str(calculator["calculator_id"]),
                    str(calculator["version"]),
                    str(calculator["role"]),
                    str(calculator["dependency_family"]),
                    str(calculator["state"]),
                    str(calculator["vote"]),
                    calculator.get("strength"),
                    int(bool(calculator["scoreable"])),
                    _canonical_json(calculator["observation"]),
                    _canonical_json(calculator["evidence_refs"]),
                    str(calculator["explanation"]),
                    str(calculator["calculator_digest"]),
                    identity["decided_at_utc"],
                ).run()

    async def create_new_cycles(
        self,
        *,
        now_utc: datetime,
        limit: int = 4,
    ) -> dict[str, Any]:
        now = _utc(now_utc, name="now_utc")
        activated = await self.ensure_activation(now_utc=now)
        result = await self._d1.prepare(
            """
            SELECT v.cycle_view_id,v.source_snapshot_id,v.decided_at_utc,
                   v.window_start_utc,v.window_end_utc
            FROM aidy_gold_cycle_views v
            LEFT JOIN aidy_gold_expert_shadow_cycles s
              ON s.cycle_view_id=v.cycle_view_id
            WHERE s.cycle_view_id IS NULL
              AND v.decided_at_utc>=?
              AND v.decided_at_utc<=?
            ORDER BY v.decided_at_utc
            LIMIT ?
            """
        ).bind(
            activated.isoformat(),
            now.isoformat(),
            max(1, min(int(limit), 20)),
        ).all()
        created = 0
        latest: dict[str, Any] | None = None
        for cycle in _results(result):
            bundle = await self._build_shadow_bundle(cycle=cycle)
            await self._store_shadow_bundle(bundle=bundle, created_at=now)
            created += 1
            latest = {
                "cycle_view_id": bundle["identity"]["cycle_view_id"],
                "meta_direction": bundle["meta_view"]["direction"],
                "expected_gate_n": len(EXPECTED_GATES),
                "known_gate_n": sum(
                    _availability(item["expert_packet"]) == "available"
                    for item in bundle["experts"]
                ),
            }
        return {
            "created": created,
            "activation_at_utc": activated.isoformat(),
            "latest": latest,
        }

    async def _insert_expert_results(
        self,
        *,
        packet: Mapping[str, Any],
        scopes: Sequence[Mapping[str, Any]],
        resolved_at: datetime,
        realised_direction: str,
        realised_return_bps: Any,
    ) -> None:
        scored = score_expert_packet(
            packet=packet,
            scopes=scopes,
            resolved_at_utc=resolved_at,
            realised_direction=realised_direction,
            realised_return_bps=realised_return_bps,
        )
        scope_type_by_key = {
            str(scope["scope_key"]): str(scope["scope_type"])
            for scope in scopes
        }
        for result in scored:
            for scope_key in result["scope_keys"]:
                await self._d1.prepare(
                    """
                    INSERT INTO aidy_gold_expert_outcome_ledger (
                        result_id,packet_digest,gate_id,gate_version,
                        subject_type,subject_id,subject_version,
                        target_horizon_minutes,scope_key,scope_type,
                        resolved_at_utc,realised_direction,realised_return_bps,
                        score,correct,impact_class,result_digest
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(result_id,scope_key) DO NOTHING
                    """
                ).bind(
                    result["result_id"],
                    result["packet_digest"],
                    result["gate_id"],
                    result["gate_version"],
                    result["subject_type"],
                    result["subject_id"],
                    result["subject_version"],
                    result["target_horizon_minutes"],
                    scope_key,
                    scope_type_by_key[scope_key],
                    result["resolved_at_utc"],
                    result["realised_direction"],
                    result["realised_return_bps"],
                    result["score"],
                    result["correct"],
                    result["impact_class"],
                    result["result_digest"],
                ).run()

        await self._refresh_context_scores(
            packet=packet,
            scopes=scopes,
            as_of=resolved_at + timedelta(microseconds=1),
        )

    async def _refresh_context_scores(
        self,
        *,
        packet: Mapping[str, Any],
        scopes: Sequence[Mapping[str, Any]],
        as_of: datetime,
    ) -> None:
        history = await self._logical_history_results(
            gate_id=str(packet["gate_id"]),
            as_of=as_of,
        )
        for subject_type, subject_id, subject_version in _gate_subject_specs(packet):
            rows = aggregate_context_rows(
                results=history,
                scopes=scopes,
                subject_type=subject_type,
                subject_id=subject_id,
                subject_version=subject_version,
                as_of_utc=as_of,
            )
            for row in rows:
                scope_key = str(row["scope_key"])
                unscoreable_n = sum(
                    1
                    for item in history
                    if str(item.get("subject_type")) == subject_type
                    and str(item.get("subject_id")) == subject_id
                    and str(item.get("subject_version")) == subject_version
                    and scope_key in (item.get("scope_keys") or [])
                    and item.get("correct") not in {0, 1}
                )
                await self._d1.prepare(
                    """
                    INSERT INTO aidy_gold_expert_context_scores (
                        subject_type,subject_id,subject_version,gate_id,
                        scope_key,scope_type,horizon_minutes,
                        sample_n,correct_n,incorrect_n,unscoreable_n,
                        net_score,score_mean,accuracy,recent_window,
                        recent_sample_n,recent_correct_n,recent_net_score,
                        recent_accuracy,first_resolved_at_utc,last_resolved_at_utc
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(
                        subject_type,subject_id,subject_version,scope_key,horizon_minutes
                    ) DO UPDATE SET
                        gate_id=excluded.gate_id,
                        scope_type=excluded.scope_type,
                        sample_n=excluded.sample_n,
                        correct_n=excluded.correct_n,
                        incorrect_n=excluded.incorrect_n,
                        unscoreable_n=excluded.unscoreable_n,
                        net_score=excluded.net_score,
                        score_mean=excluded.score_mean,
                        accuracy=excluded.accuracy,
                        recent_window=excluded.recent_window,
                        recent_sample_n=excluded.recent_sample_n,
                        recent_correct_n=excluded.recent_correct_n,
                        recent_net_score=excluded.recent_net_score,
                        recent_accuracy=excluded.recent_accuracy,
                        first_resolved_at_utc=excluded.first_resolved_at_utc,
                        last_resolved_at_utc=excluded.last_resolved_at_utc
                    """
                ).bind(
                    subject_type,
                    subject_id,
                    subject_version,
                    str(packet["gate_id"]),
                    scope_key,
                    str(row["scope_type"]),
                    int(packet["target_horizon_minutes"]),
                    int(row["sample_n"]),
                    int(row["correct_n"]),
                    int(row["incorrect_n"]),
                    unscoreable_n,
                    int(row["net_score"]),
                    row["score_mean"],
                    row["accuracy"],
                    int(row["recent_window"]),
                    int(row["recent_sample_n"]),
                    int(row["recent_correct_n"]),
                    int(row["recent_net_score"]),
                    row["recent_accuracy"],
                    row["first_resolved_at_utc"],
                    row["last_resolved_at_utc"],
                ).run()

    async def score_resolved_cycles(
        self,
        *,
        now_utc: datetime,
        limit: int = 20,
    ) -> dict[str, int]:
        now = _utc(now_utc, name="now_utc")
        result = await self._d1.prepare(
            """
            SELECT s.cycle_view_id,s.meta_view_json,
                   o.resolved_at_utc,o.realised_direction,o.return_bps
            FROM aidy_gold_expert_shadow_cycles s
            JOIN aidy_gold_cycle_outcomes o
              ON o.cycle_view_id=s.cycle_view_id
            LEFT JOIN aidy_gold_meta_view_results r
              ON r.cycle_view_id=s.cycle_view_id
            WHERE r.cycle_view_id IS NULL
              AND o.resolved_at_utc<=?
            ORDER BY o.resolved_at_utc
            LIMIT ?
            """
        ).bind(now.isoformat(), max(1, min(int(limit), 100))).all()
        scored_cycles = 0
        gate_packets_scored = 0
        for cycle in _results(result):
            cycle_view_id = str(cycle["cycle_view_id"])
            resolved_at = _utc(
                str(cycle["resolved_at_utc"]),
                name="resolved_at_utc",
            )
            realised_direction = str(cycle["realised_direction"])
            realised_return_bps = cycle.get("return_bps")

            gate_rows = await self._d1.prepare(
                """
                SELECT packet_json,trust_scopes_json
                FROM aidy_gold_expert_gate_snapshots
                WHERE cycle_view_id=?
                ORDER BY gate_id
                """
            ).bind(cycle_view_id).all()
            for gate_row in _results(gate_rows):
                packet = _json(gate_row["packet_json"], default={})
                scopes = _json(gate_row["trust_scopes_json"], default=[])
                if not verify_expert_gate_packet(packet):
                    raise RuntimeError("stored Build 24 expert packet failed verification")
                if not isinstance(scopes, list):
                    raise TypeError("stored Build 24 trust scopes are invalid")
                await self._insert_expert_results(
                    packet=packet,
                    scopes=scopes,
                    resolved_at=resolved_at,
                    realised_direction=realised_direction,
                    realised_return_bps=realised_return_bps,
                )
                gate_packets_scored += 1

            meta = _json(cycle["meta_view_json"], default={})
            frozen_direction = str(meta.get("direction") or "abstain")
            scored = score_directional_outcome(
                vote=frozen_direction,
                realised_direction=realised_direction,
                realised_return_bps=realised_return_bps,
                scoreable=frozen_direction in {"bullish", "bearish", "neutral"},
            )
            result_body = {
                "cycle_view_id": cycle_view_id,
                "resolved_at_utc": resolved_at.isoformat(),
                "frozen_direction": frozen_direction,
                "realised_direction": realised_direction,
                "realised_return_bps": realised_return_bps,
                "score": int(scored["score"]),
                "correct": scored["correct"],
            }
            result_digest = _digest(result_body)
            await self._d1.prepare(
                """
                INSERT INTO aidy_gold_meta_view_results (
                    cycle_view_id,resolved_at_utc,frozen_direction,
                    realised_direction,realised_return_bps,score,correct,
                    result_digest
                ) VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(cycle_view_id) DO NOTHING
                """
            ).bind(
                cycle_view_id,
                resolved_at.isoformat(),
                frozen_direction,
                realised_direction,
                realised_return_bps,
                int(scored["score"]),
                scored["correct"],
                result_digest,
            ).run()
            scored_cycles += 1
        return {
            "scored_cycles": scored_cycles,
            "gate_packets_scored": gate_packets_scored,
        }

    async def scorecard_snapshot(
        self,
        *,
        as_of_utc: datetime,
    ) -> dict[str, Any]:
        as_of = _utc(as_of_utc, name="as_of_utc")
        cycle = _row(
            await self._d1.prepare(
                """
                SELECT cycle_view_id,decided_at_utc,window_start_utc,
                       environment_key,selector_json,meta_view_json
                FROM aidy_gold_expert_shadow_cycles
                WHERE decided_at_utc<=?
                ORDER BY decided_at_utc DESC
                LIMIT 1
                """
            ).bind(as_of.isoformat()).first()
        )
        if cycle is None:
            return {
                "scorecard_version": GOLD_EXPERT_SCORECARD_VERSION,
                "as_of_utc": as_of.isoformat(),
                "state": "no_prospective_shadow_cycle_yet",
                "gates": [],
                "research_only": True,
                "formal_forward_authority": False,
                "live_money_execution_allowed": False,
            }

        selector = _json(cycle["selector_json"], default={})
        selector_by_gate = {
            str(item.get("gate_id")): item
            for item in selector.get("all_gates") or []
            if isinstance(item, Mapping)
        }
        gates_result = await self._d1.prepare(
            """
            SELECT gate_id,gate_version,gate_mode,dependency_family,
                   conclusion,availability_state,trust_json,
                   selector_classification,trust_score,observation_weight,
                   directional_authority_weight,mini_environment_json,
                   decided_at_utc
            FROM aidy_gold_expert_gate_snapshots
            WHERE cycle_view_id=?
            ORDER BY gate_id
            """
        ).bind(str(cycle["cycle_view_id"])).all()
        last_scores_result = await self._d1.prepare(
            """
            SELECT gate_id,MAX(resolved_at_utc) AS last_score_time
            FROM aidy_gold_expert_outcome_ledger
            WHERE subject_type='gate' AND resolved_at_utc<=?
            GROUP BY gate_id
            """
        ).bind(as_of.isoformat()).all()
        last_scores = {
            str(row["gate_id"]): row.get("last_score_time")
            for row in _results(last_scores_result)
        }

        gates: list[dict[str, Any]] = []
        for row in _results(gates_result):
            gate_id = str(row["gate_id"])
            trust = _json(row["trust_json"], default={})
            profile = _gate_profile(trust, gate_id)
            selector_row = selector_by_gate.get(gate_id) or {}
            gates.append(
                {
                    "gate_id": gate_id,
                    "gate_version": str(row["gate_version"]),
                    "gate_mode": str(row["gate_mode"]),
                    "dependency_family": str(row["dependency_family"]),
                    "availability_state": str(row["availability_state"]),
                    "current_conclusion": str(row["conclusion"]),
                    "mini_environment": _json(
                        row["mini_environment_json"],
                        default={},
                    ),
                    "sample_n": int(profile.get("sample_n") or 0),
                    "raw_reliability": profile.get("raw_accuracy"),
                    "shrunk_reliability": profile.get("shrunk_accuracy"),
                    "net_score": int(profile.get("net_score") or 0),
                    "recent_accuracy": profile.get("recent_accuracy"),
                    "drift": str(
                        profile.get("recent_state") or "insufficient_recent"
                    ),
                    "uncertainty": str(
                        profile.get("uncertainty_state") or "unknown"
                    ),
                    "selected_scope_type": str(
                        profile.get("selected_scope_type") or "neutral_prior"
                    ),
                    "current_trust_classification": str(
                        row["selector_classification"]
                    ),
                    "current_trust_score": str(row["trust_score"]),
                    "observation_weight": str(row["observation_weight"]),
                    "directional_authority_weight": str(
                        row["directional_authority_weight"]
                    ),
                    "dependency_adjustment": dict(
                        selector_row.get("dependency_adjustment") or {}
                    ),
                    "calibration": dict(
                        selector_row.get("calibration_adjustment") or {}
                    ),
                    "last_score_time_utc": last_scores.get(gate_id),
                }
            )

        meta = _json(cycle["meta_view_json"], default={})
        body = {
            "scorecard_version": GOLD_EXPERT_SCORECARD_VERSION,
            "as_of_utc": as_of.isoformat(),
            "state": "active",
            "latest_cycle_view_id": str(cycle["cycle_view_id"]),
            "latest_cycle_decided_at_utc": str(cycle["decided_at_utc"]),
            "latest_window_start_utc": str(cycle["window_start_utc"]),
            "environment_key": str(cycle["environment_key"]),
            "gate_count": len(gates),
            "gates": gates,
            "latest_aidy_view": {
                "direction": meta.get("direction"),
                "confidence_state": meta.get("confidence_state"),
                "calibrated_confidence": meta.get("calibrated_confidence"),
                "readable_why": meta.get("readable_why"),
            },
            "research_only": True,
            "formal_forward_authority": False,
            "live_money_execution_allowed": False,
        }
        body["scorecard_digest"] = _digest(body)
        return body


async def ensure_gold_expert_shadow_activation(
    d1: Any,
    *,
    now_utc: datetime,
) -> dict[str, Any]:
    store = D1GoldExpertShadowStore(d1)
    activated = await store.ensure_activation(now_utc=now_utc)
    return {
        "shadow_version": GOLD_EXPERT_SHADOW_VERSION,
        "activated_at_utc": activated.isoformat(),
        "prospective_only": True,
        "research_only": True,
        "formal_forward_authority": False,
        "live_money_execution_allowed": False,
    }


async def sync_gold_expert_shadow(
    d1: Any,
    *,
    now_utc: datetime,
) -> dict[str, Any]:
    now = _utc(now_utc, name="now_utc")
    store = D1GoldExpertShadowStore(d1)
    activation = await store.ensure_activation(now_utc=now)
    scoring = await store.score_resolved_cycles(now_utc=now)
    creation = await store.create_new_cycles(now_utc=now)
    scorecard = await store.scorecard_snapshot(as_of_utc=now)
    result = {
        "shadow_version": GOLD_EXPERT_SHADOW_VERSION,
        "scorecard_version": GOLD_EXPERT_SCORECARD_VERSION,
        "observed_at_utc": now.isoformat(),
        "activated_at_utc": activation.isoformat(),
        "scoring": scoring,
        "creation": creation,
        "scorecard_state": scorecard.get("state"),
        "latest_cycle_view_id": scorecard.get("latest_cycle_view_id"),
        "latest_meta_direction": (
            (scorecard.get("latest_aidy_view") or {}).get("direction")
            if isinstance(scorecard.get("latest_aidy_view"), Mapping)
            else None
        ),
        "research_only": True,
        "formal_forward_authority": False,
        "live_money_execution_allowed": False,
    }
    result["sync_digest"] = _digest(result)
    return result


__all__ = [
    "DEPENDENCY_LOOKBACK_CYCLES",
    "EXPECTED_GATES",
    "GOLD_EXPERT_SCORECARD_VERSION",
    "GOLD_EXPERT_SHADOW_VERSION",
    "D1GoldExpertShadowStore",
    "ensure_gold_expert_shadow_activation",
    "sync_gold_expert_shadow",
]
