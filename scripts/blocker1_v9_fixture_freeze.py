"""Blocker-1 T1 pipeline validator (READ-ONLY).

Runs the frozen source state through the REAL 15-gate production path:
  session-aware M1 spine -> aggregates -> cycle environment -> 10 real expert
  builders (+5 explicit UNKNOWN) -> real subcalculator manifest.

Run from the Aidy-Gold-Signals repo root:  uv run python <this file>
Touches no production state. Emits the real manifest for the pre-registration.
"""
from __future__ import annotations
import json
from datetime import UTC, datetime, timedelta
from collections import Counter, defaultdict
from copy import deepcopy
from hashlib import sha256
from decimal import Decimal as D
from zoneinfo import ZoneInfo

from aidy.gold_cycle_environment import build_cycle_environment
from aidy.gold_price_expert_math import build_price_expert_math_packet
from aidy.gold_expert_shadow import EXPECTED_GATES, _DISCONNECTED_CONTEXT_GATES, _unknown_context_result
from aidy.gold_m5_price_structure_expert import build_m5_price_structure_expert
from aidy.gold_m15_price_structure_expert import build_m15_price_structure_expert
from aidy.gold_h1_price_structure_expert import build_h1_price_structure_expert
from aidy.gold_h4_price_structure_expert import build_h4_price_structure_expert
from aidy.gold_d1_context_expert import build_d1_context_expert
from aidy.gold_price_location_expert import build_price_location_expert, PRICE_LOCATION_GATE_ID
from aidy.gold_momentum_impulse_expert import build_momentum_impulse_expert
from aidy.gold_liquidity_reclaim_expert import build_liquidity_reclaim_expert
from aidy.gold_volatility_jump_expert import build_volatility_jump_expert
from aidy.gold_session_participation_expert import build_session_participation_expert

NY = ZoneInfo("America/New_York")

def gold_open(dt: datetime) -> bool:
    """Frozen Gold session calendar: Sun 18:00 NY -> Fri 17:00 NY,
    with daily maintenance 17:00-18:00 NY Mon-Thu."""
    n = dt.astimezone(NY)
    wd, hm = n.weekday(), n.hour * 60 + n.minute      # Mon=0
    if wd == 5: return False                           # Saturday
    if wd == 6: return hm >= 18 * 60                   # Sunday opens 18:00
    if wd == 4: return hm < 17 * 60                    # Friday closes 17:00
    return not (17 * 60 <= hm < 18 * 60)               # Mon-Thu maintenance break

AS_OF = datetime(2026, 6, 3, 14, 0, tzinfo=UTC)        # Wednesday, NY session open
STEP = timedelta(minutes=1)

def m1_spine(days: int) -> list[dict]:
    """All MARKET-OPEN M1 minutes in the `days` before AS_OF (the aggregation source)."""
    stamps, cur, floor = [], AS_OF - STEP, AS_OF - timedelta(days=days)
    while cur >= floor:
        if gold_open(cur): stamps.append(cur)
        cur -= STEP
    stamps.reverse()
    return _price(stamps)

def _price(stamps):
    rows, price = [], D("3650.00")
    for i, opened in enumerate(stamps):
        # deterministic LCG -> varied but fully reproducible path (no RNG import)
        seed = (1103515245 * (i + 12345) + 12345) % 2147483648
        step = D(seed % 141 - 70) / D(100)
        o = price; price = (price + step).quantize(D("0.01"))
        rows.append({
            "symbol": "XAUUSD", "timeframe": "M1", "open_time_utc": opened,
            "open": str(o), "high": str(max(o, price) + D("0.15")),
            "low": str(min(o, price) - D("0.15")), "close": str(price),
            "source": "blocker1_t1_fixture", "source_file_sha256": "a"*64,
            "source_payload_sha256": "b"*64, "derivation_version": "blocker1-t1-v1",
            "load_identity": f"b1t1-M1-{i}", "provenance_class": "pit_observed",
            "pit_eligible": True,
            # PIT: a COMPLETED bar can first be observed at its CLOSE, not its open
            "first_observed_at": (opened + STEP).isoformat(),
        })
    return rows

AGG = {"M5":5, "M15":15, "H1":60, "H4":240, "D1":1440}

