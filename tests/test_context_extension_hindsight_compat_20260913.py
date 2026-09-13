from __future__ import annotations

import pytest

from aidy.setup_detector import _assert_no_hindsight


def test_setup_detector_allows_explicit_false_safety_flags() -> None:
    _assert_no_hindsight(
        {
            "architecture_v2_extensions": {
                "market_structure_context": {
                    "future_derived": False,
                    "evaluation_only": False,
                    "pit_eligible": True,
                }
            }
        },
        path="context",
    )


def test_setup_detector_still_rejects_true_future_derived() -> None:
    with pytest.raises(ValueError, match="Future-derived evidence is forbidden"):
        _assert_no_hindsight(
            {"architecture_v2_extensions": {"future_derived": True}},
            path="context",
        )


def test_setup_detector_still_rejects_true_evaluation_only() -> None:
    with pytest.raises(ValueError, match="Evaluation-only evidence is forbidden"):
        _assert_no_hindsight(
            {"architecture_v2_extensions": {"evaluation_only": True}},
            path="context",
        )
