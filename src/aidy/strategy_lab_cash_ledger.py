"""Day17 append-only, disk-backed XAUUSD research cash/equity event journal.

No actual margin/rollover policy or live brokerage. Instrument assumed USD
per ounce with an explicitly qualified ounces-per-lot numeric contract.
All state is reconstructed and rehashed from immutable SQLite event records.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from pathlib import Path

CENT=Decimal("0.01")
CASH_KINDS=frozenset({"deposit","withdrawal","commission","slippage","swap"})


def _money(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def _positive(value: str) -> Decimal:
    if not isinstance(value,str):
        raise ValueError("exact Decimal string required")
    try:
        x=Decimal(value)
    except (ValueError,ArithmeticError) as exc:
        raise ValueError("invalid value") from exc
    if not x.is_finite() or x<=0:
        raise ValueError("positive finite value required")
    return x


def _stamp(s: str) -> datetime:
    if not isinstance(s,str) or not s.endswith("Z"):
        raise ValueError("event timestamp UTC/Z required")
    try:
        dt=datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValueError("invalid timestamp") from exc
    if dt.utcoffset()!=timedelta(0):
        raise ValueError("event UTC required")
    return dt.astimezone(UTC)


def _canonical(obj: dict) -> str:
    return json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=False)


@dataclass(frozen=True)
class JournalView:
    cash_usd: Decimal
    realized_usd: Decimal
    unrealized_usd: Decimal
    equity_usd: Decimal
    open_positions: tuple[tuple[str,str,Decimal,Decimal],...]
    event_count: int
    tip_sha256: str


class CashJournal:
    def __init__(self, file_path: str | Path, *,
                 ounces_per_lot: Decimal, source_sha256: str) -> None:
        if not isinstance(ounces_per_lot,Decimal) or not ounces_per_lot.is_finite() or ounces_per_lot<=0:
            raise ValueError("positive ounces/lot required")
        if not isinstance(source_sha256,str) or len(source_sha256)!=64 or any(x not in "0123456789abcdef" for x in source_sha256):
            raise ValueError("original broker source SHA required")
        self.path=Path(file_path)
        self.ounces_per_lot=ounces_per_lot
        self.source_sha256=source_sha256

    def _conn(self):
        conn=sqlite3.connect(str(self.path),timeout=20)
        conn.row_factory=sqlite3.Row
        return conn

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self._conn() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS journal_events(
                seq INTEGER PRIMARY KEY,
                key TEXT NOT NULL UNIQUE,
                at_utc TEXT NOT NULL,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                previous_sha256 TEXT NOT NULL,
                record_sha256 TEXT NOT NULL,
                broker_source_sha256 TEXT NOT NULL
            )""")
            for act in ("UPDATE","DELETE"):
                db.execute(f"""CREATE TRIGGER IF NOT EXISTS events_no_{act.lower()}
                    BEFORE {act} ON journal_events BEGIN
                      SELECT RAISE(ABORT,'append-only journal');
                    END""")

    def _events(self, db: sqlite3.Connection) -> list[sqlite3.Row]:
        guards={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        if not {"events_no_update","events_no_delete"}<=guards:
            raise ValueError("missing append-only journal guards")
        return db.execute("SELECT * FROM journal_events ORDER BY seq").fetchall()

    def _rebuild(self, records: list[sqlite3.Row]) -> JournalView:
        cash=realized=Decimal(0)
        positions: dict[str, tuple[str,Decimal,Decimal]]={}
        mark: tuple[Decimal,Decimal] | None=None
        last_time: datetime | None=None
        prev="0"*64
        for expected,r in enumerate(records,1):
            if r["seq"]!=expected or r["previous_sha256"]!=prev or r["broker_source_sha256"]!=self.source_sha256:
                raise ValueError("journal chain or source identity mismatch")
            header={key:r[key] for key in (
                "seq","key","at_utc","kind","payload_json","previous_sha256",
                "broker_source_sha256"
            )}
            if sha256(_canonical(header).encode()).hexdigest()!=r["record_sha256"]:
                raise ValueError("journal tampering detected")
            prev=r["record_sha256"]
            at=_stamp(r["at_utc"])
            if last_time is not None and at<last_time:
                raise ValueError("journal event chronology mismatch")
            last_time=at
            try:
                obj=json.loads(r["payload_json"])
            except json.JSONDecodeError as exc:
                raise ValueError("corrupt event payload") from exc
            if _canonical(obj)!=r["payload_json"] or not isinstance(obj,dict):
                raise ValueError("noncanonical event payload")
            kind=r["kind"]
            if kind in CASH_KINDS:
                if set(obj)!={"usd"}:
                    raise ValueError("cash event schema mismatch")
                amount=Decimal(obj["usd"])
                if not amount.is_finite() or amount!=_money(amount):
                    raise ValueError("invalid cash cents")
                if kind=="deposit" and amount<=0:
                    raise ValueError("deposit must credit")
                if kind in ("withdrawal","commission","slippage") and amount>=0:
                    raise ValueError("fee/withdrawal must debit")
                cash+=amount
                if cash<0:
                    raise ValueError("negative cash unsupported")
            elif kind=="open":
                if set(obj)!={"id","direction","price","lots"}:
                    raise ValueError("open schema mismatch")
                ident=obj["id"]
                direction=obj["direction"]
                if not isinstance(ident,str) or not ident or ident in positions:
                    raise ValueError("duplicate position")
                if direction not in ("long","short"):
                    raise ValueError("position direction invalid")
                p,l=_positive(obj["price"]),_positive(obj["lots"])
                positions[ident]=(direction,p,l)
            elif kind=="close":
                if set(obj)!={"id","price","lots"} or obj["id"] not in positions:
                    raise ValueError("close schema or ID mismatch")
                ident=obj["id"]
                p,l=_positive(obj["price"]),_positive(obj["lots"])
                direction,entry,remaining=positions[ident]
                if l>remaining:
                    raise ValueError("closing more than open position")
                sign=Decimal(1) if direction=="long" else Decimal(-1)
                profit=_money((p-entry)*sign*l*self.ounces_per_lot)
                realized+=profit
                cash+=profit
                if cash<0:
                    raise ValueError("negative cash unsupported")
                if l==remaining:
                    del positions[ident]
                else:
                    positions[ident]=(direction,entry,remaining-l)
            elif kind=="mark":
                if set(obj)!={"bid","ask"}:
                    raise ValueError("mark schema")
                bid,ask=_positive(obj["bid"]),_positive(obj["ask"])
                if bid>ask:
                    raise ValueError("crossed mark prices")
                mark=(bid,ask)
            else:
                raise ValueError("unknown journal cash/event kind")
        unrealized=Decimal(0)
        if mark is not None:
            bid,ask=mark
            for direction,entry,lots in positions.values():
                exit_side=bid if direction=="long" else ask
                sign=Decimal(1) if direction=="long" else Decimal(-1)
                unrealized+=_money((exit_side-entry)*sign*lots*self.ounces_per_lot)
        elif positions:
            raise ValueError("open position without a current mark")
        return JournalView(_money(cash),_money(realized),_money(unrealized),
                           _money(cash+unrealized),
                           tuple(sorted((i,*v) for i,v in positions.items())),
                           len(records),prev)

    def view(self) -> JournalView:
        with self._conn() as db:
            return self._rebuild(self._events(db))

    def append(self, key: str, at_utc: str, kind: str, data: dict) -> JournalView:
        if not isinstance(key,str) or not key.strip() or key!=key.strip():
            raise ValueError("event key missing")
        _stamp(at_utc)
        if kind not in CASH_KINDS|{"open","close","mark"} or not isinstance(data,dict):
            raise ValueError("unknown journal event kind/data")
        payload=_canonical(data)
        with self._conn() as db:
            db.execute("BEGIN IMMEDIATE")
            existing=self._events(db)
            if any(row["key"]==key for row in existing):
                raise ValueError("duplicate event key")
            last=self._rebuild(existing)
            next_seq=len(existing)+1
            header={
                "seq":next_seq,"key":key,"at_utc":at_utc,"kind":kind,
                "payload_json":payload,"previous_sha256":last.tip_sha256,
                "broker_source_sha256":self.source_sha256
            }
            signature=sha256(_canonical(header).encode()).hexdigest()
            # Validate the entire proposed chain and cash accounting before any INSERT.
            draft=dict(header,record_sha256=signature)
            class Row(dict):
                pass
            candidate=self._rebuild([*existing,Row(draft)])
            db.execute("""INSERT INTO journal_events
                (seq,key,at_utc,kind,payload_json,previous_sha256,record_sha256,broker_source_sha256)
                VALUES(?,?,?,?,?,?,?,?)""",(
                    next_seq,key,at_utc,kind,payload,last.tip_sha256,
                    signature,self.source_sha256
                ))
            db.commit()
            return candidate
