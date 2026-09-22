"""Disposable Blocker-1 v9 fixture execution probe.

Test-only. Runs the real 10 connected expert builders against the v8
production-shaped synthetic market, with a deterministic prior-day-low
sweep/reclaim injected into the final five completed M1 bars.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from zoneinfo import ZoneInfo

from aidy.gold_cycle_environment import build_cycle_environment
from aidy.gold_price_expert_math import build_price_expert_math_packet
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
AS_OF = datetime(2026, 6, 3, 14, 0, tzinfo=UTC)
STEP = timedelta(minutes=1)
AGG = {"M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}


def gold_open(dt: datetime) -> bool:
    n = dt.astimezone(NY)
    wd, hm = n.weekday(), n.hour * 60 + n.minute
    if wd == 5:
        return False
    if wd == 6:
        return hm >= 18 * 60
    if wd == 4:
        return hm < 17 * 60
    return not (17 * 60 <= hm < 18 * 60)


def _price(stamps: list[datetime]) -> list[dict]:
    rows, price = [], D("3650.00")
    for i, opened in enumerate(stamps):
        seed = (1103515245 * (i + 12345) + 12345) % 2147483648
        step = D(seed % 141 - 70) / D(100)
        o = price
        price = (price + step).quantize(D("0.01"))
        rows.append({
            "symbol": "XAUUSD",
            "timeframe": "M1",
            "open_time_utc": opened,
            "open": str(o),
            "high": str(max(o, price) + D("0.15")),
            "low": str(min(o, price) - D("0.15")),
            "close": str(price),
            "source": "blocker1_t1_fixture",
            "source_file_sha256": "a" * 64,
            "source_payload_sha256": "b" * 64,
            "derivation_version": "blocker1-t1-v9-probe",
            "load_identity": f"b1t1-M1-{i}",
            "provenance_class": "pit_observed",
            "pit_eligible": True,
            "first_observed_at": (opened + STEP).isoformat(),
        })
    return rows


def m1_spine(days: int) -> list[dict]:
    stamps, cur, floor = [], AS_OF - STEP, AS_OF - timedelta(days=days)
    while cur >= floor:
        if gold_open(cur):
            stamps.append(cur)
        cur -= STEP
    stamps.reverse()
    return _price(stamps)


def aggregate(m1: list[dict]) -> list[dict]:
    out = []
    for tf, mins in AGG.items():
        buckets = {}
        for r in m1:
            ot = r["open_time_utc"]
            key = ot - timedelta(
                minutes=ot.minute % mins if mins < 60 else 0,
                seconds=ot.second,
                microseconds=ot.microsecond,
            )
            if mins >= 60:
                key = ot.replace(minute=0, second=0, microsecond=0)
                key -= timedelta(
                    hours=key.hour % (mins // 60) if mins < 1440 else key.hour
                )
            buckets.setdefault(key, []).append(r)
        for i, (key, grp) in enumerate(sorted(buckets.items())):
            if len(grp) < max(2, mins // 4):
                continue
            out.append({
                "symbol": "XAUUSD",
                "timeframe": tf,
                "open_time_utc": key,
                "open": grp[0]["open"],
                "high": str(max(D(g["high"]) for g in grp)),
                "low": str(min(D(g["low"]) for g in grp)),
                "close": grp[-1]["close"],
                "source": "blocker1_t1_fixture",
                "source_file_sha256": "a" * 64,
                "source_payload_sha256": "b" * 64,
                "derivation_version": "blocker1-t1-v9-probe",
                "load_identity": f"b1t1-{tf}-{i}",
                "provenance_class": "pit_observed",
                "pit_eligible": True,
                "first_observed_at": (key + timedelta(minutes=mins)).isoformat(),
            })
    return out


def prior_day_low(aggs: list[dict]) -> D:
    d1 = sorted(
        [a for a in aggs if a["timeframe"] == "D1"],
        key=lambda x: x["open_time_utc"],
    )
    if len(d1) < 2:
        raise RuntimeError("fixture requires prior D1")
    return D(d1[-2]["low"])


def inject_low_reclaim(spine: list[dict], level: D) -> None:
    # Five completed M1 bars. Bar 2 sweeps below the frozen prior-day low and
    # closes back above it; bars 3-4 retest/hold; bar 5 confirms.
    values = [
        (level + D("0.52"), level + D("0.75"), level + D("0.17"), level + D("0.39")),
        (level + D("0.39"), level + D("0.49"), level - D("0.55"), level + D("0.27")),
        (level + D("0.27"), level + D("0.52"), level - D("0.03"), level + D("0.35")),
        (level + D("0.35"), level + D("0.63"), level - D("0.04"), level + D("0.43")),
        (level + D("0.43"), level + D("0.69"), level + D("0.15"), level + D("0.58")),
    ]
    for row, (o, h, l, c) in zip(spine[-5:], values, strict=True):
        row["open"], row["high"], row["low"], row["close"] = map(str, (o, h, l, c))


def env(spine: list[dict], aggs: list[dict]) -> dict:
    mid = D(spine[-1]["close"])
    d1 = sorted(
        [a for a in aggs if a["timeframe"] == "D1"],
        key=lambda x: x["open_time_utc"],
    )
    pdh = D(d1[-2]["high"])
    pdl = D(d1[-2]["low"])

    def dist(level: D) -> str:
        return str(abs((level - mid) / mid * D(10000)).quantize(D("0.01")))

    location = {
        "mid": str(mid),
        "reference_distances": {
            "prior_day_high": {
                "level": str(pdh),
                "distance_bps": dist(pdh),
                "state": "known",
            },
            "prior_day_low": {
                "level": str(pdl),
                "distance_bps": dist(pdl),
                "state": "known",
            },
        },
        "range_positions": {
            "prior_day": {"ratio": "0.62", "state": "known"},
            "asia_overnight": {"ratio": "0.55", "state": "known"},
            "active_session": {"ratio": "0.60", "state": "known"},
        },
        "round_number_references": {
            "nearest_10_usd": {
                "level": str((mid / D(10)).quantize(D(1)) * D(10)),
                "distance_bps": dist((mid / D(10)).quantize(D(1)) * D(10)),
            },
            "nearest_50_usd": {
                "level": str((mid / D(50)).quantize(D(1)) * D(50)),
                "distance_bps": dist((mid / D(50)).quantize(D(1)) * D(50)),
            },
        },
    }
    return build_cycle_environment(
        as_of_utc=AS_OF,
        target_window_start_utc=AS_OF + timedelta(minutes=15),
        session_code="london_new_york_overlap",
        observed_state="bullish",
        gold_state={
            "market_structure": {
                "timeframes": {
                    tf: {
                        "net_close_direction": "up",
                        "directional_persistence_ratio": "0.62",
                        "latest_close_range_position": "0.68",
                        "state": "known",
                    }
                    for tf in ("M5", "M15", "H1", "H4")
                }
                | {"D1": {"net_close_direction": "up", "state": "known"}}
            },
            "move_observation": {
                "five_minute_distribution_state": "normal",
                "five_minute_range_state": "normal",
                "windows": {
                    "5m": {"direction": "up", "return_bps": "2.0"},
                    "15m": {"direction": "up", "return_bps": "3.5"},
                    "60m": {"direction": "up", "return_bps": "6.0"},
                },
            },
            "volatility": {
                "state": "normal",
                "jump_continuous": {"state": "continuous_dominant"},
            },
            "scheduled_event_risk": {
                "state": "known",
                "timing_state": "outside_near_event_window",
            },
            "location": location,
        },
        semantic_context={
            "data_quality": {
                "quote_state": "known",
                "quote_freshness": "fresh",
                "spread_state": "unknown",
            },
            "cross_market": {"series": {}},
        },
        regime={"compound_regime_key": "trend|normal"},
    )


def main() -> int:
    spine = m1_spine(45)
    preliminary = aggregate(spine)
    frozen_pdl = prior_day_low(preliminary)
    inject_low_reclaim(spine, frozen_pdl)

    rows = spine[-2880:]
    aggs = aggregate(spine)
    environment = env(spine, aggs)
    all_candles = rows + aggs
    price_math = build_price_expert_math_packet(
        as_of=AS_OF,
        symbol="XAUUSD",
        candle_rows=all_candles,
        mode="pit",
    )
    common = {
        "global_environment": environment,
        "price_math_packet": price_math,
    }

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
        r for r in results
        if r["expert_packet"]["gate_id"] == PRICE_LOCATION_GATE_ID
    )
    results.append(build_momentum_impulse_expert(**common, m1_candle_rows=rows))
    liquidity = build_liquidity_reclaim_expert(
        **common,
        price_location_result=location,
        m1_candle_rows=rows,
        retrospective_gc_flow_rows=(),
    )
    results.append(liquidity)
    results.append(
        build_volatility_jump_expert(
            **common,
            m1_candle_rows=rows,
            clock_volatility_history=(),
            qualified_volatility_state=None,
        )
    )
    results.append(
        build_session_participation_expert(
            global_environment=environment,
            m1_candle_rows=rows,
            weekday_clock_history=(),
            gc_activity_context=None,
        )
    )

    print("BLOCKER1_V9_PROBE")
    print(f"frozen_prior_day_low={frozen_pdl}")
    print(f"final_mid={spine[-1]['close']}")
    print(f"computed_gate_count={len(results)}")
    for result in results:
        packet = result["expert_packet"]
        directional = [
            f"{c['calculator_id']}={c['vote']}"
            for c in packet["subcalculators"]
            if c["role"] == "directional"
            and c["state"] == "known"
            and c["vote"] in {"bullish", "bearish", "neutral"}
        ]
        print(
            f"GATE {packet['gate_id']} conclusion={packet['conclusion']} "
            f"scoreable={packet['gate_scoreable']} directional={','.join(directional)}"
        )

    print("LIQUIDITY_ACTIVE_EVENTS")
    for event in liquidity["events"]:
        if event["proxy_state"] not in {"no_sweep", "penetrated_no_reclaim"}:
            print(
                f"{event['reference']} state={event['proxy_state']} "
                f"side={event['level_side']} depth_bps={event['penetration_depth_bps']} "
                f"reclaim_speed={event['reclaim_speed_bucket']} "
                f"confirmations={event['confirmation_closes']} "
                f"retest_hold={event['retest_hold']}"
            )
    print(f"LIQUIDITY_CONCLUSION={liquidity['expert_packet']['conclusion']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
