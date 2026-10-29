"""Reconcile actual CI ledgers, preserve83 IDs, rank evidence without promotion."""
import argparse
import copy
import hashlib
import io
import json
import zipfile
from itertools import combinations
from pathlib import Path

import pandas as pd

from scripts.oracle_gold.native_python_accounts import snapshots
from scripts.oracle_gold.phase04_review import native_packet, passive
from scripts.oracle_gold.phase05_native_accounts import quotes

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT/'reports/gold_oracle'
PHASE = BASE/'phase05'


def read(p):
    return json.loads(p.read_text(encoding='utf-8-sig'))


def write(p, value):
    p.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n')


def packet(folder, member='results/report.json'):
    receipt = read(folder/'ci_receipt.json')
    assert hashlib.sha256((folder/'ci_evidence.zip').read_bytes()).hexdigest() == receipt['zip_sha256']
    with zipfile.ZipFile(folder/'ci_evidence.zip') as z:
        for name, sha in receipt['members_sha256'].items():
            assert hashlib.sha256(z.read(name)).hexdigest() == sha, name
        report = json.loads(z.read(member))
    return report, receipt


def yearly_realised(folder, member, column, timestamp):
    with zipfile.ZipFile(folder/'ci_evidence.zip') as z:
        raw = z.read(member)
    if not raw.strip():
        return {}
    frame = pd.read_csv(io.BytesIO(raw))
    if frame.empty:
        return {}
    return {str(k): float(v) for k, v in frame.groupby(pd.to_datetime(frame[timestamp], utc=True).dt.year)[column].sum().items()}


