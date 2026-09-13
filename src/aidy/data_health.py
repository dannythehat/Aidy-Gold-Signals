"""Point-in-time production data-health telemetry for AIDY.

The Hub must be able to answer a harder question than "is the Worker alive?":
was the evidence available to AIDY actually fresh and usable at a given moment?

This module deliberately derives health only from first-observed operational facts
already stored in D1.  It never reaches out to a vendor, never fabricates freshness,
and never treats a closed Gold session as a stale-feed incident.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import uuid4

from .twelve_data_market import NEW_YORK, gold_session_is_open

HEALTH_VERSION = "aidy_data_health_v1"
DEFAULT_STALE_SECONDS = 900
DEFAULT_OPEN_GRACE_SECONDS = 900
DEFAULT_ARCHIVE_STALE_SECONDS = 3600


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("AIDY data health requires timezone-aware datetimes.")
    return value.astimezone(UTC)


def _parse_datetime(value: object | None) -> datetime | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _row(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    try:
        return dict(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise TypeError("Unexpected D1 data-health row shape.") from exc


def _results(value: object) -> list[dict[str, Any]]:
    rows = getattr(value, "results", None)
    if rows is None and isinstance(value, dict):
        rows = value.get("results")
    if rows is None:
        return []
    return [_row(item) for item in rows]


def current_gold_session_open_utc(value: datetime) -> datetime | None:
    """Return the start of the current uninterrupted canonical Gold session segment."""

    now = _utc(value)
    if not gold_session_is_open(now):
        return None
    local = now.astimezone(NEW_YORK)
    wall = local.time().replace(tzinfo=None)
    if wall >= time(18, 0):
        local_open = datetime.combine(local.date(), time(18, 0), tzinfo=NEW_YORK)
        return local_open.astimezone(UTC)
    previous = local.date() - timedelta(days=1)
    local_open = datetime.combine(previous, time(18, 0), tzinfo=NEW_YORK)
    return local_open.astimezone(UTC)


def _age_seconds(now: datetime, value: datetime | None) -> int | None:
    if value is None:
        return None
    return max(0, int((_utc(now) - _utc(value)).total_seconds()))


@dataclass(frozen=True, slots=True)
class AidyDataHealth:
    observed_at_utc: str
    status: str
    alert: bool
    reason: str
    health_version: str
    session_open: bool
    session_opened_at_utc: str | None
    capture_enabled: bool
    market_data_source: str
    scheduler: str
    latest_scheduled_success_utc: str | None
    latest_scheduled_request_utc: str | None
    latest_scheduled_request_status: str | None
    latest_scheduled_error_code: str | None
    latest_provider_context_snapshot_utc: str | None
    success_lag_seconds: int | None
    provider_context_snapshot_lag_seconds: int | None
    archive_pending_count: int
    archive_backoff_count: int
    archive_dead_letter_count: int
    oldest_archive_unarchived_utc: str | None
    oldest_archive_unarchived_age_seconds: int | None
    cross_market_archive_pending_count: int
    cross_market_archive_backoff_count: int
    cross_market_archive_dead_letter_count: int
    oldest_cross_market_archive_unarchived_utc: str | None
    oldest_cross_market_archive_unarchived_age_seconds: int | None
    latest_cross_market_first_observed_at: str | None
    latest_macro_event_first_observed_at: str | None
    checks: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


_HEARTBEAT_SQL = """
WITH latest_success AS (
  SELECT completed_at_utc
  FROM twelve_data_request_ledger
  WHERE completed_at_utc IS NOT NULL
    AND status='succeeded'
    AND request_kind='scheduled_capture'
  ORDER BY completed_at_utc DESC
  LIMIT 1
), latest_request AS (
  SELECT requested_at_utc,status,error_code
  FROM twelve_data_request_ledger
  WHERE request_kind='scheduled_capture'
  ORDER BY requested_at_utc DESC
  LIMIT 1
), latest_context AS (
  SELECT captured_at
  FROM market_snapshots
  WHERE symbol='XAUUSD'
    AND market_data_source='twelve_data'
    AND capture_status='complete'
    AND json_extract(data_availability_json,'$.request_kind')='scheduled_capture'
    AND json_extract(data_availability_json,'$.request_ledger_status')='succeeded'
  ORDER BY captured_at DESC,id DESC
  LIMIT 1
), archive_stats AS (
  SELECT
    COALESCE(SUM(CASE WHEN delivery_state='pending' THEN 1 ELSE 0 END),0) AS pending_count,
    COALESCE(SUM(CASE WHEN delivery_state='backoff' THEN 1 ELSE 0 END),0) AS backoff_count,
    COALESCE(SUM(CASE WHEN delivery_state='dead_letter' THEN 1 ELSE 0 END),0) AS dead_letter_count,
    MIN(CASE WHEN delivery_state!='archived' THEN created_at END) AS oldest_unarchived_utc
  FROM archive_outbox
), cross_archive_stats AS (
  SELECT
    COALESCE(SUM(CASE WHEN delivery_state='pending' THEN 1 ELSE 0 END),0) AS pending_count,
    COALESCE(SUM(CASE WHEN delivery_state='backoff' THEN 1 ELSE 0 END),0) AS backoff_count,
    COALESCE(SUM(CASE WHEN delivery_state='dead_letter' THEN 1 ELSE 0 END),0) AS dead_letter_count,
    MIN(CASE WHEN delivery_state!='archived' THEN created_at END) AS oldest_unarchived_utc
  FROM cross_market_archive_outbox
)
SELECT
  s.completed_at_utc AS latest_scheduled_success_utc,
  r.requested_at_utc AS latest_scheduled_request_utc,
  r.status AS latest_scheduled_request_status,
  r.error_code AS latest_scheduled_error_code,
  c.captured_at AS latest_provider_context_snapshot_utc,
  a.pending_count AS archive_pending_count,
  a.backoff_count AS archive_backoff_count,
  a.dead_letter_count AS archive_dead_letter_count,
  a.oldest_unarchived_utc AS oldest_archive_unarchived_utc,
  x.pending_count AS cross_market_archive_pending_count,
  x.backoff_count AS cross_market_archive_backoff_count,
  x.dead_letter_count AS cross_market_archive_dead_letter_count,
  x.oldest_unarchived_utc AS oldest_cross_market_archive_unarchived_utc,
  (SELECT MAX(first_observed_at) FROM cross_market_observations)
      AS latest_cross_market_first_observed_at,
  (SELECT MAX(first_observed_at) FROM market_event_observations)
      AS latest_macro_event_first_observed_at
