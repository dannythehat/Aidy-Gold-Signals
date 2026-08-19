from datetime import UTC, datetime

from aidy.market_sessions import session_code_at
from aidy.reference_price_recorder import _session_code


def test_active_reference_recorder_uses_shared_dst_aware_session_clock() -> None:
    summer_overlap = datetime(2026, 7, 1, 12, 30, tzinfo=UTC)
    assert session_code_at(summer_overlap) == "london_new_york_overlap"
    assert _session_code(summer_overlap) == session_code_at(summer_overlap)
