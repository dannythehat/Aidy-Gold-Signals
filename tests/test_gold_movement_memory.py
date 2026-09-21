from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from aidy.gold_movement_memory import (
    GOLD_MOVEMENT_MEMORY_VERSION,
    MOVEMENT_EPISODE_COOLDOWN_MINUTES,
    MOVEMENT_FORWARD_HORIZON_MINUTES,
    _forward_window_returns,
)


ROOT = Path(__file__).resolve().parents[1]


def _bar(minute: int, *, open_: str, close: str) -> dict[str, object]:
    opened = datetime(2026, 9, 21, 1, 0, tzinfo=UTC) + timedelta(minutes=minute)
    return {
        "open_time_utc": opened.isoformat(),
        "open": open_,
        "high": str(max(Decimal(open_), Decimal(close)) + Decimal("1")),
        "low": str(min(Decimal(open_), Decimal(close)) - Decimal("1")),
        "close": close,
    }


def test_forward_windows_preserve_actual_post_event_direction() -> None:
    start = datetime(2026, 9, 21, 1, 1, tzinfo=UTC)
    bars = []
    price = Decimal("4400")
    for minute in range(60):
        close = price - Decimal("0.5")
        bars.append(
            _bar(
                minute + 1,
                open_=str(price),
                close=str(close),
            )
        )
        price = close

    result = _forward_window_returns(bars=bars, start=start)

    assert Decimal(result["5m"]["return_bps"]) < 0
    assert Decimal(result["15m"]["return_bps"]) < 0
    assert Decimal(result["30m"]["return_bps"]) < 0
    assert Decimal(result["60m"]["return_bps"]) < 0
    assert abs(Decimal(result["60m"]["return_bps"])) > abs(
        Decimal(result["5m"]["return_bps"])
    )


def test_forward_windows_return_unknown_when_market_path_is_missing() -> None:
    result = _forward_window_returns(
        bars=[],
        start=datetime(2026, 9, 21, 1, 1, tzinfo=UTC),
    )
    assert all(value["return_bps"] is None for value in result.values())


def test_movement_memory_contract_is_bounded_and_not_execution_authority() -> None:
    assert GOLD_MOVEMENT_MEMORY_VERSION == "aidy_gold_movement_memory_v1"
    assert MOVEMENT_EPISODE_COOLDOWN_MINUTES == 10
    assert MOVEMENT_FORWARD_HORIZON_MINUTES == 60

    source = (ROOT / "src" / "aidy" / "gold_movement_memory.py").read_text(encoding="utf-8")
    migration = (
        ROOT / "migrations" / "d1" / "0021_gold_movement_memory.sql"
    ).read_text(encoding="utf-8")
    scan_migration = (
        ROOT / "migrations" / "d1" / "0022_gold_movement_scan_ledger.sql"
    ).read_text(encoding="utf-8")
    provider = (ROOT / "src" / "provider_entry.py").read_text(encoding="utf-8")

    assert "scan_limit: int = 10" in source
    assert "aidy_gold_movement_scan_ledger" in source
    assert "capture_status='partial'" in source
    assert "latest_m1_id IS NOT NULL" in source
    assert "latest_h4_id IS NOT NULL" in source
    assert "future_values_used INTEGER NOT NULL DEFAULT 0" in migration
    assert "live_money_execution_allowed INTEGER NOT NULL DEFAULT 0" in migration
    assert "same_episode_retrieval_allowed INTEGER NOT NULL DEFAULT 0" in migration
    assert "source_snapshot_id TEXT PRIMARY KEY" in scan_migration
    assert "investigation_required INTEGER NOT NULL" in scan_migration
    assert "episode_stored INTEGER NOT NULL DEFAULT 0" in scan_migration
    assert "live_money_execution_allowed INTEGER NOT NULL DEFAULT 0" in scan_migration
    assert "sync_gold_movement_memory" in provider
    assert "_sync_gold_movement_memory_best_effort" in provider
