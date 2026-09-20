from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from aidy.gold_movement_investigator import (
    GOLD_MOVEMENT_INVESTIGATOR_VERSION,
    GOLD_MOVEMENT_LEARNING_CARD_VERSION,
    build_gold_movement_learning_card,
    verify_gold_movement_investigation,
    verify_gold_movement_learning_card,
)
from aidy.private_forward_context import build_private_forward_decision_inputs
from aidy.twelve_data_storage import D1TwelveDataMarketStore

GOLD_MOVEMENT_MEMORY_VERSION = "aidy_gold_movement_memory_v1"
MOVEMENT_EPISODE_COOLDOWN_MINUTES = 10
MOVEMENT_FORWARD_HORIZON_MINUTES = 60


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


def _ceil_next_minute(value: datetime) -> datetime:
    stamp = value.astimezone(UTC).replace(second=0, microsecond=0)
    return stamp + timedelta(minutes=1)


def _movement_episode_id(snapshot_id: str, investigation_digest: str) -> str:
    return f"aidy_move_{_digest({'snapshot_id': snapshot_id, 'digest': investigation_digest})[:32]}"


def _movement_card_id(episode_id: str, learning_digest: str) -> str:
    return f"aidy_move_card_{_digest({'episode_id': episode_id, 'digest': learning_digest})[:32]}"


def _forward_window_returns(
    *,
    bars: list[Mapping[str, Any]],
    start: datetime,
) -> dict[str, dict[str, Any]]:
    ordered = sorted(
        (
            row
            for row in bars
            if isinstance(row, Mapping) and row.get("open_time_utc") is not None
        ),
        key=lambda row: _utc(str(row["open_time_utc"]), name="open_time_utc"),
    )
    if not ordered:
        return {
            name: {"return_bps": None}
            for name in ("5m", "15m", "30m", "60m")
        }
    reference = _decimal(ordered[0].get("open"))
    if reference is None or reference <= 0:
        return {
            name: {"return_bps": None}
            for name in ("5m", "15m", "30m", "60m")
        }

    result: dict[str, dict[str, Any]] = {}
    for name, minutes in (("5m", 5), ("15m", 15), ("30m", 30), ("60m", 60)):
        deadline = start + timedelta(minutes=minutes)
        eligible = [
            row
            for row in ordered
            if _utc(str(row["open_time_utc"]), name="open_time_utc") < deadline
        ]
        close = _decimal(eligible[-1].get("close")) if eligible else None
        if close is None:
            result[name] = {"return_bps": None}
            continue
        move_bps = ((close - reference) / reference) * Decimal("10000")
        result[name] = {"return_bps": str(move_bps.quantize(Decimal("0.000001")))}
    return result


