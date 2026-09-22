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
from decimal import Decimal as D
from zoneinfo import ZoneInfo

from aidy.gold_cycle_environment import build_cycle_environment
from aidy.gold_price_expert_math import build_price_expert_math_packet
from aidy.gold_expert_shadow import EXPECTED_GATES, _DISCONNECTED_CONTEXT_GATES
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

def main() -> int:
    spine = m1_spine(45)                      # 45-day aggregate horizon, per production
    rows = spine[-2880:]                      # M1 decision window = 2 days, per production
    print(f"M1 spine (45d market-open): {len(spine)}   M1 decision window: {len(rows)}")
    print(f"  earliest {rows[0]['open_time_utc']}  latest {rows[-1]['open_time_utc']}")
    span_h = (rows[-1]['open_time_utc'] - rows[0]['open_time_utc']).total_seconds()/3600
    print(f"  wall-clock span {span_h:.1f}h for {len(rows)} open minutes "
          f"-> {span_h*60/len(rows):.2f} wall-min per market-min (closures skipped)")
    base_aggs = aggregate(spine)
    spine, injected_level = inject_bullish_prior_day_low_reclaim(spine, base_aggs)
    rows = spine[-2880:]
    aggs = aggregate(spine)
    e = env(spine, aggs)
    print(f"  injected prior-day-low reclaim level: {injected_level}")                   # aggregates span the full 45 days
    by_tf = {}
    for a in aggs: by_tf[a["timeframe"]] = by_tf.get(a["timeframe"], 0) + 1
    print("  aggregates:", by_tf)
    allc = rows + aggs
    pm = build_price_expert_math_packet(as_of=AS_OF, symbol="XAUUSD", candle_rows=allc, mode="pit")
    common = {"global_environment": e, "price_math_packet": pm}

    results = []
    for b in (build_m5_price_structure_expert, build_m15_price_structure_expert,
              build_h1_price_structure_expert, build_h4_price_structure_expert,
              build_d1_context_expert, build_price_location_expert):
        results.append(b(**common))
    loc = next(r for r in results if r["expert_packet"]["gate_id"] == PRICE_LOCATION_GATE_ID)
    results.append(build_momentum_impulse_expert(**common, m1_candle_rows=rows))
    liq = build_liquidity_reclaim_expert(**common, price_location_result=loc,
                                                 m1_candle_rows=rows, retrospective_gc_flow_rows=())
    results.append(liq)
    print("\n-- liquidity active events --")
    for ev in liq.get("events") or []:
        if ev.get("proxy_state") not in {"no_sweep", "penetrated_no_reclaim"}:
            print(ev["reference"], ev["proxy_state"], ev["level_side"], ev.get("confirmation_closes"),
                  ev.get("retest_hold"), ev.get("penetration_depth_bps"))
    print("liquidity conclusion:", liq["expert_packet"]["conclusion"])
    print("liquidity directional votes:",
          [(x["calculator_id"], x["vote"], x["scoreable"])
           for x in liq["expert_packet"]["subcalculators"] if x["role"] == "directional"])
    results.append(build_volatility_jump_expert(**common, m1_candle_rows=rows,
                                                clock_volatility_history=(), qualified_volatility_state=None))
    results.append(build_session_participation_expert(global_environment=e, m1_candle_rows=rows,
                                                      weekday_clock_history=(), gc_activity_context=None))

    manifest = []
    for r in results:
        p = r["expert_packet"]
        for c in p["subcalculators"]:
            manifest.append({
                "subject_id": f'{p["gate_id"]}:{c["calculator_id"]}',
                "gate_id": p["gate_id"], "calculator_id": c["calculator_id"],
                "calculator_version": c["version"], "role": c["role"],
                "dependency_family": c["dependency_family"],
                "state": c["state"], "vote": c["vote"], "scoreable": c["scoreable"],
            })
    print("\n-- computed gate conclusions --")
    for rr in results:
        pp = rr["expert_packet"]
        print(pp["gate_id"], pp["gate_mode"], pp["conclusion"], pp["gate_scoreable"])
    print(f"\nreal experts computed: {len(results)}  (+{len(_DISCONNECTED_CONTEXT_GATES)} explicit UNKNOWN = {len(results)+len(_DISCONNECTED_CONTEXT_GATES)} of {len(EXPECTED_GATES)})")
    print(f"real subcalculator subjects: {len(manifest)}")
    elig = [m for m in manifest if m["role"]=="directional" and m["state"]=="known"
            and m["vote"] in ("bullish","bearish","neutral")]
    print(f"directional+known+vote in b/b/n: {len(elig)}")
    print(f"  of which scoreable (bullish/bearish): {sum(1 for m in elig if m['scoreable'])}")
    print("\n-- sample real subject ids --")
    for m in manifest[:14]:
        print(f"  {m['subject_id']:<62} {m['role']:<12} {m['state']:<9} {m['vote']:<8} sc={m['scoreable']}")
    json.dump(manifest, open("/tmp/real_manifest.json","w"), indent=2)
    print("\nwrote /tmp/real_manifest.json")
    return 0

raise SystemExit(main())
