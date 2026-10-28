"""Dedup tests use synthetic audited signatures; NEVER certify real S001-S083."""
import copy
import json
from pathlib import Path

import pytest

from scripts.gold_hunter_oracle_dedup_audit import (
    CATALOG, CORE_FIELDS, SIG_FIELDS, audit, canonical_source,
)


def source():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def mock_mechanics():
    result = {k: f"mechanic_{k}_TEST_ONLY" for k in SIG_FIELDS}
    result["parameters"] = {"period": 20, "multiplier": 1.5}
    result["risk_policy"] = {"risk": 0.005}
    return result


def signed_evidence(mechanics):
    return {
        "source_commit_sha": "a" * 40,
        "evidence_uri": "https://example.org/independently-reviewed-fixture",
        "mechanics": mechanics,
    }


def test_all_83_retained_shared_source_is_not_exact_duplicate():
    r = audit(source())
    assert r["candidates"] == 83
    assert r["distinct_upstream_urls"] == 61
    assert r["source_reuse_excess_references"] == 22
    assert r["shared_source_groups_count"] == 6
    assert r["source_audited_rule_signatures_count"] == 0
    assert len(r["audited_equivalence_pairs"]) == 0
    assert r["automatic_deletion_or_promotion"] is False
    groups = {x["source_url"]: x for x in r["shared_source_groups"]}
    assert groups["https://github.com/baturdenada/gold-sweep-backtester"]["candidate_count"] == 12
    pair = next(x for x in r["review_flags"] if {x["a"], x["b"]} == {"S020", "S021"})
    assert "SAME_UPSTREAM_URL_ONLY" in pair["flags"]
    assert pair["cannot_assert_duplicate_without_source_audit"] is True


def test_exact_same_audited_mechanics_is_canonical_review_not_auto_delete():
    m = mock_mechanics()
    r = audit(source(), {
        "S020": signed_evidence(m),
        "S021": signed_evidence(copy.deepcopy(m)),
    })
    hit = next(x for x in r["audited_equivalence_pairs"]
               if x["classification"] == "AUDITED_EXACT_MECHANICS")
    assert (hit["a"], hit["b"]) == ("S020", "S021")
    assert hit["action"] == "REVIEW_FOR_ONE_CANONICAL_STRATEGY"
    assert r["candidates"] == 83
    assert r["automatic_deletion_or_promotion"] is False


def test_parameter_variant_separate_from_full_duplicate():
    m = mock_mechanics()
    n = copy.deepcopy(m)
    n["parameters"]["period"] = 55
    r = audit(source(), {
        "S036": signed_evidence(m),
        "S037": signed_evidence(n),
    })
    pair = next(x for x in r["audited_equivalence_pairs"]
                if x["a"] == "S036" and x["b"] == "S037")
    assert pair["classification"] == "AUDITED_PARAMETER_OR_RISK_VARIANT"
    assert pair["action"].startswith("GROUP_AS_VERSION")
    n["entry_rule"] = "DIFFERENT_ORIGINAL_TRIGGER"
    changed = audit(source(), {
        "S036": signed_evidence(m),
        "S037": signed_evidence(n),
    })
    assert not changed["audited_equivalence_pairs"]


def test_missing_source_rules_and_partial_signature_rejected():
    invalid = signed_evidence(mock_mechanics())
    del invalid["mechanics"]["stop_rule"]
    with pytest.raises(ValueError, match="Incomplete rule"):
        audit(source(), {"S001": invalid})
    bad = signed_evidence(mock_mechanics())
    bad["source_commit_sha"] = "NOT_A_REAL_GIT_SHA"
    with pytest.raises(ValueError, match="source-pinned"):
        audit(source(), {"S001": bad})


def test_source_url_normalisation_does_not_remove_strategy_identity():
    assert canonical_source("HTTPS://GITHUB.COM/Example/System.git/") == (
        "https://github.com/example/system")
    r = audit(source())
    assert r["status"] == "DISCOVERY_PRECHECK_NEEDS_SOURCE_PARITY_AND_TRADE_OVERLAP"
