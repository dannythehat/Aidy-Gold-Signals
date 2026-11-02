"""Build a v1 annual bundle from MT5 Strategy Tester .htm/.xml files.

Does not launch MT5. Missing years stay null. A cross-check failure marks that
year FAILED and does not copy the disputed numbers into the bundle.

Looks for {system}_{year}_real_ticks.htm or .xml, and the synthetic-prefixed
names synthetic_{system}_{year}_real_ticks.htm or .xml.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from aidy.goldthinker_factory_contract import FactoryContractError, canonical_json
from aidy.goldthinker_factory_mt5_extract import atomic_write, build_annual_bundle


def _find(directory: Path, system_id: str, year: int) -> Path | None:
    names = [
        f"{system_id}_{year}_real_ticks.htm",
        f"{system_id}_{year}_real_ticks.html",
        f"{system_id}_{year}_real_ticks.xml",
        f"synthetic_{system_id}_{year}_real_ticks.htm",
        f"synthetic_{system_id}_{year}_real_ticks.html",
        f"synthetic_{system_id}_{year}_real_ticks.xml",
    ]
    found = [directory / name for name in names if (directory / name).is_file()]
    if len(found) > 1:
        raise FactoryContractError(f"{year}: more than one report file matches")
    return found[0] if found else None


def run(
    *,
    reports_dir: Path,
    output_dir: Path,
    system_id: str,
    family_id: str,
    source_kind: str,
    strategy_version_sha256: str,
    ea_sha256: str,
    broker_profile_sha256: str,
    test_config_sha256: str,
    data_manifest_sha256: str,
    tester_build: str,
    as_of_utc: str,
) -> dict:
    reports = {}
    for year in range(2021, 2027):
        path = _find(reports_dir, system_id, year)
        if path is None:
            reports[year] = None
            continue
        reports[year] = (str(path), path.read_bytes())
    bundle, receipt = build_annual_bundle(
        system_id=system_id,
        family_id=family_id,
        source_kind=source_kind,
        strategy_version_sha256=strategy_version_sha256,
        ea_sha256=ea_sha256,
        broker_profile_sha256=broker_profile_sha256,
        test_config_sha256=test_config_sha256,
        data_manifest_sha256=data_manifest_sha256,
        tester_build=tester_build,
        as_of_utc=as_of_utc,
        reports=reports,
        ledger_dir=output_dir / "ledgers",
    )
    atomic_write(output_dir / "bundle.json", canonical_json(bundle) + "\n")
    atomic_write(output_dir / "extraction_receipt.json", canonical_json(receipt) + "\n")
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--system", required=True)
    parser.add_argument("--family", required=True)
    parser.add_argument("--source-kind", required=True, choices=("SYNTHETIC_FIXTURE", "REAL_MT5_TESTER"))
    parser.add_argument("--strategy-sha256", required=True)
    parser.add_argument("--ea-sha256", required=True)
    parser.add_argument("--broker-profile-sha256", required=True)
    parser.add_argument("--test-config-sha256", required=True)
    parser.add_argument("--data-manifest-sha256", required=True)
    parser.add_argument("--tester-build", required=True)
    parser.add_argument("--as-of", required=True, help="UTC timestamp with Z")
    args = parser.parse_args()
    try:
        bundle = run(
            reports_dir=args.reports_dir,
            output_dir=args.out_dir,
            system_id=args.system,
            family_id=args.family,
            source_kind=args.source_kind,
            strategy_version_sha256=args.strategy_sha256,
            ea_sha256=args.ea_sha256,
            broker_profile_sha256=args.broker_profile_sha256,
            test_config_sha256=args.test_config_sha256,
            data_manifest_sha256=args.data_manifest_sha256,
            tester_build=args.tester_build,
            as_of_utc=args.as_of,
        )
    except (OSError, FactoryContractError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    admitted = sum(row["test_status"] in ("COMPLETED", "PARTIAL") and row["coverage"] == "VERIFIED" for row in bundle["results"])
    print(f"EXTRACTED: admitted_years={admitted} execution_performed=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
