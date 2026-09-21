"""Build 18: News / Movement Mechanism Expert for AIDY Gold.

Explains abnormal Gold moves using point-in-time scheduled-event and news evidence
without inventing causality. Finnhub is an optional live news adapter. The expert
is context-only: news never becomes an automatic directional vote.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

import httpx

from aidy.gold_expert_gate_contract import build_expert_gate_packet, verify_expert_gate_packet
from aidy.gold_expert_trust import (
    build_trust_envelope,
    build_trust_scopes,
    select_conditional_trust,
)
from aidy.gold_movement_investigator import verify_gold_movement_investigation

NEWS_MOVEMENT_MECHANISM_EXPERT_VERSION = "aidy_gold_news_movement_mechanism_expert_v1"
NEWS_MOVEMENT_MECHANISM_GATE_ID = "news_movement_mechanism_expert"
NEWS_MOVEMENT_MECHANISM_TARGET_HORIZON_MINUTES = 15
NEWS_SOURCE_CONTRACT_VERSION = "aidy_news_source_contract_v1"
FINNHUB_NEWS_ADAPTER_VERSION = "aidy_finnhub_market_news_adapter_v1"
FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
FINNHUB_API_KEY_ENV = "FINNHUB_API_KEY"
FINNHUB_NEWS_CATEGORIES = ("general", "forex")
MAX_NEWS_ROWS = 200
MAX_NEWS_AGE_SECONDS = 6 * 60 * 60

NEWS_MOVEMENT_MECHANISM_TRUST_REDUCED_CONTEXTS = (
    {
        "name": "mechanism_state",
        "mini_dimensions": [
            "movement_state",
            "news_state",
            "agreement_state",
            "leading_mechanism_tag",
        ],
        "global_dimensions": ["volatility_state"],
        "minimum_sample_n": 12,
    },
    {
        "name": "event_news_state",
        "mini_dimensions": ["scheduled_event_state", "news_state", "agreement_state"],
        "global_dimensions": ["event_timing_state"],
        "minimum_sample_n": 10,
    },
)

_SOURCE_AUTHORITY = {
    "reuters": "major_wire",
    "associated press": "major_wire",
    "ap": "major_wire",
    "bloomberg": "major_financial",
    "dow jones": "major_financial",
    "wall street journal": "major_financial",
    "federal reserve": "official",
    "bureau of labor statistics": "official",
    "bureau of economic analysis": "official",
    "u.s. treasury": "official",
    "us treasury": "official",
}

_MECHANISM_KEYWORDS = {
    "fed_policy": (
        "federal reserve",
        "fomc",
        "fed chair",
        "fed governor",
        "rate cut",
        "rate hike",
        "interest rate",
        "monetary policy",
    ),
    "inflation": (
        "inflation",
        "consumer price",
        "cpi",
        "pce",
        "producer price",
        "ppi",
    ),
    "labor_growth": (
        "payroll",
        "jobs",
        "employment",
        "unemployment",
        "gdp",
        "retail sales",
        "ism",
        "pmi",
    ),
    "usd_rates": (
        "dollar",
        "treasury",
        "yield",
        "bond yield",
        "real yield",
    ),
    "geopolitical_risk": (
        "war",
        "attack",
        "missile",
        "conflict",
        "sanction",
        "ceasefire",
        "geopolitical",
    ),
    "trade_policy": (
        "tariff",
        "trade war",
        "trade deal",
        "export control",
        "import duty",
    ),
    "risk_sentiment": (
        "risk-off",
        "risk on",
        "selloff",
        "sell-off",
        "safe haven",
        "safe-haven",
    ),
    "energy_inflation": (
        "oil",
        "crude",
        "energy price",
        "gas price",
    ),
    "gold_specific": (
        "gold",
        "bullion",
        "precious metal",
    ),
}

_WS = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^a-z0-9 ]+")


def _utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Build 18 timestamps must be timezone-aware")
    return parsed.astimezone(UTC)


def _canonical_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = _NON_WORD.sub(" ", text)
    return _WS.sub(" ", text).strip()


def _source_authority(source: Any) -> str:
    name = _canonical_text(source)
    if not name:
        return "unknown"
    for token, authority in _SOURCE_AUTHORITY.items():
        if token in name:
            return authority
    return "publisher"


def _mechanism_tags(*values: Any) -> list[str]:
    text = " ".join(_canonical_text(value) for value in values if value)
    tags = [
        tag
        for tag, phrases in _MECHANISM_KEYWORDS.items()
        if any(phrase in text for phrase in phrases)
    ]
    return sorted(tags)


def _story_key(*, source: str, headline: str, url: str, provider_id: str) -> str:
    if provider_id:
        return "provider:" + provider_id
    normalized = "|".join((_canonical_text(source), _canonical_text(headline), str(url or "").strip()))
    return "story:" + sha256(normalized.encode()).hexdigest()[:32]


def news_source_contract() -> dict[str, Any]:
    return {
        "contract_version": NEWS_SOURCE_CONTRACT_VERSION,
        "provider": "Finnhub",
        "adapter_version": FINNHUB_NEWS_ADAPTER_VERSION,
        "secret_env_var": FINNHUB_API_KEY_ENV,
        "base_url": FINNHUB_BASE_URL,
        "endpoint": "/news",
        "categories": list(FINNHUB_NEWS_CATEGORIES),
        "accepted_fields": [
            "id",
            "category",
            "datetime",
            "headline",
            "source",
            "summary",
            "url",
            "related",
        ],
        "published_timestamp_required": True,
        "first_observed_timestamp_required": True,
        "future_rows_allowed": False,
        "source_authority_required_for_corroboration": True,
        "duplicate_story_collapse_required": True,
        "causal_claim_from_single_headline_allowed": False,
        "news_directional_vote_allowed": False,
        "research_only": True,
        "live_money_execution_allowed": False,
    }


def normalize_finnhub_market_news(
    rows: Sequence[Mapping[str, Any]],
    *,
    fetched_at_utc: datetime | str,
    as_of_utc: datetime | str,
    category: str,
) -> list[dict[str, Any]]:
    fetched_at = _utc(fetched_at_utc)
    as_of = _utc(as_of_utc)
    if fetched_at > as_of:
        raise ValueError("Finnhub fetch observation cannot be after the Build 18 as-of time")
    category = str(category or "").strip().lower()
    if category not in FINNHUB_NEWS_CATEGORIES:
        raise ValueError("unsupported Finnhub market-news category")

    normalized: list[dict[str, Any]] = []
    for raw in rows[:MAX_NEWS_ROWS]:
        raw_ts = raw.get("datetime")
        if isinstance(raw_ts, bool):
            continue
        try:
            published = datetime.fromtimestamp(int(raw_ts), tz=UTC)
        except (TypeError, ValueError, OSError):
            continue
        if published > as_of:
            continue
        age_seconds = int((as_of - published).total_seconds())
        if age_seconds < 0 or age_seconds > MAX_NEWS_AGE_SECONDS:
            continue

        headline = str(raw.get("headline") or "").strip()
        source = str(raw.get("source") or "").strip()
        if not headline or not source:
            continue
        summary = str(raw.get("summary") or "").strip()
        url = str(raw.get("url") or "").strip()
        provider_id = str(raw.get("id") or "").strip()
        authority = _source_authority(source)
        tags = _mechanism_tags(headline, summary)
        normalized.append(
            {
                "provider": "Finnhub",
                "provider_id": provider_id or None,
                "provider_category": category,
                "story_key": _story_key(
                    source=source,
                    headline=headline,
                    url=url,
                    provider_id=provider_id,
                ),
                "headline": headline,
                "summary": summary,
                "source": source,
                "source_authority": authority,
                "published_at_utc": published.isoformat(),
                "first_observed_at_utc": fetched_at.isoformat(),
                "age_seconds_at_as_of": age_seconds,
                "url": url or None,
                "related": str(raw.get("related") or "").strip() or None,
                "mechanism_tags": tags,
                "gold_relevance_state": "relevant" if tags else "unclassified",
                "causal_claim": False,
                "directional_vote": None,
                "future_values_used": False,
            }
        )
    return normalized


def collapse_duplicate_news(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    unique: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    seen_headlines: set[str] = set()
    duplicates = 0

    authority_rank = {
        "official": 4,
        "major_wire": 3,
        "major_financial": 3,
        "publisher": 2,
        "unknown": 1,
    }
    ordered = sorted(
        (dict(row) for row in rows),
        key=lambda row: (
            authority_rank.get(str(row.get("source_authority") or "unknown"), 0),
            str(row.get("published_at_utc") or ""),
        ),
        reverse=True,
    )

    for row in ordered:
        key = str(row.get("story_key") or "").strip()
        headline_key = _canonical_text(row.get("headline"))
        if not key or not headline_key:
            continue
        if key in seen_keys or headline_key in seen_headlines:
            duplicates += 1
            continue
        seen_keys.add(key)
        seen_headlines.add(headline_key)
        unique.append(row)

    unique.sort(key=lambda row: str(row.get("published_at_utc") or ""))
    return {
        "input_story_n": len(rows),
        "unique_story_n": len(unique),
        "duplicate_story_n": duplicates,
        "stories": unique,
        "duplicate_story_collapse_applied": True,
    }


def _scheduled_context(investigation: Mapping[str, Any]) -> dict[str, Any]:
    candidates = investigation.get("mechanism_candidates")
    candidates = candidates if isinstance(candidates, list) else []
    rows: list[dict[str, Any]] = []
    tags: set[str] = set()
    for raw in candidates:
        if not isinstance(raw, Mapping):
            continue
        mechanism = str(raw.get("mechanism") or "")
        if mechanism not in {
            "scheduled_macro_event_window",
            "tiered_macro_event_window",
            "observed_macro_release_surprise",
        }:
            continue
        detail = raw.get("detail")
        detail = dict(detail) if isinstance(detail, Mapping) else {}
        row_tags = _mechanism_tags(str(detail))
        tags.update(row_tags)
        rows.append(
            {
                "mechanism": mechanism,
                "support_level": str(raw.get("support_level") or "unknown"),
                "detail": detail,
                "mechanism_tags": row_tags,
                "causal_claim": False,
            }
        )
    return {
        "state": "known" if rows else "unknown_no_scheduled_event_evidence",
        "candidate_n": len(rows),
        "mechanism_tags": sorted(tags),
        "candidates": rows,
        "causal_claim": False,
    }


def _credible_news(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    allowed = {"official", "major_wire", "major_financial"}
    return [
        dict(row)
        for row in rows
        if row.get("source_authority") in allowed
        and isinstance(row.get("mechanism_tags"), list)
        and bool(row.get("mechanism_tags"))
    ]


def _agreement_state(
    *,
    scheduled: Mapping[str, Any],
    credible: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    news_sets = [set(row.get("mechanism_tags") or []) for row in credible]
    news_union = set().union(*news_sets) if news_sets else set()
    news_intersection = set.intersection(*news_sets) if len(news_sets) >= 2 else set(news_union)
    scheduled_tags = set(scheduled.get("mechanism_tags") or [])

    if scheduled_tags and news_union:
        overlap = scheduled_tags & news_union
        if overlap:
            state = "scheduled_event_and_news_agree"
            tags = sorted(overlap)
        else:
            state = "scheduled_event_news_disagree_unresolved"
            tags = []
    elif len(credible) >= 2:
        if news_intersection:
            state = "credible_news_sources_agree"
            tags = sorted(news_intersection)
        else:
            state = "credible_news_sources_disagree_unresolved"
            tags = []
    elif len(credible) == 1:
        state = "single_credible_news_source"
        tags = sorted(news_union)
    elif scheduled_tags or scheduled.get("candidate_n"):
        state = "scheduled_event_context_only"
        tags = sorted(scheduled_tags)
    else:
        state = "unknown_no_supported_mechanism"
        tags = []

    return {
        "state": state,
        "agreement_tags": tags,
        "scheduled_tags": sorted(scheduled_tags),
        "credible_news_tags": sorted(news_union),
        "credible_news_n": len(credible),
        "disagreement_unresolved": state
        in {
            "scheduled_event_news_disagree_unresolved",
            "credible_news_sources_disagree_unresolved",
        },
        "causal_claim": False,
    }


def resolve_news_movement_mechanism(
    *,
    investigation: Mapping[str, Any],
    news_observations: Sequence[Mapping[str, Any]],
    narrative_claims: Sequence[str] = (),
) -> dict[str, Any]:
    if not verify_gold_movement_investigation(investigation):
        raise ValueError("Build 18 requires a verified Gold movement investigation")

    deduped = collapse_duplicate_news(news_observations)
    stories = deduped["stories"]
    credible = _credible_news(stories)
    scheduled = _scheduled_context(investigation)
    agreement = _agreement_state(scheduled=scheduled, credible=credible)

    unsupported = [
        str(item).strip()
        for item in narrative_claims
        if str(item).strip()
    ]
    if investigation.get("investigation_required") is not True:
        state = "not_triggered"
    elif agreement["state"] in {
        "scheduled_event_and_news_agree",
        "credible_news_sources_agree",
        "single_credible_news_source",
    }:
        state = "supported_context"
    elif agreement["disagreement_unresolved"]:
        state = "disagreement_unresolved"
    elif agreement["state"] == "scheduled_event_context_only":
        state = "scheduled_event_context_only"
    elif unsupported:
        state = "unsupported_narrative"
    else:
        state = "unknown"

    leading_tags = agreement["agreement_tags"] or agreement["credible_news_tags"]
    leading_tag = leading_tags[0] if leading_tags else "unknown"
    authority_rank = ["official", "major_wire", "major_financial", "publisher", "unknown"]
    authorities = {str(row.get("source_authority") or "unknown") for row in stories}
    strongest = next((item for item in authority_rank if item in authorities), "unknown")

    return {
        "state": state,
        "news_state": (
            "known_credible"
            if credible
            else "known_unconfirmed"
            if stories
            else "unknown_no_news_rows"
        ),
        "scheduled_event_state": str(scheduled["state"]),
        "agreement_state": str(agreement["state"]),
        "agreement": agreement,
        "scheduled_context": scheduled,
        "duplicate_collapse": {
            key: deduped[key]
            for key in ("input_story_n", "unique_story_n", "duplicate_story_n", "duplicate_story_collapse_applied")
        },
        "stories": stories,
        "credible_story_n": len(credible),
        "strongest_source_authority": strongest,
        "leading_mechanism_tag": leading_tag,
        "unsupported_narratives": unsupported,
        "unsupported_narratives_used_as_evidence": False,
        "cause_known": False,
        "causal_claim": False,
        "news_directional_vote_allowed": False,
        "future_values_used": False,
    }


class FinnhubNewsClient:
    """Bounded Finnhub market-news adapter used by Build 18."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = FINNHUB_BASE_URL,
        transport: Any = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        key = str(api_key or "").strip()
        if not key:
            raise ValueError("FINNHUB_API_KEY is required")
        self.api_key = key
        self.base_url = str(base_url).rstrip("/")
        self.transport = transport
        self.timeout_seconds = float(timeout_seconds)

    @classmethod
    def from_env(cls, **kwargs: Any) -> "FinnhubNewsClient":
        return cls(api_key=os.environ.get(FINNHUB_API_KEY_ENV, ""), **kwargs)

    async def fetch_market_news(
        self,
        *,
        category: str,
        as_of_utc: datetime | str,
    ) -> list[dict[str, Any]]:
        category = str(category or "").strip().lower()
        if category not in FINNHUB_NEWS_CATEGORIES:
            raise ValueError("unsupported Finnhub market-news category")
        as_of = _utc(as_of_utc)
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            response = await client.get(
                "/news",
                params={"category": category, "minId": 0, "token": self.api_key},
            )
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("Finnhub market-news response must be a list")
        return normalize_finnhub_market_news(
            payload,
            fetched_at_utc=as_of,
            as_of_utc=as_of,
            category=category,
        )

    async def fetch_gold_context(
        self,
        *,
        as_of_utc: datetime | str,
        categories: Sequence[str] = FINNHUB_NEWS_CATEGORIES,
    ) -> list[dict[str, Any]]:
        combined: list[dict[str, Any]] = []
        for category in categories:
            combined.extend(
                await self.fetch_market_news(
                    category=category,
                    as_of_utc=as_of_utc,
                )
            )
        return collapse_duplicate_news(combined)["stories"]


