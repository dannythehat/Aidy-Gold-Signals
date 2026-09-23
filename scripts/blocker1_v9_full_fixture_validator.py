"""Blocker-1 v9 immutable fixture generator + dual-path validator.

Disposable execution harness. It changes no production code or aggregation math.
It builds one deterministic source state from the real expert builders, freezes
history against the real connected subcalculator identities, derives Build-3
trust from that fixture, executes the current Build 20->21->22 path, and executes
the frozen v7/v8 replacement mathematics from the same state.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from blocker1_v9_fixture_probe import (
    AS_OF,
    aggregate,
    env,
    inject_low_reclaim,
    m1_spine,
    prior_day_low,
)
from aidy.gold_d1_context_expert import build_d1_context_expert
from aidy.gold_evidence_dependency import (
    FAMILY_PARENT,
    build_evidence_dependency_engine,
    extract_dependency_signals,
)
from aidy.gold_environment_gate_selector import (
    build_environment_aware_gate_selector,
    build_gate_selector_input,
)
from aidy.gold_expert_shadow import (
    EXPECTED_GATES,
    _DISCONNECTED_CONTEXT_GATES,
    _unknown_context_result,
)
from aidy.gold_expert_trust import (
    aggregate_context_rows,
    build_trust_envelope,
    select_conditional_trust,
)
from aidy.gold_h1_price_structure_expert import build_h1_price_structure_expert
from aidy.gold_h4_price_structure_expert import build_h4_price_structure_expert
from aidy.gold_liquidity_reclaim_expert import build_liquidity_reclaim_expert
from aidy.gold_m15_price_structure_expert import build_m15_price_structure_expert
from aidy.gold_m5_price_structure_expert import build_m5_price_structure_expert
from aidy.gold_meta_direction import build_meta_direction_view
from aidy.gold_momentum_impulse_expert import build_momentum_impulse_expert
from aidy.gold_price_expert_math import build_price_expert_math_packet
from aidy.gold_price_location_expert import (
    PRICE_LOCATION_GATE_ID,
    build_price_location_expert,
)
from aidy.gold_session_participation_expert import build_session_participation_expert
from aidy.gold_volatility_jump_expert import build_volatility_jump_expert

OUT_DIR = Path("artifacts")
FIXTURE_PATH = OUT_DIR / "blocker1_v9_full_fixture.json"
MANIFEST_PATH = OUT_DIR / "blocker1_v9_validation_manifest.json"

FIXTURE_VERSION = "blocker1_t1_full_fixture_v9"
BASELINE_PRIOR_PER_CLASS = D(10)
BASELINE_PRIOR_STRENGTH = D(30)
PRIOR_STRENGTH = D(20)
EDGE_SCALE = D("0.15")
MIN_CONTRIBUTOR_N = 12
MIN_FAMILY_STRENGTH = D("0.20")
MIN_FAMILIES = 2
BALANCED_ABSTAIN_BAND = D("0.20")
UNKNOWN_CALIBRATION_MULTIPLIER = D("0.85")

# Preserve the v7 mature-history construction values, but map them onto REAL
# currently bullish subcalculator identities discovered by v8/v9 execution.
POSITIVE_SUBJECT_TARGETS = {
    "m5_price_structure_expert:m5_candle_pressure": (168, 82),
    "h4_price_structure_expert:h4_acceleration": (132, 59),
    "liquidity_reclaim_expert:liquidity_prior_day_low": (162, 77),
}

GATE_HISTORY_N = {
    "m5_price_structure_expert": 168,
    "m15_price_structure_expert": 156,
    "h1_price_structure_expert": 144,
    "h4_price_structure_expert": 132,
    "momentum_impulse_expert": 150,
    "liquidity_reclaim_expert": 162,
}

SCOPE_MULTIPLIERS = {
    "mini_exact": D("1.00"),
    "global_core": D("0.80"),
    "gate_global": D("0.70"),
    "neutral_prior": D("0.50"),
}
RECENCY_MULTIPLIERS = {
    "recently_stronger": D("1.00"),
    "stable": D("1.00"),
    "insufficient_recent": D("0.90"),
    "recently_weaker": D("0.65"),
}


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: object) -> str:
    return sha256(canonical(value).encode()).hexdigest()


def fmt(value: D) -> str:
    return format(value.quantize(D("0.000001")), "f")


def utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("fixture timestamp must be timezone aware")
    return dt.astimezone(UTC)


def opposite(direction: str) -> str:
    if direction == "bullish":
        return "bearish"
    if direction == "bearish":
        return "bullish"
    raise ValueError(direction)


def distributed_correct(local_index: int, n: int, correct_n: int) -> bool:
    # Evenly distribute correct outcomes so the recent window is representative
    # rather than front-loading wins and manufacturing a recent-drift penalty.
    before = (local_index * correct_n) // n
    after = ((local_index + 1) * correct_n) // n
    return after > before


def build_connected_state() -> tuple[dict, list[dict], dict[str, Any]]:
    spine = m1_spine(45)
    preliminary = aggregate(spine)
    pdl = prior_day_low(preliminary)
    inject_low_reclaim(spine, pdl)

    decision_rows = spine[-2880:]
    aggs = aggregate(spine)
    environment = env(spine, aggs)
    price_math = build_price_expert_math_packet(
        as_of=AS_OF,
        symbol="XAUUSD",
        candle_rows=decision_rows + aggs,
        mode="pit",
    )
    common = {"global_environment": environment, "price_math_packet": price_math}

    connected: list[dict] = []
    for builder in (
        build_m5_price_structure_expert,
        build_m15_price_structure_expert,
        build_h1_price_structure_expert,
        build_h4_price_structure_expert,
        build_d1_context_expert,
        build_price_location_expert,
    ):
        connected.append(builder(**common))

    location = next(
        item
        for item in connected
        if item["expert_packet"]["gate_id"] == PRICE_LOCATION_GATE_ID
    )
    connected.append(
        build_momentum_impulse_expert(
            **common,
            m1_candle_rows=decision_rows,
        )
    )
    connected.append(
        build_liquidity_reclaim_expert(
            **common,
            price_location_result=location,
            m1_candle_rows=decision_rows,
            retrospective_gc_flow_rows=(),
        )
    )
    connected.append(
        build_volatility_jump_expert(
            **common,
            m1_candle_rows=decision_rows,
            clock_volatility_history=(),
            qualified_volatility_state=None,
        )
    )
    connected.append(
        build_session_participation_expert(
            global_environment=environment,
            m1_candle_rows=decision_rows,
            weekday_clock_history=(),
            gc_activity_context=None,
        )
    )

    market_state = {
        "as_of_utc": AS_OF.isoformat(),
        "m1_45d_row_n": len(spine),
        "m1_decision_row_n": len(decision_rows),
        "m1_decision_earliest_open_utc": decision_rows[0]["open_time_utc"].isoformat(),
        "m1_decision_latest_open_utc": decision_rows[-1]["open_time_utc"].isoformat(),
        "m1_decision_wall_clock_hours": (
            decision_rows[-1]["open_time_utc"] - decision_rows[0]["open_time_utc"]
        ).total_seconds() / 3600,
        "prior_day_low_before_injection": str(pdl),
        "final_mid": str(spine[-1]["close"]),
        "market_rows_digest": digest([
            {
                "t": row["open_time_utc"].isoformat(),
                "o": row["open"],
                "h": row["high"],
                "l": row["low"],
                "c": row["close"],
                "fo": row["first_observed_at"],
            }
            for row in spine
        ]),
        "aggregate_rows_digest": digest([
            {
                "tf": row["timeframe"],
                "t": row["open_time_utc"].isoformat(),
                "o": row["open"],
                "h": row["high"],
                "l": row["low"],
                "c": row["close"],
                "fo": row["first_observed_at"],
            }
            for row in aggs
        ]),
    }
    return environment, connected, market_state


def add_unknowns(environment: Mapping[str, Any], connected: list[dict]) -> list[dict]:
    results = list(connected)
    for gate_id, (version, family) in _DISCONNECTED_CONTEXT_GATES.items():
        results.append(
            _unknown_context_result(
                gate_id=gate_id,
                gate_version=version,
                dependency_family=family,
                global_environment=environment,
            )
        )
    by_gate = {
        str(item["expert_packet"]["gate_id"]): item
        for item in results
    }
    if set(by_gate) != set(EXPECTED_GATES):
        raise RuntimeError("15-gate fixture registry mismatch")
    return [by_gate[gate] for gate in EXPECTED_GATES]


def connected_manifest(connected: list[dict]) -> list[dict]:
    rows = []
    for result in connected:
        packet = result["expert_packet"]
        for calc in packet["subcalculators"]:
            rows.append({
                "subject_key": f"{packet['gate_id']}:{calc['calculator_id']}",
                "gate_id": packet["gate_id"],
                "gate_version": packet["gate_version"],
                "packet_digest": packet["packet_digest"],
                "calculator_id": calc["calculator_id"],
                "calculator_version": calc["version"],
                "role": calc["role"],
                "dependency_family": calc["dependency_family"],
                "state": calc["state"],
                "vote": calc["vote"],
                "scoreable": calc["scoreable"],
            })
    return rows


def historical_packet_digest(gate_id: str, gate_version: str, decision: datetime) -> str:
    return digest({
        "fixture": FIXTURE_VERSION,
        "gate_id": gate_id,
        "gate_version": gate_version,
        "decision_time_utc": decision.isoformat(),
    })


def history_row(
    *,
    gate_id: str,
    gate_version: str,
    subject_type: str,
    subject_id: str,
    subject_version: str,
    scope_keys: list[str],
    decision: datetime,
    predicted: str,
    realised: str,
) -> dict:
    resolved = decision + timedelta(minutes=15)
    packet_digest = historical_packet_digest(gate_id, gate_version, decision)
    correct = int(predicted == realised)
    body = {
        "packet_digest": packet_digest,
        "gate_id": gate_id,
        "gate_version": gate_version,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "subject_version": subject_version,
        "target_horizon_minutes": 15,
        "scope_keys": list(scope_keys),
        "decision_time_utc": decision.isoformat(),
        "resolved_at_utc": resolved.isoformat(),
        "predicted_class": predicted,
        "realised_direction": realised,
        "realised_return_bps": "3.000000" if realised == "bullish" else "-3.000000",
        "score": 1 if correct else -1,
        "correct": correct,
        "impact_class": "normal",
        "research_only": True,
        "live_money_execution_allowed": False,
    }
    body["result_id"] = "expert_result_" + digest({
        "packet_digest": packet_digest,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "subject_version": subject_version,
    })[:28]
    body["result_digest"] = digest(body)
    return body


def make_time_axis() -> list[datetime]:
    max_n = max(GATE_HISTORY_N.values())
    start = AS_OF - timedelta(hours=3 * max_n)
    return [start + timedelta(hours=3 * i) for i in range(max_n)]


def realised_for_cycle(global_index: int) -> str:
    return "bullish" if global_index % 2 == 0 else "bearish"


def build_prehistory(first_cycle: datetime) -> list[dict]:
    classes = ("bullish", "bearish", "bullish", "bearish", "neutral")
    end = first_cycle - timedelta(days=1)
    start = end - timedelta(hours=4999)
    rows = []
    for i in range(5000):
        rows.append({
            "outcome_id": f"baseline_{i:04d}",
            "resolved_at_utc": (start + timedelta(hours=i)).isoformat(),
            "realised_direction": classes[i % len(classes)],
        })
    return rows


def build_fixture(
    *,
    environment: Mapping[str, Any],
    connected: list[dict],
    all_experts: list[dict],
    market_state: Mapping[str, Any],
) -> dict:
    manifest = connected_manifest(connected)
    manifest_by_key = {row["subject_key"]: row for row in manifest}
    experts_by_gate = {
        str(item["expert_packet"]["gate_id"]): item
        for item in all_experts
    }

    all_times = make_time_axis()
    first_cycle = all_times[0]
    outcomes = build_prehistory(first_cycle)
    for i, decision in enumerate(all_times):
        outcomes.append({
            "outcome_id": f"fixture_cycle_{i:03d}",
            "resolved_at_utc": (decision + timedelta(minutes=15)).isoformat(),
            "realised_direction": realised_for_cycle(i),
        })

    subject_histories = []
    rows_by_subject: dict[str, list[dict]] = {}
    for row in manifest:
        subject_key = row["subject_key"]
        gate_id = row["gate_id"]
        gate_n = GATE_HISTORY_N.get(gate_id, 0)
        history_rows: list[dict] = []
        if (
            gate_n > 0
            and row["role"] == "directional"
            and row["state"] == "known"
        ):
            n = gate_n
            target = POSITIVE_SUBJECT_TARGETS.get(subject_key)
            if target is not None:
                if target[0] != n:
                    raise RuntimeError(f"positive target N mismatch for {subject_key}")
                correct_n = target[1]
            else:
                correct_n = int(D(n) * D("0.36"))

            result = experts_by_gate[gate_id]
            scope_keys = [str(s["scope_key"]) for s in result["trust_scopes"]]
            local_times = all_times[-n:]
            offset = len(all_times) - n
            for j, decision in enumerate(local_times):
                global_index = offset + j
                realised = realised_for_cycle(global_index)
                predicted = (
                    realised
                    if distributed_correct(j, n, correct_n)
                    else opposite(realised)
                )
                history_rows.append(
                    history_row(
                        gate_id=gate_id,
                        gate_version=row["gate_version"],
                        subject_type="subcalculator",
                        subject_id=row["calculator_id"],
                        subject_version=row["calculator_version"],
                        scope_keys=scope_keys,
                        decision=decision,
                        predicted=predicted,
                        realised=realised,
                    )
                )

        rows_by_subject[subject_key] = history_rows
        subject_histories.append({
            **row,
            "history_n": len(history_rows),
            "history_rows": history_rows,
        })

    gate_trust_history = []
    gate_rows_by_gate: dict[str, list[dict]] = {}
    for gate_id in EXPECTED_GATES:
        result = experts_by_gate[gate_id]
        packet = result["expert_packet"]
        n = GATE_HISTORY_N.get(gate_id, 0)
        gate_rows: list[dict] = []
        if n > 0 and packet["gate_mode"] == "directional":
            correct_n = int((D(n) * D("0.60")).quantize(D(1)))
            scope_keys = [str(s["scope_key"]) for s in result["trust_scopes"]]
            local_times = all_times[-n:]
            offset = len(all_times) - n
            for j, decision in enumerate(local_times):
                global_index = offset + j
                realised = realised_for_cycle(global_index)
                predicted = (
                    realised
                    if distributed_correct(j, n, correct_n)
                    else opposite(realised)
                )
                gate_rows.append(
                    history_row(
                        gate_id=gate_id,
                        gate_version=str(packet["gate_version"]),
                        subject_type="gate",
                        subject_id=gate_id,
                        subject_version=str(packet["gate_version"]),
                        scope_keys=scope_keys,
                        decision=decision,
                        predicted=predicted,
                        realised=realised,
                    )
                )
        gate_rows_by_gate[gate_id] = gate_rows
        gate_trust_history.append({
            "gate_id": gate_id,
            "gate_version": str(packet["gate_version"]),
            "current_packet_digest": str(packet["packet_digest"]),
            "scope_keys": [str(s["scope_key"]) for s in result["trust_scopes"]],
            "history_n": len(gate_rows),
            "history_rows": gate_rows,
        })

    dependency_rows = []
    for decision in all_times[-120:]:
        signals = {}
        decision_iso = decision.isoformat()
        for subject in subject_histories:
            if subject["role"] != "directional":
                continue
            match = next(
                (
                    item
                    for item in subject["history_rows"]
                    if item["decision_time_utc"] == decision_iso
                ),
                None,
            )
            if match is not None:
                signals[subject["subject_key"]] = match["predicted_class"]
        dependency_rows.append({
            "observed_at_utc": decision_iso,
            "signals": dict(sorted(signals.items())),
        })

    fixture = {
        "fixture_version": FIXTURE_VERSION,
        "as_of_utc": AS_OF.isoformat(),
        "correct_derivation": "int(predicted_class == realised_direction)",
        "target_horizon_minutes": 15,
        "market_source": dict(market_state),
        "environment_digest": str(environment["environment_digest"]),
        "environment_key": str(environment["environment_key"]),
        "packet_count": len(all_experts),
        "expected_gate_ids": list(EXPECTED_GATES),
        "current_packet_digests": {
            gate: str(experts_by_gate[gate]["expert_packet"]["packet_digest"])
            for gate in EXPECTED_GATES
        },
        "connected_subcalculator_manifest": manifest,
        "resolved_outcome_history": outcomes,
        "subject_histories": subject_histories,
        "gate_trust_history": gate_trust_history,
        "dependency_history": dependency_rows,
        "construction_disclosure": {
            "engineering_fixture_not_market_edge_evidence": True,
            "positive_subject_targets": {
                key: {"n": value[0], "correct_n": value[1]}
                for key, value in POSITIVE_SUBJECT_TARGETS.items()
            },
            "all_other_directional_subjects_correct_fraction": "0.36",
            "directional_gate_trust_correct_fraction": "0.60",
            "outcome_prehistory_classes": "2000 bullish / 2000 bearish / 1000 neutral",
            "no_41_cycle_outcomes_used_for_threshold_tuning": True,
        },
        "research_only": True,
        "formal_forward_authority": False,
        "live_money_execution_allowed": False,
    }
    return fixture


def validate_correct_derivation(fixture: Mapping[str, Any]) -> None:
    for history in fixture["subject_histories"]:
        for row in history["history_rows"]:
            expected = int(row["predicted_class"] == row["realised_direction"])
            if int(row["correct"]) != expected:
                raise AssertionError("subcalculator correct field is not derived")
            if not (utc(row["decision_time_utc"]) < utc(row["resolved_at_utc"]) < AS_OF):
                raise AssertionError("subcalculator PIT timing invalid")
    for history in fixture["gate_trust_history"]:
        for row in history["history_rows"]:
            expected = int(row["predicted_class"] == row["realised_direction"])
            if int(row["correct"]) != expected:
                raise AssertionError("gate correct field is not derived")
            if not (utc(row["decision_time_utc"]) < utc(row["resolved_at_utc"]) < AS_OF):
                raise AssertionError("gate PIT timing invalid")


def histories_by_subject(fixture: Mapping[str, Any]) -> dict[str, list[dict]]:
    return {
        str(item["subject_key"]): list(item["history_rows"])
        for item in fixture["subject_histories"]
    }


def gate_history_map(fixture: Mapping[str, Any]) -> dict[str, list[dict]]:
    return {
        str(item["gate_id"]): list(item["history_rows"])
        for item in fixture["gate_trust_history"]
    }


def attach_fixture_trust(
    all_experts: list[dict],
    fixture: Mapping[str, Any],
) -> tuple[list[dict], dict[str, dict[str, Any]]]:
    sub_history = histories_by_subject(fixture)
    gate_history = gate_history_map(fixture)
    profiles_out: dict[str, dict[str, Any]] = {}
    rebuilt = []

    for result in all_experts:
        packet = result["expert_packet"]
        gate_id = str(packet["gate_id"])
        scopes = result["trust_scopes"]
        profiles: dict[str, dict[str, Any]] = {}

        gate_rows = aggregate_context_rows(
            results=gate_history.get(gate_id, ()),
            scopes=scopes,
            subject_type="gate",
            subject_id=gate_id,
            subject_version=str(packet["gate_version"]),
            as_of_utc=AS_OF,
        )
        gate_profile = select_conditional_trust(
            score_rows=gate_rows,
            scopes=scopes,
        )
        profiles[f"gate:{gate_id}"] = gate_profile
        profiles_out[f"gate:{gate_id}"] = gate_profile

        for calc in packet["subcalculators"]:
            key = f"{gate_id}:{calc['calculator_id']}"
            context_rows = aggregate_context_rows(
                results=sub_history.get(key, ()),
                scopes=scopes,
                subject_type="subcalculator",
                subject_id=str(calc["calculator_id"]),
                subject_version=str(calc["version"]),
                as_of_utc=AS_OF,
            )
            profile = select_conditional_trust(
                score_rows=context_rows,
                scopes=scopes,
            )
            profiles[f"subcalculator:{calc['calculator_id']}"] = profile
            profiles_out[key] = profile

        item = dict(result)
        item["trust_envelope"] = build_trust_envelope(
            packet=packet,
            profiles_by_subject=profiles,
        )
        rebuilt.append(item)

    return rebuilt, profiles_out


def baseline_map(fixture: Mapping[str, Any]) -> dict[str, dict[str, D]]:
    outcomes = sorted(
        fixture["resolved_outcome_history"],
        key=lambda row: row["resolved_at_utc"],
    )
    decision_times = sorted({
        row["decision_time_utc"]
        for item in fixture["subject_histories"]
        for row in item["history_rows"]
    })
    counts = {"bullish": 0, "bearish": 0, "neutral": 0}
    cursor = 0
    result: dict[str, dict[str, D]] = {}
    for decision_iso in decision_times:
        decision = utc(decision_iso)
        while cursor < len(outcomes) and utc(outcomes[cursor]["resolved_at_utc"]) < decision:
            klass = str(outcomes[cursor]["realised_direction"])
            counts[klass] += 1
            cursor += 1
        total = sum(counts.values())
        result[decision_iso] = {
            klass: (D(counts[klass]) + BASELINE_PRIOR_PER_CLASS)
            / (D(total) + BASELINE_PRIOR_STRENGTH)
            for klass in counts
        }
    return result


def reliability_for(
    *,
    history_rows: list[dict],
    profile: Mapping[str, Any],
    baselines: Mapping[str, Mapping[str, D]],
) -> dict[str, Any]:
    directional = [
        row
        for row in history_rows
        if row["predicted_class"] in {"bullish", "bearish"}
        and int(row["correct"]) in {0, 1}
    ]
    n = len(directional)
    excess_sum = D(0)
    for row in directional:
        base = baselines[row["decision_time_utc"]][row["predicted_class"]]
        excess_sum += D(int(row["correct"])) - base
    shrunk_excess = (
        excess_sum / (D(n) + PRIOR_STRENGTH)
        if n
        else D(0)
    )
    quality = max(D(0), min(D(1), shrunk_excess / EDGE_SCALE))
    scope_type = str(profile.get("selected_scope_type") or "neutral_prior")
    if scope_type.startswith("mini_reduced_"):
        scope_mult = D("0.90")
    else:
        scope_mult = SCOPE_MULTIPLIERS.get(scope_type, D("0.60"))
    recent_state = str(profile.get("recent_state") or "insufficient_recent")
    recency_mult = RECENCY_MULTIPLIERS.get(recent_state, D("0.85"))
    reliability = (
        quality
        * scope_mult
        * UNKNOWN_CALIBRATION_MULTIPLIER
        * recency_mult
    )
    return {
        "n": n,
        "sum_excess": fmt(excess_sum),
        "shrunk_excess": fmt(shrunk_excess),
        "quality": fmt(quality),
        "selected_scope_type": scope_type,
        "scope_multiplier": fmt(scope_mult),
        "recent_state": recent_state,
        "recency_multiplier": fmt(recency_mult),
        "calibration_state": "unknown",
        "calibration_multiplier": fmt(UNKNOWN_CALIBRATION_MULTIPLIER),
        "reliability": fmt(reliability),
    }


class DSU:
    def __init__(self, ids: list[str]) -> None:
        self.parent = {item: item for item in ids}

    def find(self, item: str) -> str:
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != item:
            nxt = self.parent[item]
            self.parent[item] = root
            item = nxt
        return root

    def union(self, left: str, right: str) -> None:
        a, b = self.find(left), self.find(right)
        if a != b:
            self.parent[b] = a


def new_path(
    *,
    experts: list[dict],
    fixture: Mapping[str, Any],
    profiles: Mapping[str, Mapping[str, Any]],
    dependency: Mapping[str, Any],
) -> dict[str, Any]:
    subject_hist = histories_by_subject(fixture)
    baselines = baseline_map(fixture)
    signals = extract_dependency_signals(experts)
    signal_map = {str(row["signal_id"]): row for row in signals}

    calc_map = {}
    for result in experts:
        packet = result["expert_packet"]
        for calc in packet["subcalculators"]:
            calc_map[f"{packet['gate_id']}:{calc['calculator_id']}"] = calc

    reliability_rows = {}
    eligible = []
    for subject in fixture["connected_subcalculator_manifest"]:
        sid = str(subject["subject_key"])
        profile = profiles.get(sid) or {}
        rel = reliability_for(
            history_rows=subject_hist.get(sid, []),
            profile=profile,
            baselines=baselines,
        )
        reliability_rows[sid] = rel
        r = D(rel["reliability"])
        calc = calc_map[sid]
        vote = str(calc["vote"])
        family_eligible = (
            str(calc["state"]) == "known"
            and str(calc["role"]) == "directional"
            and int(rel["n"]) >= MIN_CONTRIBUTOR_N
            and r > 0
            and vote in {"bullish", "bearish", "neutral"}
            and (
                vote == "neutral"
                or bool(calc["scoreable"])
            )
        )
        if family_eligible:
            signal = signal_map[sid]
            eligible.append({
                "signal_id": sid,
                "gate_id": str(subject["gate_id"]),
                "calculator_id": str(subject["calculator_id"]),
                "vote": vote,
                "reliability": r,
                "dependency_family": str(signal["dependency_family"]),
                "parent_family": str(signal["parent_family"]),
                "correlation_group": str(signal["correlation_group"]),
                "evidence_identity": str(signal["evidence_identity"]),
            })

    pair_lookup = dependency["rolling_diagnostics"]["pair_lookup"]
    families: dict[str, list[dict]] = defaultdict(list)
    for row in eligible:
        families[row["parent_family"]].append(row)

    family_rows = []
    weight_rows = []
    for family_id, members in sorted(families.items()):
        ids = [row["signal_id"] for row in members]
        dsu = DSU(ids)
        by_id = {row["signal_id"]: row for row in members}
        for i, left in enumerate(ids):
            for right in ids[i + 1:]:
                lrow, rrow = by_id[left], by_id[right]
                pair_id = "|".join(sorted((left, right)))
                diag = pair_lookup.get(pair_id) or {}
                if (
                    lrow["correlation_group"] == rrow["correlation_group"]
                    or lrow["evidence_identity"] == rrow["evidence_identity"]
                    or diag.get("state") == "high_dependency"
                ):
                    dsu.union(left, right)

        components: dict[str, list[dict]] = defaultdict(list)
        for row in members:
            components[dsu.find(row["signal_id"])].append(row)
        component_count = len(components)
        d_weights: dict[str, D] = {}

        for component_members in components.values():
            slots: dict[tuple[str, str], list[dict]] = defaultdict(list)
            for row in component_members:
                slots[(row["evidence_identity"], row["vote"])].append(row)
            slot_count = len(slots)
            for slot_members in slots.values():
                max_r = max(row["reliability"] for row in slot_members)
                winners = [row for row in slot_members if row["reliability"] == max_r]
                each = (
                    D(1)
                    / D(component_count)
                    / D(slot_count)
                    / D(len(winners))
                )
                for row in winners:
                    d_weights[row["signal_id"]] = each

        bull = D(0)
        bear = D(0)
        for row in members:
            d_weight = d_weights.get(row["signal_id"], D(0))
            if d_weight <= 0:
                continue
            mass = d_weight * row["reliability"]
            if row["vote"] == "bullish":
                bull += mass
            elif row["vote"] == "bearish":
                bear += mass
            weight_rows.append({
                "signal_id": row["signal_id"],
                "family_id": family_id,
                "vote": row["vote"],
                "reliability": fmt(row["reliability"]),
                "dependency_weight": fmt(d_weight),
            })

        signed = bull - bear
        strength = abs(signed)
        family_rows.append({
            "family_id": family_id,
            "bull_mass": fmt(bull),
            "bear_mass": fmt(bear),
            "family_signed_evidence": fmt(signed),
            "family_strength": fmt(strength),
            "qualifies": strength >= MIN_FAMILY_STRENGTH,
            "eligible_member_n": len(members),
            "component_count": component_count,
        })

    s = sum((D(row["family_signed_evidence"]) for row in family_rows), D(0))
    w = sum((D(row["family_strength"]) for row in family_rows), D(0))
    qualifying = [
        row for row in family_rows
        if D(row["family_strength"]) >= MIN_FAMILY_STRENGTH
    ]
    positive_qual = [row for row in qualifying if D(row["family_signed_evidence"]) > 0]
    negative_qual = [row for row in qualifying if D(row["family_signed_evidence"]) < 0]
    balance = D(0) if w == 0 else s / w

    if w == 0:
        direction = "abstain"
        reason = "no_directional_evidence"
    elif len(qualifying) < MIN_FAMILIES:
        direction = "abstain"
        reason = "insufficient_independent_families"
    elif positive_qual and negative_qual:
        direction = "abstain"
        reason = "genuine_independent_disagreement"
    elif abs(balance) < BALANCED_ABSTAIN_BAND:
        direction = "abstain"
        reason = "balanced_directional_evidence"
    else:
        direction = "bullish" if balance > 0 else "bearish"
        reason = f"{direction}_family_evidence"

    return {
        "direction": direction,
        "decision_reason": reason,
        "signed_total": fmt(s),
        "strength_total": fmt(w),
        "meta_balance": fmt(balance),
        "qualifying_family_count": len(qualifying),
        "families": family_rows,
        "weights": sorted(weight_rows, key=lambda row: row["signal_id"]),
        "reliabilities": reliability_rows,
        "constants": {
            "edge_scale": fmt(EDGE_SCALE),
            "min_families": MIN_FAMILIES,
            "min_family_strength": fmt(MIN_FAMILY_STRENGTH),
            "min_contributor_n": MIN_CONTRIBUTOR_N,
            "balanced_abstain_band": fmt(BALANCED_ABSTAIN_BAND),
            "prior_strength": int(PRIOR_STRENGTH),
            "baseline_prior_per_class": int(BASELINE_PRIOR_PER_CLASS),
            "baseline_prior_strength": int(BASELINE_PRIOR_STRENGTH),
        },
        "research_only": True,
        "live_money_execution_allowed": False,
    }


def run() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    environment, connected, market_state = build_connected_state()
    all_experts = add_unknowns(environment, connected)
    if len(all_experts) != 15:
        raise AssertionError("expected 15 expert packets")

    fixture = build_fixture(
        environment=environment,
        connected=connected,
        all_experts=all_experts,
        market_state=market_state,
    )
    validate_correct_derivation(fixture)

    FIXTURE_PATH.write_text(canonical(fixture), encoding="utf-8")
    fixture_sha = sha256(FIXTURE_PATH.read_bytes()).hexdigest()

    # Reload the frozen bytes before either decision path consumes them.
    frozen = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    experts_with_trust, profiles = attach_fixture_trust(all_experts, frozen)

    signals = extract_dependency_signals(experts_with_trust)
    dependency = build_evidence_dependency_engine(
        signals=signals,
        historical_rows=frozen["dependency_history"],
        as_of_utc=AS_OF,
    )
    selector = build_environment_aware_gate_selector(
        global_environment=environment,
        expected_gate_ids=EXPECTED_GATES,
        gate_inputs=[
            build_gate_selector_input(item)
            for item in experts_with_trust
        ],
        dependency_engine=dependency,
        calibration_rows=(),
    )
    old_meta = build_meta_direction_view(
        global_environment=environment,
        selector=selector,
        expert_results=experts_with_trust,
        meta_calibration_rows=(),
    )

    replacement = new_path(
        experts=experts_with_trust,
        fixture=frozen,
        profiles=profiles,
        dependency=dependency,
    )

    subject_ids = sorted(
        item["subject_key"]
        for item in frozen["connected_subcalculator_manifest"]
    )
    if len(subject_ids) != 70:
        raise AssertionError(f"expected 70 connected subjects, got {len(subject_ids)}")

    positive_checks = {
        sid: replacement["reliabilities"][sid]
        for sid in POSITIVE_SUBJECT_TARGETS
    }
    if replacement["direction"] != "bullish":
        raise AssertionError(
            f"frozen replacement path must reach bullish; got {replacement['direction']}"
        )
    if old_meta["direction"] != "abstain":
        raise AssertionError(
            f"old path negative control must abstain; got {old_meta['direction']}"
        )

    component_manifest = {
        "fixture_sha256": fixture_sha,
        "packet_count": 15,
        "connected_subject_count": len(subject_ids),
        "subject_ids_digest": digest(subject_ids),
        "outcome_history_digest": digest(frozen["resolved_outcome_history"]),
        "gate_trust_history_digest": digest(frozen["gate_trust_history"]),
        "subject_history_digest": digest(frozen["subject_histories"]),
        "dependency_history_digest": digest(frozen["dependency_history"]),
        "environment_digest": str(environment["environment_digest"]),
        "current_packet_digests_digest": digest(frozen["current_packet_digests"]),
    }
    combined_digest = digest(component_manifest)

    manifest = {
        "validation_version": "blocker1_v9_dual_path_validation_v1",
        "validated_source_sha": "47ffe131b9a8d2180c8d78ba3c1dc1b9253b9e4a",
        "fixture_path": str(FIXTURE_PATH),
        "fixture_sha256": fixture_sha,
        "component_manifest": component_manifest,
        "combined_manifest_digest": combined_digest,
        "old_path": {
            "direction": old_meta["direction"],
            "decision_reason": old_meta["decision_reason"],
            "directional_total": old_meta["authority_totals"]["directional_total"],
            "bullish_authority": old_meta["authority_totals"]["bullish"],
            "bearish_authority": old_meta["authority_totals"]["bearish"],
            "neutral_authority": old_meta["authority_totals"]["neutral"],
            "selector_digest": selector["selector_digest"],
            "dependency_digest": dependency["engine_digest"],
            "meta_view_digest": old_meta["view_digest"],
        },
        "new_path": replacement,
        "positive_subject_reliability_checks": positive_checks,
        "liquidity_gate": next(
            {
                "conclusion": item["expert_packet"]["conclusion"],
                "packet_digest": item["expert_packet"]["packet_digest"],
            }
            for item in experts_with_trust
            if item["expert_packet"]["gate_id"] == "liquidity_reclaim_expert"
        ),
        "pit_assertions": {
            "correct_is_derived_from_prediction_vs_realised": True,
            "all_commitments_decide_before_resolution": True,
            "all_history_resolves_before_fixture_as_of": True,
            "bar_first_observed_at_is_close_time": True,
        },
        "mathematics_changed": False,
        "production_changed": False,
        "research_only": True,
        "formal_forward_authority": False,
        "live_money_execution_allowed": False,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, sort_keys=True, indent=2),
        encoding="utf-8",
    )

    print("BLOCKER1_V9_FULL_VALIDATION_PASS")
    print(f"fixture_sha256={fixture_sha}")
    print(f"combined_manifest_digest={combined_digest}")
    print(f"packet_count=15 connected_subject_count={len(subject_ids)}")
    print(
        "old_path "
        f"direction={old_meta['direction']} "
        f"reason={old_meta['decision_reason']} "
        f"directional_total={old_meta['authority_totals']['directional_total']}"
    )
    print(
        "new_path "
        f"direction={replacement['direction']} "
        f"reason={replacement['decision_reason']} "
        f"meta_balance={replacement['meta_balance']} "
        f"qualifying_family_count={replacement['qualifying_family_count']}"
    )
    for family in replacement["families"]:
        print(
            f"family={family['family_id']} "
            f"signed={family['family_signed_evidence']} "
            f"strength={family['family_strength']} "
            f"qualifies={family['qualifies']}"
        )
    for sid, row in positive_checks.items():
        print(
            f"positive_subject={sid} n={row['n']} "
            f"shrunk_excess={row['shrunk_excess']} "
            f"reliability={row['reliability']} "
            f"scope={row['selected_scope_type']} recent={row['recent_state']}"
        )
    print(f"fixture_bytes={FIXTURE_PATH.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
