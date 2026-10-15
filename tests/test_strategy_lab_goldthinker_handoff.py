"""Day34 handoff policy: authenticated, fully evidence-qualified REVIEW ONLY."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from aidy.strategy_lab_evidence_rating import (
    FACTOR_WEIGHTS,
    EvidenceBasis,
    FactorFinding,
)
from aidy.strategy_lab_goldthinker_handoff import (
    ResearchEvidence,
    check_handoff,
    digest,
    evaluate_receipt,
    issue_internal_receipt,
    prepare_private_handoff,
)
from test_strategy_lab_evidence_rating import example, full

KEY = b"test-only-fixed-32-byte-key-never-use-in-production"
OTHER_KEY = b"separately-generated-test-only-secret-key-000000000"
HASH = tuple(f"{i:064x}" for i in range(1, 8))


def qualified(test_fixture: bool = True) -> ResearchEvidence:
    basis = example()
    return ResearchEvidence(
        strategy_id="HYPOTHETICAL_POLICY_TEST_001",
        original_source_sha256=basis.historical_input_sha256,
        rule_version_sha256=basis.strategy_rule_sha256,
        original_run_sha256=basis.original_run_sha256,
        full_trial_registry_sha256=basis.oos_holdout_trial_tip_sha256,
        costed_trade_ledger_sha256=basis.verified_costed_trade_ledger_sha256,
        independently_matched_benchmark_sha256=basis.fair_matched_benchmark_sha256,
        rights_review_status="VERIFIED_RIGHTS_TO_REVIEW",
        evidence_basis=basis, factor_findings=full(),
        is_test_fixture=test_fixture,
    )


def sign(candidate: ResearchEvidence) -> dict:
    return issue_internal_receipt(candidate, KEY)


def test_frozen_goldthinker_handoff_has_no_automatic_paper_or_live_authority():
    p = prepare_private_handoff([], KEY)
    check_handoff(p)
    assert p["candidate_count"] == 0
    assert p["production_status"] == "NO_DEPLOYMENT"
    assert p["no_real_money_or_paper_trades_created"]
    assert p["engine"] == "AIDY" and p["future_customer_brand"] == "GoldThinker"
    assert p["all_production_actions_blocked"]
    assert all(value is False for value in p["all_production_actions_blocked"].values())


def test_perfect_hypothetical_policy_fixture_cannot_leave_research_as_real_handoff():
    receipt = sign(qualified())
    result = evaluate_receipt(receipt, KEY)
    assert result["research_rating"]["score_out_of_100"] == 100
    assert result["is_test_fixture"] is True
    assert not result["eligible_for_separate_human_review"]
    assert "TEST_FIXTURE_NOT_RELEASEABLE" in result["blockers"]
    assert prepare_private_handoff([receipt], KEY)["candidate_count"] == 0


def test_positive_branch_is_only_owner_claude_review_even_for_fake_qualified_inputs():
    # A hypothetical signed source contract checks POLICY MATH ONLY.
    # A real production issuer does not yet exist; this cannot attest market alpha.
    receipt = sign(qualified(test_fixture=False))
    row = evaluate_receipt(receipt, KEY)
    assert row["eligible_for_separate_human_review"] is True
    packet = prepare_private_handoff([receipt], KEY)
    check_handoff(packet)
    assert packet["candidate_count"] == 1
    review = packet["candidates"][0]
    assert review["research_governance"] == "GREEN_HIGH_PRIORITY"
    assert review["research_score"] == 100
    assert review["claude_review_decision"] == "PENDING"
    assert review["owner_review_decision"] == "PENDING"
    assert review["goldthinker_product_name"] is None
    assert review["forward_paper_account_id"] is None
    assert review["customer_join_enabled"] is False
    assert packet["production_status"] == "NO_DEPLOYMENT"


@pytest.mark.parametrize("field", [
    "original_source_sha256", "rule_version_sha256",
    "original_run_sha256", "full_trial_registry_sha256",
    "costed_trade_ledger_sha256", "independently_matched_benchmark_sha256",
])
def test_cross_stage_sha_mismatch_cannot_be_signed(field):
    candidate = qualified()
    with pytest.raises(ValueError, match="mismatch"):
        issue_internal_receipt(replace(candidate, **{field:"a"*64}), KEY)


@pytest.mark.parametrize("field", [
    "internal_attestation_hmac_sha256", "evidence_sha256",
])
def test_invalid_receipt_hashes_rejected(field):
    r = sign(qualified(test_fixture=False))
    r[field] = "f"*64
    with pytest.raises(ValueError, match="untrusted"):
        evaluate_receipt(r, KEY)


def test_source_rating_and_stronger_paper_assertions_fail_even_with_changed_hash():
    r = sign(qualified(test_fixture=False))
    r["evidence"]["rating"]["score_out_of_100"] = 0
    r["evidence_sha256"] = digest(r["evidence"])
    with pytest.raises(ValueError, match="untrusted"):
        evaluate_receipt(r, KEY)


def test_unapproved_external_key_cannot_forge_internal_issuer():
    r = sign(qualified(test_fixture=False))
    with pytest.raises(ValueError, match="untrusted"):
        evaluate_receipt(r, OTHER_KEY)


def test_copying_external_claimed_qualification_flags_unsupported():
    orig = qualified()
    source = replace(
        orig.evidence_basis, origin="retrospective_bid_only",
        actual_bid_ask_costed_trades_independently_replayed=False,
        chronological_oos_trading_independently_verified=False,
        fair_benchmark_independently_verified=False,
    )
    r = sign(replace(orig, evidence_basis=source))
    result = evaluate_receipt(r, KEY)
    assert result["research_rating"]["score_out_of_100"] is None
    assert not result["eligible_for_separate_human_review"]
    assert "NO_INDEPENDENT_QUALIFIED_GREEN_EVIDENCE" in result["blockers"]


def test_nonpositive_edge_cannot_be_transferred_even_when_nine_factors_perfect():
    candidate = qualified(test_fixture=False)
    basis = replace(candidate.evidence_basis, observed_benchmark_edge_usd=0)
    with pytest.raises(ValueError):
        issue_internal_receipt(replace(candidate, evidence_basis=basis), KEY)


def test_unverified_review_rights_block_goldthinker_handoff():
    candidate = replace(qualified(False), rights_review_status="REVIEW_REQUIRED")
    outcome = evaluate_receipt(sign(candidate), KEY)
    assert not outcome["eligible_for_separate_human_review"]
    assert "STRATEGY_REVIEW_RIGHTS_NOT_VERIFIED" in outcome["blockers"]


def test_green_score_below_80_does_not_get_owner_claude_queue():
    candidate = qualified(False)
    factors = list(candidate.factor_findings)
    factors[0] = replace(factors[0], awarded_points=0)
    outcome = evaluate_receipt(
        sign(replace(candidate, factor_findings=tuple(factors))), KEY
    )
    assert outcome["research_rating"]["governance"] != "GREEN_HIGH_PRIORITY"
    assert not outcome["eligible_for_separate_human_review"]


def test_old_or_duplicate_strategy_cannot_increase_reviewer_jobs():
    ticket = sign(qualified(test_fixture=False))
    with pytest.raises(ValueError, match="duplicate"):
        prepare_private_handoff([ticket, ticket], KEY)


def test_unverified_public_green_claim_cannot_be_accepted():
    fake = {
        "issuer": "USER_UPLOAD",
        "evidence_sha256": "f"*64,
        "internal_attestation_hmac_sha256": "f"*64,
        "evidence": {"rating": {"governance": "GREEN_HIGH_PRIORITY"}},
    }
    with pytest.raises(ValueError, match="issuer"):
        evaluate_receipt(fake, KEY)


def test_foreign_field_is_not_ignored_in_signed_receipt():
    ticket = sign(qualified(False))
    ticket["unexpected_live_deployment"] = True
    with pytest.raises(ValueError, match="missing authenticated"):
        evaluate_receipt(ticket, KEY)


def test_scoring_policy_cannot_be_overwritten_by_signed_wrapper():
    r = sign(qualified(False))
    altered = deepcopy(r)
    altered["evidence"]["rating"]["governance"] = "RED_REJECT"
    altered["evidence_sha256"] = digest(altered["evidence"])
    # Recomputing the inner SHA is not adequate without independent issuer.
    with pytest.raises(ValueError, match="untrusted"):
        evaluate_receipt(altered, KEY)


def test_handoff_packet_rejects_tampered_customer_join_and_paper_figure():
    p = prepare_private_handoff([sign(qualified(False))], KEY)
    for field, value in (
        ("customer_join_enabled", True),
        ("forward_paper_pnl_usd", "9999999.00"),
        ("owner_review_decision", "APPROVED"),
        ("goldthinker_product_name", "The Down Hunter"),
    ):
        changed = deepcopy(p)
        changed["candidates"][0][field] = value
        changed["packet_sha256"] = digest({
            k:v for k,v in changed.items() if k != "packet_sha256"
        })
        with pytest.raises(ValueError, match="premature"):
            check_handoff(changed)


def test_fifty_user_submissions_without_receipts_denied():
    bad = [
        {"strategy_id": f"S{i:03d}", "rating": {"score_out_of_100": 90}}
        for i in range(50)
    ]
    with pytest.raises(ValueError, match="missing authenticated"):
        prepare_private_handoff(bad, KEY)


def test_key_short_or_missing_will_not_fail_open():
    with pytest.raises(ValueError, match="server-side"):
        prepare_private_handoff([], b"key")


def test_oversized_handoff_input_refused():
    with pytest.raises(ValueError, match="bounded"):
        prepare_private_handoff([{}]*101, KEY)
