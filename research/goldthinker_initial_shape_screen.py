"""Exploratory GoldThinker shape census on AIDY retrospective XAUUSD data.

This is not a backtest, portfolio simulator, Bible validator, or broker fill study.
Shape thresholds are copied from GoldThinker's current canonical.py where noted.
Previous-14-bar mean range is an explicit ATR proxy, not GoldThinker's ATR.
The entire 2024-25 period is exploratory; it cannot serve as untouched holdout.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path

from google.cloud import bigquery
from google.oauth2 import service_account

PROJECT = "aidy-signals"
TIMES = {"M15": 15, "H1": 60, "H4": 240, "D1": 1440}
MAX_BYTES = 750_000_000
LOOKBACK = 14
LOOKAHEAD = 4
QUERY = """
SELECT timeframe, open_time_utc, open, high, low, close, research_identity
FROM `aidy-signals.aidy_analytics_test.research_candles`
WHERE open_time_utc >= TIMESTAMP('2024-01-01 00:00:00+00')
  AND open_time_utc < TIMESTAMP('2026-01-01 00:00:00+00')
  AND source = 'histdata'
  AND symbol = 'XAUUSD'
  AND provenance_class = 'retrospective_history'
  AND pit_eligible = FALSE
  AND timeframe IN ('M15', 'H1', 'H4', 'D1')
