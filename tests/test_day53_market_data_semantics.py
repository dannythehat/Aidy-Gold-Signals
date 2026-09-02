from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aidy.historical_backfill import DERIVATION_VERSION, HISTDATA_SOURCE
from aidy.market_data_semantics import (
    EQUIVALENCE_CONTRACT_RECORD_TYPE,
    QUALIFICATION_RESULT_RECORD_TYPE,
    accepted_market_data_equivalences,
    assert_semantic_compatible,
    histdata_semantic_identity,
    identity_from_source_links,
    twelve_data_semantic_identity,
    verify_semantic_identity,
)
from aidy.research_trials import (
    build_record,
    digest as research_digest,
    equivalence_contract_payload,
    governance_genesis_payload,
    qualification_result_payload,
)
from aidy.twelve_data_market import RAW_M1_SOURCE

SHA40 = "a" * 40


def _equivalence_chain(*, outcome: str = "pass") -> list[dict]:
    hist = histdata_semantic_identity()
    twelve = twelve_data_semantic_identity()
    start = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)
    genesis = build_record(
        sequence=0,
        previous_digest=None,
        record_type="governance_genesis",
        recorded_at=start,
        code_head_sha=SHA40,
        initiated_by="human",
        payload=governance_genesis_payload(),
    )
    contract = equivalence_contract_payload(
        qualification_id="histdata-twelve-regime-v1",
        affected_surface="regime_classifier.volatility_band",
        source_identity_a_digest=hist["semantic_identity_digest"],
        source_identity_b_digest=twelve["semantic_identity_digest"],
        comparison_population_digest="b" * 64,
        minimum_paired_sample=100,
        coverage_requirements={"sessions": ["asia", "london", "new_york"]},
        distribution_metrics=[{"metric": "paired_abs_difference_bps"}],
        decision_surface_metrics=[{"metric": "20_50_band_disagreement_rate"}],
        pass_criteria={"state": "frozen_before_run"},
        fail_criteria={"state": "frozen_before_run"},
        insufficient_evidence_criteria={"paired_sample_lt": 100},
    )
    contract_record = build_record(
        sequence=1,
        previous_digest=genesis["record_digest"],
        record_type=EQUIVALENCE_CONTRACT_RECORD_TYPE,
        recorded_at=start + timedelta(minutes=1),
        code_head_sha=SHA40,
        initiated_by="human",
        payload=contract,
    )
    result = qualification_result_payload(
        qualification_id="histdata-twelve-regime-v1",
        contract_digest=research_digest(contract),
        outcome=outcome,
        evidence_digest="c" * 64,
    )
    result_record = build_record(
        sequence=2,
        previous_digest=contract_record["record_digest"],
        record_type=QUALIFICATION_RESULT_RECORD_TYPE,
        recorded_at=start + timedelta(minutes=2),
        code_head_sha=SHA40,
        initiated_by="registered_search_engine",
        payload=result,
    )
    return [genesis, contract_record, result_record]


def test_histdata_and_twelve_data_have_distinct_semantic_identities() -> None:
    hist = histdata_semantic_identity()
    twelve = twelve_data_semantic_identity()
    assert verify_semantic_identity(hist)
    assert verify_semantic_identity(twelve)
    assert hist["semantic_identity_digest"] != twelve["semantic_identity_digest"]


def test_source_links_resolve_known_families_and_reject_mixed_or_unknown() -> None:
    hist = identity_from_source_links(
        {"M1": [{"source": HISTDATA_SOURCE, "derivation_version": DERIVATION_VERSION}]}
    )
    twelve = identity_from_source_links({"M1": [{"source": RAW_M1_SOURCE}]})
    assert hist["provider_source_family"] == "histdata"
    assert twelve["provider_source_family"] == "twelve_data"

    with pytest.raises(ValueError, match="mixed market-data semantic families"):
        identity_from_source_links(
            {
                "M1": [
                    {"source": HISTDATA_SOURCE, "derivation_version": DERIVATION_VERSION},
                    {"source": RAW_M1_SOURCE},
                ]
            }
        )
    with pytest.raises(ValueError, match="cannot be established"):
        identity_from_source_links({"M1": [{"source": "unknown_vendor"}]})


def test_cross_source_analogue_semantics_fail_closed_without_qualified_contract() -> None:
    hist = histdata_semantic_identity()
    twelve = twelve_data_semantic_identity()
    with pytest.raises(ValueError, match="cross-source analogue comparison blocked"):
        assert_semantic_compatible(twelve, hist)


def test_same_identity_passes_without_equivalence() -> None:
    twelve = twelve_data_semantic_identity()
    result = assert_semantic_compatible(twelve, twelve)
    assert result["state"] == "same_semantic_identity"
    assert result["equivalence_contract_digest"] is None
    assert result["qualification_result_record_digest"] is None


def test_only_valid_hash_chained_pass_record_unlocks_cross_source_equivalence() -> None:
    hist = histdata_semantic_identity()
    twelve = twelve_data_semantic_identity()
    accepted = accepted_market_data_equivalences(_equivalence_chain(outcome="pass"))
    key = f'{twelve["semantic_identity_digest"]}:{hist["semantic_identity_digest"]}'
    assert key in accepted
    qualified = assert_semantic_compatible(
        twelve,
        hist,
        accepted_equivalence=accepted[key],
    )
    assert qualified["state"] == "qualified_equivalence_contract"
    assert len(qualified["equivalence_contract_digest"]) == 64
    assert len(qualified["qualification_result_record_digest"]) == 64


def test_fail_result_does_not_unlock_cross_source_equivalence() -> None:
    assert accepted_market_data_equivalences(_equivalence_chain(outcome="fail")) == {}


def test_broken_ledger_chain_cannot_unlock_cross_source_equivalence() -> None:
    chain = _equivalence_chain(outcome="pass")
    chain[1]["previous_digest"] = "d" * 64
    with pytest.raises(ValueError, match="ledger chain is invalid"):
        accepted_market_data_equivalences(chain)