class D1GoldMovementMemoryStore:
    def __init__(self, d1: Any) -> None:
        self._d1 = d1

    async def _latest_candidate_snapshots(
        self, *, as_of: datetime, limit: int
    ) -> list[dict[str, Any]]:
        result = await self._d1.prepare(
            """
            SELECT id,captured_at
            FROM market_snapshots
            WHERE symbol='XAUUSD'
              AND market_data_source='twelve_data'
              AND capture_status='complete'
              AND captured_at<=?
              AND json_extract(data_availability_json,'$.request_kind')='scheduled_capture'
              AND json_extract(data_availability_json,'$.request_ledger_status')='succeeded'
            ORDER BY captured_at DESC,id DESC
            LIMIT ?
            """
        ).bind(as_of.isoformat(), max(1, min(int(limit), 30))).all()
        rows = _results(result)
        rows.reverse()
        return rows

    async def _already_seen_snapshot(self, snapshot_id: str) -> bool:
        row = _row(
            await self._d1.prepare(
                """
                SELECT movement_episode_id
                FROM aidy_gold_movement_investigations
                WHERE source_snapshot_id=?
                LIMIT 1
                """
            ).bind(snapshot_id).first()
        )
        return row is not None

    async def _recent_episode_exists(
        self, *, trigger_at: datetime, move_direction: str
    ) -> bool:
        lower = trigger_at - timedelta(minutes=MOVEMENT_EPISODE_COOLDOWN_MINUTES)
        row = _row(
            await self._d1.prepare(
                """
                SELECT movement_episode_id
                FROM aidy_gold_movement_investigations
                WHERE trigger_at_utc>=?
                  AND trigger_at_utc<=?
                  AND move_direction=?
                ORDER BY trigger_at_utc DESC
                LIMIT 1
                """
            ).bind(lower.isoformat(), trigger_at.isoformat(), move_direction).first()
        )
        return row is not None

    async def detect_and_store(
        self, *, now_utc: datetime, limit: int = 10
    ) -> dict[str, int]:
        now = _utc(now_utc, name="now_utc")
        rows = await self._latest_candidate_snapshots(as_of=now, limit=limit)
        stats = {"snapshots_checked": 0, "abnormal_detected": 0, "episodes_stored": 0, "deduped": 0}

        for row in rows:
            snapshot_id = str(row.get("id") or "")
            if not snapshot_id or await self._already_seen_snapshot(snapshot_id):
                continue
            stats["snapshots_checked"] += 1
            inputs = await build_private_forward_decision_inputs(
                d1=self._d1,
                snapshot_id=snapshot_id,
            )
            context = inputs.get("context")
            context = context if isinstance(context, Mapping) else {}
            extensions = context.get("architecture_v2_extensions")
            extensions = extensions if isinstance(extensions, Mapping) else {}
            investigation = extensions.get("gold_movement_investigation")
            if not isinstance(investigation, Mapping):
                continue
            if not verify_gold_movement_investigation(investigation):
                raise ValueError("Gold movement memory received invalid investigation.")
            if investigation.get("investigation_required") is not True:
                continue

            stats["abnormal_detected"] += 1
            trigger_at = _utc(str(investigation["as_of_utc"]), name="investigation.as_of_utc")
            direction = str(investigation.get("move_direction") or "unknown")
            if await self._recent_episode_exists(
                trigger_at=trigger_at,
                move_direction=direction,
            ):
                stats["deduped"] += 1
                continue

            investigation_digest = str(investigation["investigation_digest"])
            episode_id = _movement_episode_id(snapshot_id, investigation_digest)
            text = _canonical_json(dict(investigation))
            await self._d1.prepare(
                """
                INSERT INTO aidy_gold_movement_investigations (
                    movement_episode_id,investigator_version,source_snapshot_id,
                    trigger_at_utc,move_direction,attribution_state,triggered_by_json,
                    investigation_json,investigation_digest,recorded_at_utc
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(movement_episode_id) DO NOTHING
                """
            ).bind(
                episode_id,
                GOLD_MOVEMENT_INVESTIGATOR_VERSION,
                snapshot_id,
                trigger_at.isoformat(),
                direction,
                str(investigation.get("attribution_state") or "cause_unknown"),
                _canonical_json(list(investigation.get("triggered_by") or [])),
                text,
                investigation_digest,
                now.isoformat(),
            ).run()
            stats["episodes_stored"] += 1
        return stats

    async def resolve_matured(
        self, *, now_utc: datetime, limit: int = 10
    ) -> dict[str, int]:
        now = _utc(now_utc, name="now_utc")
        result = await self._d1.prepare(
            """
            SELECT i.movement_episode_id,i.trigger_at_utc,i.investigation_json
            FROM aidy_gold_movement_investigations i
            LEFT JOIN aidy_gold_movement_learning_cards c
              ON c.movement_episode_id=i.movement_episode_id
            WHERE c.movement_card_id IS NULL
              AND julianday(i.trigger_at_utc) + (? / 1440.0) <= julianday(?)
            ORDER BY i.trigger_at_utc,i.movement_episode_id
            LIMIT ?
            """
        ).bind(
            MOVEMENT_FORWARD_HORIZON_MINUTES,
            now.isoformat(),
            max(1, min(int(limit), 50)),
        ).all()
        rows = _results(result)
        market = D1TwelveDataMarketStore(self._d1)
        stats = {"matured": len(rows), "cards_stored": 0, "pending_market_path": 0}

        for row in rows:
            investigation = json.loads(str(row["investigation_json"]))
            if not isinstance(investigation, dict) or not verify_gold_movement_investigation(
                investigation
            ):
                raise ValueError("Stored Gold movement investigation failed verification.")
            trigger_at = _utc(str(row["trigger_at_utc"]), name="trigger_at_utc")
            start = _ceil_next_minute(trigger_at)
            deadline = start + timedelta(minutes=MOVEMENT_FORWARD_HORIZON_MINUTES)
            bars = await market.latest_m1_bars(start_utc=start, end_utc=deadline)
            windows = _forward_window_returns(bars=bars, start=start)
            if windows["60m"]["return_bps"] is None:
                stats["pending_market_path"] += 1
                continue

            card = build_gold_movement_learning_card(
                investigation=investigation,
                available_at=now,
                forward_windows=windows,
            )
            if not verify_gold_movement_learning_card(card):
                raise RuntimeError("Gold movement learning card failed verification.")
            card_id = _movement_card_id(
                str(row["movement_episode_id"]),
                str(card["learning_card_digest"]),
            )
            await self._d1.prepare(
                """
                INSERT INTO aidy_gold_movement_learning_cards (
                    movement_card_id,learning_card_version,movement_episode_id,
                    available_at_utc,path_class,initial_move_direction,attribution_state,
                    card_json,learning_card_digest,recorded_at_utc
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(movement_card_id) DO NOTHING
                """
            ).bind(
                card_id,
                GOLD_MOVEMENT_LEARNING_CARD_VERSION,
                str(row["movement_episode_id"]),
                str(card["available_at_utc"]),
                str(card["path_class"]),
                str(card["initial_move_direction"]),
                str(card["attribution_state"]),
                _canonical_json(card),
                str(card["learning_card_digest"]),
                now.isoformat(),
            ).run()
            stats["cards_stored"] += 1
        return stats

    async def analogous_cards(
        self,
        *,
        as_of_utc: datetime,
        investigation: Mapping[str, Any],
        limit: int = 8,
        candidate_limit: int = 100,
    ) -> dict[str, Any]:
        """Retrieve prior movement lessons available before the current investigation."""

        if not verify_gold_movement_investigation(investigation):
            raise ValueError("Movement analogue retrieval requires a verified investigation.")
        as_of = _utc(as_of_utc, name="as_of_utc")
        cards = await self.recent_cards(
            as_of_utc=as_of,
            limit=max(limit, min(int(candidate_limit), 100)),
        )
        current_direction = str(investigation.get("move_direction") or "unknown")
        current_triggers = set(str(x) for x in investigation.get("triggered_by") or [])
        current_leading = investigation.get("leading_mechanism")
        current_leading = current_leading if isinstance(current_leading, Mapping) else {}
        current_mechanism = str(current_leading.get("mechanism") or "unknown")
        current_attribution = str(investigation.get("attribution_state") or "cause_unknown")

        ranked: list[tuple[Decimal, dict[str, Any]]] = []
        for card in cards:
            trigger_at = card.get("trigger_at_utc")
            if trigger_at is not None and _utc(str(trigger_at), name="card.trigger_at_utc") >= as_of:
                continue
            score = Decimal("0")
            if str(card.get("initial_move_direction") or "") == current_direction:
                score += Decimal("2")
            card_triggers = set(str(x) for x in card.get("triggered_by") or [])
            union = current_triggers | card_triggers
            if union:
                score += Decimal("2") * Decimal(len(current_triggers & card_triggers)) / Decimal(
                    len(union)
                )
            card_leading = card.get("leading_mechanism")
            card_leading = card_leading if isinstance(card_leading, Mapping) else {}
            card_mechanism = str(card_leading.get("mechanism") or "unknown")
            if current_mechanism != "unknown" and card_mechanism == current_mechanism:
                score += Decimal("3")
            if str(card.get("attribution_state") or "") == current_attribution:
                score += Decimal("1")
            ranked.append((score, card))

        ranked.sort(
            key=lambda item: (
                item[0],
                str(item[1].get("available_at_utc") or ""),
            ),
            reverse=True,
        )
        selected = ranked[: max(1, min(int(limit), 20))]
        analogues: list[dict[str, Any]] = []
        counts = {"continuation": 0, "reversal": 0, "mixed": 0, "insufficient_forward_path": 0}
        for score, card in selected:
            path_class = str(card.get("path_class") or "insufficient_forward_path")
            counts[path_class] = counts.get(path_class, 0) + 1
            analogues.append(
                {
                    "learning_card_digest": card.get("learning_card_digest"),
                    "available_at_utc": card.get("available_at_utc"),
                    "initial_move_direction": card.get("initial_move_direction"),
                    "attribution_state": card.get("attribution_state"),
                    "leading_mechanism": card.get("leading_mechanism"),
                    "triggered_by": card.get("triggered_by"),
                    "forward_path": card.get("forward_path"),
                    "path_class": path_class,
                    "similarity_score": str(score.quantize(Decimal("0.000001"))),
                }
            )

        return {
            "retrieval_version": "aidy_gold_movement_analogue_retrieval_v1",
            "as_of_utc": as_of.isoformat(),
            "current_investigation_digest": investigation.get("investigation_digest"),
            "candidate_count": len(ranked),
            "selected_count": len(analogues),
            "path_class_counts": counts,
            "analogues": analogues,
            "counterexamples_preserved": True,
            "selection_bias_possible": True,
            "usable_for_live_edge_claim": False,
            "live_money_execution_allowed": False,
        }

    async def recent_cards(
        self, *, as_of_utc: datetime, limit: int = 20
    ) -> list[dict[str, Any]]:
        as_of = _utc(as_of_utc, name="as_of_utc")
        result = await self._d1.prepare(
            """
            SELECT card_json
            FROM aidy_gold_movement_learning_cards
            WHERE available_at_utc<=?
            ORDER BY available_at_utc DESC,movement_card_id DESC
            LIMIT ?
            """
        ).bind(as_of.isoformat(), max(1, min(int(limit), 100))).all()
        cards: list[dict[str, Any]] = []
        for row in _results(result):
            raw = json.loads(str(row["card_json"]))
            if isinstance(raw, dict) and verify_gold_movement_learning_card(raw):
                cards.append(raw)
        return cards


async def sync_gold_movement_memory(
    d1: Any,
    *,
    now_utc: datetime,
    scan_limit: int = 1,
    resolve_limit: int = 10,
) -> dict[str, Any]:
    now = _utc(now_utc, name="now_utc")
    store = D1GoldMovementMemoryStore(d1)
    detection = await store.detect_and_store(now_utc=now, limit=scan_limit)
    resolution = await store.resolve_matured(now_utc=now, limit=resolve_limit)
    result = {
        "memory_version": GOLD_MOVEMENT_MEMORY_VERSION,
        "observed_at_utc": now.isoformat(),
        "detection": detection,
        "resolution": resolution,
        "research_only": True,
        "live_money_execution_allowed": False,
    }
    result["sync_digest"] = _digest(result)
    return result


__all__ = [
    "GOLD_MOVEMENT_MEMORY_VERSION",
    "MOVEMENT_EPISODE_COOLDOWN_MINUTES",
    "MOVEMENT_FORWARD_HORIZON_MINUTES",
    "D1GoldMovementMemoryStore",
    "_forward_window_returns",
    "sync_gold_movement_memory",
]