ORDER BY timeframe, open_time_utc
"""


def detect(curr: dict, prev: dict, atr_proxy: Decimal) -> list[tuple[str, str]]:
    o, h, l, c = curr["o"], curr["h"], curr["l"], curr["c"]
    po, ph, pl, pc = prev["o"], prev["h"], prev["l"], prev["c"]
    width, body = h - l, abs(c - o)
    pwidth, pbody = ph - pl, abs(pc - po)
    found: list[tuple[str, str]] = []
    if width <= 0 or pwidth <= 0:
        return found
    if width >= Decimal("0.5") * atr_proxy and body <= Decimal("0.33") * width:
        if min(o, c) - l >= Decimal("0.66") * width and h - max(o, c) <= Decimal("0.10") * width and c >= l + Decimal("0.75") * width:
            found.append(("P03_like_pin", "BULL"))
        if h - max(o, c) >= Decimal("0.66") * width and min(o, c) - l <= Decimal("0.10") * width and c <= h - Decimal("0.75") * width:
            found.append(("P03_like_pin", "BEAR"))
    if pbody > Decimal("0.05") * pwidth and body > pbody:
        if pc < po and c > o and o <= pc and c >= po:
            found.append(("P06_P07_like_engulf", "BULL"))
        if pc > po and c < o and o >= pc and c <= po:
            found.append(("P06_P07_like_engulf", "BEAR"))
    if h < ph and l > pl:
        found.append(("P09_inside_mother_shape", "NEUTRAL"))
    if body <= Decimal("0.05") * width:
        found.append(("doji_shape_observation", "NEUTRAL"))
    return found


def main() -> None:
    raw = os.environ.get("AIDY_GCP_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise SystemExit("Missing GitHub-held AIDY credential")
    info = json.loads(raw)
    if info.get("type") != "service_account" or info.get("project_id") != PROJECT:
        raise SystemExit("Service-account project mismatch")
    credentials = service_account.Credentials.from_service_account_info(info)
    client = bigquery.Client(project=PROJECT, location="EU", credentials=credentials)
    check = client.query(QUERY, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False), location="EU")
    if check.total_bytes_processed is None or check.total_bytes_processed > MAX_BYTES:
        raise SystemExit(f"Query size exceeds ceiling: {check.total_bytes_processed}")
    job = client.query(QUERY, job_config=bigquery.QueryJobConfig(maximum_bytes_billed=MAX_BYTES, use_query_cache=False), location="EU", job_id_prefix="goldthinker_shape_census_")
    items: dict[str, list[dict]] = defaultdict(list)
    source_ids = set()
    for r in job.result(timeout=150):
        tf = str(r.timeframe)
        row = {"t": r.open_time_utc, "o": Decimal(r.open), "h": Decimal(r.high), "l": Decimal(r.low), "c": Decimal(r.close), "id": r.research_identity}
        if row["h"] < max(row["o"], row["c"]) or row["l"] > min(row["o"], row["c"]) or row["h"] < row["l"]:
            raise SystemExit(f"Invalid OHLC record in {tf}")
        items[tf].append(row)
        source_ids.add(row["id"])
    if not source_ids:
        raise SystemExit("No data returned")
    if len(source_ids) != sum(len(rows) for rows in items.values()):
        raise SystemExit("Duplicate research identities")
    summary = defaultdict(lambda: {"shapes": 0, "forward_complete": 0, "forward_favourable": 0, "forward_flat": 0, "signed_4bar_R_total": Decimal(0)})
    source_counts = {}
    baselines = defaultdict(lambda: {"n": 0, "favourable": 0})
    for tf, bars in sorted(items.items()):
        bars.sort(key=lambda x: x["t"])
        if len(set(b["t"] for b in bars)) != len(bars):
            raise SystemExit(f"Multiple revisions for timeframe timestamps: {tf}")
        source_counts[tf] = len(bars)
        segments = []
        seg = []
        for b in bars:
            if seg:
                previous = seg[-1]["t"]
                delta_mins = int((b["t"] - previous).total_seconds() // 60)
                regular = delta_mins == TIMES[tf]
                # Friday-to-Sunday / Friday-to-Monday D1 gaps are expected
                # Gold-market closures. Other gaps remain censored.
                expected_d1_weekend = (
                    tf == "D1" and previous.weekday() == 4
                    and ((b["t"].weekday() == 6 and delta_mins == 2880)
                         or (b["t"].weekday() == 0 and delta_mins == 4320))
                )
                if not regular and not expected_d1_weekend:
                    segments.append(seg)
                    seg = []
            seg.append(b)
        if seg:
            segments.append(seg)
        for segment in segments:
            for i in range(LOOKBACK, len(segment)):
                cur, prev = segment[i], segment[i-1]
                atr_proxy = sum((x["h"] - x["l"] for x in segment[i-LOOKBACK:i]), Decimal(0)) / Decimal(LOOKBACK)
                if atr_proxy <= 0:
                    continue
                # Five previous completed-bar net close direction. A descriptive proxy, NOT market structure.
                prior_direction = "UP" if prev["c"] > segment[i-6]["c"] else ("DOWN" if prev["c"] < segment[i-6]["c"] else "FLAT")
                year = cur["t"].year
                if i + LOOKAHEAD < len(segment) and cur["h"] > cur["l"]:
                    forward_delta = segment[i+LOOKAHEAD]["c"] - cur["c"]
                    for baseline_side, factor in (("BULL", Decimal(1)), ("BEAR", Decimal(-1))):
                        base = baselines[(str(year),tf,prior_direction,baseline_side)]
                        base["n"] += 1
                        if factor*forward_delta > 0:
                            base["favourable"] += 1
                for pattern, side in detect(cur, prev, atr_proxy):
                    key = (str(year), tf, pattern, side, prior_direction)
                    agg = summary[key]
                    agg["shapes"] += 1
                    if side == "NEUTRAL" or i + LOOKAHEAD >= len(segment):
                        continue
                    future_close = segment[i+LOOKAHEAD]["c"]
                    direction = Decimal(1) if side == "BULL" else Decimal(-1)
                    delta_r = direction * (future_close - cur["c"]) / (cur["h"] - cur["l"])
                    agg["forward_complete"] += 1
                    agg["signed_4bar_R_total"] += delta_r
                    if delta_r > 0:
                        agg["forward_favourable"] += 1
                    elif delta_r == 0:
                        agg["forward_flat"] += 1
    data = []
    for key, v in sorted(summary.items()):
        year, tf, pattern, side, prior_direction = key
        n = v["forward_complete"]
        baseline = baselines.get((year,tf,prior_direction,side))
        baseline_pct = round(100*baseline["favourable"]/baseline["n"],2) if baseline and baseline["n"] else None
        data.append({
            "year": int(year), "timeframe": tf,
            "pattern": pattern, "side": side,
            "previous_5bar_close_direction_proxy": prior_direction,
            "candidate_shapes": v["shapes"],
            "four_bar_forward_evaluable": n,
            "four_bar_forward_favourable": v["forward_favourable"],
            "four_bar_forward_flat": v["forward_flat"],
            "directional_followthrough_pct": round(100*v["forward_favourable"]/n, 2) if n else None,
            "same_tf_year_prior_direction_all_bar_baseline_pct": baseline_pct,
            "mean_signed_forward_close_move_in_signal_range_units": round(float(v["signed_4bar_R_total"]/n), 4) if n else None,
        })
    totals = defaultdict(lambda: {"shapes": 0, "evaluable": 0, "favourable": 0})
    for x in data:
        k = (x["timeframe"], x["pattern"], x["side"])
        totals[k]["shapes"] += x["candidate_shapes"]
        totals[k]["evaluable"] += x["four_bar_forward_evaluable"]
        totals[k]["favourable"] += x["four_bar_forward_favourable"]
    aggregate = [
        {"timeframe":tf,"pattern":pattern,"side":side,**v,
         "followthrough_pct":round(100*v["favourable"]/v["evaluable"],2) if v["evaluable"] else None}
        for (tf,pattern,side),v in sorted(totals.items())
    ]
    result = {
        "status":"EXPLORATORY_ONLY",
        "source":"AIDY accepted 2024-25 retrospective HistData bid candles",
        "candidate_source":"GoldThinker canonical.py P03 / P06-P07 / P09-like independent screening, additional doji observation",
        "source_caveats":["This is a separate shape screener, NOT GoldThinker canonical engine parity", "Prior-14-bar mean range proxy is NOT GoldThinker ATR", "Previous-five-close direction is NOT market-structure trend", "Four subsequent completed same-timeframe bars, no abnormal gap bridging; D1 expected Friday-to-Sunday/Monday closures allowed", "No entry, stop, target, fills, spread, swap or PnL", "2024-25 entire period used for discovery; holdout NOT intact", "Shape patterns overlap, not independent trade opportunities"],
        "observed_utc":datetime.now(timezone.utc).isoformat(),
        "source_counts":source_counts,
        "baseline_groups":len(baselines),
        "total_source_research_identities":len(source_ids),
        "billed_bytes":job.total_bytes_billed,
        "group_rows":data,
        "all_year_summary":aggregate,
    }
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/goldthinker-shape-discovery.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"status":result["status"],"source_counts":source_counts,"total_source_research_identities":len(source_ids),"summary":aggregate},sort_keys=True))


if __name__ == "__main__":
    main()
