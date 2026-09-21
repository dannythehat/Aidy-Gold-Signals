from __future__ import annotations

from scripts.build17_genuine_microstructure_holdout import (
    MICRO_RULES,
    choose_rule,
    combine_prediction,
    micro_vote,
)


def _normalized(signed: str | None, vwap: str | None) -> dict[str, str | None]:
    return {
        "signed_trade_imbalance_z": signed,
        "vwap_distance_z": vwap,
    }


def test_build17_genuine_rule_votes_require_signed_flow_and_vwap_agreement() -> None:
    assert micro_vote(_normalized("1.2", "0.7"), "tie_break_1_0p5") == "bullish"
    assert micro_vote(_normalized("-1.2", "-0.7"), "tie_break_1_0p5") == "bearish"
    assert micro_vote(_normalized("1.2", "-0.7"), "tie_break_1_0p5") == "neutral"
    assert micro_vote(_normalized(None, "2"), "tie_break_1_0p5") == "neutral"


def test_build17_genuine_override_rule_is_stricter() -> None:
    assert micro_vote(_normalized("1.2", "0.7"), "override_1p5_0p5") == "neutral"
    assert micro_vote(_normalized("1.6", "0.7"), "override_1p5_0p5") == "bullish"


def test_build17_genuine_combination_rules_are_frozen() -> None:
    assert combine_prediction("neutral", "bullish", "tie_break_1_0p5") == "bullish"
    assert combine_prediction("bearish", "bullish", "tie_break_1_0p5") == "bearish"
    assert combine_prediction("bearish", "bullish", "override_1p5_0p5") == "bullish"
    assert combine_prediction("bearish", "bullish", "veto_1_0p5") == "neutral"


def test_build17_genuine_dev_selection_never_reads_holdout() -> None:
    dev_rows = [
        {
            "spot_prediction": "neutral",
            "outcome_direction": "bullish",
            "normalized": _normalized("1.2", "0.7"),
        },
        {
            "spot_prediction": "bearish",
            "outcome_direction": "bearish",
            "normalized": _normalized("1.2", "0.7"),
        },
    ]
    selected = choose_rule(dev_rows)
    assert selected["selected"] in MICRO_RULES
    assert all(row["sample_n"] == len(dev_rows) for row in selected["candidates"])


def test_build17_genuine_rule_catalogue_is_small_and_preregistered() -> None:
    assert MICRO_RULES == (
        "tie_break_1_0p5",
        "override_1p5_0p5",
        "veto_1_0p5",
    )
