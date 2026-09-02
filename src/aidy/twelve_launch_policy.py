from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from aidy.market_data_semantics import twelve_data_semantic_identity
from aidy.regime_classifier import (
    classify_gold_regime,
    compute_regime_digest,
    verify_regime_digest,
)
from aidy.safety_gates import compute_safety_gate_digest, evaluate_pre_model_safety
from aidy.twelve_data_market import day53_twelve_data_market_manifest

TWELVE_LAUNCH_POLICY_VERSION = "aidy_twelve_private_forward_launch_policy_v1"
STEP2_OUTCOME = "insufficient_evidence"
BLOCKED_SOURCE_SCALE_SURFACES = (
    "h1_atr_volatility_band_threshold_20_bps",
    "h1_atr_volatility_band_threshold_50_bps",
    "v2_h1_atr_similarity_scale_40_bps",
)


def _is_twelve_context(context: Mapping[str, Any]) -> bool:
    expected = twelve_data_semantic_identity()["semantic_identity_digest"]
    identity = context.get("market_data_semantic_identity_digest")
    provenance = context.get("provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    embedded = provenance.get("gold_market_data_semantic_identity")
    return (
        identity == expected
        and isinstance(embedded, Mapping)
        and embedded.get("semantic_identity_digest") == expected
        and embedded.get("provider_source_family") == "twelve_data"
    )


def classify_twelve_private_forward_regime(context: Mapping[str, Any]) -> dict[str, Any]:
    """Preserve transferable regime labels while refusing unqualified 20/50 inheritance."""

    if not _is_twelve_context(context):
        raise ValueError("Twelve private-forward regime policy requires Twelve semantic context")
    base = classify_gold_regime(context)
    if not verify_regime_digest(base):
        raise RuntimeError("Base regime classifier returned an invalid digest")
    result = copy.deepcopy(base)
    result.pop("regime_digest", None)
    result["labels"] = dict(result["labels"])
    result["labels"]["volatility_band"] = "unknown"
    unknown = set(result.get("unknown_labels") or [])
    unknown.add("volatility_band")
    result["unknown_labels"] = sorted(unknown)
    rules = dict(result.get("rule_evidence") or {})
    rules["volatility_band"] = {
        "state": "blocked_unqualified_source_scale",
        "step2_outcome": STEP2_OUTCOME,
        "inherited_thresholds_used": False,
        "blocked_thresholds_bps": [20, 50],
        "reason": "day53_step2_structural_insufficient_evidence",
    }
    result["rule_evidence"] = rules
    result["twelve_launch_policy"] = {
        "policy_version": TWELVE_LAUNCH_POLICY_VERSION,
        "blocked_source_scale_surfaces": list(BLOCKED_SOURCE_SCALE_SURFACES),
        "unqualified_values_used": False,
        "cross_source_analogue_permission": False,
    }
    result["regime_digest"] = compute_regime_digest(result)
    if not verify_regime_digest(result):
        raise RuntimeError("Twelve private-forward regime digest failed verification")
    return result


def evaluate_twelve_pre_model_safety(
    context: Mapping[str, Any],
    *,
    now_utc: Any,
    instruction_type: str,
    seen_context_hashes=(),
) -> dict[str, Any]:
    """Apply Day-22 gates while honoring the frozen Twelve missing-spread contract only."""

    if not _is_twelve_context(context):
        raise ValueError("Twelve safety policy requires Twelve semantic context")
    manifest = day53_twelve_data_market_manifest()
    if manifest.get("spread_missing_blocks") is not False:
        raise RuntimeError("Twelve market manifest no longer permits advisory missing spread")

    result = evaluate_pre_model_safety(
        context,
        now_utc=now_utc,
        instruction_type=instruction_type,
        seen_context_hashes=seen_context_hashes,
    )
    checks = [dict(item) for item in result["checks"]]
    spread = next((item for item in checks if item.get("gate") == "spread_availability"), None)
    if spread is None:
        raise RuntimeError("Day-22 safety receipt lacks spread availability check")

    quote = context.get("gold")
    quote = quote.get("quote_context") if isinstance(quote, Mapping) else None
    quote = quote if isinstance(quote, Mapping) else {}
    quality = context.get("data_quality")
    quality = quality if isinstance(quality, Mapping) else {}
    advisory_only = quality.get("spread_state") == "unknown" and quote.get("spread") is None
    if spread.get("passed") is not True and advisory_only:
        spread["passed"] = True
        spread["reason_code"] = "pre_spread_advisory_twelve_data"
        spread["detail"] = TWELVE_LAUNCH_POLICY_VERSION

    blocked = [str(item["reason_code"]) for item in checks if item.get("passed") is not True]
    result = dict(result)
    result["checks"] = checks
    result["status"] = "passed" if not blocked else "blocked"
    result["model_call_allowed"] = not blocked
    result["reason_codes"] = ["pre_model_allowed"] if not blocked else blocked
    result["twelve_launch_policy_version"] = TWELVE_LAUNCH_POLICY_VERSION
    result["missing_spread_advisory_applied"] = advisory_only
    result.pop("gate_digest", None)
    result["gate_digest"] = compute_safety_gate_digest(result)
    return result


def twelve_launch_policy_manifest() -> dict[str, Any]:
    return {
        "policy_version": TWELVE_LAUNCH_POLICY_VERSION,
        "step2_outcome": STEP2_OUTCOME,
        "blocked_source_scale_surfaces": list(BLOCKED_SOURCE_SCALE_SURFACES),
        "volatility_band_masked_unknown": True,
        "volatility_dependent_setups_can_only_be_unresolved": True,
        "cross_source_analogue_permission": False,
        "no_comparable_case_allowed": True,
        "missing_spread_advisory_only_for_twelve_semantic_context": True,
        "public_publication_enabled": False,
        "live_money_execution_allowed": False,
    }
