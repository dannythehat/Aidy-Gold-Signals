"""Day18 deterministic replay against real append-only Day17 SQLite journal.

An immutable externally pinned source manifest binds full ordered event bytes.
Repeated identical replay is idempotent; differences and damaged chains fail.
No trading system or broker automation.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any

from aidy.strategy_lab_cash_ledger import CashJournal


def canonical_events(events: list[dict], broker_sha256: str) -> bytes:
    if not isinstance(events, list) or not events:
        raise ValueError("requires non-empty source event list")
    required={"key","at_utc","kind","data"}
    seen=set()
    for item in events:
        if not isinstance(item,dict) or set(item)!=required or not isinstance(item["data"],dict):
            raise ValueError("event schema incomplete or contains unknown fields")
        key=item["key"]
        if not isinstance(key,str) or not key.strip() or key in seen:
            raise ValueError("duplicate or malformed source event identity")
        seen.add(key)
    if not isinstance(broker_sha256,str) or len(broker_sha256)!=64:
        raise ValueError("source contract digest missing")
    return json.dumps({"schema":"aidy.replay.v1","broker_source_sha256":broker_sha256,
                       "events":events},sort_keys=True,separators=(",",":")).encode()


@dataclass(frozen=True)
class ReplayReceipt:
    manifest_sha256: str
    journal_tip_sha256: str
    journal_event_count: int
    cash_usd: Decimal
    unrealized_usd: Decimal
    equity_usd: Decimal
    idempotent_events: int


def replay_cash_events(path: Path, events: list[dict], *,
                       source_sha256: str, ounces_per_lot: Decimal,
                       expected_manifest_sha256: str) -> ReplayReceipt:
    frozen=canonical_events(events,source_sha256)
    if sha256(frozen).hexdigest()!=expected_manifest_sha256:
        raise ValueError("frozen replay manifest digest mismatch")
    if not isinstance(path,Path):
        raise ValueError("expected isolated SQLite path")
    journal=CashJournal(path,ounces_per_lot=ounces_per_lot,source_sha256=source_sha256)
    journal.initialize()
    duplicate_count=0
    for item in events:
        # Verify immutable chain BEFORE considering whether a key already exists.
        journal.view()
        with sqlite3.connect(path) as db:
            existing=db.execute("SELECT at_utc,kind,payload_json FROM journal_events WHERE key=?",
                                (item["key"],)).fetchone()
        encoded=json.dumps(item["data"],sort_keys=True,separators=(",",":"),ensure_ascii=False)
        if existing is not None:
            if existing != (item["at_utc"],item["kind"],encoded):
                raise ValueError("conflicting replay event identity")
            duplicate_count+=1
            continue
        journal.append(item["key"],item["at_utc"],item["kind"],item["data"])
    v=journal.view()
    if v.event_count!=len(events):
        raise ValueError("journal contains extras or missing source events")
    return ReplayReceipt(expected_manifest_sha256,v.tip_sha256,v.event_count,
                         v.cash_usd,v.unrealized_usd,v.equity_usd,duplicate_count)
