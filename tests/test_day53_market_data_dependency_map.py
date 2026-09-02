from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from aidy import analogue_retrieval as v1
from aidy import analogue_retrieval_v2 as v2
from aidy.regime_classifier import VOLATILITY_HIGH_GTE_BPS, VOLATILITY_LOW_LT_BPS
from aidy.setup_detector import SETUP_DEFINITIONS


MAP = Path("docs/day53-market-data-dependency-provenance-map.md")


def _component_scale(components, name: str):
    return next(item[4] for item in components if item[0] == name)


def test_dependency_map_binds_current_volatility_and_similarity_geometry() -> None:
    assert VOLATILITY_LOW_LT_BPS == Decimal(20)
    assert VOLATILITY_HIGH_GTE_BPS == Decimal(50)
    assert _component_scale(v1._COMPONENTS, "h1_atr") == Decimal(40)
    assert _component_scale(v1._COMPONENTS, "m15_realized_vol") == Decimal(30)
    assert _component_scale(v2._COMPONENTS, "h1_atr") == Decimal(40)
    assert all(item[0] != "m15_realized_vol" for item in v2._COMPONENTS)
    excluded = v2.similarity_manifest_v2()["deliberately_excluded_redundant_soft_votes"]
    assert "m15_realized_vol_20_bps" in excluded


def test_dependency_map_enumerates_all_volatility_band_setup_consumers() -> None:
    consumers = sorted(
        definition["setup_id"]
        for definition in SETUP_DEFINITIONS
        if any(clause["observation"] == "volatility_band" for clause in definition["clauses"])
    )
    assert consumers == [
        "high_vol_recovery_long",
        "high_vol_recovery_short",
        "low_vol_break_pressure_long",
        "low_vol_break_pressure_short",
    ]
    text = MAP.read_text(encoding="utf-8")
    for setup_id in consumers:
        assert f"`{setup_id}`" in text


def test_dependency_map_records_preledger_setup_provenance_and_no_step2_search() -> None:
    text = MAP.read_text(encoding="utf-8")
    required = (
        "FROZEN BEFORE STEP 2 EMPIRICAL QUALIFICATION",
        "predates the Step 0 immutable trials ledger",
        "20/50",
        "40 bps",
        "30 bps",
        "m15_range_atr_ratio",
        "FAIL and INSUFFICIENT both prohibit inheritance",
        "No empirical parameter qualification was performed",
        "aidy_semantic_context_composer_v1",
    )
    for value in required:
        assert value in text
