"""Retrospective research history must never become decision evidence.

Shadow research needs to know whether a provider's past trades made money, which is a
question about objective price history. AIDY's live decisions must never use a bar it
could not have seen at the time. These tests pin the line between the two.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aidy.twelve_data_market import RAW_M1_SOURCE
from aidy.twelve_data_retrospective import (
    MAX_RETROSPECTIVE_WINDOW_MINUTES,
    RETROSPECTIVE_M1_SOURCE,
    AidyRetrospectiveBackfillService,
    validate_window,
)

ROOT = Path(__file__).resolve().parents[1]

# A gap day where capture was down and shadow trades are stranded.
GAP_START = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
GAP_END = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)


class _Bar:
    def __init__(self, opened: datetime, price: str) -> None:
        self.open_time_utc = opened
        self.open = price
        self.high = price
        self.low = price
        self.close = price
        self.payload_digest = f"digest-{opened.isoformat()}"


class _Fetch:
    def __init__(self, bars) -> None:
        self.closed_bars = tuple(bars)
        self.fetched_at_utc = datetime(2026, 9, 15, 4, 0, tzinfo=UTC)
        self.response_digest = "response-digest"


class _Gateway:
    def __init__(self, bars) -> None:
        self._bars = bars
        self.calls: list[tuple[datetime, datetime]] = []

    async def fetch_1m(self, *, start_date, end_date):
        self.calls.append((start_date, end_date))
        return _Fetch(self._bars)


class _Store:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    async def reserve_request(self, *, requested_at, request_kind, outputsize):
        self.requests.append({"kind": request_kind, "status": "reserved"})
        return len(self.requests)

    async def finish_request(self, *, request_id, completed_at, status, **kwargs):
        self.requests[request_id - 1]["status"] = status


class _Repository:
    def __init__(self) -> None:
        self.stored: list[dict] = []

    async def store_candle(self, payload):
        self.stored.append(payload)
        return None, None, True


def _service(bars):
    gateway = _Gateway(bars)
    repository = _Repository()
    store = _Store()

    async def _no_sleep(_seconds):
        return None

    service = AidyRetrospectiveBackfillService(
        repository=repository,
        gateway=gateway,
        store=store,
        sleep=_no_sleep,
        monotonic=lambda: 0.0,
    )
    return service, gateway, repository, store


def _hour_of_bars(start: datetime, minutes: int = 60):
    return [_Bar(start + timedelta(minutes=i), "4290.00") for i in range(minutes)]


@pytest.mark.asyncio
async def test_retrospective_bars_are_written_under_a_non_admitted_source() -> None:
    """The whole safety property in one assertion."""
    service, _, repository, _ = _service(_hour_of_bars(GAP_START))

    result = await service.ingest_window(start_utc=GAP_START, end_utc=GAP_END)

    assert result["persisted_new_minutes"] == 60
    assert result["pit_eligible"] is False
    assert result["decision_admitted"] is False
    assert repository.stored, "no bars persisted"
    for payload in repository.stored:
        assert payload["source"] == RETROSPECTIVE_M1_SOURCE
        assert payload["source"] != RAW_M1_SOURCE


def test_decision_admitted_view_cannot_select_the_retrospective_source() -> None:
    """The exclusion is enforced by the view definition, not by a caller's discipline.

    twelve_data_decision_admitted_m1_v1 filters source='twelve_data_vendor_m1_v1', so a
    retrospective bar is not in the set the PIT read is built from. If a future migration
    widens that filter, this test fails and the safety property is gone.
    """
    migrations = sorted((ROOT / "migrations" / "d1").glob("*.sql"))
    definitions = [
        text
        for text in (path.read_text(encoding="utf-8") for path in migrations)
        if "CREATE VIEW twelve_data_decision_admitted_m1_v1" in text
    ]
    assert definitions, "decision-admitted view definition not found"

    for text in definitions:
        assert RETROSPECTIVE_M1_SOURCE not in text
        assert re.search(r"source\s*=\s*'twelve_data_vendor_m1_v1'", text)


@pytest.mark.asyncio
async def test_bars_outside_the_requested_window_are_discarded() -> None:
    """A wide vendor response must not silently widen what was asked for."""
    bars = _hour_of_bars(GAP_START - timedelta(minutes=30), minutes=180)
    service, _, repository, _ = _service(bars)

    result = await service.ingest_window(start_utc=GAP_START, end_utc=GAP_END)

    assert result["vendor_minutes_returned"] == 60
    opens = [payload["open_time_utc"] for payload in repository.stored]
    assert min(opens) == GAP_START
    assert max(opens) == GAP_END - timedelta(minutes=1)


@pytest.mark.asyncio
async def test_request_is_ledgered_under_its_own_kind() -> None:
    """Research traffic is distinguishable from scheduled capture and bootstrap."""
    service, _, _, store = _service(_hour_of_bars(GAP_START))

    await service.ingest_window(start_utc=GAP_START, end_utc=GAP_END)

    assert [entry["kind"] for entry in store.requests] == ["retrospective_research"]
    assert [entry["status"] for entry in store.requests] == ["succeeded"]


@pytest.mark.asyncio
async def test_a_failed_vendor_call_still_closes_its_ledger_row() -> None:
    service, gateway, _, store = _service(_hour_of_bars(GAP_START))

    async def _boom(*, start_date, end_date):
        raise RuntimeError("vendor_unavailable")

    gateway.fetch_1m = _boom

    with pytest.raises(RuntimeError):
        await service.ingest_window(start_utc=GAP_START, end_utc=GAP_END)

    assert store.requests[0]["status"] == "failed"


def test_window_must_be_settled_history() -> None:
    """Forming bars belong to scheduled capture; taking them here mislabels provenance."""
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    with pytest.raises(ValueError, match="not_settled"):
        validate_window(now - timedelta(minutes=30), now)


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (GAP_END, GAP_START, "invalid"),
        (GAP_START, GAP_START, "invalid"),
        (
            GAP_START,
            GAP_START + timedelta(minutes=MAX_RETROSPECTIVE_WINDOW_MINUTES + 1),
            "too_large",
        ),
        (GAP_START + timedelta(seconds=30), GAP_END, "not_minute_aligned"),
    ],
)
def test_window_bounds_are_enforced(start, end, expected) -> None:
    with pytest.raises(ValueError, match=expected):
        validate_window(start, end)


def test_naive_timestamps_are_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        validate_window(GAP_START.replace(tzinfo=None), GAP_END.replace(tzinfo=None))


def test_research_read_is_separate_from_the_decision_read() -> None:
    """The two endpoints must keep answering different questions.

    /market/ohlc answers "what could AIDY have seen at the time": it reads the
    decision-admitted view and refuses a row observed after the window closed.
    /research/market/ohlc answers "what did the market do": it reads market_candles
    across both sources with no cutoff, and says so on every response.
    """
    api = (ROOT / "src" / "aidy" / "provider_market_api.py").read_text(encoding="utf-8")

    decision = api.index("async def market_ohlc_response")
    research = api.index("async def research_market_ohlc_response")
    assert decision < research

    decision_body = api[decision:research]
    research_body = api[research:]

    # The decision path reads the admitted view and enforces the PIT cutoff.
    assert "twelve_data_decision_admitted_m1_v1" in decision_body
    assert "admitted_row_exceeds_pit_cutoff" in decision_body

    # The research path reads neither the view nor applies that cutoff, and never
    # presents itself as evidence.
    assert "twelve_data_decision_admitted_m1_v1" not in research_body
    assert "admitted_row_exceeds_pit_cutoff" not in research_body
    assert '"pit_eligible": False' in research_body
    assert '"decision_admitted": False' in research_body
    assert RETROSPECTIVE_M1_SOURCE in research_body


def test_retrospective_source_is_absent_from_every_decision_path() -> None:
    """Nothing on AIDY's forward path may name the retrospective source."""
    forward_surfaces = (
        ROOT / "src" / "aidy" / "twelve_data_recorder.py",
        ROOT / "src" / "aidy" / "twelve_data_bootstrap.py",
        ROOT / "src" / "aidy" / "forward_live_observer.py",
    )
    for path in forward_surfaces:
        if not path.exists():
            continue
        assert RETROSPECTIVE_M1_SOURCE not in path.read_text(encoding="utf-8"), path.name
