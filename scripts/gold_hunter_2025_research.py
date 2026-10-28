"""Genuine AIDY source-gated, Bible-constrained multiple-system 2025 evaluation.

Reads same-run verified historical CSV+receipts. Never reads broker accounts,
places orders, or manufactures prices from absent archival data.
"""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pandas as pd

from gold_hunter.bible_engine import FAMILIES, Parameters, research_backtest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'artifacts/strategy_lab/s010_paid_customer_example'
DEST = ROOT / 'artifacts/gold_hunter/bible_2025'


def run() -> dict:
    raw_file = SOURCE / 'source_verified_2025_h1_bid.csv'
    upstream_file = SOURCE / 'full_independent_research.json'
    if not raw_file.is_file() or not upstream_file.is_file():
        raise ValueError('No same-run authenticated AIDY original 2025 historical source')
    original = json.loads(upstream_file.read_text(encoding='utf-8'))
    receipts = original.get('source_receipts')
    if (original.get('status') != 'PASS_REAL_12_MONTH_HISTORICAL_RESEARCH'
            or not isinstance(receipts, list) or len(receipts) != 12
            or [r.get('calendar_month_utc') for r in receipts] !=
            [f'2025-{month:02d}' for month in range(1,13)]
            or original.get('paper_and_live_broker_orders') != 0
            or any(not r.get('query_job_id') or
                   r.get('invalid_original_rows', 0) != 0 for r in receipts)):
        raise ValueError('Upstream immutable source/provenance receipts fail')
    market_sha = hashlib.sha256(raw_file.read_bytes()).hexdigest()
    with raw_file.open(encoding='utf-8', newline='') as f:
        source = pd.DataFrame(csv.DictReader(f))
    if len(source) < 3500 or len(source) != sum(r['complete_h1'] for r in receipts):
        raise ValueError('H1 bars do not match original monthly source evidence')
    source['m1_count'] = pd.to_numeric(source['m1_count'], errors='raise').astype(int)
    results = {}
    scenarios = {
        'base': Parameters(),
        'stress': replace(Parameters(), spread_usd_oz=.80,
                          slip_usd_oz_each_side=.25,
                          commission_usd_oz_roundtrip=.14),
    }
    for scenario, cfg in scenarios.items():
        for family_set in [FAMILIES] + [(name,) for name in FAMILIES]:
            label = 'COMBINED' if len(family_set) > 1 else family_set[0]
            result = research_backtest(source, cfg=cfg, families=family_set)
            key = f'{label}_{scenario}'
            if result['price_rows'] != len(source) or result['status'] != 'HISTORICAL_RESEARCH_ONLY':
                raise ValueError('Incomplete historical account evidence')
            results[key] = result
            DEST.mkdir(parents=True, exist_ok=True)
            (DEST / f'{key}.json').write_text(
                json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + '\n',
                encoding='utf-8')
            trades = result['trades']
            with (DEST / f'{key}_trades.csv').open('w', encoding='utf-8', newline='') as stream:
                if trades:
                    writer = csv.DictWriter(stream, fieldnames=list(trades[0]))
                    writer.writeheader()
                    writer.writerows(trades)
                else:
                    stream.write('no_closed_trades\n')
    report = {
        'status': 'REAL_SOURCE_BIBLE_RESEARCH_COMPLETE',
        'original_year': 2025,
        'source_kind': 'RETROSPECTIVE_NATIVE_M1_DERIVED_H1_BID',
        'original_source_receipts': [r['query_job_id'] for r in receipts],
        'market_csv_sha256': market_sha,
        'original_s010_research_sha256': original.get('research_sha256'),
        'model_count': len(results),
        'summary': {key: {k: result[k] for k in
                          ('closed_trades', 'net_modelled_usd',
                           'ending_equity_usd', 'max_marked_drawdown_percent',
                           'counts_selected')}
                    for key, result in results.items()},
        'broker_executable': False,
        'genuine_sealed_oos': False,
        'live_or_paper_orders': 0,
        'source_reader_full_original_book_completed_in_this_run': False,
    }
    report['sha256'] = hashlib.sha256(json.dumps(
        report, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    (DEST / 'report.json').write_text(
        json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + '\n',
        encoding='utf-8')
    print('GOLD_HUNTER_BIBLE_REAL_2025_REPORT', json.dumps(report['summary'], sort_keys=True))
    return report


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        DEST.mkdir(parents=True, exist_ok=True)
        (DEST / 'blocked_result.json').write_text(json.dumps({
            'status': 'BLOCKED_REAL_SOURCE_OR_ENGINE',
            'error_type': type(exc).__name__, 'error': str(exc)[:600],
            'no_invented_results': True, 'live_or_paper_orders': 0,
        }, indent=2) + '\n', encoding='utf-8')
        raise