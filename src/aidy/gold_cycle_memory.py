"""Continuous 15-minute Gold cycle learning.

This is an additive research lens inside AIDY's wider Gold-first intelligence system.
It freezes a point-in-time view before a target 15-minute window, stores the reasons
and toolbox evidence behind that view, and attaches the realised path only after the
window closes. Retrospective analogues remain explicitly non-PIT research evidence.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy.gold_movement_investigator import verify_gold_movement_investigation
from aidy.gold_state_engine import verify_gold_state_engine
from aidy.gold_toolbox_registry import verify_gold_toolbox_manifest
from aidy.private_forward_context import build_private_forward_decision_inputs

GOLD_CYCLE_MEMORY_VERSION = "aidy_gold_cycle_memory_v1"
GOLD_CYCLE_VIEW_VERSION = "aidy_gold_cycle_view_v1"
GOLD_CYCLE_OUTCOME_VERSION = "aidy_gold_cycle_outcome_v1"
CYCLE_WINDOW_MINUTES = 15
CYCLE_VIEW_LEAD_MINUTES = 5
CYCLE_NEUTRAL_BAND_BPS = Decimal("2.000000")


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode()).hexdigest()


def _utc(value: datetime | str, *, name: str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware.")
    return parsed.astimezone(UTC)


def _row(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    try:
        return dict(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise TypeError("Unexpected D1 row shape.") from exc


def _results(value: object) -> list[dict[str, Any]]:
    rows = getattr(value, "results", None)
    if rows is None and isinstance(value, dict):
        rows = value.get("results")
    if rows is None:
        return []
    return [row for item in rows if (row := _row(item)) is not None]


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
    return format(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN), "f")


def _direction_vote(value: str | None) -> int:
    return {
        "up": 1,
        "bullish": 1,
        "down": -1,
        "bearish": -1,
    }.get(str(value or "").lower(), 0)


def _state_from_return(return_bps: Decimal | None) -> str:
    if return_bps is None:
        return "unknown"
    if return_bps > CYCLE_NEUTRAL_BAND_BPS:
        return "bullish"
    if return_bps < -CYCLE_NEUTRAL_BAND_BPS:
        return "bearish"
    return "neutral"


def _next_window_start(now: datetime) -> datetime:
    current = _utc(now, name="now")
    base = current.replace(second=0, microsecond=0)
    bucket_minute = (base.minute // CYCLE_WINDOW_MINUTES) * CYCLE_WINDOW_MINUTES
    bucket = base.replace(minute=bucket_minute)
    return bucket + timedelta(minutes=CYCLE_WINDOW_MINUTES)


def _observed_state(gold_state: Mapping[str, Any]) -> tuple[str, str | None]:
    move = gold_state.get("move_observation")
    move = move if isinstance(move, Mapping) else {}
    windows = move.get("windows")
    windows = windows if isinstance(windows, Mapping) else {}
    m15 = windows.get("15m")
    m15 = m15 if isinstance(m15, Mapping) else {}
    value = _decimal(m15.get("return_bps"))
    return _state_from_return(value), _fmt(value)


def _reason(
    *,
    surface: str,
    observation: str,
    vote: int,
    weight: int,
    source_path: str,
) -> dict[str, Any]:
    return {
        "surface": surface,
        "observation": observation,
        "vote": "bullish" if vote > 0 else "bearish" if vote < 0 else "neutral",
        "weight": weight,
        "source_path": source_path,
    }


def build_cycle_view_payload(
    *,
    as_of: datetime,
    window_start: datetime,
    session_code: str,
    gold_state: Mapping[str, Any],
    movement_investigation: Mapping[str, Any],
    toolbox_manifest: Mapping[str, Any],
    prior_observed_states: list[str],
    analogue_summary: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one frozen and auditable 15-minute Gold research view."""

    if not verify_gold_state_engine(gold_state):
        raise ValueError("cycle_view_requires_verified_gold_state")
    if movement_investigation and not verify_gold_movement_investigation(
        movement_investigation
    ):
        raise ValueError("cycle_view_requires_verified_movement_investigation")
    if not verify_gold_toolbox_manifest(toolbox_manifest):
        raise ValueError("cycle_view_requires_verified_toolbox_manifest")

    observed_state, observed_return_bps = _observed_state(gold_state)
    structure = gold_state.get("market_structure")
    structure = structure if isinstance(structure, Mapping) else {}
    timeframes = structure.get("timeframes")
    timeframes = timeframes if isinstance(timeframes, Mapping) else {}
    move = gold_state.get("move_observation")
    move = move if isinstance(move, Mapping) else {}
    windows = move.get("windows")
    windows = windows if isinstance(windows, Mapping) else {}

    reasons: list[dict[str, Any]] = []
    for timeframe, weight, tool_name in (
        ("M15", 3, "gold_m15_structure"),
        ("H1", 2, "gold_h1_structure"),
        ("H4", 1, "gold_h4_structure"),
    ):
        frame = timeframes.get(timeframe)
        frame = frame if isinstance(frame, Mapping) else {}
        raw = str(frame.get("net_close_direction") or "unknown")
        vote = _direction_vote(raw)
        if vote:
            reasons.append(
                _reason(
                    surface=tool_name,
                    observation=f"{timeframe} completed-bar close path is {raw}",
                    vote=vote,
                    weight=weight,
                    source_path=f"gold_state.market_structure.timeframes.{timeframe}.net_close_direction",
                )
            )

    for horizon, weight, tool_name in (
        ("15m", 2, "gold_m15_structure"),
        ("5m", 1, "gold_m5_structure"),
    ):
        window = windows.get(horizon)
        window = window if isinstance(window, Mapping) else {}
        raw = str(window.get("direction") or "unknown")
        vote = _direction_vote(raw)
        if vote:
            reasons.append(
                _reason(
                    surface=tool_name,
                    observation=(
                        f"recent {horizon} move is {raw} "
                        f"({window.get('return_bps')} bps)"
                    ),
                    vote=vote,
                    weight=weight,
                    source_path=f"gold_state.move_observation.windows.{horizon}",
                )
            )

    if movement_investigation.get("investigation_required") is True:
        raw = str(movement_investigation.get("move_direction") or "unknown")
        vote = _direction_vote(raw)
        if vote:
            reasons.append(
                _reason(
                    surface="gold_movement_detector",
                    observation=(
                        f"abnormal Gold move detected {raw}; attribution="
                        f"{movement_investigation.get('attribution_state')}"
                    ),
                    vote=vote,
                    weight=1,
                    source_path="gold_state.movement_investigation",
                )
            )

    analogue_n = int(analogue_summary.get("sample_n") or 0)
    analogue_distribution = analogue_summary.get("next_state_distribution")
    analogue_distribution = (
        analogue_distribution if isinstance(analogue_distribution, Mapping) else {}
    )
    if analogue_n >= 20:
        ranked = sorted(
            (
                (str(name), int(count))
                for name, count in analogue_distribution.items()
                if str(name) in {"bullish", "bearish", "neutral"}
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        if ranked and ranked[0][1] / analogue_n >= 0.60:
            vote = _direction_vote(ranked[0][0])
            if vote:
                reasons.append(
                    _reason(
                        surface="gold_cycle_analogue_memory",
                        observation=(
                            f"{ranked[0][0]} followed {ranked[0][1]}/{analogue_n} "
                            "comparable prior cycle states"
                        ),
                        vote=vote,
                        weight=1,
                        source_path="cycle_analogue_memory.next_state_distribution",
                    )
                )

    score = sum(
        (1 if item["vote"] == "bullish" else -1) * int(item["weight"])
        for item in reasons
    )
    weight_total = sum(int(item["weight"]) for item in reasons)
    if weight_total == 0:
        view_direction = "unknown"
        confidence = Decimal(0)
    elif score >= 2:
        view_direction = "bullish"
        confidence = Decimal(abs(score)) / Decimal(weight_total)
    elif score <= -2:
        view_direction = "bearish"
        confidence = Decimal(abs(score)) / Decimal(weight_total)
    else:
        view_direction = "neutral"
        confidence = Decimal(1) - (Decimal(abs(score)) / Decimal(weight_total))

    supporting: list[dict[str, Any]] = []
    contradicting: list[dict[str, Any]] = []
    for item in reasons:
        vote = str(item["vote"])
        if view_direction in {"bullish", "bearish"} and vote == view_direction:
            supporting.append(item)
        elif view_direction in {"bullish", "bearish"} and vote in {"bullish", "bearish"}:
            contradicting.append(item)
        elif view_direction == "neutral":
            contradicting.append(item)

    capabilities = toolbox_manifest.get("capabilities")
    capabilities = capabilities if isinstance(capabilities, list) else []
    considered = [
        str(item.get("name"))
        for item in capabilities
        if isinstance(item, Mapping) and item.get("name")
    ]
    capability_status = {
        str(item.get("name")): str(item.get("status") or "known_unknown")
        for item in capabilities
        if isinstance(item, Mapping) and item.get("name")
    }
    used = sorted({str(item["surface"]) for item in reasons})

    unavailable: list[dict[str, str]] = []
    for name in movement_investigation.get("required_follow_up_tools") or []:
        capability_name = str(name)
        status = capability_status.get(capability_name, "not_connected_in_standalone")
        if status not in {"live_here"}:
            unavailable.append(
                {
                    "surface": capability_name,
                    "status": status,
                    "reason": "material follow-up evidence was not live/PIT-available",
                }
            )
    for item in capabilities:
        if not isinstance(item, Mapping):
            continue
        if item.get("status") == "research_exists_not_live_connected":
            unavailable.append(
                {
                    "surface": str(item.get("name")),
                    "status": str(item.get("status")),
                    "reason": "capability exists but cannot be treated as current evidence",
                }
            )

    contradiction_weight = sum(int(item["weight"]) for item in contradicting)
    if weight_total and contradiction_weight:
        confidence *= max(
            Decimal("0.40"),
            Decimal(1) - (Decimal(contradiction_weight) / Decimal(weight_total)),
        )
    if unavailable:
        confidence = min(confidence, Decimal("0.650000"))

    prior_sequence = [*prior_observed_states[-3:], observed_state]
    cycle_signature = ">".join(prior_sequence)
    if view_direction == "unknown":
        reasoning_summary = "No directional view: connected evidence did not produce a coherent directional case."
    elif view_direction == "neutral":
        reasoning_summary = (
            f"Neutral 15-minute view: directional evidence is mixed/weak; weighted score={score}/{weight_total}."
        )
    else:
        reasoning_summary = (
            f"{view_direction.title()} 15-minute view: weighted connected evidence "
            f"score={score}/{weight_total}, with {len(contradicting)} contradictory reason(s) "
            f"and {len(unavailable)} unavailable evidence item(s)."
        )

    result: dict[str, Any] = {
        "view_version": GOLD_CYCLE_VIEW_VERSION,
        "as_of_utc": _utc(as_of, name="as_of").isoformat(),
        "window_start_utc": _utc(window_start, name="window_start").isoformat(),
        "window_end_utc": (
            _utc(window_start, name="window_start")
            + timedelta(minutes=CYCLE_WINDOW_MINUTES)
        ).isoformat(),
        "session_code": session_code,
        "observed_state": observed_state,
        "observed_15m_return_bps": observed_return_bps,
        "view_direction": view_direction,
        "view_confidence": _fmt(confidence) or "0.000000",
        "cycle_signature": cycle_signature,
        "reasoning_summary": reasoning_summary,
        "supporting_reasons": supporting,
        "contradicting_reasons": contradicting,
        "unavailable_evidence": unavailable,
        "all_directional_reasons": reasons,
        "analogue_summary": dict(analogue_summary),
        "toolbox_considered": considered,
        "toolbox_used": used,
        "toolbox_manifest_digest": str(toolbox_manifest.get("manifest_digest") or ""),
        "neutral_band_bps": _fmt(CYCLE_NEUTRAL_BAND_BPS),
        "research_only": True,
        "predictive_edge_claimed": False,
        "live_money_execution_allowed": False,
        "future_values_used": False,
    }
    result["view_digest"] = _digest(result)
    return result


class D1GoldCycleMemoryStore:
    def __init__(self, d1: Any) -> None:
        self._d1 = d1

    async def _snapshot_at_or_before(self, cutoff: datetime) -> dict[str, Any] | None:
        row = _row(
            await self._d1.prepare(
                """
                SELECT id,captured_at,session_code
                FROM market_snapshots
                WHERE symbol='XAUUSD'
                  AND market_data_source='twelve_data'
                  AND captured_at<=?
                  AND capture_status IN ('complete','partial')
                  AND json_extract(data_availability_json,'$.request_kind')='scheduled_capture'
                  AND json_extract(data_availability_json,'$.request_ledger_status')='succeeded'
                  AND json_extract(data_availability_json,'$.freshness_state')='fresh'
                  AND latest_m1_id IS NOT NULL
                  AND latest_m5_id IS NOT NULL
                  AND latest_m15_id IS NOT NULL
                  AND latest_h1_id IS NOT NULL
                  AND latest_h4_id IS NOT NULL
                ORDER BY captured_at DESC,id DESC
                LIMIT 1
                """
            )
            .bind(cutoff.isoformat())
            .first()
        )
        if row is None:
            return None
        captured = _utc(str(row["captured_at"]), name="snapshot.captured_at")
        if cutoff - captured > timedelta(minutes=10):
            return None
        return row

    async def _prior_states(self, *, before: datetime, limit: int = 3) -> list[str]:
        start = before.replace(hour=0, minute=0, second=0, microsecond=0)
        result = await self._d1.prepare(
            """
            SELECT observed_state
            FROM aidy_gold_cycle_views
            WHERE window_start_utc>=? AND window_start_utc<?
            ORDER BY window_start_utc DESC
            LIMIT ?
            """
        ).bind(start.isoformat(), before.isoformat(), max(1, min(limit, 8))).all()
        values = [str(row["observed_state"]) for row in _results(result)]
        values.reverse()
        return values

    async def _analogue_summary(
        self,
        *,
        before: datetime,
        session_code: str,
        time_slot_utc: str,
        observed_state: str,
        sequence_signature: str,
    ) -> dict[str, Any]:
        counts = {"bullish": 0, "bearish": 0, "neutral": 0}
        durations: list[int] = []

        historical_result = await self._d1.prepare(
            """
            SELECT next_state,state_run_length_windows
            FROM aidy_gold_cycle_historical
            WHERE window_start_utc<?
              AND session_code=?
              AND time_slot_utc=?
              AND observed_state=?
              AND prior_sequence_signature=?
            ORDER BY window_start_utc DESC
            LIMIT 200
            """
        ).bind(
            before.isoformat(),
            session_code,
            time_slot_utc,
            observed_state,
            sequence_signature,
        ).all()
        historical_rows = _results(historical_result)
        for row in historical_rows:
            state = str(row.get("next_state") or "")
            if state in counts:
                counts[state] += 1
                durations.append(int(row.get("state_run_length_windows") or 1))

        live_result = await self._d1.prepare(
            """
            SELECT o.realised_direction
            FROM aidy_gold_cycle_views v
            JOIN aidy_gold_cycle_outcomes o ON o.cycle_view_id=v.cycle_view_id
            WHERE v.window_start_utc<?
              AND v.session_code=?
              AND v.observed_state=?
              AND v.cycle_signature=?
              AND o.resolved_at_utc<=?
            ORDER BY v.window_start_utc DESC
            LIMIT 50
            """
        ).bind(
            before.isoformat(),
            session_code,
            observed_state,
            sequence_signature,
            before.isoformat(),
        ).all()
        live_rows = _results(live_result)
        for row in live_rows:
            state = str(row.get("realised_direction") or "")
            if state in counts:
                counts[state] += 1

        sample_n = sum(counts.values())
        return {
            "sample_n": sample_n,
            "next_state_distribution": counts,
            "mean_historical_run_length_windows": (
                None
                if not durations
                else str(
                    (
                        Decimal(sum(durations)) / Decimal(len(durations))
                    ).quantize(Decimal("0.000001"))
                )
            ),
            "historical_seed_rows": len(historical_rows),
            "live_resolved_rows": len(live_rows),
            "descriptive_only": True,
            "selection_bias_possible": True,
            "usable_for_live_edge_claim": False,
        }

    async def create_next_view(self, *, now_utc: datetime) -> dict[str, Any]:
        now = _utc(now_utc, name="now_utc")
        window_start = _next_window_start(now)
        lead = window_start - now
        if lead > timedelta(minutes=CYCLE_VIEW_LEAD_MINUTES):
            return {"created": False, "reason": "outside_view_lead_window"}
        if lead <= timedelta(0):
            return {"created": False, "reason": "target_window_already_started"}

        exists = _row(
            await self._d1.prepare(
                "SELECT cycle_view_id FROM aidy_gold_cycle_views WHERE window_start_utc=? LIMIT 1"
            ).bind(window_start.isoformat()).first()
        )
        if exists is not None:
            return {"created": False, "reason": "view_already_frozen"}

        snapshot = await self._snapshot_at_or_before(now)
        if snapshot is None:
            return {"created": False, "reason": "no_fresh_pre_window_snapshot"}

        inputs = await build_private_forward_decision_inputs(
            d1=self._d1,
            snapshot_id=str(snapshot["id"]),
        )
        context = inputs.get("context")
        context = context if isinstance(context, Mapping) else {}
        extensions = context.get("architecture_v2_extensions")
        extensions = extensions if isinstance(extensions, Mapping) else {}
        gold_state = extensions.get("gold_state_engine")
        gold_state = gold_state if isinstance(gold_state, Mapping) else {}
        investigation = extensions.get("gold_movement_investigation")
        investigation = investigation if isinstance(investigation, Mapping) else {}
        toolbox = extensions.get("gold_toolbox_manifest")
        toolbox = toolbox if isinstance(toolbox, Mapping) else {}

        prior_states = await self._prior_states(before=window_start, limit=3)
        observed_state, _ = _observed_state(gold_state)
        preliminary_signature = ">".join([*prior_states[-3:], observed_state])
        analogue = await self._analogue_summary(
            before=window_start,
            session_code=str(snapshot.get("session_code") or "unknown"),
            time_slot_utc=window_start.strftime("%H:%M"),
            observed_state=observed_state,
            sequence_signature=preliminary_signature,
        )
        payload = build_cycle_view_payload(
            as_of=now,
            window_start=window_start,
            session_code=str(snapshot.get("session_code") or "unknown"),
            gold_state=gold_state,
            movement_investigation=investigation,
            toolbox_manifest=toolbox,
            prior_observed_states=prior_states,
            analogue_summary=analogue,
        )
        cycle_view_id = f"aidy_cycle_{payload['view_digest'][:32]}"
        await self._d1.prepare(
            """
            INSERT INTO aidy_gold_cycle_views (
                cycle_view_id,window_start_utc,window_end_utc,decided_at_utc,
                source_snapshot_id,source_snapshot_at_utc,session_code,observed_state,
                view_direction,view_confidence,cycle_signature,reasoning_summary,
                supporting_reasons_json,contradicting_reasons_json,
                unavailable_evidence_json,evidence_json,toolbox_manifest_digest,
                toolbox_considered_json,toolbox_used_json,analogue_summary_json,view_digest
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(window_start_utc) DO NOTHING
            """
        ).bind(
            cycle_view_id,
            payload["window_start_utc"],
            payload["window_end_utc"],
            now.isoformat(),
            str(snapshot["id"]),
            str(snapshot["captured_at"]),
            payload["session_code"],
            payload["observed_state"],
            payload["view_direction"],
            payload["view_confidence"],
            payload["cycle_signature"],
            payload["reasoning_summary"],
            _canonical_json(payload["supporting_reasons"]),
            _canonical_json(payload["contradicting_reasons"]),
            _canonical_json(payload["unavailable_evidence"]),
            _canonical_json(payload),
            payload["toolbox_manifest_digest"],
            _canonical_json(payload["toolbox_considered"]),
            _canonical_json(payload["toolbox_used"]),
            _canonical_json(payload["analogue_summary"]),
            payload["view_digest"],
        ).run()
        return {
            "created": True,
            "cycle_view_id": cycle_view_id,
            "view_direction": payload["view_direction"],
            "observed_state": payload["observed_state"],
            "cycle_signature": payload["cycle_signature"],
            "reasoning_summary": payload["reasoning_summary"],
        }

    async def _outcome_bars(
        self,
        *,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        result = await self._d1.prepare(
            """
            SELECT open_time_utc,open,high,low,close
            FROM twelve_data_decision_admitted_m1_v1
            WHERE open_time_utc>=? AND open_time_utc<?
            ORDER BY open_time_utc
            """
        ).bind(start.isoformat(), end.isoformat()).all()
        return _results(result)

    async def resolve_matured(
        self,
        *,
        now_utc: datetime,
        limit: int = 20,
    ) -> dict[str, int]:
        now = _utc(now_utc, name="now_utc")
        result = await self._d1.prepare(
            """
            SELECT v.cycle_view_id,v.window_start_utc,v.window_end_utc,
                   v.view_direction,v.reasoning_summary,
                   v.supporting_reasons_json,v.contradicting_reasons_json
            FROM aidy_gold_cycle_views v
            LEFT JOIN aidy_gold_cycle_outcomes o ON o.cycle_view_id=v.cycle_view_id
            WHERE o.cycle_view_id IS NULL AND v.window_end_utc<=?
            ORDER BY v.window_end_utc
            LIMIT ?
            """
        ).bind(now.isoformat(), max(1, min(int(limit), 100))).all()
        stats = {"eligible": 0, "resolved": 0, "incomplete": 0}
        for row in _results(result):
            stats["eligible"] += 1
            start = _utc(str(row["window_start_utc"]), name="window_start_utc")
            end = _utc(str(row["window_end_utc"]), name="window_end_utc")
            bars = await self._outcome_bars(start=start, end=end)
            if len(bars) < 15:
                stats["incomplete"] += 1
                continue

            first_open = _decimal(bars[0].get("open"))
            last_close = _decimal(bars[-1].get("close"))
            highs = [
                value for item in bars if (value := _decimal(item.get("high"))) is not None
            ]
            lows = [
                value for item in bars if (value := _decimal(item.get("low"))) is not None
            ]
            if (
                first_open is None
                or first_open <= 0
                or last_close is None
                or not highs
                or not lows
            ):
                stats["incomplete"] += 1
                continue

            return_bps = ((last_close - first_open) / first_open) * Decimal(10000)
            mfe_bps = ((max(highs) - first_open) / first_open) * Decimal(10000)
            mae_bps = ((min(lows) - first_open) / first_open) * Decimal(10000)
            realised = _state_from_return(return_bps)
            view = str(row.get("view_direction") or "unknown")
            correct = (
                None
                if view == "unknown" or realised == "unknown"
                else int(view == realised)
            )
            if correct is None:
                verdict = "unscored_unknown"
            elif correct:
                verdict = "reasoning_direction_confirmed"
            else:
                verdict = "reasoning_direction_not_confirmed"

            review = {
                "verdict": verdict,
                "view_direction": view,
                "realised_direction": realised,
                "reasoning_summary_at_decision": str(row.get("reasoning_summary") or ""),
                "supporting_reasons_at_decision": json.loads(
                    str(row.get("supporting_reasons_json") or "[]")
                ),
                "contradicting_reasons_at_decision": json.loads(
                    str(row.get("contradicting_reasons_json") or "[]")
                ),
                "future_result_was_unavailable_at_decision": True,
                "reasoning_rewrite_allowed": False,
            }
            outcome: dict[str, Any] = {
                "outcome_version": GOLD_CYCLE_OUTCOME_VERSION,
                "cycle_view_id": str(row["cycle_view_id"]),
                "window_start_utc": start.isoformat(),
                "window_end_utc": end.isoformat(),
                "resolved_at_utc": now.isoformat(),
                "realised_direction": realised,
                "return_bps": _fmt(return_bps),
                "mfe_bps": _fmt(mfe_bps),
                "mae_bps": _fmt(mae_bps),
                "m1_bars_observed": len(bars),
                "exact_direction_correct": correct,
                "reasoning_review": review,
                "post_outcome_only": True,
                "research_only": True,
                "live_money_execution_allowed": False,
            }
            outcome["outcome_digest"] = _digest(outcome)
            await self._d1.prepare(
                """
                INSERT INTO aidy_gold_cycle_outcomes (
                    cycle_view_id,resolved_at_utc,realised_direction,return_bps,
                    mfe_bps,mae_bps,m1_bars_observed,exact_direction_correct,
                    reasoning_review_json,outcome_json,outcome_digest
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(cycle_view_id) DO NOTHING
                """
            ).bind(
                outcome["cycle_view_id"],
                outcome["resolved_at_utc"],
                outcome["realised_direction"],
                outcome["return_bps"],
                outcome["mfe_bps"],
                outcome["mae_bps"],
                outcome["m1_bars_observed"],
                outcome["exact_direction_correct"],
                _canonical_json(outcome["reasoning_review"]),
                _canonical_json(outcome),
                outcome["outcome_digest"],
            ).run()
            stats["resolved"] += 1
        return stats

    async def context_summary(self, *, as_of_utc: datetime) -> dict[str, Any]:
        as_of = _utc(as_of_utc, name="as_of_utc")
        day_start = as_of.replace(hour=0, minute=0, second=0, microsecond=0)
        result = await self._d1.prepare(
            """
            SELECT v.window_start_utc,v.observed_state,v.view_direction,v.view_confidence,
                   v.cycle_signature,v.reasoning_summary,v.toolbox_used_json,
                   o.realised_direction,o.exact_direction_correct,o.return_bps
            FROM aidy_gold_cycle_views v
            LEFT JOIN aidy_gold_cycle_outcomes o
              ON o.cycle_view_id=v.cycle_view_id AND o.resolved_at_utc<=?
            WHERE v.decided_at_utc<=? AND v.window_start_utc>=?
            ORDER BY v.window_start_utc DESC
            LIMIT 32
            """
        ).bind(as_of.isoformat(), as_of.isoformat(), day_start.isoformat()).all()
        rows = _results(result)
        resolved = [row for row in rows if row.get("realised_direction") is not None]
        scored = [row for row in resolved if row.get("exact_direction_correct") is not None]
        correct = sum(int(row.get("exact_direction_correct") or 0) for row in scored)
        latest = rows[0] if rows else None

        sequence = [str(row["observed_state"]) for row in reversed(rows)]
        runs: list[dict[str, Any]] = []
        for state in sequence:
            if runs and runs[-1]["state"] == state:
                runs[-1]["windows"] += 1
            else:
                runs.append({"state": state, "windows": 1})
        for run in runs:
            run["minutes"] = int(run["windows"]) * CYCLE_WINDOW_MINUTES

        return {
            "memory_version": GOLD_CYCLE_MEMORY_VERSION,
            "as_of_utc": as_of.isoformat(),
            "window_minutes": CYCLE_WINDOW_MINUTES,
            "views_today": len(rows),
            "resolved_today": len(resolved),
            "scored_today": len(scored),
            "correct_today": correct,
            "accuracy_today": (
                None
                if not scored
                else _fmt(Decimal(correct) / Decimal(len(scored)))
            ),
            "observed_state_sequence_today": sequence,
            "state_runs_today": runs,
            "latest_view": (
                None
                if latest is None
                else {
                    "window_start_utc": latest["window_start_utc"],
                    "observed_state": latest["observed_state"],
                    "view_direction": latest["view_direction"],
                    "view_confidence": latest["view_confidence"],
                    "cycle_signature": latest["cycle_signature"],
                    "reasoning_summary": latest["reasoning_summary"],
                    "toolbox_used": json.loads(
                        str(latest.get("toolbox_used_json") or "[]")
                    ),
                    "realised_direction": latest.get("realised_direction"),
                    "exact_direction_correct": latest.get("exact_direction_correct"),
                    "return_bps": latest.get("return_bps"),
                }
            ),
            "research_only": True,
            "live_money_execution_allowed": False,
        }


async def sync_gold_cycle_memory(
    d1: Any,
    *,
    now_utc: datetime,
) -> dict[str, Any]:
    now = _utc(now_utc, name="now_utc")
    store = D1GoldCycleMemoryStore(d1)
    resolution = await store.resolve_matured(now_utc=now)
    creation = await store.create_next_view(now_utc=now)
    result = {
        "memory_version": GOLD_CYCLE_MEMORY_VERSION,
        "observed_at_utc": now.isoformat(),
        "resolution": resolution,
        "creation": creation,
        "research_only": True,
        "live_money_execution_allowed": False,
    }
    result["sync_digest"] = _digest(result)
    return result


__all__ = [
    "CYCLE_NEUTRAL_BAND_BPS",
    "CYCLE_VIEW_LEAD_MINUTES",
    "CYCLE_WINDOW_MINUTES",
    "GOLD_CYCLE_MEMORY_VERSION",
    "GOLD_CYCLE_OUTCOME_VERSION",
    "GOLD_CYCLE_VIEW_VERSION",
    "D1GoldCycleMemoryStore",
    "build_cycle_view_payload",
    "sync_gold_cycle_memory",
]
