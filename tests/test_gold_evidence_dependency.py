from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aidy.gold_evidence_dependency import (
    FAMILY_PARENT,
    apply_dependency_adjustments,
    build_evidence_dependency_engine,
    evidence_family_graph,
    rolling_dependency_diagnostics,
    verify_evidence_dependency_engine,
    verify_evidence_family_graph,
    verify_rolling_dependency_diagnostics,
)

AS_OF = datetime(2026, 9, 21, 12, tzinfo=UTC)


def _signal(
    signal_id: str,
    *,
    family: str,
    vote: str = "bullish",
    group: str | None = None,
    evidence: str | None = None,
    weight: str = "1",
    role: str = "directional",
    state: str = "known",
) -> dict:
    return {
        "signal_id": signal_id,
        "gate_id": signal_id.split(":", 1)[0],
        "calculator_id": signal_id.split(":", 1)[-1],
        "dependency_family": family,
        "parent_family": FAMILY_PARENT[family],
        "correlation_group": group or f"group:{signal_id}",
        "role": role,
        "state": state,
        "vote": vote,
        "raw_weight": weight,
        "evidence_identity": evidence or f"evidence:{signal_id}",
    }


def _history(
    signal_ids: list[str],
    *,
    cycles: int = 20,
    correlated: bool = True,
) -> list[dict]:
    rows = []
    for index in range(cycles):
        base = "bullish" if index % 2 == 0 else "bearish"
        values = {}
        for offset, signal_id in enumerate(signal_ids):
            if correlated:
                values[signal_id] = base
            else:
                values[signal_id] = (
                    base if (index + offset * 3) % 5 < 3 else
                    ("bearish" if base == "bullish" else "bullish")
                )
        rows.append(
            {
                "observed_at_utc": (
                    AS_OF - timedelta(minutes=15 * (cycles - index))
                ).isoformat(),
                "signals": values,
            }
        )
    return rows


def _adjust(signals: list[dict], history: list[dict] | None = None) -> dict:
    diagnostics = rolling_dependency_diagnostics(
        signals=signals,
        historical_rows=history or [],
        as_of_utc=AS_OF,
    )
    return apply_dependency_adjustments(
        signals=signals,
        diagnostics=diagnostics,
    )


def _by_id(result: dict) -> dict[str, dict]:
    return {
        item["signal_id"]: item
        for item in result["adjusted_signals"]
    }


def test_build20_family_graph_declares_price_macro_and_independent_roots() -> None:
    graph = evidence_family_graph()

    assert verify_evidence_family_graph(graph)
    assert FAMILY_PARENT["structure"] == "price_action"
    assert FAMILY_PARENT["momentum"] == "price_action"
    assert FAMILY_PARENT["location"] == "price_action"
    assert FAMILY_PARENT["liquidity"] == "liquidity_mechanism"
    assert FAMILY_PARENT["event"] == "macro_information"
    assert FAMILY_PARENT["rates_usd"] == "macro_information"
    assert FAMILY_PARENT["news_mechanism"] == "macro_information"
    assert graph["future_values_used"] is False
    assert graph["outcomes_used"] is False


def test_build20_exact_duplicate_signal_adds_zero_increment() -> None:
    signals = [
        _signal(
            "m5:trend",
            family="structure",
            evidence="same-price-evidence",
        ),
        _signal(
            "copy:trend",
            family="structure",
            evidence="same-price-evidence",
        ),
    ]
    result = _adjust(signals)
    rows = _by_id(result)

    effective = sorted(
        Decimal(item["effective_weight"])
        for item in rows.values()
    )
    assert effective == [Decimal("0.000000"), Decimal("1.000000")]
    assert sum(
        item["exact_duplicate_increment_zero"] is True
        for item in rows.values()
    ) == 1


def test_build20_removing_exact_duplicate_does_not_change_research_score() -> None:
    original = [
        _signal(
            "structure:a",
            family="structure",
            vote="bullish",
            evidence="shared-evidence",
            weight="0.8",
        ),
        _signal(
            "structure:duplicate",
            family="structure",
            vote="bullish",
            evidence="shared-evidence",
            weight="0.8",
        ),
        _signal(
            "liquidity:a",
            family="liquidity",
            vote="bearish",
            weight="0.4",
        ),
    ]
    without_duplicate = [original[0], original[2]]

    left = _adjust(original)
    right = _adjust(without_duplicate)

    assert (
        left["dependency_adjusted_research_score"]
        == right["dependency_adjusted_research_score"]
    )
    assert (
        left["directional_signed_weight"]
        == right["directional_signed_weight"]
    )
    assert (
        left["directional_effective_weight_total"]
        == right["directional_effective_weight_total"]
    )


