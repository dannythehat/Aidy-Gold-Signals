"""S004 auditable test-contract assertions before 22 months of raw tick conversion."""
from scripts.strategy_lab.s004_original_backtrader_two_period import (
    DATE_BANDS,MONTHS,SOURCE_GIT_BLOB,SOURCE_COMMIT,
)
def test_exact_2025_and_current_2026_year_separate_10k():
    assert DATE_BANDS["2025"]["from"]=="2025-01-01"
    assert DATE_BANDS["2025"]["to"]=="2026-01-01"
    assert DATE_BANDS["2026"]["from"]=="2026-01-01"
    assert DATE_BANDS["2026"]["to"]=="2026-10-01"
    assert DATE_BANDS["2025"]["month_count"]==12
    assert DATE_BANDS["2026"]["month_count"]==9

def test_original_author_source_is_immutably_pinned():
    assert len(SOURCE_GIT_BLOB)==40 and len(SOURCE_COMMIT)==40
    assert MONTHS[0]=="202412"
    assert MONTHS[-1]=="202609"
    assert len(MONTHS)==22
    assert len(set(MONTHS))==22

def test_unmodified_M5_data_requirement_is_strict():
    from scripts.strategy_lab.s004_original_tick_to_m5 import original_tick_m5
    from pathlib import Path
    import pytest
    with pytest.raises(ValueError):
        original_tick_m5(Path("/tmp/does-not-exist"),"202402")
    with pytest.raises(ValueError):
        original_tick_m5(Path("/tmp/does-not-exist"),"202610")