def source_passive(frame, allowance):
    entry = float(frame.ask_o.iloc[0])+.05
    units = int(10000*.95/(entry+allowance/2))
    eq = 10000-units*entry-units*allowance/2+units*frame.bid_c
    peak = pd.concat([pd.Series([10000.]), eq.reset_index(drop=True)]).cummax()
    dd = pd.concat([pd.Series([10000.]), eq.reset_index(drop=True)])/peak-1
    monthly, prior = [], 10000.
    for month, group in eq.groupby(eq.index.strftime('%Y-%m')):
        end = float(group.iloc[-1])
        monthly.append({'month': month, 'net_usd': end-prior, 'return_pct': (end/prior-1)*100})
        prior = end
    return {'units': units, 'entry_actual_ask_plus_source_slip': entry, 'monthly': monthly,
        'net_marked_usd': float(eq.iloc[-1]-10000), 'minute_close_drawdown_pct': float(dd.min()*100),
        'open_holding_preserved': True, 'estimated_additional_exit_allowance_if_liquidated_usd': units*(allowance/2+.05),
        'actual_broker_qualified': False, 'funding_verified': False}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--quotes', type=Path, required=True)
    p.add_argument('--snapshots', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    pine, pine_receipt = packet(PHASE/'pine_accounts')
    native, native_receipt = packet(PHASE/'S083_native', 'report.json')
    cost, cost_receipt = packet(PHASE/'S083_costs')
    native_indicators, indicator_receipt = packet(PHASE/'native_indicator_attempt03', 'parity.json')
    write(a.out/'native_execution_milestone.json', {'native_indicator_and_latest_entry': native_indicators,
        'evidence': indicator_receipt, 'price_tester_account_blocker': 'tester not started because the account is not specified',
        'price_tester_evidence': read(PHASE/'native_parity_attempt02/ci_receipt.json'),
        'native_full_account_or_trade_by_trade_parity_passed': False,
        'broker_connection_or_trading_activation': False})
    models = []
    for key, model in pine['models'].items():
        v = copy.deepcopy(model)
        v.update({'case': key, 'id': model['strategy_id'], 'engine': 'PINE_CONTINUOUS_SOURCE_FORMULA_MODEL; native rounding/parity unverified',
            'ci': pine_receipt['ci'], 'archive': 'reports/gold_oracle/phase05/pine_accounts/ci_evidence.zip',
            'ledger_member': 'results/'+key+'_trades.csv'})
        v['yearly_realised_usd'] = yearly_realised(PHASE/'pine_accounts', v['ledger_member'], 'pnl', 'exit_ts')
        models.append(v)
    for key, model in native['models'].items():
        v = copy.deepcopy(model)
        v.update({'case': 'S083_'+key, 'id': 'S083', 'engine': 'UNCHANGED_ORIGINAL001B_ACCOUNT_ENGINE',
            'ci': native_receipt['ci'], 'archive': 'reports/gold_oracle/phase05/S083_native/ci_evidence.zip',
            'ledger_member': 'S083_'+key+'_trades.csv'})
        # Original ledger rounds every trade. Exact observed profits are kept
        # separately; never imply sum(rounded profits) is exact native equity.
        with zipfile.ZipFile(PHASE/'S083_native/ci_evidence.zip') as z:
            obs = pd.DataFrame(json.loads(z.read('S083_'+key+'_observer.json')))
        v['yearly_realised_usd'] = {str(k): float(n) for k, n in obs.groupby(pd.to_datetime(obs.exit_ts, utc=True).dt.year).pnl_exact.sum().items()}
        models.append(v)
    for key, model in cost['models'].items():
        v = copy.deepcopy(model)
        v.update({'case': 'S083_gap_and_'+key, 'id': 'S083', 'scenario': key,
            'engine': 'DISCLOSED_SOURCE_ENGINE_EXECUTION_SENSITIVITY; original parameters/strategy unchanged',
            'ci': cost_receipt['ci'], 'archive': 'reports/gold_oracle/phase05/S083_costs/ci_evidence.zip',
            'ledger_member': 'results/S083_'+key+'_exact_trades.csv'})
        v['yearly_realised_usd'] = yearly_realised(PHASE/'S083_costs', v['ledger_member'], 'pnl', 'exit_ts')
        models.append(v)
    for model in models:
        # Full daily/weekly evidence remains in the immutable CI ZIPs, avoiding
        # duplicate multi-megabyte inline registers.
        model.pop('daily', None)
        model.pop('weekly', None)
    write(a.out/'account_results_register.json', {'models': models, 'new_distinct_ids': ['S052', 'S066', 'S083'],
        'case_count': len(models), 'original_and_standard10000_S083_are_same_account': True,
        'all_original_inputs_parameters_and_losses_retained': True, 'funding_verified': False,
        'native_broker_execution_or_independent_qualification_passes': 0})
    old_shortlist = read(BASE/'phase04/review/shortlist.json')
    new_stress = cost['models']['common_stress']
    watch = {'id': 'S083', 'family': 'S083_001B_ZONE_REJECTION', 'classification': 'BLOCKED',
        'research_priority': 2, 'net_stressed_allowance_usd': new_stress['net_marked_usd'],
        'years': new_stress['yearly'], 'reason': 'Positive total, but stress2023 negative; modest61-trade sample; venue/lot/margin/funding and independent validation unresolved',
        'is_independent_certified_winner': False, 'source_version': native['source'],
        'execution_cost_extension': new_stress['execution_extension_receipt'], 'evidence': cost_receipt}
    write(a.out/'shortlist.json', {'primary_provisional_family_preserved': old_shortlist['provisional_research_candidates'],
        'earlier_watchlist_preserved': old_shortlist['earlier_profitable_watchlist'],
        'new_execution_research_watchlist': [watch], 'new_rejected_as_tested': ['S052', 'S066'],
        'next_engineering_priority': 'S040 native entry/indicator evidence; full account tests still require actual execution contract and native tester prerequisites',
        'historically_qualified': [], 'packaging_ready': [], 'no_fresh_holdout_claim': True,
        'new_account_tested_distinct_systems': 3, 'new_positive_stressed_model_total': 1,
        'new_positive_in_every_stressed_tested_year': 0, 'new_full_execution_and_independent_validation_passes': 0,
        'new_rejected': 2, 'new_blocked': 1,
        'profit_scope': 'After declared AIDY cost allowances; excludes unverified financing. Two new Pine accounts are continuous-quantity diagnostic models, not native platform certificates.'})
    frame, manifests = quotes(a.quotes)
    bid, old_manifests = snapshots(a.snapshots)
    benchmarks = {'S083_'+name: source_passive(frame, allowance) for name, allowance in [('common_base', .47), ('common_stress', 1.44)]}
    for capital in (10000., 25000., 1000000.):
        for name in ('common_base', 'common_stress'):
            benchmarks[f'PINE_BID_{capital:.0f}_{name}'] = passive(bid, capital, name)
    quote_stats = []
    for year, group in frame.groupby(frame.index.year):
        quote_stats.append({'year': int(year), 'rows': len(group), 'median_observed_open_spread': float((group.ask_o-group.bid_o).median()),
            'zero_open_spread_pct': float((group.ask_o == group.bid_o).mean()*100),
            'median_tick_weighted_minute_spread': float(group.spread_mean.median()),
            'maximum_minute_mean_spread': float(group.spread_mean.max())})
    write(a.out/'benchmarks_and_data.json', {'models': benchmarks, 'quote_statistics': quote_stats,
        'new_r2_rows': len(frame), 'r2_source_months': len(manifests), 'old_bid_rows': len(bid),
        'old_bid_manifests': old_manifests, 'calendar_verified': False, 'fresh_oos': False,
        'comparability': 'Pine uses prior BID chart; S083 uses genuine R2 BID/ASK and its native mid-chart. Capital and exposure differ; no arithmetic master portfolio.'})
    series = {}
    for v in models:
        if v['case'].endswith(('common_base', 'common_stress')):
            series[v['case']] = pd.Series({r['period'][:7]: r['return_pct'] for r in v['monthly']})
    previous, _ = native_packet(BASE/'phase04/native_accounts_exact_stack')
    for key, v in previous['models'].items():
        if 'STANDARDISED_CAPITAL' in key and key.endswith(('common_base', 'common_stress')):
            series[key] = pd.Series({r['month']: r['return_pct'] for r in v['monthly']})
    for ident in ('S005', 'S006', 'S007', 'S008', 'S009', 'S010'):
        for scenario in ('base', 'stress'):
            vals = {}
            for year in (2023, 2024, 2025):
                f = pd.read_csv(BASE/f'batch01_common/{year}/{ident}_{scenario}_monthly.csv')
                vals.update(dict(zip(f.month, f.return_pct, strict=True)))
            series[f'{ident}_common_{scenario}'] = pd.Series(vals)
    pairs = []
    for (ka, sa), (kb, sb) in combinations(series.items(), 2):
        if ('common_stress' in ka) != ('common_stress' in kb):
            continue
        joined = pd.concat([sa, sb], axis=1).dropna()
        corr = joined.iloc[:, 0].corr(joined.iloc[:, 1]) if (joined.std() > 0).all() else None
        pairs.append({'a': ka, 'b': kb, 'months': len(joined),
            'pearson_monthly_returns': None if corr is None or pd.isna(corr) else float(corr),
            'simultaneous_losing_months': list(joined.index[(joined.iloc[:, 0] < 0)&(joined.iloc[:, 1] < 0)])})
    write(a.out/'correlation_and_portfolio_gates.json', {'pairs': pairs,
        'master_account_simulated': False, 'master_profit_claimed': False,
        'blockers': ['No qualified source-faithful account engines share a verified venue/netting/lot/margin/funding contract',
                     'Source cash-stocklike S016 and continuous-ounce S083 cannot be added into an executable gold CFD account',
                     'Shared position/correlation/drawdown policy and broker contract require explicit reproducible simulation before a master result'],
        'limits': ['Already-examined36months', 'Different data/chart/capital/account-reset conventions',
                   'Cost sensitivity and source parameter relatives are not independent strategies', 'No independence inferred from correlation alone']})
    prior = read(BASE/'phase04/review/83_strategy_register.json')
    rows = copy.deepcopy(prior['rows'])
    for row in rows:
        ident = row['id']
        row['previous_disposition_preserved_at'] = row['prior_audit_and_results']
        row['phase05_classification'] = 'RESEARCH PROMISING' if ident in ('S016', 'S010') else 'REJECTED' if ident in ('S019', 'S052', 'S058', 'S060', 'S061', 'S066', 'S081') else 'BLOCKED'
        row['phase05_account_cases'] = [v['case'] for v in models if v['id'] == ident]
        row['phase05_evidence'] = [{k: v[k] for k in ('case', 'ci', 'archive', 'ledger_member')} for v in models if v['id'] == ident]
        if ident == 'S052':
            row['blockers'] += ['Stress10k net−866.509349;2023/24 negative; continuous fractional units and native Pine parity unverified']
        if ident == 'S066':
            row['blockers'] += ['Original1m loses after base/stress costs and in each stress year; source240k order is unaffordable on source-margin100%10k account;2207 entry rejections per scenario']
        if ident == 'S083':
            row['blockers'] += ['Cost-aware gap-floor stress total+298.100331 but2023−9.605936; source-native3 gap-stop underfills retained',
                                'Financing/contract/lot/margin/full calendar and independent validation remain unverified; no fresh OOS']
        if ident == 'S040':
            row['phase05_native_price_tester_blocker'] = 'MT5 imported1018298 actual M1 bars then refused price tester: account is not specified. No broker connection supplied.'
            row['phase05_native_indicator_evidence'] = {'ci': indicator_receipt['ci'],
                'bars': native_indicators['native_closed_bars'],
                'original_entry_function_calls': native_indicators['native_original_entry_function_rows_actually_executed'],
                'full_historical_native_entry_trace': False, 'native_account_test': False}
        if ident in ('S064', 'S065'):
            row['blockers'] += ['Recovered publication chart is BITSTAMP:BTCUSD with mintick1; cannot silently infer native gold symbol/tick contract from that example']
        row['historically_qualified'] = False
        row['execution_enabled'] = False
    write(a.out/'83_strategy_register.json', {'rows': rows, 'source_obtained_ids': 74, 'source_access_blockers': 9,
        'new_distinct_account_model_ids': ['S052', 'S066', 'S083'], 'case_count': len(models),
        'full_execution_and_independent_validation_passes': 0, 'packaging_ready': [],
        'all74_obtainable_sources_fully_verified': False, 'all83_backtested': False,
        'old_source_audits_ledgers_and_results_preserved': True})
    comparisons = read(BASE/'phase03/125_duplicate_comparisons.json')
    comparisons['phase05_note'] = 'No newly accessible original source for the seven unresolved pairs. All125 prior source decisions preserved exactly; no new independent winner or alias from profitability/correlation.'
    write(a.out/'125_duplicate_comparisons.json', comparisons)
    write(a.out/'S083_source_version_and_readiness.json', {'source': native['source'], 'reference_defaults': '001B/ema50/session/2R/0.25percent/10000',
        'original_native_evidence': native_receipt, 'disclosed_execution_sensitivity': cost_receipt,
        'execution_expression_receipt': new_stress['execution_extension_receipt'],
        'classification': 'BLOCKED; positive total but repeatability/native gates incomplete',
        'historically_qualified': False, 'release_created': False, 'execution_enabled': False,
        'blockers': ['Stress2023 negative', 'Source gap-stop and timeout defects; native original losses/receipts preserved',
                     'Rights and actual broker contract/lot/margin/financing not verified',
                     'Already-examined history; no independent untouched holdout', 'Native original dataset was another provider; AIDY application is explicitly HistData R2']})


if __name__ == '__main__':
    main()
