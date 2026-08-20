from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from aidy.context_packet import build_context_packet
from aidy.feature_engine import build_feature_packet
from aidy.no_trade_counterfactual import (
    COUNTERFACTUAL_VERSION,
    HORIZONS_MINUTES,
    RESEARCH_NO_TRADE_COUNTERFACTUALS,
    SETUP_EVIDENCE_VERSION,
    build_no_trade_counterfactual,
    build_setup_eligibility_evidence,
    compute_setup_evidence_digest,
    no_trade_counterfactual_distribution,
    no_trade_counterfactual_storage_row,
    verify_no_trade_counterfactual_digest,
    verify_setup_evidence_digest,
)

ANCHOR = datetime(2025, 1, 6, 12, 0, tzinfo=UTC)
ANCHOR_PRICE = "2000"
CONTEXT_HASH = "a" * 64
REGIME_DIGEST = "b" * 64


def _row(
    minute: int,
    *,
    open_price: str = "2000",
    high: str = "2001",
    low: str = "1999",
    close: str = "2000",
) -> dict[str, object]:
    return {
        "research_identity": f"research-{minute:04d}-{open_price}-{high}-{low}-{close}",
        "provenance_class": "retrospective_history",
        "pit_eligible": False,
        "symbol": "XAUUSD",
        "timeframe": "M1",
        "open_time_utc": (ANCHOR + timedelta(minutes=minute)).isoformat(),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "source": "histdata",
        "source_file_sha256": "c" * 64,
        "source_payload_sha256": "d" * 64,
    }


def _quiet_rows(minutes: int = 240) -> list[dict[str, object]]:
    return [_row(minute) for minute in range(1, minutes + 1)]


def _target_before_stop_rows() -> list[dict[str, object]]:
    rows = _quiet_rows()
    rows[9] = _row(10, high="2006", low="1999", close="2004")
    rows[19] = _row(20, open_price="2004", high="2011", low="2000", close="2008")
    rows[-1] = _row(240, open_price="2008", high="2009", low="2003", close="2007")
    return rows


def _stop_before_target_rows() -> list[dict[str, object]]:
    rows = _quiet_rows()
    rows[4] = _row(5, high="2001", low="1994", close="1996")
    rows[29] = _row(30, open_price="1996", high="2006", low="1995", close="2004")
    return rows


def _same_bar_rows() -> list[dict[str, object]]:
    rows = _quiet_rows()
    rows[9] = _row(10, high="2006", low="1994", close="2000")
    return rows


def _short_target_rows() -> list[dict[str, object]]:
    rows = _quiet_rows()
    rows[9] = _row(10, high="2001", low="1994", close="1996")
    rows[19] = _row(20, open_price="1996", high="2000", low="1989", close="1992")
    return rows


def _trade_spec(
    *,
    direction: str = "long",
    entry: str = "2000",
) -> dict[str, object]:
    if direction == "long":
        return {
            "entry_type": "market",
            "entry": entry,
            "stop_loss": "1995",
            "targets": ["2005", "2010"],
        }
    return {
        "entry_type": "market",
        "entry": entry,
        "stop_loss": "2005",
        "targets": ["1995", "1990"],
    }


def _evidence(
    *,
    setup_state: str = "present",
    risk_state: str = "valid",
    direction: str | None = "long",
    trade_spec: dict[str, object] | None = None,
    setup_ids: tuple[str, ...] = ("breakout_v1",),
    as_of: datetime = ANCHOR,
) -> dict[str, object]:
    if trade_spec is None and setup_state == "present" and risk_state == "valid":
        trade_spec = _trade_spec(direction=direction or "long")
    if setup_state == "absent":
        direction = None
        risk_state = "not_applicable"
        trade_spec = None
        setup_ids = ()
    elif setup_state in {"unknown", "ambiguous"}:
        direction = None
        risk_state = "unknown"
        trade_spec = None
        if setup_state == "unknown":
            setup_ids = ()
        elif len(setup_ids) < 2:
            setup_ids = ("candidate_a", "candidate_b")

    return build_setup_eligibility_evidence(
        as_of=as_of,
        taxonomy_version="fixture_taxonomy_v1",
        detector_version="fixture_detector_v1",
        source_context_hash=CONTEXT_HASH,
        source_regime_digest=REGIME_DIGEST,
        setup_state=setup_state,
        risk_state=risk_state,
        candidate_setup_ids=setup_ids,
        direction=direction,
        trade_spec=trade_spec,
        reason_codes=("fixture_reason_b", "fixture_reason_a"),
    )


