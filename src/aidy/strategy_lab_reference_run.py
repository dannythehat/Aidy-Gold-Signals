"""Day19 first complete synthetic closed-bar -> orders -> cost -> USD ledger run.

THIS IS AN INTERNAL ENGINEERING FIXTURE, NOT A REAL STRATEGY OR VERIFIED ALPHA.
No external source fidelity or real Vantage broker fills are claimed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from aidy.strategy_lab_bidask_execution import QuoteTape, research_round_trip
from aidy.strategy_lab_broker_profile import BrokerProfile
from aidy.strategy_lab_deterministic_replay import canonical_events, replay_cash_events
from aidy.strategy_lab_fees_funding import apply_research_costs
from aidy.strategy_lab_order_lifecycle import OrderIntent, simulate_order


def _closed_bars(original: bytes, expected_sha: str) -> list[tuple[datetime,Decimal]]:
    if sha256(original).hexdigest()!=expected_sha:
        raise ValueError("reference candle source hash mismatched")
    try:
        obj=json.loads(original.decode())
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("invalid closed-bar source") from exc
    if not isinstance(obj,dict) or set(obj)!={"schema_version","source_class","symbol","clock","bars"}:
        raise ValueError("invalid reference market source format")
    if (obj["schema_version"],obj["source_class"],obj["symbol"],obj["clock"])!=(
        "aidy.internal_closed_m1.v1","internal_fixture_not_histdata","XAUUSD","UTC"
    ):
        raise ValueError("unsupported candle-source identity")
    if not isinstance(obj["bars"],list) or len(obj["bars"])!=55:
        raise ValueError("exact frozen 55 bar sample required")
    out=[]
    last=None
    for data in obj["bars"]:
        if not isinstance(data,dict) or set(data)!={"closed_at_utc","close"}:
            raise ValueError("closed bar schema mismatch")
        stamp=data["closed_at_utc"]
        if not isinstance(stamp,str) or not stamp.endswith("Z"):
            raise ValueError("closed-bar timestamp must be UTC/Z")
        at=datetime.fromisoformat(stamp).astimezone(UTC)
        price=Decimal(data["close"])
        if not price.is_finite() or price<=0:
            raise ValueError("invalid source close")
        if last is not None and at-last!=timedelta(minutes=1):
            raise ValueError("source M1 bars missing or reordered")
        last=at
        out.append((at,price))
    return out


@dataclass(frozen=True)
class ReferenceResult:
    closed_candle_sha256: str
    quote_sha256: str
    rule_sha256: str
    entry_order_id: str
    exit_order_id: str
    entry_utc: datetime
    exit_utc: datetime
    journal_tip_sha256: str
    gross_usd: Decimal
    commissions_usd: Decimal
    slippage_usd: Decimal
    swaps_usd: Decimal
    net_usd: Decimal
    opening_cash_usd: Decimal
    closing_cash_usd: Decimal
    actual_broker_attested: bool = False


def run_internal_reference(
    *,
    closed_bar_source: bytes,
    expected_closed_bar_sha256: str,
    quote_tape: QuoteTape,
    broker_profile: BrokerProfile,
    broker_source_bytes: bytes,
    sqlite_path: Path,
) -> ReferenceResult:
    bars=_closed_bars(closed_bar_source,expected_closed_bar_sha256)
    # Exact limited reference rule, not an arbitrary third-party rule adapter.
    params={"schema":"aidy.internal_ref_rule.v1","threshold":"2649.00",
            "warmup_closed_bars":50,"maximum_holding_bars":5,
            "direction":"long","entry":"first_close_above_threshold"}
    rule_hash=sha256(json.dumps(params,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    threshold=Decimal(params["threshold"])
    if any(price>threshold for _,price in bars[:49]):
        raise ValueError("reference history violates first-cross rule")
    # Only the 50th CLOSED bar at 14:00 UTC may trigger.
    close_at,closing_price=bars[49]
    if closing_price<=threshold or bars[48][1]>threshold:
        raise ValueError("closed threshold signal not reproduced")
    exit_at=bars[54][0]
    if exit_at-close_at!=timedelta(minutes=5):
        raise ValueError("maximum holding clock mismatch")
    version="aidy-v1-"+rule_hash
    buy=simulate_order(broker_profile,broker_source_bytes,quote_tape,OrderIntent(
        version,"threshold_long_entry","buy","market",Decimal("0.1"),close_at,
        close_at+timedelta(seconds=30),
    ))
    sell=simulate_order(broker_profile,broker_source_bytes,quote_tape,OrderIntent(
        version,"five_closed_bars_exit","sell","market",Decimal("0.1"),exit_at,
        exit_at+timedelta(seconds=30),
    ))
    if buy.state!="filled" or sell.state!="filled":
        raise ValueError("reference quote entry or close not filled")
    actual=research_round_trip(
        broker_profile,broker_source_bytes,quote_tape,direction="long",lots="0.1",
        entry_signal_closed_at_utc=close_at,exit_signal_closed_at_utc=exit_at,
    )
    if (buy.events[-1].price!=actual.entry.fill_price
        or sell.events[-1].price!=actual.exit.fill_price
        or buy.events[-1].at_utc!=actual.entry.filled_at_utc
        or sell.events[-1].at_utc!=actual.exit.filled_at_utc):
        raise ValueError("order state machine and quote-side fill mismatch")
    costed=apply_research_costs(broker_profile,broker_source_bytes,quote_tape,actual)
    ev=[
        {"key":"fund","at_utc":"2026-10-14T13:00:00Z","kind":"deposit",
         "data":{"usd":"10000.00"}},
        {"key":"initial_mark","at_utc":"2026-10-14T14:00:00Z","kind":"mark",
         "data":{"bid":str(quote_tape.quotes[0].bid),
                 "ask":str(quote_tape.quotes[0].ask)}},
        {"key":"open","at_utc":actual.entry.filled_at_utc.isoformat().replace("+00:00","Z"),
         "kind":"open","data":{"id":"reference_trade","direction":"long",
                               "price":str(actual.entry.fill_price),"lots":"0.1"}},
    ]
    for i,event in enumerate(e for e in costed.events if e.at_utc==actual.entry.filled_at_utc):
        ev.append({"key":f"entry_charge_{i}","at_utc":event.at_utc.isoformat().replace("+00:00","Z"),
                   "kind":"slippage" if event.kind=="slippage_scenario" else event.kind,
                   "data":{"usd":format(event.usd,"f")}})
    ev.append({"key":"exit_mark","at_utc":actual.exit.filled_at_utc.isoformat().replace("+00:00","Z"),
               "kind":"mark","data":{"bid":str(quote_tape.quotes[actual.exit.quote_index].bid),
                                    "ask":str(quote_tape.quotes[actual.exit.quote_index].ask)}})
    ev.append({"key":"close","at_utc":actual.exit.filled_at_utc.isoformat().replace("+00:00","Z"),
               "kind":"close","data":{"id":"reference_trade","price":str(actual.exit.fill_price),"lots":"0.1"}})
    for i,event in enumerate(e for e in costed.events if e.at_utc==actual.exit.filled_at_utc):
        ev.append({"key":f"exit_charge_{i}","at_utc":event.at_utc.isoformat().replace("+00:00","Z"),
                   "kind":event.kind,"data":{"usd":format(event.usd,"f")}})
    source_sha=broker_profile.provenance.source_sha256
    manifest_sha=sha256(canonical_events(ev,source_sha)).hexdigest()
    journal=replay_cash_events(sqlite_path,ev,source_sha256=source_sha,
                               ounces_per_lot=broker_profile.contract.contract_ounces_per_lot,
                               expected_manifest_sha256=manifest_sha)
    if journal.equity_usd!=Decimal("10000.00")+costed.net_usd or journal.cash_usd!=journal.equity_usd:
        raise ValueError("full end-to-end $10000 cash ledger mismatch")
    return ReferenceResult(
        expected_closed_bar_sha256,quote_tape.snapshot_sha256,rule_hash,
        buy.order_id,sell.order_id,actual.entry.filled_at_utc,actual.exit.filled_at_utc,
        journal.journal_tip_sha256,costed.quote_gross_usd,
        costed.commission_usd,costed.slippage_usd,costed.funding_usd,
        costed.net_usd,Decimal("10000.00"),journal.cash_usd,
    )
