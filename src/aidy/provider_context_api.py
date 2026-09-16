from __future__ import annotations

import hmac
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

from aidy.private_forward_context import build_private_forward_decision_inputs
from aidy.twelve_data_market import AIDY_SYMBOL

PROVIDER_CONTEXT_API_VERSION = "aidy_provider_context_api_v2"
MAX_CONTEXT_LAG = timedelta(minutes=10)
_PROVIDER_TOKEN_ENV = "AIDY_PROVIDER_MARKET_TOKEN"
_CACHE_LIMIT = 32
_CONTEXT_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
_REQUIRED_PROVIDER_CONTEXT_FIELDS = (
    "latest_m1_id",
    "latest_m5_id",
    "latest_m15_id",
    "latest_h1_id",
    "latest_h4_id",
)
_TIMEFRAME_FIELDS = {
    "1m": "latest_m1_id",
    "5m": "latest_m5_id",
    "15m": "latest_m15_id",
    "1h": "latest_h1_id",
    "4h": "latest_h4_id",
    "1d": "latest_d1_id",
}


def _utc_iso(value: str, *, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a valid ISO-8601 timestamp.") from exc
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


def _authorized(request: Any, env: Any) -> bool:
    expected = str(getattr(env, _PROVIDER_TOKEN_ENV, "") or "").strip()
    if not expected:
        return False
    raw = str(request.headers.get("Authorization") or "").strip()
    if not raw.startswith("Bearer "):
        return False
    supplied = raw[7:].strip()
    if not supplied:
        return False
    try:
        return hmac.compare_digest(supplied, expected)
    except (TypeError, ValueError):
        return False


def _provider_context_evidence(snapshot: Mapping[str, Any]) -> tuple[str, list[str]]:
    """Grade a scheduled snapshot for Provider Intelligence only.

    Formal AIDY forward execution keeps its existing all-timeframe ``complete`` gate.
    Provider Intelligence is allowed to remain observationally alive when the current
    intraday stack is intact but the prior D1 aggregate is unavailable because of a
    historical capture gap. Missing M1/M5/M15/H1/H4 is never admitted here.
    """

    status = str(snapshot.get("capture_status") or "").strip().lower()
    missing = [
        timeframe
        for timeframe, field in _TIMEFRAME_FIELDS.items()
        if snapshot.get(field) in {None, ""}
    ]
    if status == "complete":
        if missing:
            raise ValueError("provider_context_complete_snapshot_missing_timeframe")
        return "complete", []
    if status != "partial":
        raise ValueError("provider_context_snapshot_status_ineligible")
    if any(snapshot.get(field) in {None, ""} for field in _REQUIRED_PROVIDER_CONTEXT_FIELDS):
        raise ValueError("provider_context_intraday_stack_incomplete")
    if missing != ["1d"]:
        raise ValueError("provider_context_partial_scope_exceeded")
    return "intraday_complete_d1_missing", missing


async def _snapshot_at_or_before(d1: Any, *, as_of: datetime) -> dict[str, Any] | None:
    value = await d1.prepare(
        """
        SELECT id,captured_at,symbol,capture_status,market_data_source,session_code,
               snapshot_digest,archive_key,data_availability_json,
               latest_m1_id,latest_m5_id,latest_m15_id,latest_h1_id,latest_h4_id,latest_d1_id
        FROM market_snapshots
        WHERE symbol=? AND market_data_source='twelve_data'
          AND capture_status IN ('complete','partial') AND captured_at<=?
          AND json_extract(data_availability_json,'$.request_kind')='scheduled_capture'
          AND json_extract(data_availability_json,'$.request_ledger_status')='succeeded'
          AND json_extract(data_availability_json,'$.freshness_state')='fresh'
          AND latest_m1_id IS NOT NULL
          AND latest_m5_id IS NOT NULL
          AND latest_m15_id IS NOT NULL
          AND latest_h1_id IS NOT NULL
          AND latest_h4_id IS NOT NULL
        ORDER BY captured_at DESC,id DESC
        LIMIT 1
        """
    ).bind(AIDY_SYMBOL, as_of.isoformat()).first()
    snapshot = _row(value)
    if snapshot is None:
        return None
    try:
        _provider_context_evidence(snapshot)
    except ValueError:
        return None
    return snapshot


def _compact_join_packet(inputs: Mapping[str, Any], *, snapshot: Mapping[str, Any]) -> dict[str, Any]:
    context = inputs.get("context")
    context = context if isinstance(context, Mapping) else {}
    extensions = context.get("architecture_v2_extensions")
    extensions = extensions if isinstance(extensions, Mapping) else {}
    gold = context.get("gold")
    gold = gold if isinstance(gold, Mapping) else {}
    quote = gold.get("quote_context")
    quote = quote if isinstance(quote, Mapping) else {}
    session = context.get("session")
    session = session if isinstance(session, Mapping) else {}
    versions = context.get("source_contract_versions")
    versions = versions if isinstance(versions, Mapping) else {}
    regime = inputs.get("regime")
    regime = regime if isinstance(regime, Mapping) else {}
    data_quality = context.get("data_quality")
    data_quality = data_quality if isinstance(data_quality, Mapping) else {}

    snapshot_captured = _utc_iso(str(snapshot["captured_at"]), name="snapshot.captured_at")
    built_as_of = _utc_iso(str(inputs["as_of_utc"]), name="inputs.as_of_utc")
    if built_as_of != snapshot_captured:
        raise RuntimeError("canonical_context_snapshot_timestamp_mismatch")
    evidence_grade, missing_timeframes = _provider_context_evidence(snapshot)

    return {
        "api_version": PROVIDER_CONTEXT_API_VERSION,
        "adapter_version": str(inputs.get("adapter_version") or ""),
        "symbol": AIDY_SYMBOL,
        "context_as_of_utc": built_as_of.isoformat(),
        "context_hash": str(context.get("context_hash") or ""),
        "snapshot": {
            "id": str(snapshot.get("id") or ""),
            "captured_at_utc": snapshot_captured.isoformat(),
            "capture_status": str(snapshot.get("capture_status") or ""),
            "market_data_source": str(snapshot.get("market_data_source") or ""),
            "session_code": str(snapshot.get("session_code") or ""),
            "snapshot_digest": str(snapshot.get("snapshot_digest") or ""),
            "archive_key": str(snapshot.get("archive_key") or ""),
            "provider_context_evidence_grade": evidence_grade,
            "provider_context_missing_timeframes": missing_timeframes,
        },
        "session": dict(session),
        "regime": dict(regime),
        "data_quality": dict(data_quality),
        "market": {
            "quote_context": dict(quote),
            "architecture_v2_extension_digest": str(extensions.get("extension_digest") or ""),
            "price_structure_digest": str(
                (
                    (extensions.get("price_structure_context") or {})
                    if isinstance(extensions.get("price_structure_context"), Mapping)
                    else {}
                ).get("structure_semantic_digest")
                or ""
            ),
        },
        "provenance": {
            "source_contract_versions": dict(versions),
            "private_forward_only": True,
            "cross_source_analogue_permission": False,
            "public_publication_enabled": False,
            "live_money_execution_allowed": False,
            "provider_context_observational_only": True,
            "provider_context_evidence_grade": evidence_grade,
            "provider_context_missing_timeframes": missing_timeframes,
            "formal_forward_complete_snapshot_required": True,
        },
    }


async def _context_for_snapshot(d1: Any, *, snapshot: Mapping[str, Any]) -> dict[str, Any]:
    snapshot_id = str(snapshot.get("id") or "").strip()
    if not snapshot_id:
        raise RuntimeError("canonical_context_snapshot_id_missing")
    cached = _CONTEXT_CACHE.get(snapshot_id)
    if cached is not None:
        _CONTEXT_CACHE.move_to_end(snapshot_id)
        return dict(cached)
    inputs = await build_private_forward_decision_inputs(d1=d1, snapshot_id=snapshot_id)
    packet = _compact_join_packet(inputs, snapshot=snapshot)
    _CONTEXT_CACHE[snapshot_id] = packet
    _CONTEXT_CACHE.move_to_end(snapshot_id)
    while len(_CONTEXT_CACHE) > _CACHE_LIMIT:
        _CONTEXT_CACHE.popitem(last=False)
    return dict(packet)


async def provider_context_response(request: Any, env: Any, *, now: datetime | None = None) -> Any:
    """Return PIT-safe observational market context for a provider signal timestamp.

    The endpoint is read-only, bearer-authenticated and fails closed if the latest
    Provider-Intelligence-eligible scheduled snapshot is more than ten minutes older
    than the signal. Formal AIDY execution authority is never granted here.
    """
    from workers import Response

    observed_now = (now or datetime.now(UTC)).astimezone(UTC)
    if request.method != "GET":
        return Response("Method not allowed", status=405)
    if not _authorized(request, env):
        return Response("Unauthorized", status=401)

    params = parse_qs(urlparse(request.url).query, keep_blank_values=True)
    raw_as_of = str(params.get("as_of", [""])[0]).strip()
    try:
        requested_as_of = _utc_iso(raw_as_of, name="as_of")
    except ValueError as exc:
        return Response.json({"ok": False, "error": "invalid_as_of", "message": str(exc)}, status=400)
    if requested_as_of > observed_now + timedelta(seconds=5):
        return Response.json({"ok": False, "error": "future_as_of_forbidden"}, status=400)

    snapshot = await _snapshot_at_or_before(env.AIDY_OPS, as_of=requested_as_of)
    if snapshot is None:
        return Response.json({"ok": False, "error": "no_pit_context"}, status=404)
    snapshot_at = _utc_iso(str(snapshot["captured_at"]), name="snapshot.captured_at")
    if snapshot_at > requested_as_of:
        return Response.json({"ok": False, "error": "future_snapshot_forbidden"}, status=503)
    lag = requested_as_of - snapshot_at
    if lag > MAX_CONTEXT_LAG:
        return Response.json(
            {
                "ok": False,
                "error": "pit_context_stale",
                "requested_as_of_utc": requested_as_of.isoformat(),
                "snapshot_captured_at_utc": snapshot_at.isoformat(),
                "context_lag_seconds": int(lag.total_seconds()),
                "max_context_lag_seconds": int(MAX_CONTEXT_LAG.total_seconds()),
            },
            status=409,
        )

    try:
        packet = await _context_for_snapshot(env.AIDY_OPS, snapshot=snapshot)
    except (KeyError, RuntimeError, TypeError, ValueError) as exc:
        return Response.json(
            {"ok": False, "error": "canonical_context_unavailable", "message": str(exc)},
            status=503,
        )
    context_at = _utc_iso(str(packet["context_as_of_utc"]), name="context_as_of_utc")
    if context_at > requested_as_of:
        return Response.json({"ok": False, "error": "future_context_forbidden"}, status=503)

    return Response.json(
        {
            "ok": True,
            "requested_as_of_utc": requested_as_of.isoformat(),
            "context_lag_seconds": int((requested_as_of - context_at).total_seconds()),
            "max_context_lag_seconds": int(MAX_CONTEXT_LAG.total_seconds()),
            "join_eligible": True,
            "context": packet,
        }
    )