def _record(
    rows: list[dict[str, object]],
    *,
    evidence: dict[str, object] | None = None,
    decision_id: str = "decision-1",
) -> dict[str, object]:
    return build_no_trade_counterfactual(
        decision_id=decision_id,
        decision_time=ANCHOR,
        anchor_price=ANCHOR_PRICE,
        setup_evidence=_evidence() if evidence is None else evidence,
        research_rows=rows,
    )


def test_setup_evidence_is_versioned_pit_safe_and_deterministic() -> None:
    first = _evidence(setup_ids=("z", "a"))
    second = _evidence(setup_ids=("a", "z"))
    assert first == second
    assert first["evidence_version"] == SETUP_EVIDENCE_VERSION
    assert first["pit_eligible"] is True
    assert first["future_derived"] is False
    assert first["decision_input_allowed"] is True
    assert first["candidate_setup_ids"] == ["a", "z"]
    assert first["reason_codes"] == ["fixture_reason_a", "fixture_reason_b"]
    assert verify_setup_evidence_digest(first) is True


def test_directional_move_after_absent_setup_is_good_restraint_not_a_miss() -> None:
    record = _record(
        _target_before_stop_rows(),
        evidence=_evidence(setup_state="absent"),
    )
    assert record["path_bundle"]["labels"][-1]["path_class"] != "quiet"
    assert record["primary_classification"] == "good_restraint"
    assert record["primary_reason_code"] == "no_valid_setup_at_decision"


def test_directional_move_with_unknown_setup_is_indeterminate_not_a_miss() -> None:
    record = _record(
        _target_before_stop_rows(),
        evidence=_evidence(setup_state="unknown"),
    )
    assert record["primary_classification"] == "indeterminate"
    assert record["primary_reason_code"] == "setup_evidence_unknown"


def test_ambiguous_setup_evidence_remains_indeterminate() -> None:
    record = _record(
        _target_before_stop_rows(),
        evidence=_evidence(
            setup_state="ambiguous",
            setup_ids=("long_breakout", "short_reversal"),
        ),
    )
    assert record["primary_classification"] == "indeterminate"
    assert record["primary_reason_code"] == "setup_evidence_ambiguous"


def test_valid_long_setup_target_before_stop_is_missed_opportunity() -> None:
    record = _record(_target_before_stop_rows())
    assert record["primary_classification"] == "missed_opportunity"
    assert record["primary_reason_code"] == "valid_setup_target_before_stop"
    assert record["trade_outcome_bundle"]["outcomes"][-1]["outcome_state"] == "target_only"


def test_valid_short_setup_target_before_stop_is_missed_opportunity() -> None:
    evidence = _evidence(
        direction="short",
        trade_spec=_trade_spec(direction="short"),
        setup_ids=("short_breakdown_v1",),
    )
    record = _record(_short_target_rows(), evidence=evidence)
    assert record["primary_classification"] == "missed_opportunity"
    assert record["trade_outcome_bundle"]["trade_spec"]["direction"] == "short"


def test_valid_setup_stop_before_target_is_good_restraint() -> None:
    record = _record(_stop_before_target_rows())
    assert record["primary_classification"] == "good_restraint"
    assert record["primary_reason_code"] == "valid_setup_stop_before_target"
    assert record["trade_outcome_bundle"]["outcomes"][-1]["outcome_state"] == (
        "stop_before_any_target"
    )


def test_same_bar_stop_target_order_is_indeterminate() -> None:
    record = _record(_same_bar_rows())
    assert record["primary_classification"] == "indeterminate"
    assert record["primary_reason_code"] == "stop_target_same_bar_order_unknown"
    assert record["trade_outcome_bundle"]["outcomes"][-1]["outcome_state"] == (
        "same_bar_order_unknown"
    )


def test_valid_setup_without_decisive_level_outcome_is_indeterminate() -> None:
    record = _record(_quiet_rows())
    assert record["primary_classification"] == "indeterminate"
    assert record["primary_reason_code"] == "valid_setup_no_decisive_level_outcome"
    assert record["trade_outcome_bundle"]["outcomes"][-1]["outcome_state"] == "neither"


def test_incomplete_primary_horizon_fails_closed_to_indeterminate() -> None:
    rows = [
        row
        for row in _target_before_stop_rows()
        if row["open_time_utc"] != (ANCHOR + timedelta(minutes=120)).isoformat()
    ]
    record = _record(rows)
    assert record["primary_classification"] == "indeterminate"
    assert record["primary_reason_code"] == "future_outcome_incomplete"
    assert record["path_bundle"]["labels"][-1]["coverage_state"] == "incomplete"


def test_present_setup_with_invalid_risk_is_good_restraint_even_after_move() -> None:
    evidence = _evidence(
        risk_state="invalid",
        trade_spec=None,
    )
    record = _record(_target_before_stop_rows(), evidence=evidence)
    assert record["trade_outcome_bundle"] is None
    assert record["primary_classification"] == "good_restraint"
    assert record["primary_reason_code"] == "risk_invalid_at_decision"