def test_build20_highly_correlated_m5_m15_momentum_are_damped() -> None:
    signals = [
        _signal("m5:structure", family="structure", group="m5_path"),
        _signal("m15:structure", family="structure", group="m15_path"),
        _signal("momentum:impulse", family="momentum", group="momentum_path"),
    ]
    history = _history([item["signal_id"] for item in signals], cycles=20)
    diagnostics = rolling_dependency_diagnostics(
        signals=signals,
        historical_rows=history,
        as_of_utc=AS_OF,
    )
    result = apply_dependency_adjustments(
        signals=signals,
        diagnostics=diagnostics,
    )
    rows = _by_id(result)

    assert all(
        item["state"] == "high_dependency"
        for item in diagnostics["pairs"]
    )
    effective = sorted(
        Decimal(item["effective_weight"])
        for item in rows.values()
    )
    assert effective == [
        Decimal("0.250000"),
        Decimal("0.250000"),
        Decimal("1.000000"),
    ]
    assert result["directional_effective_weight_total"] == "1.500000"


def test_build20_same_correlation_group_is_damped_without_empirical_history() -> None:
    signals = [
        _signal(
            "m15:latest_momentum",
            family="momentum",
            group="m15_latest_bar_momentum",
        ),
        _signal(
            "m15:candle_pressure",
            family="momentum",
            group="m15_latest_bar_momentum",
        ),
    ]
    result = _adjust(signals)
    rows = _by_id(result)

    assert sorted(
        Decimal(item["effective_weight"])
        for item in rows.values()
    ) == [Decimal("0.350000"), Decimal("1.000000")]
    assert any(
        "same_correlation_group_damped" in item["adjustment_reasons"]
        for item in rows.values()
    )


def test_build20_parent_root_incremental_cap_stops_five_price_votes() -> None:
    signals = [
        _signal("m5:a", family="structure"),
        _signal("m15:a", family="structure"),
        _signal("h1:a", family="structure"),
        _signal("momentum:a", family="momentum"),
        _signal("location:a", family="location"),
    ]
    result = _adjust(signals)

    assert result["directional_effective_weight_total"] == "1.500000"
    assert sum(
        "parent_root_incremental_cap" in item["adjustment_reasons"]
        for item in result["adjusted_signals"]
    ) == 4


def test_build20_independent_liquidity_macro_structure_remain_distinct() -> None:
    signals = [
        _signal("m15:structure", family="structure"),
        _signal("liquidity:reclaim", family="liquidity"),
        _signal("macro:event", family="event"),
    ]
    result = _adjust(signals)
    rows = _by_id(result)
    bonus = result["independent_agreement_bonus"]

    assert all(
        Decimal(item["effective_weight"]) == Decimal("1.000000")
        for item in rows.values()
    )
    assert bonus["state"] == "justified"
    assert bonus["direction"] == "bullish"
    assert bonus["independent_root_count"] == 3
    assert bonus["independent_roots"] == [
        "liquidity_mechanism",
        "macro_information",
        "price_action",
    ]
    assert bonus["bonus_multiplier"] == "1.050000"


def test_build20_two_roots_do_not_earn_independence_bonus() -> None:
    result = _adjust(
        [
            _signal("structure:a", family="structure"),
            _signal("liquidity:a", family="liquidity"),
        ]
    )

    assert result["independent_agreement_bonus"]["state"] == "not_justified"
    assert result["independent_agreement_bonus"]["bonus_multiplier"] == "1.000000"


def test_build20_future_history_rows_are_excluded_from_correlation() -> None:
    signals = [
        _signal("m5:a", family="structure"),
        _signal("m15:a", family="structure"),
    ]
    past = _history(["m5:a", "m15:a"], cycles=12)
    future = [
        {
            "observed_at_utc": (AS_OF + timedelta(minutes=15 * index)).isoformat(),
            "signals": {
                "m5:a": "bullish",
                "m15:a": "bearish",
            },
        }
        for index in range(1, 20)
    ]
    diagnostics = rolling_dependency_diagnostics(
        signals=signals,
        historical_rows=past + future,
        as_of_utc=AS_OF,
    )

    assert diagnostics["eligible_historical_row_n"] == 12
    assert diagnostics["pairs"][0]["state"] == "high_dependency"
    assert diagnostics["pairs"][0]["correlation"] == "1.000000"
    assert diagnostics["pairs"][0]["future_rows_used"] is False


