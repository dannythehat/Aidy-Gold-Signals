from __future__ import annotations

import pytest

from aidy.historical_backfill import DERIVATION_VERSION, HISTDATA_SOURCE
from aidy.market_data_semantics import (
    assert_semantic_compatible,
    histdata_semantic_identity,
    identity_from_source_links,
    twelve_data_semantic_identity,
    verify_semantic_identity,
)
from aidy.twelve_data_market import RAW_M1_SOURCE


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


def test_same_identity_passes_and_explicit_equivalence_is_visible() -> None:
    twelve = twelve_data_semantic_identity()
    result = assert_semantic_compatible(twelve, twelve)
    assert result["state"] == "same_semantic_identity"
    assert result["equivalence_contract_digest"] is None

    hist = histdata_semantic_identity()
    qualified = assert_semantic_compatible(
        twelve,
        hist,
        accepted_equivalence_contract_digest="a" * 64,
    )
    assert qualified["state"] == "qualified_equivalence_contract"
    assert qualified["equivalence_contract_digest"] == "a" * 64