def test_present_setup_with_unknown_risk_is_indeterminate() -> None:
    evidence = _evidence(
        risk_state="unknown",
        trade_spec=None,
    )
    record = _record(_target_before_stop_rows(), evidence=evidence)
    assert record["primary_classification"] == "indeterminate"
    assert record["primary_reason_code"] == "risk_evidence_unknown"


def test_setup_evidence_timestamp_and_market_entry_are_strict() -> None:
    with pytest.raises(ValueError, match="exactly match"):
        _record(
            _quiet_rows(),
            evidence=_evidence(as_of=ANCHOR + timedelta(minutes=1)),
        )

    mismatched_entry = _evidence(
        trade_spec=_trade_spec(entry="2001"),
    )
    with pytest.raises(ValueError, match="must equal anchor_price"):
        _record(_quiet_rows(), evidence=mismatched_entry)

    pending = _trade_spec()
    pending["entry_type"] = "limit"
    with pytest.raises(ValueError, match="market-entry"):
        _evidence(trade_spec=pending)


def test_future_fields_cannot_be_injected_even_with_recomputed_evidence_digest() -> None:
    evidence = _evidence()
    evidence["future_return"] = "100"
    evidence["evidence_digest"] = compute_setup_evidence_digest(evidence)
    with pytest.raises(ValueError, match="unsupported or missing"):
        _record(_target_before_stop_rows(), evidence=evidence)


def test_record_has_all_three_horizons_and_hard_future_only_boundary() -> None:
    record = _record(_target_before_stop_rows())
    assert record["counterfactual_version"] == COUNTERFACTUAL_VERSION
    assert record["evaluation_only"] is True
    assert record["future_derived"] is True
    assert record["pit_eligible"] is False
    assert record["decision_input_allowed"] is False
    assert record["realized_pnl_included"] is False
    assert record["directional_movement_alone_sufficient"] is False
    assert [item["horizon_minutes"] for item in record["horizon_assessments"]] == list(
        HORIZONS_MINUTES
    )
    assert verify_no_trade_counterfactual_digest(record) is True


def test_same_evidence_is_deterministic_under_reordered_research_rows() -> None:
    rows = _target_before_stop_rows()
    first = _record(rows)
    second = _record(list(reversed(rows)))
    assert first == second


def test_storage_contract_is_separate_from_pit_and_day10_rejects_record() -> None:
    record = _record(_target_before_stop_rows())
    fields = {field.name for field in RESEARCH_NO_TRADE_COUNTERFACTUALS.fields}
    assert RESEARCH_NO_TRADE_COUNTERFACTUALS.name == "research_no_trade_counterfactuals"
    assert "first_observed_at" not in fields
    stored = no_trade_counterfactual_storage_row(record)
    assert stored["pit_eligible"] is False
    assert stored["decision_input_allowed"] is False

    feature = build_feature_packet(
        as_of=ANCHOR,
        symbol="XAUUSD",
        candle_rows=[],
        mode="pit",
        snapshot=None,
    )
    with pytest.raises(ValueError, match="Unsupported AIDY signal-state fields"):
        build_context_packet(
            as_of=ANCHOR,
            symbol="XAUUSD",
            feature_packet=feature,
            event_rows=[],
            macro_evidence_state="known",
            cross_market_rows=[],
            aidy_signal_state=record,
        )


def test_distribution_preserves_three_way_labels_and_rejects_tampering() -> None:
    missed = _record(_target_before_stop_rows(), decision_id="missed")
    restraint = _record(
        _target_before_stop_rows(),
        evidence=_evidence(setup_state="absent"),
        decision_id="restraint",
    )
    unknown = _record(
        _target_before_stop_rows(),
        evidence=_evidence(setup_state="unknown"),
        decision_id="unknown",
    )
    distribution = no_trade_counterfactual_distribution([unknown, restraint, missed])
    assert distribution["primary_classification_counts"] == {
        "good_restraint": 1,
        "indeterminate": 1,
        "missed_opportunity": 1,
    }
    assert distribution["directional_movement_alone_sufficient"] is False
    assert distribution["missed_opportunity_requires_valid_setup_and_risk"] is True

    tampered = deepcopy(missed)
    tampered["primary_classification"] = "good_restraint"
    assert verify_no_trade_counterfactual_digest(tampered) is False
    with pytest.raises(ValueError, match="invalid Day 14"):
        no_trade_counterfactual_distribution([tampered])
    with pytest.raises(ValueError, match="valid Day 14"):
        no_trade_counterfactual_storage_row(tampered)