def test_build20_historical_outcome_fields_are_rejected() -> None:
    signals = [
        _signal("m5:a", family="structure"),
        _signal("m15:a", family="structure"),
    ]
    rows = _history(["m5:a", "m15:a"], cycles=12)
    rows[0]["outcome"] = "winner"

    with pytest.raises(ValueError, match="hindsight"):
        rolling_dependency_diagnostics(
            signals=signals,
            historical_rows=rows,
            as_of_utc=AS_OF,
        )


def test_build20_insufficient_history_does_not_fake_correlation() -> None:
    signals = [
        _signal("m5:a", family="structure"),
        _signal("m15:a", family="structure"),
    ]
    diagnostics = rolling_dependency_diagnostics(
        signals=signals,
        historical_rows=_history(["m5:a", "m15:a"], cycles=5),
        as_of_utc=AS_OF,
    )

    assert diagnostics["pairs"][0]["sample_n"] == 5
    assert diagnostics["pairs"][0]["state"] == "insufficient"
    assert diagnostics["pairs"][0]["correlation"] is None


def test_build20_context_only_signal_gets_no_directional_weight() -> None:
    signals = [
        _signal(
            "news:context",
            family="news_mechanism",
            vote="context_only",
            role="context_only",
        ),
        _signal("structure:a", family="structure"),
    ]
    result = _adjust(signals)
    rows = _by_id(result)

    assert rows["news:context"]["eligible_for_directional_weight"] is False
    assert rows["news:context"]["effective_weight"] == "0.000000"
    assert rows["structure:a"]["effective_weight"] == "1.000000"


def test_build20_opposite_votes_from_same_evidence_are_not_silent_duplicates() -> None:
    signals = [
        _signal(
            "structure:a",
            family="structure",
            vote="bullish",
            evidence="same-evidence",
        ),
        _signal(
            "structure:b",
            family="structure",
            vote="bearish",
            evidence="same-evidence",
        ),
    ]
    result = _adjust(signals)
    rows = _by_id(result)

    assert all(
        item["exact_duplicate_increment_zero"] is False
        for item in rows.values()
    )
    assert result["dependency_adjusted_research_score"] == "0.000000"


def test_build20_is_deterministic_under_signal_and_history_reordering() -> None:
    signals = [
        _signal("m5:a", family="structure"),
        _signal("m15:a", family="structure"),
        _signal("momentum:a", family="momentum"),
        _signal("liquidity:a", family="liquidity"),
    ]
    history = _history([item["signal_id"] for item in signals], cycles=20)

    left = build_evidence_dependency_engine(
        signals=signals,
        historical_rows=history,
        as_of_utc=AS_OF,
    )
    right = build_evidence_dependency_engine(
        signals=list(reversed(signals)),
        historical_rows=list(reversed(history)),
        as_of_utc=AS_OF,
    )

    assert left["engine_digest"] == right["engine_digest"]
    assert left == right


def test_build20_engine_packet_is_verified_and_has_no_authority() -> None:
    signals = [
        _signal("structure:a", family="structure"),
        _signal("liquidity:a", family="liquidity"),
        _signal("macro:a", family="event"),
    ]
    engine = build_evidence_dependency_engine(
        signals=signals,
        historical_rows=[],
        as_of_utc=AS_OF,
    )

    assert verify_evidence_dependency_engine(engine)
    assert verify_rolling_dependency_diagnostics(engine["rolling_diagnostics"])
    assert engine["exact_duplicates_do_not_add_weight"] is True
    assert engine["same_correlation_group_damped"] is True
    assert engine["highly_correlated_same_parent_damped"] is True
    assert engine["outcomes_used"] is False
    assert engine["future_values_used"] is False
    assert engine["formal_forward_evidence_created"] is False
    assert engine["live_money_execution_allowed"] is False


def test_build20_tampering_breaks_engine_digest() -> None:
    engine = build_evidence_dependency_engine(
        signals=[_signal("structure:a", family="structure")],
        historical_rows=[],
        as_of_utc=AS_OF,
    )
    engine["parent_incremental_cap_fraction"] = "0.99"

    assert not verify_evidence_dependency_engine(engine)
