"""Offline MT5 report extraction. Fixtures are synthetic. No terminal is started."""
from __future__ import annotations

import ast
import hashlib
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from aidy.goldthinker_factory_contract import (
    FactoryContractError,
    select_best_completed_year,
    validate_mt5_bundle,
)
from aidy.goldthinker_factory_mt5_extract import (
    analyse_report,
    build_annual_bundle,
    closed_trades_from_deals,
    parse_decimal,
)
from tests.goldthinker_factory_synthetic_reports import synthetic_report_html, synthetic_report_xml

AS_OF = datetime.fromisoformat("2026-11-02T06:00:00+00:00")
AS_OF_TEXT = "2026-11-02T06:00:00Z"
ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/goldthinker_factory/synthetic/synthetic_GT_TEST01_2023_real_ticks.htm"
EXTRAS = {
    2021: Decimal("-140.00"),
    2022: Decimal("-140.00"),
    2023: Decimal("0.00"),
    2024: Decimal("50.00"),
    2025: Decimal("-130.00"),
    2026: Decimal("5000.00"),
}


def _end(year: int) -> str:
    return f"{year + 1}.01.01" if year < 2026 else "2026.11.02"


def _raw(year: int, **kwargs) -> bytes:
    extra = kwargs.pop("extra_last_profit", EXTRAS[year])
    return synthetic_report_html(year, end=_end(year), extra_last_profit=extra, **kwargs).encode("utf-8")


def _reports(overrides: dict | None = None) -> dict:
    overrides = overrides or {}
    reports = {}
    for year in range(2021, 2027):
        if year in overrides:
            reports[year] = overrides[year]
        else:
            reports[year] = (f"synthetic/synthetic_GT_TEST01_{year}_real_ticks.htm", _raw(year))
    return reports


def _bundle(root: Path, reports=None):
    return build_annual_bundle(
        system_id="GT_TEST01",
        family_id="S016",
        source_kind="SYNTHETIC_FIXTURE",
        strategy_version_sha256="a" * 64,
        ea_sha256="d" * 64,
        broker_profile_sha256="e" * 64,
        test_config_sha256="f" * 64,
        data_manifest_sha256="1" * 64,
        tester_build="FIXTURE_NOT_MT5",
        as_of_utc=AS_OF_TEXT,
        reports=reports if reports is not None else _reports(),
        ledger_dir=root / "ledgers",
    )


