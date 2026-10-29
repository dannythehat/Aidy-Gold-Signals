import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts.oracle_gold.phase05_review import packet

ROOT = Path(__file__).resolve().parents[1]
P = ROOT/'reports/gold_oracle/phase05'


def read(path):
    return json.loads(path.read_text())


def test_ci_archives_all_members_and_money_reconcile():
    for name, member in [('pine_accounts', 'results/report.json'), ('S083_native', 'report.json'),
                         ('S083_costs', 'results/report.json'), ('native_indicator_attempt03', 'parity.json')]:
        packet(P/name, member)
    models = read(P/'review/account_results_register.json')['models']
    assert len(models) == 17
    assert {m['id'] for m in models} == {'S052', 'S066', 'S083'}
    for m in models:
        assert sum(y['net_usd'] for y in m['yearly']) == pytest.approx(m['net_marked_usd'], abs=1e-7)
        assert sum(m['yearly_realised_usd'].values()) == pytest.approx(m['net_marked_usd'], abs=1e-7)
        assert sum(y['net_usd'] for y in m['monthly']) == pytest.approx(m['net_marked_usd'], abs=1e-7)


def test_winner_count_does_not_hide_losing_year_or_zero_trade_account():
    shortlist = read(P/'review/shortlist.json')
    assert shortlist['new_account_tested_distinct_systems'] == 3
    assert shortlist['new_positive_stressed_model_total'] == 1
    assert shortlist['new_positive_in_every_stressed_tested_year'] == 0
    assert shortlist['new_full_execution_and_independent_validation_passes'] == 0
    assert not shortlist['packaging_ready']
    models = read(P/'review/account_results_register.json')['models']
    s083 = next(m for m in models if m['case'] == 'S083_gap_and_common_stress')
    assert s083['net_marked_usd'] == pytest.approx(298.1003311771419)
    assert s083['yearly'][0]['net_usd'] < 0
    zero = next(m for m in models if m['case'] == 'S066_standard10000_common_stress')
    assert zero['closed_trades'] == 0 and zero['rejected_entries'] == 2207
    assert zero['net_marked_usd'] == 0


def test_all83_ids_and_exact125_prior_comparisons_retained():
    register = read(P/'review/83_strategy_register.json')
    assert [r['id'] for r in register['rows']] == [f'S{i:03}' for i in range(1, 84)]
    assert register['source_obtained_ids'] == 74 and register['source_access_blockers'] == 9
    assert not register['all74_obtainable_sources_fully_verified']
    assert not register['all83_backtested']
    prior = read(ROOT/'reports/gold_oracle/phase03/125_duplicate_comparisons.json')
    new = read(P/'review/125_duplicate_comparisons.json')
    assert new['comparisons'] == prior['comparisons']
    assert len(new['comparisons']) == 125
    assert new['counts']['UNRESOLVED_SOURCE_BLOCKED'] == 7
    assert sum(len(r['phase05_account_cases']) for r in register['rows']) == 17


def test_native_indicators_are_not_claimed_as4570_entry_or_account_backtests():
    report, _ = packet(P/'native_indicator_attempt03', 'parity.json')
    assert report['native_closed_bars'] == 4570
    assert all(report['price_checks'].values())
    assert report['native_iATR20_vs_TR_rolling_SMA_max_abs_error'] < 1e-7
    assert report['native_iMA200_vs_first_close_seeded_EMA_max_abs_error'] < 1e-7
    assert report['native_original_entry_function_rows_actually_executed'] == 1
    assert not report['complete_historical_native_entry_trace']
    assert not report['account_backtest']
    assert not report['native_broker_execution_qualified']
    with zipfile.ZipFile(P/'native_parity_attempt02/ci_evidence.zip') as z:
        found = False
        for name in z.namelist():
            if name.endswith('.log'):
                raw = z.read(name)
                text = raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig')
                found |= 'tester not started because the account is not specified' in text
        assert found


def test_authentic_ask_receipts_and_distinct_cache_identities_are_not_lost():
    data = read(P/'review/benchmarks_and_data.json')
    assert data['new_r2_rows'] == 1018298 and data['old_bid_rows'] == 1018296
    assert data['r2_source_months'] == 36
    assert all(v['median_observed_open_spread'] > 0 for v in data['quote_statistics'])
    assert all(v['zero_open_spread_pct'] == 0 for v in data['quote_statistics'])
    cache = read(ROOT/'research/gold_oracle/phase05/bidask_cache_receipts.json')
    assert sum(m['receipt']['prior2023_identity_verified'] for m in cache['monthly_snapshots']) == 12
    assert not cache['original_archives_modified']
    assert data['models']['S083_common_stress']['net_marked_usd'] > 298.11


def test_first_local_harness_and_native_failures_remain_auditable():
    receipt = read(P/'local_pine_attempt01/receipt.json')
    assert hashlib.sha256((P/'local_pine_attempt01/evidence.zip').read_bytes()).hexdigest() == receipt['zip_sha256']
    receipt = read(P/'native_parity_attempt01/ci_receipt.json')
    assert 'PYTHONPATH' in receipt['failure']
    assert hashlib.sha256((P/'native_parity_attempt01/ci_evidence.zip').read_bytes()).hexdigest() == receipt['zip_sha256']
