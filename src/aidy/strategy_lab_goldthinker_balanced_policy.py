"""Owner-locked GoldThinker selection policy, separate from immutable AIDY research.

Research may retain original and rejected refinements. GoldThinker packaging
must use an owner-selected, evidence-supported risk-balanced configuration.
Nothing here connects a broker or authorises paper/live orders.
"""
from __future__ import annotations

from aidy.strategy_lab_nursery_refinement import checksum, verify_draft

POLICY_ID = "goldthinker.balanced_platform_selection.v1"
CROSSFIRE_ID = "S010"
CROSSFIRE_BALANCED = "hourly_state_half_new"
OWNER_DECISION_DATE = "2026-10-18"


def select_crossfire_platform_version(nursery_draft: dict) -> dict:
    """Apply owner's CROSSFIRE GoldThinker product choice, NOT an AIDY research mutation.

    The dated owner direction elects the previously tested H1 balanced variant.
    This is a *version selection for the future product*, not clearance to trade.
    The source generation job must independently replay source H1 history first.
    """
    verify_draft(nursery_draft)
    if nursery_draft.get("system_id") != CROSSFIRE_ID:
        raise ValueError("CROSSFIRE decision cannot select another system")
    if nursery_draft.get("proposed_compromise") != CROSSFIRE_BALANCED:
        raise ValueError("chosen balanced risk version missing from AIDY report")
    periods = nursery_draft.get("comparison", {})
    if set(periods) != {"2025", "2026"}:
        raise ValueError("independent historical comparison missing")
    for year in ("2025", "2026"):
        original = periods[year]["original"]
        balanced = periods[year][CROSSFIRE_BALANCED]
        if (balanced["dd_improvement_pp"] <= 0 or
                balanced["profit_usd"] <= 0 or
                balanced["max_dd_pct"] >= 0 or
                original["max_dd_pct"] >= 0):
            raise ValueError("selected GoldThinker balance case fails risk evidence")
    outcome = {
        "schema": POLICY_ID,
        "platform": "GoldThinker",
        "private_only": True,
        "system_id": CROSSFIRE_ID,
        "owner_decision_date": OWNER_DECISION_DATE,
        "owner_selection": CROSSFIRE_BALANCED,
        "owner_selection_status": "SELECTED_FOR_PLATFORM_PAPER_PREFLIGHT",
        "original_source_preserved": True,
        "nursery_research_draft_sha256": nursery_draft["draft_sha256"],
        "underlying_historical_packet_sha256": nursery_draft["source_packet_sha256"],
        "selection_reasons": [
            "GoldThinker defaults to independently tested, owner-approved risk-balanced versions, not maximum historical profit.",
            "CROSSFIRE H1-updated half-size new-entry guard reduced marked drawdown in both sampled research periods.",
            "Original entry and exit triggers remain unchanged; overlay changes only future entry exposure.",
        ],
        "future_systems_policy": (
            "Evaluate and compare risk-managed alternatives first. "
            "Without an actually tested and owner-approved balanced variant, "
            "hold packaging and deployment. Never silently manufacture an overlay."
        ),
        "paper_account_connected": False,
        "paper_execution_authorised": False,
        "funded_live_trading_authorised": False,
        "broker_risk_and_margin_verified": False,
        "customer_copy_authorised": False,
        "public_performance_authorised": False,
        "paper_start_date": None,
        "required_next_action": (
            "Complete independent data/robustness and broker-risk acceptance, "
            "then configure the owner-selected balanced version for a separate "
            "demo account using the secure paper preflight."
        ),
    }
    outcome["selection_record_sha256"] = checksum(outcome)
    return outcome


def verify_platform_selection(selection: dict, nursery_draft: dict) -> None:
    """Fail closed on swapping original/variant or inventing execution authority."""
    expected = select_crossfire_platform_version(nursery_draft)
    if selection != expected:
        raise ValueError("platform version selection or safety flags modified")


def selection_markdown(selection: dict, nursery_draft: dict) -> str:
    verify_platform_selection(selection, nursery_draft)
    return (
        "# GoldThinker S010 — OWNED platform configuration selection\n\n"
        "**PRIVATE OWNER CHOICE (18 October 2026):** "
        "CROSSFIRE uses **hourly_state_half_new** for future GoldThinker "
        "packaging and paper-account preflight, not the original 3.28x "
        "exposure policy.\n\n"
        "AIDY keeps all original research and alternative result ledgers "
        "unmodified. GoldThinker does not choose the highest backtested "
        "profit at the expense of risk. This selection says what version "
        "would run *if* separately approved for Infants.\n\n"
        "## Independent activation blockers\n"
        "- [ ] Unseen/out-of-sample robustness and original-source completeness reviewed.\n"
        "- [ ] Broker executable spread, swap, contract, margin/stopout model verified.\n"
        "- [ ] Separate hard account kill switch and loss controls accepted.\n"
        "- [ ] Isolated MT5 DEMO account, source-version parity and broker clock verified.\n"
        "- [ ] Owner separately authorises paper order flow and logs its real first fill.\n"
        "- [ ] Public/paid customer copying remains separately forbidden until qualified.\n\n"
        "**Paper connected: NO. Broker orders authorised: NO. "
        "Funded trading authorised: NO.**\n\n"
        "Selected version: " + selection["owner_selection"] + "\n\n"
        "Underlying research packet SHA: " + selection["underlying_historical_packet_sha256"] + "\n\n"
        "Platform selection record SHA: " + selection["selection_record_sha256"] + "\n"
    )