class ExtractTests(unittest.TestCase):
    def test_committed_synthetic_fixture_matches_renderer_and_admits(self):
        raw = FIXTURE.read_bytes()
        self.assertIn(b"SYNTHETIC_FIXTURE", raw)
        self.assertEqual(raw.decode("utf-8"), synthetic_report_html(2023, end="2024.01.01"))
        analysed = analyse_report(
            raw, year=2023, as_of=AS_OF, source_kind="SYNTHETIC_FIXTURE",
        )
        self.assertTrue(analysed["admitted"])
        self.assertEqual(analysed["claims"]["net_profit_usd"], "150.00")
        self.assertEqual(analysed["claims"]["closed_trades"], 2)
        self.assertEqual(analysed["claims"]["max_equity_drawdown_pct"], "1.0500")
        self.assertEqual(analysed["report_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(
            analysed["ledger_sha256"],
            hashlib.sha256(analysed["ledger_csv"].encode("utf-8")).hexdigest(),
        )
        self.assertIn("time,deal,order,symbol,type,direction,volume,price,commission,swap,profit,balance,comment\n", analysed["ledger_csv"])

    def test_utf16_keeps_ledger_hash_and_changes_report_hash(self):
        text = synthetic_report_html(2023, end="2024.01.01")
        utf8 = analyse_report(text.encode("utf-8"), year=2023, as_of=AS_OF, source_kind="SYNTHETIC_FIXTURE")
        utf16 = analyse_report(text.encode("utf-16"), year=2023, as_of=AS_OF, source_kind="SYNTHETIC_FIXTURE")
        self.assertTrue(utf16["admitted"])
        self.assertEqual(utf8["ledger_sha256"], utf16["ledger_sha256"])
        self.assertNotEqual(utf8["report_sha256"], utf16["report_sha256"])

    def test_localized_numbers_nbsp_and_spreadsheetml(self):
        for raw in (
            synthetic_report_html(2023, end="2024.01.01", decimal_comma=True).encode(),
            synthetic_report_html(2023, end="2024.01.01", nbsp=True).encode(),
            synthetic_report_xml(2023, end="2024.01.01").encode(),
        ):
            analysed = analyse_report(raw, year=2023, as_of=AS_OF, source_kind="SYNTHETIC_FIXTURE")
            self.assertTrue(analysed["admitted"], analysed.get("discrepancies") or analysed.get("parse_error"))
            self.assertEqual(analysed["claims"]["net_profit_usd"], "150.00")

    def test_ambiguous_number_and_balance_break_are_not_repaired(self):
        ambiguous = analyse_report(
            synthetic_report_html(2023, end="2024.01.01", profit_override="1.234").encode(),
            year=2023, as_of=AS_OF, source_kind="SYNTHETIC_FIXTURE",
        )
        self.assertFalse(ambiguous["admitted"])
        self.assertIn("ambiguous", ambiguous["parse_error"])
        self.assertIsNone(ambiguous["ledger_csv"])
        broken = synthetic_report_html(2023, end="2024.01.01").replace("9 995.00", "9 996.00", 1)
        parsed = analyse_report(broken.encode(), year=2023, as_of=AS_OF, source_kind="SYNTHETIC_FIXTURE")
        self.assertFalse(parsed["admitted"])
        self.assertIn("balance column", parsed["parse_error"])

    def test_summary_disagreement_fails_the_year_and_keeps_bundle_nulls(self):
        raw = synthetic_report_html(
            2023, end="2024.01.01", label_overrides={"Total Net Profit:": "151.00"},
        ).encode()
        reports = _reports({2023: ("synthetic/synthetic_GT_TEST01_2023_real_ticks.htm", raw)})
        with tempfile.TemporaryDirectory() as tmp:
            bundle, receipt = _bundle(Path(tmp), reports)
        row = bundle["results"][2]
        self.assertEqual(row["year"], 2023)
        self.assertEqual(row["test_status"], "FAILED")
        self.assertIsNone(row["net_profit_usd"])
        self.assertIsNone(row["report_sha256"])
        self.assertIsNone(row["ledger_sha256"])
        year = receipt["years"][2]
        self.assertEqual(year["admission"], "CROSSCHECK_FAILED")
        self.assertIn("net profit disagrees with the deal ledger", year["discrepancies"])
        self.assertEqual(year["archive_report_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertIsNotNone(year["archive_ledger_sha256"])
        validate_mt5_bundle(bundle)

    def test_missing_year_stays_null_and_blocks_selection(self):
        reports = _reports({2022: None})
        with tempfile.TemporaryDirectory() as tmp:
            bundle, receipt = _bundle(Path(tmp), reports)
            self.assertFalse((Path(tmp) / "ledgers" / "GT_TEST01_2022_deals.csv").exists())
        self.assertEqual(bundle["results"][1]["coverage"], "MISSING")
        self.assertEqual(bundle["results"][1]["test_status"], "BLOCKED")
        self.assertIsNone(bundle["results"][1]["net_profit_usd"])
        self.assertEqual(receipt["years"][1]["admission"], "MISSING")
        selected = select_best_completed_year(bundle)
        self.assertIsNone(selected["aidy_year"])

    def test_2026_partial_cannot_win_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle, receipt = _bundle(Path(tmp))
        self.assertEqual(bundle["results"][-1]["test_status"], "PARTIAL")
        self.assertEqual(bundle["results"][-1]["net_profit_usd"], "5150.00")
        self.assertFalse(receipt["execution_performed"])
        self.assertFalse(receipt["broker_credentials_used"])
        self.assertFalse(receipt["tick_coverage_verified"])
        self.assertEqual(receipt["time_basis"], "BROKER_SERVER_CLOCK_NOT_UTC")
        selected = select_best_completed_year(bundle)
        self.assertEqual(selected["aidy_year"], 2024)
        self.assertEqual(selected["aidy_expected_net_usd"], "200.00")
        self.assertNotEqual(selected["aidy_year"], 2026)
        for flag in (
            "historical_edge_verified", "real_mt5_evidence_authenticated",
            "paper_authorised", "cent_authorised", "live_authorised",
            "public_performance_publication_authorised",
        ):
            self.assertFalse(selected[flag])

    def test_synthetic_path_and_real_marker_are_fail_closed(self):
        raw = _raw(2023, extra_last_profit=Decimal("0.00"))
        reports = _reports({2023: ("GT_TEST01_2023_real_ticks.htm", raw)})
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FactoryContractError):
                _bundle(Path(tmp), reports)
        analysed = analyse_report(raw, year=2023, as_of=AS_OF, source_kind="REAL_MT5_TESTER")
        self.assertFalse(analysed["admitted"])
        self.assertIn("synthetic marker", analysed["discrepancies"][0])

    def test_decimal_parser_fail_closed_cases(self):
        self.assertEqual(parse_decimal("1 234.50", "n"), Decimal("1234.50"))
        self.assertEqual(parse_decimal("1.234,50", "n"), Decimal("1234.50"))
        self.assertEqual(parse_decimal("-90.00", "n"), Decimal("-90.00"))
        with self.assertRaises(FactoryContractError):
            parse_decimal("1.234", "n")

    def test_partial_close_splits_and_inout_is_refused(self):
        running = Decimal("0")
        deals = []

        def add(**kwargs):
            nonlocal running
            running += kwargs["profit"] + kwargs["commission"] + kwargs["swap"]
            deals.append({
                "time": kwargs["time"], "deal": kwargs["deal"], "order": kwargs["order"],
                "symbol": kwargs["symbol"], "type": kwargs["type"], "direction": kwargs["direction"],
                "volume": kwargs["volume"], "price": kwargs["price"],
                "commission": kwargs["commission"], "swap": kwargs["swap"],
                "profit": kwargs["profit"], "balance": running, "comment": "SYNTHETIC_FIXTURE",
            })

        add(time="2023-01-02T00:00:00", deal=1, order=None, symbol="", type="balance",
            direction="", volume=None, price=None, commission=Decimal("0"), swap=Decimal("0"),
            profit=Decimal("10000"))
        add(time="2023-02-01T10:00:00", deal=2, order=10, symbol="XAUUSD", type="buy",
            direction="in", volume=Decimal("0.20"), price=Decimal("1900"), commission=Decimal("-4"),
            swap=Decimal("0"), profit=Decimal("0"))
        add(time="2023-02-01T12:00:00", deal=3, order=11, symbol="XAUUSD", type="sell",
            direction="out", volume=Decimal("0.10"), price=Decimal("1910"), commission=Decimal("-1"),
            swap=Decimal("0"), profit=Decimal("10"))
        add(time="2023-02-01T13:00:00", deal=4, order=12, symbol="XAUUSD", type="sell",
            direction="out", volume=Decimal("0.10"), price=Decimal("1920"), commission=Decimal("-1"),
            swap=Decimal("0"), profit=Decimal("20"))
        trades, residual = closed_trades_from_deals(deals)
        self.assertEqual(residual, 0)
        self.assertEqual(len(trades), 2)
        self.assertEqual(trades[0].commission, Decimal("-3"))
        self.assertEqual(sum(trade.net_pnl for trade in trades), Decimal("24"))
        deals[2]["direction"] = "in/out"
        with self.assertRaises(FactoryContractError):
            closed_trades_from_deals(deals)

    def test_sources_do_not_execute_or_embed_credentials(self):
        files = [
            ROOT / "src/aidy/goldthinker_factory_mt5_extract.py",
            ROOT / "src/aidy/goldthinker_factory_metrics.py",
            ROOT / "src/aidy/goldthinker_factory_reconcile.py",
            ROOT / "scripts/goldthinker_factory/extract_mt5_bundle.py",
            ROOT / "scripts/goldthinker_factory/reconcile_selected_year.py",
            ROOT / "tests/goldthinker_factory_synthetic_reports.py",
        ]
        forbidden_imports = {
            "subprocess", "socket", "urllib", "requests", "http", "ftplib", "smtplib",
        }
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            self.assertFalse(imported & forbidden_imports, path.name)
            text = path.read_text(encoding="utf-8")
            for token in ("Password", "Login=", "terminal64", "AccountNumber", "MetaApi"):
                self.assertNotIn(token, text, path.name)


if __name__ == "__main__":
    unittest.main()
