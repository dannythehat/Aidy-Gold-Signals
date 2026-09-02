from pathlib import Path


CONTRACT = Path("docs/day53-decision-context-adapter-qualification.md")
DEPENDENCY_MAP = Path("docs/day53-market-data-dependency-provenance-map.md")


def test_twelve_epoch_turn_on_requires_semantic_safe_wrappers_and_ledger_pass() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    required = (
        "aidy_market_data_semantic_identity_v1",
        "aidy_semantic_gold_feature_packet_v1",
        "aidy_semantic_market_context_v1",
        "aidy_semantic_case_input_wrapper_v1",
        "aidy_semantic_analogue_query_v1",
        "aidy_semantic_analogue_retrieval_v1",
        "aidy_semantic_context_composer_v1",
        "market_data_equivalence_contract_registered",
        "qualification_result",
        "pass",
        "inheritance_allowed=true",
        "aidy_research_ledger_anchor_v1",
    )
    for value in required:
        assert value in text
    assert "caller-supplied equivalence string" in text.lower()
    assert "direct use of legacy retrieval plus `compose_context_v2` does not qualify" in text.lower()
    assert "legacy `build_feature_packet` / `build_context_packet` / `build_pit_case_input`" in text


def test_step2_contract_discloses_known_reconciliation_before_preregistration() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    assert "informed rather than blind" in text
    assert "10–14 bps" in text
    assert "38–57 bps" in text
    assert "97 bps" in text
    assert "prior knowledge" in text


def test_step2_cannot_start_before_dependency_map_is_frozen() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    dependency = DEPENDENCY_MAP.read_text(encoding="utf-8")
    assert "Step 2 must not begin until" in text
    assert "day53-market-data-dependency-provenance-map.md" in text
    assert "FROZEN BEFORE STEP 2 EMPIRICAL QUALIFICATION" in dependency
    assert "No empirical parameter qualification was performed" in dependency


def test_formal_accumulation_remains_off_until_complete_qualification() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    assert "NOT YET QUALIFIED FOR NEW TWELVE DATA COHORT" in text
    assert "off for formal accumulation" in text