FROM (SELECT 1) anchor
LEFT JOIN latest_success s ON 1=1
LEFT JOIN latest_request r ON 1=1
LEFT JOIN latest_context c ON 1=1
LEFT JOIN archive_stats a ON 1=1
LEFT JOIN cross_archive_stats x ON 1=1
"""


async def read_data_health_facts(d1: Any) -> dict[str, Any]:
    """Read one bounded heartbeat row from D1 without forcing a SQLite query plan."""

    return _row(await d1.prepare(_HEARTBEAT_SQL).first())


def evaluate_data_health(
    *,
    now: datetime,
    facts: dict[str, Any],
    capture_enabled: bool,
    market_data_source: str,
    scheduler: str,
    stale_seconds: int = DEFAULT_STALE_SECONDS,
    open_grace_seconds: int = DEFAULT_OPEN_GRACE_SECONDS,
    archive_stale_seconds: int = DEFAULT_ARCHIVE_STALE_SECONDS,
) -> AidyDataHealth:
    if stale_seconds < 60:
        raise ValueError("stale_seconds must be >= 60")
    if open_grace_seconds < 0:
        raise ValueError("open_grace_seconds must be >= 0")
    if archive_stale_seconds < 60:
        raise ValueError("archive_stale_seconds must be >= 60")

    observed = _utc(now)
    session_open = gold_session_is_open(observed)
    session_opened = current_gold_session_open_utc(observed)
    latest_success = _parse_datetime(facts.get("latest_scheduled_success_utc"))
    latest_request = _parse_datetime(facts.get("latest_scheduled_request_utc"))
    latest_context = _parse_datetime(facts.get("latest_provider_context_snapshot_utc"))
    oldest_archive = _parse_datetime(facts.get("oldest_archive_unarchived_utc"))
    oldest_cross_archive = _parse_datetime(
        facts.get("oldest_cross_market_archive_unarchived_utc")
    )

    success_lag = _age_seconds(observed, latest_success)
    context_lag = _age_seconds(observed, latest_context)
    archive_age = _age_seconds(observed, oldest_archive)
    cross_archive_age = _age_seconds(observed, oldest_cross_archive)

    latest_status = facts.get("latest_scheduled_request_status")
    latest_status = None if latest_status is None else str(latest_status)
    latest_error = facts.get("latest_scheduled_error_code")
    latest_error = None if latest_error is None else str(latest_error)

    archive_pending = int(facts.get("archive_pending_count") or 0)
    archive_backoff = int(facts.get("archive_backoff_count") or 0)
    archive_dead = int(facts.get("archive_dead_letter_count") or 0)
    cross_pending = int(facts.get("cross_market_archive_pending_count") or 0)
    cross_backoff = int(facts.get("cross_market_archive_backoff_count") or 0)
    cross_dead = int(facts.get("cross_market_archive_dead_letter_count") or 0)

    archive_alert = bool(
        archive_dead
        or cross_dead
        or (
            (archive_pending or archive_backoff)
            and archive_age is not None
            and archive_age > archive_stale_seconds
        )
        or (
            (cross_pending or cross_backoff)
            and cross_archive_age is not None
            and cross_archive_age > archive_stale_seconds
        )
    )

    status = "fresh"
    alert = False
    reason = "scheduled market capture and complete Provider Context are fresh"

    if not capture_enabled:
        status = "capture_disabled"
        alert = True
        reason = "AIDY production market capture is disabled"
    elif archive_alert:
        status = "archive_backlog"
        alert = True
        reason = "durable R2 archive delivery has a stale backlog or dead-letter evidence"
    elif not session_open:
        status = "session_closed"
        reason = "canonical Gold session is closed; open-session freshness is not required"
    else:
        assert session_opened is not None
        seconds_since_open = int((observed - session_opened).total_seconds())
        if seconds_since_open < open_grace_seconds:
            status = "open_grace"
            reason = "Gold session reopened inside the capture startup grace window"
        elif (
            latest_status == "failed"
            and latest_request is not None
            and (latest_success is None or latest_request > latest_success)
        ):
            status = "capture_failed"
            alert = True
            reason = "the most recent scheduled market capture failed after the last success"
        elif latest_success is None or success_lag is None or success_lag > stale_seconds:
            status = "stale_capture"
            alert = True
            reason = "scheduled market capture is missing or older than the allowed open-session lag"
        elif latest_context is None or context_lag is None or context_lag > stale_seconds:
            status = "stale_provider_context"
            alert = True
            reason = "market capture is fresh but complete Provider Context is stale or missing"

    latest_cross_market = facts.get("latest_cross_market_first_observed_at")
    latest_macro = facts.get("latest_macro_event_first_observed_at")
    checks: dict[str, object] = {
        "market_capture": {
            "required": True,
            "latest_success_utc": None if latest_success is None else latest_success.isoformat(),
            "latest_request_utc": None if latest_request is None else latest_request.isoformat(),
            "latest_request_status": latest_status,
            "latest_error_code": latest_error,
            "lag_seconds": success_lag,
            "stale_after_seconds": stale_seconds,
        },
        "provider_context": {
            "required": True,
            "latest_complete_snapshot_utc": (
                None if latest_context is None else latest_context.isoformat()
            ),
            "lag_seconds": context_lag,
            "stale_after_seconds": stale_seconds,
        },
        "archive_delivery": {
            "required": True,
            "pending_count": archive_pending,
            "backoff_count": archive_backoff,
            "dead_letter_count": archive_dead,
            "oldest_unarchived_utc": (
                None if oldest_archive is None else oldest_archive.isoformat()
            ),
            "oldest_unarchived_age_seconds": archive_age,
            "stale_after_seconds": archive_stale_seconds,
        },
        "cross_market_archive_delivery": {
            "required": True,
            "pending_count": cross_pending,
            "backoff_count": cross_backoff,
            "dead_letter_count": cross_dead,
            "oldest_unarchived_utc": (
                None if oldest_cross_archive is None else oldest_cross_archive.isoformat()
            ),
            "oldest_unarchived_age_seconds": cross_archive_age,
            "stale_after_seconds": archive_stale_seconds,
        },
        # These feeds exist in AIDY but are not yet mandatory live-decision inputs.
        # Expose their real last-observed times so the Hub cannot imply otherwise.
        "cross_market_context": {
            "required": False,
            "latest_first_observed_at": latest_cross_market,
        },
        "macro_events": {
            "required": False,
            "latest_first_observed_at": latest_macro,
        },
    }

    return AidyDataHealth(
        observed_at_utc=observed.isoformat(),
        status=status,
        alert=alert,
        reason=reason,
        health_version=HEALTH_VERSION,
        session_open=session_open,
        session_opened_at_utc=None if session_opened is None else session_opened.isoformat(),
        capture_enabled=bool(capture_enabled),
        market_data_source=str(market_data_source),
        scheduler=str(scheduler),
        latest_scheduled_success_utc=(
            None if latest_success is None else latest_success.isoformat()
        ),
        latest_scheduled_request_utc=(
            None if latest_request is None else latest_request.isoformat()
        ),
        latest_scheduled_request_status=latest_status,
        latest_scheduled_error_code=latest_error,
        latest_provider_context_snapshot_utc=(
            None if latest_context is None else latest_context.isoformat()
        ),
        success_lag_seconds=success_lag,
        provider_context_snapshot_lag_seconds=context_lag,
        archive_pending_count=archive_pending,
        archive_backoff_count=archive_backoff,
        archive_dead_letter_count=archive_dead,
        oldest_archive_unarchived_utc=(
            None if oldest_archive is None else oldest_archive.isoformat()
        ),
        oldest_archive_unarchived_age_seconds=archive_age,
        cross_market_archive_pending_count=cross_pending,
        cross_market_archive_backoff_count=cross_backoff,
        cross_market_archive_dead_letter_count=cross_dead,
        oldest_cross_market_archive_unarchived_utc=(
            None if oldest_cross_archive is None else oldest_cross_archive.isoformat()
        ),
        oldest_cross_market_archive_unarchived_age_seconds=cross_archive_age,
        latest_cross_market_first_observed_at=(
            None if latest_cross_market is None else str(latest_cross_market)
        ),
        latest_macro_event_first_observed_at=(None if latest_macro is None else str(latest_macro)),
        checks=checks,
    )


async def collect_data_health(
    d1: Any,
    *,
    now: datetime,
    capture_enabled: bool,
    market_data_source: str,
    scheduler: str,
    stale_seconds: int = DEFAULT_STALE_SECONDS,
    open_grace_seconds: int = DEFAULT_OPEN_GRACE_SECONDS,
    archive_stale_seconds: int = DEFAULT_ARCHIVE_STALE_SECONDS,
) -> AidyDataHealth:
    facts = await read_data_health_facts(d1)
    return evaluate_data_health(
        now=now,
        facts=facts,
        capture_enabled=capture_enabled,
        market_data_source=market_data_source,
        scheduler=scheduler,
        stale_seconds=stale_seconds,
        open_grace_seconds=open_grace_seconds,
        archive_stale_seconds=archive_stale_seconds,
    )


async def record_data_health(d1: Any, health: AidyDataHealth) -> str:
    """Persist one immutable health observation for point-in-time Hub reconstruction."""

    event_id = str(uuid4())
    await d1.prepare(
        """
        INSERT INTO aidy_data_health_events (
          id,observed_at_utc,status,alert,session_open,capture_enabled,market_data_source,scheduler,
          latest_scheduled_success_utc,latest_scheduled_request_utc,
          latest_scheduled_request_status,latest_scheduled_error_code,
          latest_provider_context_snapshot_utc,success_lag_seconds,
          provider_context_snapshot_lag_seconds,archive_pending_count,archive_backoff_count,
          archive_dead_letter_count,oldest_archive_unarchived_utc,
          cross_market_archive_pending_count,cross_market_archive_backoff_count,
          cross_market_archive_dead_letter_count,oldest_cross_market_archive_unarchived_utc,
          latest_cross_market_first_observed_at,latest_macro_event_first_observed_at,
          reason,checks_json,health_version
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """
    ).bind(
        event_id,
        health.observed_at_utc,
        health.status,
        1 if health.alert else 0,
        1 if health.session_open else 0,
        1 if health.capture_enabled else 0,
        health.market_data_source,
        health.scheduler,
        health.latest_scheduled_success_utc,
        health.latest_scheduled_request_utc,
        health.latest_scheduled_request_status,
        health.latest_scheduled_error_code,
        health.latest_provider_context_snapshot_utc,
        health.success_lag_seconds,
        health.provider_context_snapshot_lag_seconds,
        health.archive_pending_count,
        health.archive_backoff_count,
        health.archive_dead_letter_count,
        health.oldest_archive_unarchived_utc,
        health.cross_market_archive_pending_count,
        health.cross_market_archive_backoff_count,
        health.cross_market_archive_dead_letter_count,
        health.oldest_cross_market_archive_unarchived_utc,
        health.latest_cross_market_first_observed_at,
        health.latest_macro_event_first_observed_at,
        health.reason,
        json.dumps(health.checks, sort_keys=True, separators=(",", ":"), default=str),
        health.health_version,
    ).run()
    return event_id


async def collect_and_record_data_health(
    d1: Any,
    *,
    now: datetime,
    capture_enabled: bool,
    market_data_source: str,
    scheduler: str,
) -> AidyDataHealth:
    health = await collect_data_health(
        d1,
        now=now,
        capture_enabled=capture_enabled,
        market_data_source=market_data_source,
        scheduler=scheduler,
    )
    await record_data_health(d1, health)
    return health


async def recent_data_health_events(d1: Any, *, limit: int = 120) -> list[dict[str, Any]]:
    bounded = max(1, min(int(limit), 500))
    result = await d1.prepare(
        """
        SELECT id,observed_at_utc,status,alert,session_open,capture_enabled,market_data_source,
               scheduler,latest_scheduled_success_utc,latest_scheduled_request_utc,
               latest_scheduled_request_status,latest_scheduled_error_code,
               latest_provider_context_snapshot_utc,success_lag_seconds,
               provider_context_snapshot_lag_seconds,archive_pending_count,archive_backoff_count,
               archive_dead_letter_count,oldest_archive_unarchived_utc,
               cross_market_archive_pending_count,cross_market_archive_backoff_count,
               cross_market_archive_dead_letter_count,oldest_cross_market_archive_unarchived_utc,
               latest_cross_market_first_observed_at,latest_macro_event_first_observed_at,
               reason,checks_json,health_version
        FROM aidy_data_health_events
        ORDER BY observed_at_utc DESC,id DESC
        LIMIT ?
        """
    ).bind(bounded).all()
    rows = _results(result)
    for row in rows:
        raw_checks = row.pop("checks_json", "{}")
        try:
            row["checks"] = json.loads(str(raw_checks or "{}"))
        except json.JSONDecodeError:
            row["checks"] = {"parse_error": True}
        row["alert"] = bool(int(row.get("alert") or 0))
        row["session_open"] = bool(int(row.get("session_open") or 0))
        row["capture_enabled"] = bool(int(row.get("capture_enabled") or 0))
    return rows
