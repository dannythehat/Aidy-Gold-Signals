from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from aidy.no_trade_counterfactual import (
    build_no_trade_counterfactual,
    build_setup_eligibility_evidence,
)

ANCHOR = datetime(2025, 1, 6, 12, 0, tzinfo=UTC)
CONTEXT_HASH = "a" * 64
REGIME_DIGEST = "b" * 64


def _row(
    minute: int,
    *,
    high: str = "2001",
    low: str = "1999",
    close: str = "2000",
) -> dict[str, object]:
    return {
        "research_identity": f"day14-example-{minute:04d}-{high}-{low}-{close}",
        "provenance_class": "retrospective_history",
        "pit_eligible": False,
        "symbol": "XAUUSD",
        "timeframe": "M1",
        "open_time_utc": (ANCHOR + timedelta(minutes=minute)).isoformat(),
        "open": "2000",
        "high": high,
        "low": low,
        "close": close,
        "source": "fixture",
        "source_file_sha256": "c" * 64,
        "source_payload_sha256": "d" * 64,
    }


def _rows() -> list[dict[str, object]]:
    rows = [_row(minute) for minute in range(1, 241)]
    rows[9] = _row(10, high="2006", low="1999", close="2004")
    rows[19] = _row(20, high="2011", low="2000", close="2008")
    return rows


def _evidence(setup_state: str) -> dict[str, object]:
    if setup_state == "present":
        return build_setup_eligibility_evidence(
            as_of=ANCHOR,
            taxonomy_version="example_taxonomy_v1",
            detector_version="example_detector_v1",
            source_context_hash=CONTEXT_HASH,
            source_regime_digest=REGIME_DIGEST,
            setup_state="present",
            risk_state="valid",
            candidate_setup_ids=("example_long_setup",),
            direction="long",
            trade_spec={
                "entry_type": "market",
                "entry": "2000",
                "stop_loss": "1995",
                "targets": ["2005", "2010"],
            },
            reason_codes=("fixture_valid_setup",),
        )
    if setup_state == "absent":
        return build_setup_eligibility_evidence(
            as_of=ANCHOR,
            taxonomy_version="example_taxonomy_v1",
            detector_version="example_detector_v1",
            source_context_hash=CONTEXT_HASH,
            source_regime_digest=REGIME_DIGEST,
            setup_state="absent",
            risk_state="not_applicable",
            reason_codes=("fixture_no_setup",),
        )
    return build_setup_eligibility_evidence(
        as_of=ANCHOR,
        taxonomy_version="example_taxonomy_v1",
        detector_version="example_detector_v1",
        source_context_hash=CONTEXT_HASH,
        source_regime_digest=REGIME_DIGEST,
        setup_state="unknown",
        risk_state="unknown",
        reason_codes=("fixture_setup_unknown",),
    )


def main() -> None:
    rows = _rows()
    examples = []
    for setup_state in ("present", "absent", "unknown"):
        record = build_no_trade_counterfactual(
            decision_id=f"example-{setup_state}",
            decision_time=ANCHOR,
            anchor_price="2000",
            setup_evidence=_evidence(setup_state),
            research_rows=rows,
        )
        examples.append(
            {
                "decision_id": record["decision_id"],
                "setup_state": setup_state,
                "primary_classification": record["primary_classification"],
                "primary_reason_code": record["primary_reason_code"],
                "path_class_240m": record["path_bundle"]["labels"][-1]["path_class"],
                "counterfactual_digest": record["counterfactual_digest"],
            }
        )

    print(
        json.dumps(
            {
                "ok": True,
                "evaluation_only": True,
                "future_derived": True,
                "pit_eligible": False,
                "directional_movement_alone_sufficient": False,
                "examples": examples,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