def aggregate(m1: list[dict]) -> list[dict]:
    """Derive M5/M15/H1/H4/D1 from the market-open M1 series (deterministic)."""
    out = []
    for tf, mins in AGG.items():
        buckets = {}
        for r in m1:
            ot = r["open_time_utc"]
            key = ot - timedelta(minutes=ot.minute % mins if mins < 60 else 0,
                                 seconds=ot.second, microseconds=ot.microsecond)
            if mins >= 60:
                key = ot.replace(minute=0, second=0, microsecond=0)
                key -= timedelta(hours=key.hour % (mins // 60) if mins < 1440 else key.hour)
            buckets.setdefault(key, []).append(r)
        for i, (key, grp) in enumerate(sorted(buckets.items())):
            if len(grp) < max(2, mins // 4):     # ignore stub buckets
                continue
            out.append({
                "symbol": "XAUUSD", "timeframe": tf, "open_time_utc": key,
                "open": grp[0]["open"],
                "high": str(max(D(g["high"]) for g in grp)),
                "low": str(min(D(g["low"]) for g in grp)),
                "close": grp[-1]["close"],
                "source": "blocker1_t1_fixture", "source_file_sha256": "a"*64,
                "source_payload_sha256": "b"*64, "derivation_version": "blocker1-t1-v1",
                "load_identity": f"b1t1-{tf}-{i}", "provenance_class": "pit_observed",
                "pit_eligible": True,
                "first_observed_at": (key + timedelta(minutes=mins)).isoformat(),
            })
    return out

def env(spine=None, aggs=None) -> dict:
    mid = D(spine[-1]["close"]) if spine else D("3650.00")
    d1 = sorted([a for a in (aggs or []) if a["timeframe"]=="D1"], key=lambda x: x["open_time_utc"])
    pdh = D(d1[-2]["high"]) if len(d1) >= 2 else mid + D("8.00")
    pdl = D(d1[-2]["low"])  if len(d1) >= 2 else mid - D("8.00")
    def dist(level): return str(abs((level - mid) / mid * D(10000)).quantize(D("0.01")))
    location = {
        "mid": str(mid),
        "reference_distances": {
            "prior_day_high": {"level": str(pdh), "distance_bps": dist(pdh), "state": "known"},
            "prior_day_low":  {"level": str(pdl), "distance_bps": dist(pdl), "state": "known"},
        },
        "range_positions": {
            "prior_day": {"ratio": "0.62", "state": "known"},
            "asia_overnight": {"ratio": "0.55", "state": "known"},
            "active_session": {"ratio": "0.60", "state": "known"},
        },
        "round_number_references": {
            "nearest_10_usd": {"level": str((mid/D(10)).quantize(D(1))*D(10)),
                               "distance_bps": dist((mid/D(10)).quantize(D(1))*D(10))},
            "nearest_50_usd": {"level": str((mid/D(50)).quantize(D(1))*D(50)),
                               "distance_bps": dist((mid/D(50)).quantize(D(1))*D(50))},
        },
    }
    return build_cycle_environment(
        as_of_utc=AS_OF, target_window_start_utc=AS_OF + timedelta(minutes=15),
        session_code="london_new_york_overlap", observed_state="bullish",
        gold_state={
            "market_structure": {"timeframes": {
                tf: {"net_close_direction": "up", "directional_persistence_ratio": "0.62",
                     "latest_close_range_position": "0.68", "state": "known"}
                for tf in ("M5", "M15", "H1", "H4")} | {"D1": {"net_close_direction": "up", "state": "known"}}},
            "move_observation": {"five_minute_distribution_state": "normal",
                "five_minute_range_state": "normal",
                "windows": {"5m": {"direction": "up", "return_bps": "2.0"},
                            "15m": {"direction": "up", "return_bps": "3.5"},
                            "60m": {"direction": "up", "return_bps": "6.0"}}},
            "volatility": {"state": "normal", "jump_continuous": {"state": "continuous_dominant"}},
            "scheduled_event_risk": {"state": "known", "timing_state": "outside_near_event_window"},
            "location": location,
        },
        semantic_context={"data_quality": {"quote_state": "known", "quote_freshness": "fresh",
                                           "spread_state": "unknown"},
                          "cross_market": {"series": {}}},
        regime={"compound_regime_key": "trend|normal"},
    )


def inject_bullish_prior_day_low_reclaim(spine: list[dict], aggs: list[dict]) -> tuple[list[dict], str]:
    """Force one explicit, PIT-safe low sweep/reclaim scenario into the last completed M1 bars."""
    d1 = sorted(
        [a for a in aggs if a["timeframe"] == "D1"],
        key=lambda x: x["open_time_utc"],
    )
    if len(d1) < 2:
        raise RuntimeError("need prior D1 bar for reclaim probe")
    level = D(d1[-2]["low"])
    closes = [
        level + D("1.40"), level + D("1.00"), level + D("0.70"),
        level + D("0.45"), level + D("0.65"), level + D("0.85"),
        level + D("1.05"), level + D("1.25"), level + D("1.45"),
        level + D("1.65"),
    ]
    start = len(spine) - len(closes)
    prev = closes[0] + D("0.20")
    for off, close in enumerate(closes):
        i = start + off
        row = dict(spine[i])
        opened = prev
        if off == 3:
            # Penetrate the known prior-day low, then close back above it in the same bar.
            low = level - D("1.20")
            high = max(opened, close) + D("0.25")
        elif off == 4:
            # Retest the level and hold above it.
            low = level - D("0.10")
            high = max(opened, close) + D("0.20")
        else:
            low = min(opened, close) - D("0.15")
            high = max(opened, close) + D("0.15")
        row["open"] = str(opened.quantize(D("0.01")))
        row["high"] = str(high.quantize(D("0.01")))
        row["low"] = str(low.quantize(D("0.01")))
        row["close"] = str(close.quantize(D("0.01")))
        spine[i] = row
        prev = close
    return spine, str(level)


from aidy.gold_expert_trust import (
    aggregate_context_rows,
    build_trust_envelope,
    select_conditional_trust,
    score_directional_outcome,
)
from aidy.gold_evidence_dependency import (
    FAMILY_PARENT,
    build_evidence_dependency_engine,
    extract_dependency_signals,
)
from aidy.gold_environment_gate_selector import (
    build_environment_aware_gate_selector,
    build_gate_selector_input,
)
from aidy.gold_meta_direction import build_meta_direction_view

FIXTURE_VERSION = "blocker1_t1_real_fixture_v9"
SOURCE_SHA = "47ffe131b9a8d2180c8d78ba3c1dc1b9253b9e4a"
HISTORY_CYCLES = 180
BASELINE_OUTCOMES = 5000
PRIOR_STRENGTH = D("20")
EDGE_SCALE = D("0.15")
MIN_CONTRIBUTOR_N = 12
MIN_FAMILIES = 2
MIN_FAMILY_STRENGTH = D("0.20")
BALANCED_ABSTAIN_BAND = D("0.20")

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def digest(value):
    return sha256(canonical(value).encode()).hexdigest()

def build_real_fixture_state():
    spine = m1_spine(45)
    base_aggs = aggregate(spine)
    spine, injected_level = inject_bullish_prior_day_low_reclaim(spine, base_aggs)
    rows = spine[-2880:]
    aggs = aggregate(spine)
    environment = env(spine, aggs)
    math = build_price_expert_math_packet(
        as_of=AS_OF,
        symbol="XAUUSD",
        candle_rows=rows + aggs,
        mode="pit",
    )
    common = {"global_environment": environment, "price_math_packet": math}
    results = []
    for builder in (
        build_m5_price_structure_expert,
        build_m15_price_structure_expert,
        build_h1_price_structure_expert,
        build_h4_price_structure_expert,
        build_d1_context_expert,
        build_price_location_expert,
    ):
        results.append(builder(**common))
    location = next(
        item for item in results
        if item["expert_packet"]["gate_id"] == "price_location_expert"
    )
    results.append(build_momentum_impulse_expert(
        **common,
        m1_candle_rows=rows,
    ))
    results.append(build_liquidity_reclaim_expert(
        **common,
        price_location_result=location,
        m1_candle_rows=rows,
        retrospective_gc_flow_rows=(),
    ))
    results.append(build_volatility_jump_expert(
        **common,
        m1_candle_rows=rows,
        clock_volatility_history=(),
        qualified_volatility_state=None,
    ))
    results.append(build_session_participation_expert(
        global_environment=environment,
        m1_candle_rows=rows,
        weekday_clock_history=(),
        gc_activity_context=None,
    ))
    for gate_id, (version, family) in _DISCONNECTED_CONTEXT_GATES.items():
        results.append(_unknown_context_result(
            gate_id=gate_id,
            gate_version=version,
            dependency_family=family,
            global_environment=environment,
        ))
    by_gate = {
        str(item["expert_packet"]["gate_id"]): item
        for item in results
    }
    if set(by_gate) != set(EXPECTED_GATES):
        raise AssertionError("fixture gate registry mismatch")
    experts = [by_gate[gate_id] for gate_id in EXPECTED_GATES]
    liq = by_gate["liquidity_reclaim_expert"]
    if liq["expert_packet"]["conclusion"] != "bullish":
        raise AssertionError("fixture must contain a real builder-detected bullish liquidity reclaim")
    if not any(
        item["scoreable"] and item["vote"] == "bullish"
        for item in liq["expert_packet"]["subcalculators"]
    ):
        raise AssertionError("liquidity fixture has no scoreable bullish calculator")
    return {
        "spine": spine,
        "m1_window": rows,
        "aggregates": aggs,
        "environment": environment,
        "experts": experts,
        "injected_level": injected_level,
    }

def _window_market_open(start):
    return all(gold_open(start + timedelta(minutes=i)) for i in range(15))

def historical_cycle_times(count):
    cursor = AS_OF - timedelta(minutes=15)
    out = []
    while len(out) < count:
        if (
            cursor.minute % 15 == 0
            and cursor.second == 0
            and _window_market_open(cursor)
        ):
            out.append(cursor)
        cursor -= timedelta(minutes=15)
    return list(reversed(out))

def build_outcome_history():
    times = historical_cycle_times(BASELINE_OUTCOMES)
    pattern = ("bullish", "bearish", "bullish", "bearish", "neutral")
    rows = []
    for i, decision in enumerate(times):
        realised = pattern[i % len(pattern)]
        return_bps = "6.000000" if realised == "bullish" else "-6.000000" if realised == "bearish" else "0.500000"
        resolved = decision + timedelta(minutes=15)
        row = {
            "outcome_id": f"fixture_outcome_{i:05d}",
            "decision_time_utc": decision.isoformat(),
            "resolved_at_utc": resolved.isoformat(),
            "realised_direction": realised,
            "realised_return_bps": return_bps,
        }
        row["outcome_digest"] = digest(row)
        rows.append(row)
    if not all(datetime.fromisoformat(r["resolved_at_utc"]) < AS_OF for r in rows):
        raise AssertionError("all fixture outcomes must resolve before as_of")
    return rows

def _target_rate(subject_type, current):
    if subject_type == "gate":
        return D("0.52") if current["gate_mode"] == "directional" else None
    if current["role"] != "directional" or current["state"] != "known":
        return None
    if current["scoreable"] and current["vote"] == "bullish":
        return D("0.55")
    if current["scoreable"] and current["vote"] == "bearish":
        return D("0.39")
    if current["vote"] == "neutral":
        return D("0.38")
    return None

def _prediction_plan(subject_key, cycles, rate):
    directional_positions = [
        i for i, row in enumerate(cycles)
        if row["realised_direction"] in {"bullish", "bearish"}
    ]
    target_correct = int((rate * D(len(cycles))).to_integral_value())
    target_correct = min(target_correct, len(directional_positions))
    correct_positions = set()
    total = len(directional_positions)
    for rank, idx in enumerate(directional_positions):
        before = (rank * target_correct) // total
        after = ((rank + 1) * target_correct) // total
        if after > before:
            correct_positions.add(idx)
    predictions = []
    for i, row in enumerate(cycles):
        realised = row["realised_direction"]
        if i in correct_positions:
            predicted = realised
        elif realised == "bullish":
            predicted = "bearish"
        elif realised == "bearish":
            predicted = "bullish"
        else:
            bit = int(sha256(f"{subject_key}|{i}".encode()).hexdigest()[:2], 16) % 2
            predicted = "bullish" if bit == 0 else "bearish"
        predictions.append(predicted)
    return predictions

def subject_specs(experts):
    specs = []
    for expert in experts:
        packet = expert["expert_packet"]
        gate_id = str(packet["gate_id"])
        specs.append({
            "subject_type": "gate",
            "subject_id": gate_id,
            "subject_version": str(packet["gate_version"]),
            "gate_id": gate_id,
            "gate_version": str(packet["gate_version"]),
            "gate_mode": str(packet["gate_mode"]),
            "target_horizon_minutes": int(packet["target_horizon_minutes"]),
            "current_packet_digest": str(packet["packet_digest"]),
            "current_vote": str(packet["conclusion"]),
            "role": "directional" if packet["gate_mode"] == "directional" else "context_only",
            "state": "known" if any(x["state"] == "known" for x in packet["subcalculators"]) else "unavailable",
            "scoreable": bool(packet["gate_scoreable"]),
            "dependency_family": str(packet["dependency_family"]),
            "scope_keys": [str(x["scope_key"]) for x in expert["trust_scopes"]],
        })
        for calc in packet["subcalculators"]:
            specs.append({
                "subject_type": "subcalculator",
                "subject_id": str(calc["calculator_id"]),
                "subject_version": str(calc["version"]),
                "signal_id": f"{gate_id}:{calc['calculator_id']}",
                "gate_id": gate_id,
                "gate_version": str(packet["gate_version"]),
                "gate_mode": str(packet["gate_mode"]),
                "target_horizon_minutes": int(packet["target_horizon_minutes"]),
                "current_packet_digest": str(packet["packet_digest"]),
                "current_vote": str(calc["vote"]),
                "role": str(calc["role"]),
                "state": str(calc["state"]),
                "scoreable": bool(calc["scoreable"]),
                "dependency_family": str(calc["dependency_family"]),
                "scope_keys": [str(x["scope_key"]) for x in expert["trust_scopes"]],
            })
    return specs

def build_commitment_history(experts, outcomes):
    cycles = outcomes[-HISTORY_CYCLES:]
    specs = subject_specs(experts)
    ledger = []
    subject_summary = []
    for spec in specs:
        current = {
            "gate_mode": spec["gate_mode"],
            "role": spec["role"],
            "state": spec["state"],
            "scoreable": spec["scoreable"],
            "vote": spec["current_vote"],
        }
        rate = _target_rate(spec["subject_type"], current)
        key = f"{spec['subject_type']}:{spec['gate_id']}:{spec['subject_id']}"
        if rate is None:
            subject_summary.append({
                **spec,
                "history_commitment_n": 0,
                "construction_target_rate": None,
            })
            continue
        predictions = _prediction_plan(key, cycles, rate)
        correct_n = 0
        for idx, (cycle, predicted) in enumerate(zip(cycles, predictions, strict=True)):
            decision_time = str(cycle["decision_time_utc"])
            realised = str(cycle["realised_direction"])
            scored = score_directional_outcome(
                vote=predicted,
                realised_direction=realised,
                realised_return_bps=cycle["realised_return_bps"],
                scoreable=True,
            )
            derived_correct = int(predicted == realised)
            if scored["correct"] != derived_correct:
                raise AssertionError("production scorer and explicit correctness derivation disagree")
            correct_n += derived_correct
            packet_digest = "fixture_packet_" + sha256(
                f"{spec['gate_id']}|{decision_time}".encode()
            ).hexdigest()[:48]
            row = {
                "result_id": "fixture_result_" + sha256(
                    f"{packet_digest}|{spec['subject_type']}|{spec['subject_id']}".encode()
                ).hexdigest()[:40],
                "packet_digest": packet_digest,
                "current_packet_digest_anchor": spec["current_packet_digest"],
                "gate_id": spec["gate_id"],
                "gate_version": spec["gate_version"],
                "subject_type": spec["subject_type"],
                "subject_id": spec["subject_id"],
                "subject_version": spec["subject_version"],
                "target_horizon_minutes": spec["target_horizon_minutes"],
                "decision_time_utc": decision_time,
                "scope_keys": list(spec["scope_keys"]),
                "outcome_id": cycle["outcome_id"],
                "resolved_at_utc": cycle["resolved_at_utc"],
                "predicted_class": predicted,
                "realised_direction": realised,
                "realised_return_bps": cycle["realised_return_bps"],
                "score": int(scored["score"]),
                "correct": derived_correct,
                "impact_class": scored["impact_class"],
                "research_only": True,
                "live_money_execution_allowed": False,
            }
            if row["correct"] != int(row["predicted_class"] == row["realised_direction"]):
                raise AssertionError("correct was not derived")
            row["result_digest"] = digest(row)
            ledger.append(row)
        subject_summary.append({
            **spec,
            "history_commitment_n": len(cycles),
            "history_correct_n": correct_n,
            "history_accuracy": f"{D(correct_n) / D(len(cycles)):.6f}",
            "construction_target_rate": str(rate),
        })
    return ledger, subject_summary

def build_trust_rows_and_attach(experts, ledger):
    updated = []
    trust_rows = []
    for expert in experts:
        item = deepcopy(expert)
        packet = item["expert_packet"]
        scopes = item["trust_scopes"]
        profiles = {}
        subjects = [("gate", str(packet["gate_id"]), str(packet["gate_version"]))]
        subjects.extend(
            ("subcalculator", str(c["calculator_id"]), str(c["version"]))
            for c in packet["subcalculators"]
        )
        for subject_type, subject_id, subject_version in subjects:
            rows = aggregate_context_rows(
                results=ledger,
                scopes=scopes,
                subject_type=subject_type,
                subject_id=subject_id,
                subject_version=subject_version,
                as_of_utc=AS_OF,
            )
            for row in rows:
                trust_rows.append({
                    "gate_id": str(packet["gate_id"]),
                    "gate_version": str(packet["gate_version"]),
                    "current_packet_digest": str(packet["packet_digest"]),
                    "subject_type": subject_type,
                    "subject_id": subject_id,
                    "subject_version": subject_version,
                    **row,
                })
            profiles[f"{subject_type}:{subject_id}"] = select_conditional_trust(
                score_rows=rows,
                scopes=scopes,
            )
        item["trust_envelope"] = build_trust_envelope(
            packet=packet,
            profiles_by_subject=profiles,
        )
        updated.append(item)
    return updated, trust_rows

def dependency_history_from_ledger(ledger):
    by_time = defaultdict(dict)
    for row in ledger:
        if row["subject_type"] != "subcalculator":
            continue
        signal_id = f"{row['gate_id']}:{row['subject_id']}"
        by_time[row["decision_time_utc"]][signal_id] = row["predicted_class"]
    return [
        {"observed_at_utc": ts, "signals": dict(sorted(signals.items()))}
        for ts, signals in sorted(by_time.items())
    ]

def old_path(environment, experts, dep_history):
    signals = extract_dependency_signals(experts)
    dependency = build_evidence_dependency_engine(
        signals=signals,
        historical_rows=dep_history,
        as_of_utc=AS_OF,
    )
    selector = build_environment_aware_gate_selector(
        global_environment=environment,
        expected_gate_ids=EXPECTED_GATES,
        gate_inputs=[build_gate_selector_input(x) for x in experts],
        dependency_engine=dependency,
        calibration_rows=(),
    )
    meta = build_meta_direction_view(
        global_environment=environment,
        selector=selector,
        expert_results=experts,
        meta_calibration_rows=(),
    )
    return signals, dependency, selector, meta

def _baseline_at(outcomes, predicted, decision_time):
    decision = datetime.fromisoformat(decision_time)
    counts = Counter()
    total = 0
    for row in outcomes:
        if datetime.fromisoformat(row["resolved_at_utc"]) >= decision:
            break
        counts[row["realised_direction"]] += 1
        total += 1
    return (D(counts[predicted]) + D(10)) / (D(total) + D(30))

def _profile_map(experts):
    out = {}
    for expert in experts:
        for row in expert["trust_envelope"]["subject_profiles"]:
            out[(str(row["subject_type"]), str(row["subject_id"]))] = dict(row["profile"])
    return out

def _new_reliabilities(experts, ledger, outcomes):
    profiles = _profile_map(experts)
    by_subject = defaultdict(list)
    for row in ledger:
        if row["subject_type"] == "subcalculator":
            by_subject[(row["gate_id"], row["subject_id"], row["subject_version"])].append(row)
    recency_mults = {
        "recently_stronger": D("1"),
        "stable": D("1"),
        "insufficient_recent": D("0.90"),
        "recently_weaker": D("0.65"),
    }
    scope_mults = {
        "mini_exact": D("1"),
        "global_core": D("0.80"),
        "gate_global": D("0.70"),
        "neutral_prior": D("0.50"),
    }
    result = {}
    for expert in experts:
        packet = expert["expert_packet"]
        for calc in packet["subcalculators"]:
            signal_id = f"{packet['gate_id']}:{calc['calculator_id']}"
            rows = by_subject.get(
                (str(packet["gate_id"]), str(calc["calculator_id"]), str(calc["version"])),
                [],
            )
            n = len(rows)
            excess_sum = D(0)
            for row in rows:
                baseline = _baseline_at(
                    outcomes,
                    str(row["predicted_class"]),
                    str(row["decision_time_utc"]),
                )
                excess_sum += D(int(row["correct"])) - baseline
            shrunk_excess = (
                excess_sum / (D(n) + PRIOR_STRENGTH)
                if n else D(0)
            )
            quality = max(D(0), min(D(1), shrunk_excess / EDGE_SCALE))
            profile = profiles.get(("subcalculator", str(calc["calculator_id"])), {})
            scope_type = str(profile.get("selected_scope_type") or "neutral_prior")
            scope_mult = D("0.90") if scope_type.startswith("mini_reduced_") else scope_mults.get(scope_type, D("0.60"))
            recency_state = str(profile.get("recent_state") or "insufficient_recent")
            recency_mult = recency_mults.get(recency_state, D("0.85"))
            calibration_mult = D("0.85")
            reliability = quality * scope_mult * calibration_mult * recency_mult
            result[signal_id] = {
                "signal_id": signal_id,
                "n": n,
                "excess_sum": f"{excess_sum:.9f}",
                "shrunk_excess": f"{shrunk_excess:.9f}",
                "quality": f"{quality:.9f}",
                "scope_type": scope_type,
                "scope_multiplier": f"{scope_mult:.6f}",
                "calibration_multiplier": f"{calibration_mult:.6f}",
                "recency_state": recency_state,
                "recency_multiplier": f"{recency_mult:.6f}",
                "reliability": f"{reliability:.9f}",
            }
    return result

def new_path(signals, dependency, reliabilities):
    current = {str(x["signal_id"]): x for x in signals}
    high_pairs = {
        frozenset((str(p["left_signal_id"]), str(p["right_signal_id"])))
        for p in dependency["rolling_diagnostics"]["pairs"]
        if p.get("state") == "high_dependency"
    }
    eligible = {}
    excluded = {}
    for signal_id, signal in current.items():
        r = D(reliabilities.get(signal_id, {}).get("reliability", "0"))
        vote = str(signal["vote"])
        ok = (
            str(signal["state"]) == "known"
            and str(signal["role"]) == "directional"
            and int(reliabilities.get(signal_id, {}).get("n", 0)) >= MIN_CONTRIBUTOR_N
            and r > 0
            and vote in {"bullish", "bearish", "neutral"}
            and (
                vote == "neutral"
                or bool(
                    next(
                        (
                            c["scoreable"]
                            for e in EXPERTS_FOR_NEW_PATH
                            if e["expert_packet"]["gate_id"] == signal["gate_id"]
                            for c in e["expert_packet"]["subcalculators"]
                            if c["calculator_id"] == signal["calculator_id"]
                        ),
                        False,
                    )
                )
            )
        )
        if ok:
            eligible[signal_id] = signal
        else:
            excluded[signal_id] = {
                "vote": vote,
                "state": str(signal["state"]),
                "role": str(signal["role"]),
                "n": int(reliabilities.get(signal_id, {}).get("n", 0)),
                "reliability": str(reliabilities.get(signal_id, {}).get("reliability", "0")),
            }

    by_root = defaultdict(list)
    for signal_id, signal in eligible.items():
        by_root[str(signal["parent_family"])].append(signal_id)

    families = {}
    weights = {}
    for root, ids in sorted(by_root.items()):
        parent = {x: x for x in ids}
        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra
        for i, left in enumerate(ids):
            for right in ids[i+1:]:
                a, b = eligible[left], eligible[right]
                if (
                    str(a["correlation_group"]) == str(b["correlation_group"])
                    or str(a["evidence_identity"]) == str(b["evidence_identity"])
                    or frozenset((left, right)) in high_pairs
                ):
                    union(left, right)
        components = defaultdict(list)
        for sid in ids:
            components[find(sid)].append(sid)
        component_rows = []
        component_count = len(components)
        for members in components.values():
            slots = defaultdict(list)
            for sid in members:
                s = eligible[sid]
                slots[(str(s["evidence_identity"]), str(s["vote"]))].append(sid)
            slot_winners = []
            for slot_members in slots.values():
                max_r = max(D(reliabilities[s]["reliability"]) for s in slot_members)
                winners = sorted(
                    s for s in slot_members
                    if D(reliabilities[s]["reliability"]) == max_r
                )
                slot_winners.append(winners)
            slot_count = len(slot_winners)
            for winners in slot_winners:
                for sid in winners:
                    d_i = D(1) / D(component_count) / D(slot_count) / D(len(winners))
                    weights[sid] = d_i
            component_rows.append({
                "members": sorted(members),
                "slot_count": slot_count,
                "winner_sets": slot_winners,
            })
        bull = D(0)
        bear = D(0)
        neutral_share = D(0)
        for sid in ids:
            p = weights.get(sid, D(0))
            r = D(reliabilities[sid]["reliability"])
            vote = str(eligible[sid]["vote"])
            if vote == "bullish":
                bull += p * r
            elif vote == "bearish":
                bear += p * r
            elif vote == "neutral":
                neutral_share += p
        signed = bull - bear
        family_rel = bull + bear
        balance = D(0) if family_rel == 0 else signed / family_rel
        families[root] = {
            "eligible_signal_ids": sorted(ids),
            "component_count": component_count,
            "components": sorted(component_rows, key=lambda x: x["members"]),
            "bull_mass": f"{bull:.9f}",
            "bear_mass": f"{bear:.9f}",
            "neutral_share": f"{neutral_share:.9f}",
            "family_signed_evidence": f"{signed:.9f}",
            "family_strength": f"{abs(signed):.9f}",
            "family_reliability": f"{family_rel:.9f}",
            "family_balance": f"{balance:.9f}",
        }

    signed_total = sum((D(f["family_signed_evidence"]) for f in families.values()), D(0))
    strength_total = sum((D(f["family_strength"]) for f in families.values()), D(0))
    meta_balance = D(0) if strength_total == 0 else signed_total / strength_total
    qualifying = {
        k: v for k, v in families.items()
        if D(v["family_strength"]) >= MIN_FAMILY_STRENGTH
    }
    pos = [k for k, v in qualifying.items() if D(v["family_signed_evidence"]) > 0]
    neg = [k for k, v in qualifying.items() if D(v["family_signed_evidence"]) < 0]
    if strength_total == 0:
        direction, reason = "abstain", "no_directional_evidence"
    elif len(qualifying) < MIN_FAMILIES:
        direction, reason = "abstain", "insufficient_independent_families"
    elif pos and neg:
        direction, reason = "abstain", "genuine_independent_disagreement"
    elif abs(meta_balance) < BALANCED_ABSTAIN_BAND:
        direction, reason = "abstain", "balanced_directional_evidence"
    else:
        direction = "bullish" if meta_balance > 0 else "bearish"
        reason = f"{direction}_independent_family_evidence"
    return {
        "direction": direction,
        "decision_reason": reason,
        "S": f"{signed_total:.9f}",
        "W": f"{strength_total:.9f}",
        "meta_balance": f"{meta_balance:.9f}",
        "qualifying_family_count": len(qualifying),
        "qualifying_families": sorted(qualifying),
        "bullish_qualifying_families": sorted(pos),
        "bearish_qualifying_families": sorted(neg),
        "families": families,
        "weights": {k: f"{v:.12f}" for k, v in sorted(weights.items())},
        "eligible_signal_ids": sorted(eligible),
        "excluded_signals": excluded,
    }

def main():
    state = build_real_fixture_state()
    experts = state["experts"]
    outcomes = build_outcome_history()
    ledger, subject_summary = build_commitment_history(experts, outcomes)
    experts_with_trust, trust_rows = build_trust_rows_and_attach(experts, ledger)
    dep_history = dependency_history_from_ledger(ledger)
    signals, dependency, selector, old_meta = old_path(
        state["environment"],
        experts_with_trust,
        dep_history,
    )

    global EXPERTS_FOR_NEW_PATH
    EXPERTS_FOR_NEW_PATH = experts_with_trust
    reliabilities = _new_reliabilities(experts_with_trust, ledger, outcomes)
    new_meta = new_path(signals, dependency, reliabilities)

    learned_subjects = [
        row for row in subject_summary
        if row["subject_type"] == "subcalculator"
        and row["gate_id"] not in _DISCONNECTED_CONTEXT_GATES
    ]
    packet_subjects = [row for row in subject_summary if row["subject_type"] == "subcalculator"]
    if len(learned_subjects) != 70:
        raise AssertionError(f"expected 70 learned subcalculator subjects, got {len(learned_subjects)}")
    if len(packet_subjects) != 75:
        raise AssertionError(f"expected 75 packet subcalculators incl availability sentinels, got {len(packet_subjects)}")
    if len(experts) != 15:
        raise AssertionError("expected 15 packets")
    if not all(row["correct"] == int(row["predicted_class"] == row["realised_direction"]) for row in ledger):
        raise AssertionError("fixture contains independently stored correctness")
    if old_meta["direction"] != "abstain":
        raise AssertionError(f"old path should fail reachability fixture, got {old_meta['direction']}")
    if new_meta["direction"] != "bullish":
        raise AssertionError(f"new path should be bullish in Scenario A, got {new_meta['direction']}: {new_meta['decision_reason']}")
    if new_meta["qualifying_family_count"] < 2:
        raise AssertionError("new path did not establish two independent qualifying families")

    market_digest_payload = {
        "m1_window": state["m1_window"],
        "aggregates": state["aggregates"],
    }
    packet_digest_map = {
        x["expert_packet"]["gate_id"]: x["expert_packet"]["packet_digest"]
        for x in experts
    }
    digests = {
        "market_data_digest": digest(market_digest_payload),
        "environment_digest": str(state["environment"]["environment_digest"]),
        "packet_digest_map_digest": digest(packet_digest_map),
        "learned_subject_manifest_digest": digest(learned_subjects),
        "packet_subject_manifest_digest": digest(packet_subjects),
        "outcome_history_digest": digest(outcomes),
        "commitment_history_digest": digest(ledger),
        "trust_history_digest": digest(trust_rows),
        "dependency_history_digest": digest(dep_history),
        "old_path_dependency_digest": str(dependency["engine_digest"]),
        "old_path_selector_digest": str(selector["selector_digest"]),
        "old_path_meta_digest": str(old_meta["view_digest"]),
        "new_path_reliability_digest": digest(reliabilities),
        "new_path_result_digest": digest(new_meta),
    }
    combined = digest(digests)

    fixture = {
        "fixture_version": FIXTURE_VERSION,
        "source_aidy_sha": SOURCE_SHA,
        "as_of_utc": AS_OF.isoformat(),
        "mathematics_changed": False,
        "purpose": "production-shaped executable T1 reachability fixture; not empirical performance evidence",
        "construction_policy": {
            "market": "real session-aware builders, production-shaped 2-day M1 plus 45-day aggregates",
            "liquidity_scenario": "explicit prior-day-low OHLC sweep, reclaim, confirmation and retest hold; votes are builder-produced",
            "history_cycles": HISTORY_CYCLES,
            "baseline_outcome_rows": BASELINE_OUTCOMES,
            "global_outcome_pattern": ["bullish", "bearish", "bullish", "bearish", "neutral"],
            "gate_directional_target_accuracy": "0.52",
            "current_bullish_scoreable_subcalculator_target_accuracy": "0.55",
            "current_bearish_scoreable_subcalculator_target_accuracy": "0.39",
            "current_neutral_directional_subcalculator_target_accuracy": "0.38",
            "correctness_rule": "correct := int(predicted_class == realised_direction); never an independent construction field",
            "same_context_history": True,
            "calibration_rows": "empty -> production unknown multiplier 0.85",
            "formal_forward_authority": False,
            "live_money_execution_allowed": False,
        },
        "counts": {
            "packet_n": len(experts),
            "computed_packet_n": 10,
            "explicit_unknown_packet_n": 5,
            "learned_subcalculator_subject_n": len(learned_subjects),
            "packet_subcalculator_n_including_unknown_availability_sentinels": len(packet_subjects),
            "commitment_row_n": len(ledger),
            "trust_context_row_n": len(trust_rows),
            "outcome_row_n": len(outcomes),
            "dependency_history_cycle_n": len(dep_history),
        },
        "injected_prior_day_low_level": state["injected_level"],
        "environment": state["environment"],
        "packet_digest_map": packet_digest_map,
        "learned_subject_manifest": learned_subjects,
        "packet_subject_manifest": packet_subjects,
        "outcome_history": outcomes,
        "commitment_history": ledger,
        "trust_history": trust_rows,
        "dependency_history": dep_history,
        "new_path_reliabilities": reliabilities,
        "digests": digests,
        "combined_fixture_digest": combined,
    }
    execution = {
        "fixture_version": FIXTURE_VERSION,
        "source_aidy_sha": SOURCE_SHA,
        "combined_fixture_digest": combined,
        "old_path": {
            "direction": old_meta["direction"],
            "decision_reason": old_meta["decision_reason"],
            "directional_total": old_meta["authority_totals"]["directional_total"],
            "bullish": old_meta["authority_totals"]["bullish"],
            "bearish": old_meta["authority_totals"]["bearish"],
            "neutral": old_meta["authority_totals"]["neutral"],
            "selector_gate_rows": selector["all_gates"],
            "dependency_effective_weight_total": dependency["adjustments"]["directional_effective_weight_total"],
            "meta_view_digest": old_meta["view_digest"],
        },
        "new_path": new_meta,
        "assertions": {
            "real_15_packet_pipeline": True,
            "learned_subject_n_70": True,
            "five_unknown_availability_sentinels_separated_from_learned_manifest": True,
            "decision_time_explicit_on_every_commitment": True,
            "correctness_derived_not_independent": True,
            "old_path_executed_not_estimated": True,
            "old_path_abstains": True,
            "new_path_executes_same_state": True,
            "new_path_bullish": True,
            "two_or_more_qualifying_root_families": True,
            "mathematics_untouched": True,
            "production_untouched": True,
        },
    }
    open("blocker1_t1_v9_fixture.json", "w").write(json.dumps(fixture, sort_keys=True, indent=2) + "\n")
    open("blocker1_t1_v9_execution.json", "w").write(json.dumps(execution, sort_keys=True, indent=2) + "\n")
    print("V9_FIXTURE_COMBINED_DIGEST", combined)
    print("COUNTS", fixture["counts"])
    print("OLD_PATH", execution["old_path"]["direction"], execution["old_path"]["decision_reason"], execution["old_path"]["directional_total"])
    print("NEW_PATH", new_meta["direction"], new_meta["decision_reason"], new_meta["meta_balance"], new_meta["qualifying_families"])
    print("LIQUIDITY_LEVEL", state["injected_level"])
    return 0

EXPERTS_FOR_NEW_PATH = []
raise SystemExit(main())