def _context_calculator(
    *,
    calculator_id: str,
    evidence_ref: str,
    known: bool,
    observation: Mapping[str, Any],
    explanation: str,
    dependency_family: str = "news_mechanism",
) -> dict[str, Any]:
    return {
        "calculator_id": calculator_id,
        "version": f"{calculator_id}_v1",
        "role": "context_only",
        "dependency_family": dependency_family,
        "state": "known" if known else "insufficient",
        "vote": "context_only" if known else "unknown",
        "evidence_refs": [evidence_ref],
        "observation": dict(observation),
        "explanation": explanation,
    }


def _subject_keys(packet: Mapping[str, Any]) -> list[str]:
    return [
        f"gate:{packet['gate_id']}",
        *(f"subcalculator:{item['calculator_id']}" for item in packet["subcalculators"]),
    ]


def build_news_movement_mechanism_expert(
    *,
    global_environment: Mapping[str, Any],
    movement_investigation: Mapping[str, Any],
    news_observations: Sequence[Mapping[str, Any]] = (),
    narrative_claims: Sequence[str] = (),
    trust_score_rows_by_subject: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    exact = global_environment.get("exact_facts")
    exact = exact if isinstance(exact, Mapping) else {}
    as_of = _utc(str(exact.get("as_of_utc")))

    if not verify_gold_movement_investigation(movement_investigation):
        raise ValueError("Build 18 requires a verified movement investigation")
    investigation_as_of = _utc(str(movement_investigation.get("as_of_utc")))
    if investigation_as_of != as_of:
        raise ValueError("Build 18 movement investigation must share the global as-of")

    bounded_news: list[dict[str, Any]] = []
    for row in news_observations:
        observed = _utc(str(row.get("first_observed_at_utc")))
        published = _utc(str(row.get("published_at_utc")))
        if observed > as_of or published > as_of:
            continue
        bounded_news.append(dict(row))

    mechanism = resolve_news_movement_mechanism(
        investigation=movement_investigation,
        news_observations=bounded_news,
        narrative_claims=narrative_claims,
    )
    source_contract = news_source_contract()

    evidence_inputs = [
        {
            "evidence_id": "news_movement_investigation_evidence",
            "source": "aidy_gold_movement_investigator_v1",
            "path": "news_movement_mechanism.investigation",
            "observed_at_utc": as_of,
            "state": "known",
            "value": {
                "state": movement_investigation.get("state"),
                "investigation_required": movement_investigation.get("investigation_required"),
                "triggered_by": movement_investigation.get("triggered_by"),
                "move_direction": movement_investigation.get("move_direction"),
                "attribution_state": movement_investigation.get("attribution_state"),
                "mechanism_candidates": movement_investigation.get("mechanism_candidates"),
                "cause_known": False,
            },
            "provenance": {
                "investigation_digest": movement_investigation.get("investigation_digest"),
                "future_values_used": False,
            },
        },
        {
            "evidence_id": "news_source_rows_evidence",
            "source": "finnhub_market_news_adapter",
            "path": "news_movement_mechanism.news_rows",
            "observed_at_utc": as_of,
            "state": "known" if mechanism["stories"] else "unavailable",
            "value": {
                "news_state": mechanism["news_state"],
                "stories": mechanism["stories"],
                "credible_story_n": mechanism["credible_story_n"],
                "strongest_source_authority": mechanism["strongest_source_authority"],
            },
            "provenance": {
                "source_contract_version": NEWS_SOURCE_CONTRACT_VERSION,
                "adapter_version": FINNHUB_NEWS_ADAPTER_VERSION,
                "future_values_used": False,
            },
        },
        {
            "evidence_id": "news_mechanism_resolution_evidence",
            "source": NEWS_MOVEMENT_MECHANISM_EXPERT_VERSION,
            "path": "news_movement_mechanism.resolution",
            "observed_at_utc": as_of,
            "state": "known" if mechanism["state"] != "unknown" else "unknown",
            "value": {
                key: mechanism[key]
                for key in (
                    "state",
                    "scheduled_event_state",
                    "agreement_state",
                    "agreement",
                    "duplicate_collapse",
                    "leading_mechanism_tag",
                    "unsupported_narratives",
                    "unsupported_narratives_used_as_evidence",
                    "cause_known",
                    "causal_claim",
                    "news_directional_vote_allowed",
                )
            },
            "provenance": {"future_values_used": False},
        },
        {
            "evidence_id": "news_source_contract_evidence",
            "source": NEWS_SOURCE_CONTRACT_VERSION,
            "path": "news_movement_mechanism.source_contract",
            "observed_at_utc": as_of,
            "state": "known",
            "value": source_contract,
            "provenance": {"future_values_used": False},
        },
    ]

    calculators = [
        _context_calculator(
            calculator_id="news_abnormal_move_trigger",
            evidence_ref="news_movement_investigation_evidence",
            known=True,
            observation={
                "investigation_required": movement_investigation.get("investigation_required"),
                "triggered_by": movement_investigation.get("triggered_by"),
                "move_direction": movement_investigation.get("move_direction"),
                "cause_known": False,
            },
            explanation=(
                "Uses the frozen abnormal-movement investigation as context; the observed "
                "move direction is never treated as proof of its cause."
            ),
        ),
        _context_calculator(
            calculator_id="news_source_authority_timestamp",
            evidence_ref="news_source_rows_evidence",
            known=bool(mechanism["stories"]),
            observation={
                "news_state": mechanism["news_state"],
                "credible_story_n": mechanism["credible_story_n"],
                "strongest_source_authority": mechanism["strongest_source_authority"],
                "unique_story_n": mechanism["duplicate_collapse"]["unique_story_n"],
            },
            explanation=(
                "News is usable only when publication/observation timestamps are at or before "
                "the decision as-of. Source authority is explicit rather than inferred silently."
            ),
        ),
        _context_calculator(
            calculator_id="news_duplicate_story_collapse",
            evidence_ref="news_mechanism_resolution_evidence",
            known=True,
            observation=mechanism["duplicate_collapse"],
            explanation=(
                "Syndicated/duplicate stories are collapsed before evidence agreement is assessed "
                "so repeated copies cannot manufacture confirmation."
            ),
        ),
        _context_calculator(
            calculator_id="news_evidence_agreement",
            evidence_ref="news_mechanism_resolution_evidence",
            known=mechanism["state"] != "unknown",
            observation={
                "state": mechanism["state"],
                "agreement_state": mechanism["agreement_state"],
                "agreement": mechanism["agreement"],
                "scheduled_event_state": mechanism["scheduled_event_state"],
                "leading_mechanism_tag": mechanism["leading_mechanism_tag"],
            },
            explanation=(
                "Scheduled-event and credible-news evidence may agree, disagree or remain unknown. "
                "Disagreement is preserved rather than resolved by invention."
            ),
        ),
        _context_calculator(
            calculator_id="news_causality_boundary",
            evidence_ref="news_source_contract_evidence",
            known=True,
            observation={
                "causal_claim_from_single_headline_allowed": False,
                "unsupported_narratives_used_as_evidence": False,
                "news_directional_vote_allowed": False,
                "live_money_execution_allowed": False,
            },
            explanation=(
                "News explains possible mechanisms only. A headline cannot create causality, "
                "a directional vote, live weight or live-money authority."
            ),
            dependency_family="data_quality",
        ),
    ]

    dimensions = global_environment["learning_dimensions"]
    move_snapshot = movement_investigation.get("move_snapshot")
    move_snapshot = move_snapshot if isinstance(move_snapshot, Mapping) else {}
    mini_environment = {
        "session": dimensions["session"],
        "session_phase": dimensions["session_phase"],
        "volatility_state": dimensions["volatility_state"],
        "event_timing_state": dimensions["event_timing_state"],
        "movement_state": str(
            move_snapshot.get("five_minute_distribution_state")
            or movement_investigation.get("state")
            or "unknown"
        ),
        "news_state": mechanism["news_state"],
        "scheduled_event_state": mechanism["scheduled_event_state"],
        "agreement_state": mechanism["agreement_state"],
        "leading_mechanism_tag": mechanism["leading_mechanism_tag"],
        "source_authority": mechanism["strongest_source_authority"],
    }

    contradiction_rows = []
    if mechanism["agreement"]["disagreement_unresolved"]:
        contradiction_rows.append(
            {
                "text": (
                    "Credible evidence sources disagree on the mechanism; Build 18 leaves "
                    "the disagreement unresolved."
                ),
                "source_refs": ["calc:news_evidence_agreement"],
            }
        )
    if mechanism["unsupported_narratives"]:
        contradiction_rows.append(
            {
                "text": (
                    "One or more narrative claims have no admitted source evidence and are "
                    "not used to explain the move."
                ),
                "source_refs": ["calc:news_causality_boundary"],
            }
        )

    packet = build_expert_gate_packet(
        gate_id=NEWS_MOVEMENT_MECHANISM_GATE_ID,
        gate_version=NEWS_MOVEMENT_MECHANISM_EXPERT_VERSION,
        gate_mode="context_only",
        dependency_family="news_mechanism",
        target_horizon_minutes=NEWS_MOVEMENT_MECHANISM_TARGET_HORIZON_MINUTES,
        as_of_utc=as_of,
        global_environment=global_environment,
        mini_environment=mini_environment,
        evidence_inputs=evidence_inputs,
        subcalculators=calculators,
        conclusion="context_only",
        internal_conviction=None,
        explanation_parts=(
            {
                "text": (
                    f"Movement mechanism state={mechanism['state']}; "
                    f"agreement={mechanism['agreement_state']}; "
                    f"news={mechanism['news_state']}."
                ),
                "source_refs": [
                    "calc:news_abnormal_move_trigger",
                    "calc:news_source_authority_timestamp",
                    "calc:news_evidence_agreement",
                ],
            },
            {
                "text": (
                    "Duplicate stories are collapsed and unsupported narratives are excluded. "
                    "News context never creates an automatic directional vote."
                ),
                "source_refs": [
                    "calc:news_duplicate_story_collapse",
                    "calc:news_causality_boundary",
                ],
            },
        ),
        contradictions=contradiction_rows,
    )
    if not verify_expert_gate_packet(packet):
        raise ValueError("constructed News/Movement Mechanism packet failed Build-2 verification")

    scopes = build_trust_scopes(
        packet=packet,
        reduced_contexts=NEWS_MOVEMENT_MECHANISM_TRUST_REDUCED_CONTEXTS,
    )
    rows_by_subject = trust_score_rows_by_subject or {}
    profiles = {
        key: select_conditional_trust(
            score_rows=rows_by_subject.get(key, ()),
            scopes=scopes,
        )
        for key in _subject_keys(packet)
    }
    trust_envelope = build_trust_envelope(
        packet=packet,
        profiles_by_subject=profiles,
    )

    return {
        "expert_version": NEWS_MOVEMENT_MECHANISM_EXPERT_VERSION,
        "expert_packet": packet,
        "mechanism_resolution": mechanism,
        "source_contract": source_contract,
        "trust_scopes": scopes,
        "trust_envelope": trust_envelope,
        "context_only": True,
        "directional_authority": False,
        "predictive_edge_claimed": False,
        "cause_known": False,
        "future_values_used": False,
        "live_money_execution_allowed": False,
    }


__all__ = [
    "FINNHUB_API_KEY_ENV",
    "FINNHUB_NEWS_ADAPTER_VERSION",
    "FINNHUB_NEWS_CATEGORIES",
    "FinnhubNewsClient",
    "NEWS_MOVEMENT_MECHANISM_EXPERT_VERSION",
    "NEWS_MOVEMENT_MECHANISM_GATE_ID",
    "NEWS_MOVEMENT_MECHANISM_TARGET_HORIZON_MINUTES",
    "NEWS_MOVEMENT_MECHANISM_TRUST_REDUCED_CONTEXTS",
    "NEWS_SOURCE_CONTRACT_VERSION",
    "build_news_movement_mechanism_expert",
    "collapse_duplicate_news",
    "news_source_contract",
    "normalize_finnhub_market_news",
    "resolve_news_movement_mechanism",
]
