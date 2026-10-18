"""CROSSFIRE platform selects risk-balanced variant, without trading side effects."""
from copy import deepcopy

import pytest

from aidy.strategy_lab_goldthinker_balanced_policy import (
    CROSSFIRE_BALANCED, select_crossfire_platform_version,
    selection_markdown, verify_platform_selection,
)
from aidy.strategy_lab_nursery_refinement import build_refinement, checksum
from test_strategy_lab_nursery_refinement import synthetic_source


def prepared():
    return build_refinement(synthetic_source())


def test_goldthinker_fixes_balanced_not_original():
    case = prepared()
    selected = select_crossfire_platform_version(case)
    verify_platform_selection(selected, case)
    assert selected["owner_selection"] == CROSSFIRE_BALANCED
    assert selected["owner_selection"] != "original"
    assert selected["owner_selection_status"] == "SELECTED_FOR_PLATFORM_PAPER_PREFLIGHT"
    assert selected["original_source_preserved"] is True
    assert selected["owner_decision_date"] == "2026-10-18"
    assert case["selected_version"] is None  # Research immutable
    assert case["school_admission_approved"] is False
    for forbidden in (
        "paper_account_connected", "paper_execution_authorised",
        "funded_live_trading_authorised", "broker_risk_and_margin_verified",
        "customer_copy_authorised", "public_performance_authorised",
    ):
        assert selected[forbidden] is False
    assert selected["paper_start_date"] is None
    m = selection_markdown(selected, case)
    assert "hourly_state_half_new" in m
    assert "Paper connected: NO" in m
    assert "Broker orders authorised: NO" in m


def test_cannot_swap_selection_to_original_or_use_another_system():
    case = prepared()
    sel = select_crossfire_platform_version(case)
    sel["owner_selection"] = "original"
    sel["selection_record_sha256"] = checksum({
        k: v for k, v in sel.items() if k != "selection_record_sha256"
    })
    with pytest.raises(ValueError, match="selection"):
        verify_platform_selection(sel, case)
    other = deepcopy(case)
    other["system_id"] = "S999"
    other["draft_sha256"] = checksum({
        k: v for k, v in other.items() if k != "draft_sha256"
    })
    with pytest.raises(ValueError, match="another system"):
        select_crossfire_platform_version(other)


@pytest.mark.parametrize("field,value", [
    ("paper_execution_authorised", True),
    ("funded_live_trading_authorised", True),
    ("paper_account_connected", True),
    ("public_performance_authorised", True),
    ("customer_copy_authorised", True),
    ("broker_risk_and_margin_verified", True),
    ("paper_start_date", "2026-10-18"),
])
def test_selection_cannot_fake_execution_or_start(field, value):
    case = prepared()
    sel = select_crossfire_platform_version(case)
    sel[field] = value
    sel["selection_record_sha256"] = checksum({
        k: v for k, v in sel.items() if k != "selection_record_sha256"
    })
    with pytest.raises(ValueError, match="selection"):
        verify_platform_selection(sel, case)


def test_rejects_missing_balanced_source_gain_even_when_rehashed():
    draft = prepared()
    draft["comparison"]["2026"][CROSSFIRE_BALANCED]["dd_improvement_pp"] = 0
    draft["draft_sha256"] = checksum({
        k: v for k, v in draft.items() if k != "draft_sha256"
    })
    with pytest.raises(ValueError, match="risk evidence"):
        select_crossfire_platform_version(draft)


def test_selection_is_stable_and_bound_to_research_sha():
    one = prepared()
    first = select_crossfire_platform_version(one)
    second = select_crossfire_platform_version(one)
    assert first == second
    one["source_packet_sha256"] = "b" * 64
    one["draft_sha256"] = checksum({
        k: v for k, v in one.items() if k != "draft_sha256"
    })
    changed = select_crossfire_platform_version(one)
    assert changed["selection_record_sha256"] != first["selection_record_sha256"]
