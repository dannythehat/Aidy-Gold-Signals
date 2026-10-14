"""Read-only single-public-page TradingView source/report evidence probe.

This is a narrowly scoped, unauthenticated research diagnostic. The unofficial
third-party SDK relies on private website endpoints and is NOT TradingView
endorsed. Avoid logging complete copyrighted Pine sources; preserve a digest
and minimal metadata. No session cookies, API keys, trading or write actions.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass

from tradingview_sdk import TradingView


SLUGS = (
    "5Q1KJZuZ-XAUUSD-M5-Hybrid-EMA-9-15-Partial-TP-Runner",
    "NX1lrLtL-EMA-Pullback-Dual-Crossover-Pro-EA-v14-XAUUSD",
    "V7pgMYj7-EMA-Pullback-Dual-Crossover-Pro-Strategy",
    "5q4PsY3a-XAUUSD-Scalping-AGRESIV",
    "JjQLyuRb-EMA-9-21-Cross-Touch-Breakout-BOT-Enter-System",
    "FM0NqXZL-GOLD-EMA-Crossover-Strategy",
)


def short(value):
    if value is None:
        return None
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, (str, float, int, bool)):
        return str(value)[:240]
    return repr(value)[:450]


def main():
    outcomes = []
    with TradingView() as tv:
        for slug in SLUGS:
            result = {"slug": slug}
            try:
                page = tv.get_strategy(slug)
                original = page.source.source_text if page.source else None
                trades = page.report.trades if page.report else None
                result.update({
                    "status": "SOURCE_AND_REPORT_READ",
                    "title": short(page.title),
                    "chart_symbol": short(page.chart_symbol),
                    "chart_interval": short(page.chart_interval),
                    "source_present": isinstance(original, str) and len(original) > 0,
                    "source_sha256": (
                        hashlib.sha256(original.encode()).hexdigest()
                        if isinstance(original, str) else None
                    ),
                    "source_length": len(original) if original else 0,
                    "has_v6": "//@version=6" in original if original else False,
                    "contains_crossover": "ta.crossover" in original if original else False,
                    "report_present": page.report is not None,
                    "trade_records": len(trades) if trades is not None else None,
                    "trade_sample": [short(x) for x in (trades or [])[:3]],
                })
            except Exception as exc:
                result.update({
                    "status": "UNAVAILABLE",
                    "exception_type": type(exc).__name__,
                    "reason": str(exc)[:320],
                })
            if (result["status"] == "SOURCE_AND_REPORT_READ"
                and slug == "5q4PsY3a-XAUUSD-Scalping-AGRESIV"
                and trades):
                from datetime import UTC, datetime
                ordered = sorted((t["e"]["tm"], t["e"].get("c", ""))
                                 for t in trades if isinstance(t, dict)
                                 and isinstance(t.get("e"), dict)
                                 and type(t["e"].get("tm")) is int)
                print("TV_GOLD_TRADE_CLOCK_RANGE", json.dumps({
                    "count":len(ordered),
                    "earliest":datetime.fromtimestamp(ordered[0][0]/1000, UTC).isoformat(),
                    "latest":datetime.fromtimestamp(ordered[-1][0]/1000, UTC).isoformat(),
                    "last_three":[
                        (datetime.fromtimestamp(t/1000, UTC).isoformat(),label)
                        for t,label in ordered[-3:]],
                },sort_keys=True))
            if (result["status"] == "SOURCE_AND_REPORT_READ"
                and slug == "5q4PsY3a-XAUUSD-Scalping-AGRESIV"):
                try:
                    native_trades=page.report.trades
                    entry_times=sorted(int(x["e"]["tm"]) for x in native_trades
                                       if isinstance(x,dict) and isinstance(x.get("e"),dict)
                                       and "tm" in x["e"])
                    result["trade_first_epoch_ms"]=entry_times[0] if entry_times else None
                    result["trade_last_epoch_ms"]=entry_times[-1] if entry_times else None
                    result["trade_latest_8_epoch_ms"]=entry_times[-8:]
                    hist=tv.get_bars("OANDA:XAUUSD", "5", bars=1500)
                    rows=list(hist)
                    result["native_m5_bars_count"]=len(rows)
                    result["native_m5_first_epoch_s"]=rows[0].time if rows else None
                    result["native_m5_last_epoch_s"]=rows[-1].time if rows else None
                    result["native_m5_latest_3"]=[
                        {"time":x.time,"open":x.open,"high":x.high,"low":x.low,"close":x.close}
                        for x in rows[-3:]
                    ]
                except Exception as exc:
                    result["bar_probe_exception"]=type(exc).__name__ + ": " + str(exc)[:300]
            outcomes.append(result)
            print("TV_REFERENCE_PROBE", json.dumps(result, sort_keys=True))
    print("TV_PROBE_SUMMARY", json.dumps({
        "source": "TradingView public published strategy page via nonofficial SDK",
        "unauthenticated_read_only": True,
        "outcomes": outcomes,
        "original_user_pine_ema_fixture_executed_by_platform": False,
        "day22_original_source_parity_proven": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
