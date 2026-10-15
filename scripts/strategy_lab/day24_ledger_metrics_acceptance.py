"""Day24 executable acceptance: two real SQLite journals, same pinned known answer.

Values are INTERNAL synthetic engineering answers, not historical returns.
"""
from __future__ import annotations

import json
import tempfile
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from aidy.strategy_lab_deterministic_replay import canonical_events, replay_cash_events
from aidy.strategy_lab_risk_metrics import compute_ledger_metrics

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "research/strategy_lab/fixtures/day24_known_answer_journal.json"
OUT = ROOT / "artifacts/strategy_lab/day24_ledger_metrics_acceptance.json"


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    try:
        original = SOURCE.read_bytes()
        frozen = sha256(original).hexdigest()
        source = json.loads(original.decode())
        if (set(source) != {"schema", "source_type", "broker_source_sha256",
                            "ounces_per_lot", "events"}
                or source["schema"] != "aidy.day24.known_answer.v1"
                or source["source_type"] != "INTERNAL_SYNTHETIC_RESEARCH_FIXTURE_NOT_TRADING"):
            raise ValueError("not the frozen internal source manifest")
        events, digest = source["events"], source["broker_source_sha256"]
        ounces = Decimal(source["ounces_per_lot"])
        manifest_sha = sha256(canonical_events(events, digest)).hexdigest()
        with tempfile.TemporaryDirectory(prefix="aidy-day24-") as directory:
            reports = []
            receipts = []
            for index in (1, 2):
                path = Path(directory) / f"journal_{index}.sqlite3"
                result = replay_cash_events(
                    path, events, source_sha256=digest,
                    ounces_per_lot=ounces, expected_manifest_sha256=manifest_sha,
                )
                assert result.idempotent_events == 0
                duplicate = replay_cash_events(
                    path, events, source_sha256=digest,
                    ounces_per_lot=ounces, expected_manifest_sha256=manifest_sha,
                )
                if duplicate.idempotent_events != len(events):
                    raise ValueError("source identical replay not idempotent")
                report = compute_ledger_metrics(
                    path, source_sha256=digest, ounces_per_lot=ounces,
                    expected_tip_sha256=result.journal_tip_sha256,
                )
                reports.append(report)
                receipts.append(result)
            if reports[0] != reports[1] or receipts[0].journal_tip_sha256 != receipts[1].journal_tip_sha256:
                raise ValueError("two independent SQLite replay reports diverged")
            report = reports[0]
            # Independent arithmetic, fixed before actual CI. Net per trade:
            # $10-$0.50, -$5-$0.50, $15-$0.50, -$5-$0.50.
            expected = [
                Decimal("9.50"), Decimal("-5.50"), Decimal("14.50"),
                Decimal("-5.50"),
            ]
            if ([t.net_usd for t in report.trades] != expected
                    or report.realized_gross_usd != Decimal("15.00")
                    or report.transaction_costs_usd != Decimal("-2.00")
                    or report.net_profit_usd != Decimal("13.00")
                    or report.final_cash_usd != Decimal("10013.00")
                    or report.final_equity_usd != Decimal("10013.00")
                    or report.expectancy_net_usd_per_trade != Decimal("3.25")
                    or report.win_rate_percent != Decimal(50)
                    or report.profit_factor != Decimal(24) / Decimal(11)
                    or report.max_observed_drawdown_usd != Decimal("6.00")
                    or [(m.month_utc, m.closed_trades, m.net_usd) for m in report.monthly] != [
                        ("2026-09", 2, Decimal("4.00")),
                        ("2026-10", 2, Decimal("9.00")),
                    ]
                    or report.sharpe_annualized is not None):
                raise ValueError("four-trade independent known-answer ledger metrics differ")
            proof = {
                "status": "PASS", "scope": "INTERNAL_SYNTHETIC_CENT_EXACT_REAL_SQLITE_REPLAY",
                "original_fixture_sha256": frozen,
                "frozen_event_manifest_sha256": manifest_sha,
                "replay_journal_tip_sha256": receipts[0].journal_tip_sha256,
                "independently_rebuilt_journals": 2,
                "source_replay_idempotent": True,
                "journal_event_count": len(events),
                "metrics": report.to_wire(),
                "historical_profitability_qualified": False,
                "live_broker_attested": False,
            }
    except Exception as exc:  # noqa: BLE001 - evidence must preserve failures
        proof = {"status": "BLOCKED", "error_type": type(exc).__name__,
                 "message": str(exc)[:400]}
    OUT.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(proof, sort_keys=True))
    return 0 if proof["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
