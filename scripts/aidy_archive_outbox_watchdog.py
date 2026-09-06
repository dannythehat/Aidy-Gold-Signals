"""Evaluate bounded D1 -> R2 archive-outbox health for AIDY.

The watchdog is intentionally independent of the Worker runtime. It receives a small,
bounded JSON sample of pending archive rows and classifies whether R2 archival is keeping
up or whether an old/retrying poison item needs operator attention.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_MAX_PENDING_AGE_SECONDS = 900
DEFAULT_POISON_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class ArchiveOutboxDiagnostic:
    status: str
    alert: bool
    reason: str
    observed_at_utc: str
    pending_sample_count: int
    gold_pending_count: int
    cross_market_pending_count: int
    retrying_count: int
    poison_count: int
    max_attempts: int
    oldest_pending_at_utc: str | None
    oldest_pending_age_seconds: int | None
    max_pending_age_seconds: int
    poison_attempts: int
    sample_truncated: bool
    worst_items: list[dict[str, Any]]


def _parse_utc(value: object) -> datetime:
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _normalize_rows(payload: object) -> tuple[list[dict[str, Any]], bool]:
    """Accept direct row lists or Cloudflare D1 REST result envelopes."""

    if isinstance(payload, list):
        # Direct fixtures are row lists. Wrangler/REST result lists contain `results`.
        if payload and all(isinstance(row, dict) and "outbox_kind" in row for row in payload):
            return [dict(row) for row in payload], False
        rows: list[dict[str, Any]] = []
        truncated = False
        for result in payload:
            if not isinstance(result, dict):
                continue
            candidate = result.get("results")
            if isinstance(candidate, list):
                rows.extend(dict(row) for row in candidate if isinstance(row, dict))
            meta = result.get("meta")
            if isinstance(meta, dict) and bool(meta.get("sample_truncated")):
                truncated = True
        return rows, truncated
    if isinstance(payload, dict):
        candidate = payload.get("results")
        if isinstance(candidate, list):
            return [dict(row) for row in candidate if isinstance(row, dict)], bool(
                payload.get("sample_truncated", False)
            )
        if "outbox_kind" in payload:
            return [dict(payload)], False
    return [], False


def evaluate(
    *,
    now: datetime,
    rows: list[dict[str, Any]],
    max_pending_age_seconds: int = DEFAULT_MAX_PENDING_AGE_SECONDS,
    poison_attempts: int = DEFAULT_POISON_ATTEMPTS,
    sample_truncated: bool = False,
) -> ArchiveOutboxDiagnostic:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if max_pending_age_seconds < 60:
        raise ValueError("max_pending_age_seconds must be >= 60")
    if poison_attempts < 1:
        raise ValueError("poison_attempts must be >= 1")

    observed = now.astimezone(UTC)
    normalized: list[dict[str, Any]] = []
    for row in rows:
        created = _parse_utc(row["created_at"])
        attempts = int(row.get("attempts") or 0)
        age = max(0, int((observed - created).total_seconds()))
        normalized.append(
            {
                "outbox_kind": str(row.get("outbox_kind") or "unknown"),
                "id": str(row.get("id") or ""),
                "record_type": str(row.get("record_type") or "unknown"),
                "archive_key": str(row.get("archive_key") or ""),
                "attempts": attempts,
                "last_error": None if row.get("last_error") is None else str(row.get("last_error")),
                "created_at_utc": created.isoformat(),
                "age_seconds": age,
            }
        )

    normalized.sort(key=lambda row: (-int(row["attempts"]), -int(row["age_seconds"])))
    retrying = [row for row in normalized if int(row["attempts"]) > 0]
    poison = [row for row in normalized if int(row["attempts"]) >= poison_attempts]
    stale = [row for row in normalized if int(row["age_seconds"]) > max_pending_age_seconds]
    oldest = max(normalized, key=lambda row: int(row["age_seconds"]), default=None)
    max_attempts = max((int(row["attempts"]) for row in normalized), default=0)
    gold_count = sum(row["outbox_kind"] == "gold" for row in normalized)
    cross_count = sum(row["outbox_kind"] == "cross_market" for row in normalized)

    if sample_truncated:
        status = "sample_truncated"
        alert = True
        reason = "archive pending sample hit its safety cap; backlog is larger than the bounded watchdog sample"
    elif poison:
        status = "poison"
        alert = True
        reason = "one or more archive items reached the poison retry threshold"
    elif stale:
        status = "stale"
        alert = True
        reason = "one or more archive items have remained pending beyond the allowed age"
    elif normalized:
        status = "pending_recent"
        alert = False
        reason = "archive items are pending but remain inside the normal delivery grace window"
    else:
        status = "healthy"
        alert = False
        reason = "no pending D1 to R2 archive items were found in the bounded production sample"

    return ArchiveOutboxDiagnostic(
        status=status,
        alert=alert,
        reason=reason,
        observed_at_utc=observed.isoformat(),
        pending_sample_count=len(normalized),
        gold_pending_count=gold_count,
        cross_market_pending_count=cross_count,
        retrying_count=len(retrying),
        poison_count=len(poison),
        max_attempts=max_attempts,
        oldest_pending_at_utc=None if oldest is None else str(oldest["created_at_utc"]),
        oldest_pending_age_seconds=None if oldest is None else int(oldest["age_seconds"]),
        max_pending_age_seconds=max_pending_age_seconds,
        poison_attempts=poison_attempts,
        sample_truncated=sample_truncated,
        worst_items=normalized[:5],
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--d1-json", required=True)
    parser.add_argument("--diagnostic", required=True)
    parser.add_argument("--now")
    parser.add_argument("--max-pending-age-seconds", type=int, default=DEFAULT_MAX_PENDING_AGE_SECONDS)
    parser.add_argument("--poison-attempts", type=int, default=DEFAULT_POISON_ATTEMPTS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        raw = json.loads(Path(args.d1_json).read_text(encoding="utf-8"))
        rows, truncated = _normalize_rows(raw)
        now = _parse_utc(args.now) if args.now else datetime.now(UTC)
        diagnostic = evaluate(
            now=now,
            rows=rows,
            max_pending_age_seconds=args.max_pending_age_seconds,
            poison_attempts=args.poison_attempts,
            sample_truncated=truncated,
        )
        target = Path(args.diagnostic)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(asdict(diagnostic), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(asdict(diagnostic), sort_keys=True))
        return 2 if diagnostic.alert else 0
    except Exception as exc:  # noqa: BLE001 - monitoring must surface deterministic failure evidence.
        print(f"archive_watchdog_error={type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
