"""Day34 private AIDY -> GoldThinker human REVIEW handoff gate.

No trading, broker connections, publication, paper-account creation, automatic
promotion or system renaming occurs here. Only qualified, internally attested
research may be exported for SEPARATE Claude and owner decisions. A paper
deployment remains a wholly separate future owner-controlled process.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from decimal import Decimal

from aidy.strategy_lab_evidence_rating import (
    EvidenceBasis,
    FactorFinding,
    rate_strategy_evidence,
)

SCHEMA = "aidy.strategy_lab.goldthinker_review_handoff.v1"
ISSUER = "AIDY_INTERNAL_RESEARCH_EVIDENCE_ADAPTER_V1"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,79}$")
SAFE_ACTIONS = ("CLAUDE_REVIEW_PENDING", "OWNER_REVIEW_PENDING")
BLOCKED_ACTIONS = (
    "paper_account_created", "live_trading_enabled", "broker_order_allowed",
    "system_publication_allowed", "customer_connection_allowed",
    "master_portfolio_join_allowed", "production_automatically_approved",
)


def canonical(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      allow_nan=False, ensure_ascii=True).encode("ascii")


def digest(obj: object) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def _secret(key: bytes) -> None:
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("trusted server-side receipt signing key is required")


def _sha(value: object) -> bool:
    return isinstance(value, str) and SHA_RE.fullmatch(value) is not None


@dataclass(frozen=True)
class ResearchEvidence:
    """Evidence is only trusted when authenticated by the INTERNAL issuer.

    Signer itself belongs inside the trusted qualified-research service; public
    user inputs cannot choose an 'independently_verified' boolean as proof.
    """
    strategy_id: str
    original_source_sha256: str
    rule_version_sha256: str
    original_run_sha256: str
    full_trial_registry_sha256: str
    costed_trade_ledger_sha256: str
    independently_matched_benchmark_sha256: str
    rights_review_status: str
    evidence_basis: EvidenceBasis
    factor_findings: tuple[FactorFinding, ...]
    is_test_fixture: bool = False

    def content(self) -> dict:
        if (not isinstance(self.strategy_id, str) or not ID_RE.fullmatch(self.strategy_id)
                or any(not _sha(value) for value in (
                    self.original_source_sha256,
                    self.rule_version_sha256,
                    self.original_run_sha256,
                    self.full_trial_registry_sha256,
                    self.costed_trade_ledger_sha256,
                    self.independently_matched_benchmark_sha256,
                )) or self.rights_review_status not in (
                    "REVIEW_REQUIRED", "VERIFIED_RIGHTS_TO_REVIEW",
                ) or type(self.is_test_fixture) is not bool):
            raise ValueError("malformed independent strategy or source identity")
        basis = self.evidence_basis
        if (basis.strategy_rule_sha256 != self.rule_version_sha256
                or basis.historical_input_sha256 != self.original_source_sha256
                or basis.original_run_sha256 != self.original_run_sha256
                or basis.verified_costed_trade_ledger_sha256
                != self.costed_trade_ledger_sha256
                or basis.fair_matched_benchmark_sha256
                != self.independently_matched_benchmark_sha256
                or basis.oos_holdout_trial_tip_sha256
                != self.full_trial_registry_sha256):
            raise ValueError("receipt source, trial, trade, or benchmark mismatch")
        rating = rate_strategy_evidence(basis, self.factor_findings)
        return {
            "strategy_id": self.strategy_id,
            "original_source_sha256": self.original_source_sha256,
            "rule_version_sha256": self.rule_version_sha256,
            "original_run_sha256": self.original_run_sha256,
            "full_trial_registry_sha256": self.full_trial_registry_sha256,
            "costed_trade_ledger_sha256": self.costed_trade_ledger_sha256,
            "independently_matched_benchmark_sha256":
                self.independently_matched_benchmark_sha256,
            "rights_review_status": self.rights_review_status,
            "is_test_fixture": self.is_test_fixture,
            "evidence_basis": basis.to_wire(),
            "rating": rating.to_wire(),
        }


def issue_internal_receipt(evidence: ResearchEvidence, server_key: bytes) -> dict:
    """Only the privately operated independently qualified AIDY issuer calls this.

    This is a packet integrity mechanism, not an independent source validator.
    Day34 has NO live issuer adapter for customer trading claims.
    """
    _secret(server_key)
    data = evidence.content()
    body = {"issuer": ISSUER, "evidence": data,
            "evidence_sha256": digest(data)}
    return {
        **body,
        "internal_attestation_hmac_sha256":
            hmac.new(server_key, canonical(body), hashlib.sha256).hexdigest(),
    }


def evaluate_receipt(receipt: dict, server_key: bytes) -> dict:
    _secret(server_key)
    if not isinstance(receipt, dict) or set(receipt) != {
        "issuer", "evidence", "evidence_sha256", "internal_attestation_hmac_sha256",
    }:
        raise ValueError("missing authenticated internal source receipt")
    if receipt["issuer"] != ISSUER or not _sha(receipt["evidence_sha256"]):
        raise ValueError("unknown evidence issuer")
    mac = receipt["internal_attestation_hmac_sha256"]
    if not _sha(mac):
        raise ValueError("invalid internal attestation format")
    body = {k: receipt[k] for k in ("issuer", "evidence", "evidence_sha256")}
    if (digest(receipt["evidence"]) != receipt["evidence_sha256"]
            or not hmac.compare_digest(
                hmac.new(server_key, canonical(body), hashlib.sha256).hexdigest(),
                mac,
            )):
        raise ValueError("untrusted or modified evidence receipt")
    original = receipt["evidence"]
    if not isinstance(original, dict):
        raise TypeError("malformed attested evidence body")
    basis = original["evidence_basis"]
    source = EvidenceBasis(**{
        **basis,
        "observed_net_expectancy_usd": (
            Decimal(basis["observed_net_expectancy_usd"])
            if basis["observed_net_expectancy_usd"] is not None else None
        ),
        "observed_benchmark_edge_usd": (
            Decimal(basis["observed_benchmark_edge_usd"])
            if basis["observed_benchmark_edge_usd"] is not None else None
        ),
    })
    findings = tuple(FactorFinding(**f) for f in original["rating"]["factor_scores"])
    reconstructed = ResearchEvidence(
        strategy_id=original["strategy_id"],
        original_source_sha256=original["original_source_sha256"],
        rule_version_sha256=original["rule_version_sha256"],
        original_run_sha256=original["original_run_sha256"],
        full_trial_registry_sha256=original["full_trial_registry_sha256"],
        costed_trade_ledger_sha256=original["costed_trade_ledger_sha256"],
        independently_matched_benchmark_sha256=
            original["independently_matched_benchmark_sha256"],
        rights_review_status=original["rights_review_status"],
        is_test_fixture=original["is_test_fixture"],
        evidence_basis=source,
        factor_findings=findings,
    )
    recomputed = reconstructed.content()
    if recomputed != original:
        raise ValueError("attested rating does not agree with independent policy replay")
    rating = recomputed["rating"]
    blocked = []
    if original["is_test_fixture"]:
        blocked.append("TEST_FIXTURE_NOT_RELEASEABLE")
    if rating["governance"] != "GREEN_HIGH_PRIORITY":
        blocked.append("NO_INDEPENDENT_QUALIFIED_GREEN_EVIDENCE")
    if rating["score_out_of_100"] is None or rating["score_out_of_100"] < 80:
        blocked.append("NO_QUALIFIED_NUMERIC_RESEARCH_SCORE")
    if rating["historical_profitability_qualified"] is not True:
        blocked.append("NO_PROVEN_NET_COSTED_BASELINE_ADVANTAGE")
    if source.qualified_for_economic_scoring() is not True:
        blocked.append("INDEPENDENT_EXECUTION_OOS_BASELINE_PROOF_REQUIRED")
    if original["rights_review_status"] != "VERIFIED_RIGHTS_TO_REVIEW":
        blocked.append("STRATEGY_REVIEW_RIGHTS_NOT_VERIFIED")
    if rating["veto_reasons"] or rating["missing_evidence"]:
        blocked.append("EVIDENCE_VETO_OR_UNRESOLVED_BLOCKER")
    return {
        "strategy_id": original["strategy_id"],
        "evidence_sha256": receipt["evidence_sha256"],
        "rule_version_sha256": original["rule_version_sha256"],
        "original_run_sha256": original["original_run_sha256"],
        "full_trial_registry_sha256": original["full_trial_registry_sha256"],
        "costed_trade_ledger_sha256": original["costed_trade_ledger_sha256"],
        "independently_matched_benchmark_sha256":
            original["independently_matched_benchmark_sha256"],
        "original_source_sha256": original["original_source_sha256"],
        "research_rating": rating,
        "eligible_for_separate_human_review": not blocked,
        "blockers": blocked,
        "source_receipt_authenticated": True,
        "is_test_fixture": original["is_test_fixture"],
    }


def prepare_private_handoff(receipts: list[dict], server_key: bytes) -> dict:
    """Queue human review only; NO account, trading or customer side effects."""
    _secret(server_key)
    if not isinstance(receipts, list) or len(receipts) > 100:
        raise ValueError("bounded internal research handoff input required")
    seen: set[str] = set()
    entries = []
    for receipt in receipts:
        finding = evaluate_receipt(receipt, server_key)
        ident = finding["strategy_id"]
        if ident in seen:
            raise ValueError("duplicate strategy cannot bypass independent review")
        seen.add(ident)
        if not finding["eligible_for_separate_human_review"]:
            continue
        entries.append({
            "strategy_id": ident,
            "research_run_sha256": finding["original_run_sha256"],
            "original_rule_sha256": finding["rule_version_sha256"],
            "original_source_sha256": finding["original_source_sha256"],
            "trials_sha256": finding["full_trial_registry_sha256"],
            "journal_sha256": finding["costed_trade_ledger_sha256"],
            "benchmark_sha256": finding["independently_matched_benchmark_sha256"],
            "attested_evidence_sha256": finding["evidence_sha256"],
            "research_score": finding["research_rating"]["score_out_of_100"],
            "research_governance": "GREEN_HIGH_PRIORITY",
            "review_steps": list(SAFE_ACTIONS),
            "claude_review_decision": "PENDING",
            "owner_review_decision": "PENDING",
            "goldthinker_product_name": None,
            "goldthinker_production_status": "NOT_STARTED",
            "forward_paper_account_id": None,
            "forward_paper_pnl_usd": None,
            "customer_join_enabled": False,
            "automatically_promoted": False,
        })
    if len(entries) > 20:
        raise ValueError("owner handoff review batch exceeds twenty proposals")
    packet = {
        "schema": SCHEMA,
        "purpose": "PRIVATE_OWNER_AND_CLAUDE_REVIEW_ONLY",
        "engine": "AIDY", "future_customer_brand": "GoldThinker",
        "authority": "INTERNAL_SIGNED_EVIDENCE_RECEIPTS_NOT_PUBLIC_ASSERTIONS",
        "candidate_count": len(entries),
        "candidates": entries,
        "excluded_input_count": len(receipts)-len(entries),
        "review_decision": "AWAITING_SEPARATE_OWNER_AND_CLAUDE_REVIEW",
        "production_status": "NO_DEPLOYMENT",
        "no_broker_or_customer_side_effects": True,
        "all_production_actions_blocked": {name: False for name in BLOCKED_ACTIONS},
        "no_real_money_or_paper_trades_created": True,
    }
    packet["packet_sha256"] = digest(packet)
    return packet


def check_handoff(packet: dict) -> None:
    if not isinstance(packet, dict) or packet.get("schema") != SCHEMA:
        raise ValueError("invalid research-to-production packet")
    original = {k: v for k, v in packet.items() if k != "packet_sha256"}
    if packet.get("packet_sha256") != digest(original):
        raise ValueError("handoff content modified")
    if (packet["purpose"] != "PRIVATE_OWNER_AND_CLAUDE_REVIEW_ONLY"
            or packet["review_decision"] != "AWAITING_SEPARATE_OWNER_AND_CLAUDE_REVIEW"
            or packet["production_status"] != "NO_DEPLOYMENT"
            or packet["no_broker_or_customer_side_effects"] is not True
            or packet["no_real_money_or_paper_trades_created"] is not True
            or packet["all_production_actions_blocked"]
            != {name: False for name in BLOCKED_ACTIONS}
            or packet["candidate_count"] != len(packet["candidates"])):
        raise ValueError("unexpected customer trading, paper or promotion authority")
    for entry in packet["candidates"]:
        if (entry["review_steps"] != list(SAFE_ACTIONS)
                or entry["claude_review_decision"] != "PENDING"
                or entry["owner_review_decision"] != "PENDING"
                or entry["forward_paper_account_id"] is not None
                or entry["forward_paper_pnl_usd"] is not None
                or entry["goldthinker_product_name"] is not None
                or entry["goldthinker_production_status"] != "NOT_STARTED"
                or entry["customer_join_enabled"] is not False
                or entry["automatically_promoted"] is not False):
            raise ValueError("handoff may never contain premature GoldThinker operation")
