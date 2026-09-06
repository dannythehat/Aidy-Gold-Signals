#!/usr/bin/env python3
"""Cloudflare D1 rows-read budget monitor with bounded retries and durable diagnostics."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

TRANSIENT_GRAPHQL_MARKERS = (
    "unable to execute query",
    "too many queries in progress",
    "temporarily unavailable",
    "service unavailable",
    "timeout",
    "timed out",
)


@dataclass
class Diagnostic:
    status: str
    day_utc: str
    database_id: str
    attempts: int
    rows_read: int | None = None
    threshold: int | None = None
    free_limit: int | None = None
    alert: bool | None = None
    error: str | None = None
    generated_at_utc: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_diagnostic(path: str, diagnostic: Diagnostic) -> None:
    diagnostic.generated_at_utc = _now_iso()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(asdict(diagnostic), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_github_output(path: str | None, values: dict[str, Any]) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        for key, value in values.items():
            if isinstance(value, bool):
                value = str(value).lower()
            fh.write(f"{key}={value}\n")


def _graphql_body(account_id: str, database_id: str, day: str) -> bytes:
    query = """query D1Usage($accountTag: string!, $day: Date, $databaseId: string) {
      viewer { accounts(filter: { accountTag: $accountTag }) {
        d1AnalyticsAdaptiveGroups(limit: 10, filter: {
          date_geq: $day, date_leq: $day, databaseId: $databaseId
        }) {
          sum { rowsRead }
          dimensions { date databaseId }
        }
      } }
    }"""
    return json.dumps(
        {
            "query": query,
            "variables": {
                "accountTag": account_id,
                "day": day,
                "databaseId": database_id,
            },
        }
    ).encode()


def _transient_graphql_error(errors: list[dict[str, Any]]) -> bool:
    text = " ".join(str(item.get("message", "")) for item in errors).lower()
    return any(marker in text for marker in TRANSIENT_GRAPHQL_MARKERS)


def query_rows_read(
    *,
    endpoint: str,
    token: str,
    account_id: str,
    database_id: str,
    day: str,
    max_attempts: int = 3,
    base_backoff_seconds: float = 1.0,
    opener: Callable[..., Any] = urllib.request.urlopen,
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[int, int]:
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    body = _graphql_body(account_id, database_id, day)
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        request = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
            },
        )
        try:
            with opener(request, timeout=30) as response:
                result = json.load(response)
            errors = result.get("errors") or []
            if errors:
                err = RuntimeError(json.dumps(errors, sort_keys=True))
                if _transient_graphql_error(errors) and attempt < max_attempts:
                    last_error = err
                    sleeper(base_backoff_seconds * (2 ** (attempt - 1)))
                    continue
                raise err

            accounts = result["data"]["viewer"]["accounts"]
            if not accounts:
                raise RuntimeError("Cloudflare GraphQL returned no matching account")
            groups = accounts[0]["d1AnalyticsAdaptiveGroups"]
            rows_read = sum(int(item.get("sum", {}).get("rowsRead") or 0) for item in groups)
            return rows_read, attempt

        except urllib.error.HTTPError as exc:
            last_error = exc
            if (exc.code == 429 or 500 <= exc.code <= 599) and attempt < max_attempts:
                sleeper(base_backoff_seconds * (2 ** (attempt - 1)))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
            last_error = exc
            if attempt < max_attempts:
                sleeper(base_backoff_seconds * (2 ** (attempt - 1)))
                continue
            raise

    raise RuntimeError(f"D1 analytics query exhausted retries: {last_error}")


def run(args: argparse.Namespace) -> int:
    day = args.day or datetime.now(timezone.utc).date().isoformat()
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    database_id = os.environ.get("AIDY_D1_DATABASE_ID", "")
    threshold = int(os.environ.get("D1_ROWS_READ_ALERT_THRESHOLD", "3250000"))
    free_limit = int(os.environ.get("D1_ROWS_READ_FREE_LIMIT", "5000000"))
    github_output = os.environ.get("GITHUB_OUTPUT")

    if not token or not account_id or not database_id:
        missing = [
            name
            for name, value in (
                ("CLOUDFLARE_API_TOKEN", token),
                ("CLOUDFLARE_ACCOUNT_ID", account_id),
                ("AIDY_D1_DATABASE_ID", database_id),
            )
            if not value
        ]
        diagnostic = Diagnostic(
            status="error",
            day_utc=day,
            database_id=database_id or "missing",
            attempts=0,
            threshold=threshold,
            free_limit=free_limit,
            error="missing environment: " + ",".join(missing),
        )
        _write_diagnostic(args.diagnostic, diagnostic)
        print(diagnostic.error, file=sys.stderr)
        return 1

    try:
        rows_read, attempts = query_rows_read(
            endpoint=args.endpoint,
            token=token,
            account_id=account_id,
            database_id=database_id,
            day=day,
            max_attempts=args.max_attempts,
            base_backoff_seconds=args.base_backoff_seconds,
        )
        alert = rows_read >= threshold
        diagnostic = Diagnostic(
            status="ok",
            day_utc=day,
            database_id=database_id,
            attempts=attempts,
            rows_read=rows_read,
            threshold=threshold,
            free_limit=free_limit,
            alert=alert,
        )
        _write_diagnostic(args.diagnostic, diagnostic)
        _append_github_output(
            github_output,
            {"day": day, "rows_read": rows_read, "alert": alert, "attempts": attempts},
        )
        print(
            f"date_utc={day} rows_read={rows_read} threshold={threshold} "
            f"free_limit={free_limit} alert={str(alert).lower()} attempts={attempts}"
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI must preserve diagnostics for every failure mode.
        diagnostic = Diagnostic(
            status="error",
            day_utc=day,
            database_id=database_id,
            attempts=args.max_attempts,
            threshold=threshold,
            free_limit=free_limit,
            error=f"{type(exc).__name__}: {exc}",
        )
        _write_diagnostic(args.diagnostic, diagnostic)
        print(diagnostic.error, file=sys.stderr)
        return 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", help="UTC day YYYY-MM-DD; defaults to current UTC day")
    parser.add_argument(
        "--endpoint",
        default="https://api.cloudflare.com/client/v4/graphql",
        help="Cloudflare GraphQL endpoint",
    )
    parser.add_argument("--diagnostic", default="artifacts/aidy-d1-budget-diagnostic.json")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--base-backoff-seconds", type=float, default=1.0)
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
