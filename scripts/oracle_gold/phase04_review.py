"""Review immutable native results; separate research candidates from admission.

The screen is explicitly post-hoc, never a new sealed validation claim. Original
presets/capital, losing siblings, passive benchmark and all83 IDs stay visible.
"""
import argparse
import csv
import hashlib
import json
import zipfile
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.oracle_gold.native_python_accounts import ROOT, snapshots

BASE=ROOT/'reports/gold_oracle'
PHASE=BASE/'phase04'


def read(path):
    return json.loads(path.read_text())


def write(path,obj):
    path.write_text(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False)+'\n')


def native_packet(folder):
    receipt=read(folder/'ci_receipt.json')
    raw=(folder/'ci_evidence.zip').read_bytes()
    assert hashlib.sha256(raw).hexdigest()==receipt['zip_sha256']
    with zipfile.ZipFile(folder/'ci_evidence.zip') as z:
        for name,digest in receipt['members_sha256'].items():
            assert hashlib.sha256(z.read(name)).hexdigest()==digest
        return json.loads(z.read('results/report.json')),receipt


def screen(model,policy):
    details=model['details']
    checks=details.get('signal_and_execution_prefix_checks',details.get('signal_prefix_checks',[]))
    failures=[]
    if model['closed_trades']<policy['minimum_closed_trades_total']:
        failures.append('INSUFFICIENT_TOTAL_CLOSED_TRADES')
    for year in model['years']:
        if year['net_usd']<=0:
            failures.append('NONPOSITIVE_STRESS_PERIOD_'+str(year['year']))
        if year['closed_trades']<policy['minimum_closed_trades_per_period']:
            failures.append('SPARSE_PERIOD_'+str(year['year']))
    if model['closed_net_without_largest_winner_usd']<=0:
        failures.append('CLOSED_PROFIT_DEPENDS_ON_LARGEST_WINNER_OR_IS_NONPOSITIVE')
    if not checks or not all(c['same'] for c in checks):
        failures.append('PREFIX_EXECUTION_PARITY_UNPROVEN')
    if not details.get('observer_final_equity_parity'):
        failures.append('NATIVE_ACCOUNT_RECONCILIATION_UNPROVEN')
    return failures


def passive(frame,capital,cost):
    half={"common_base":.47/2,"common_stress":1.44/2}[cost]
    entry=float(frame.open.iloc[0])
    units=int(capital*.95/(entry+half))
    eq=capital-units*entry-units*half+units*frame.close
    peak=np.maximum.accumulate(np.r_[capital,eq.to_numpy()])[1:]
    monthly=[];prior=capital
    for month,group in eq.groupby(eq.index.strftime('%Y-%m')):
        end=float(group.iloc[-1])
        monthly.append({'month':month,'start_equity':prior,'end_equity':end,
                        'net_usd':end-prior,'return_pct':(end/prior-1)*100})
        prior=end
    return {'capital':capital,'cost':cost,'units':units,'entry_price':entry,
        'net_marked_usd':float(eq.iloc[-1])-capital,
        'estimated_exit_cost_if_liquidated_usd':units*half,
        'minute_close_drawdown_pct':float(((eq.to_numpy()/peak)-1).min()*100),
        'monthly':monthly,'rule':'95%initial cash, integer source-model units, first observed open, fixed holding; no added final liquidation',
        'actual_broker_qualified':False}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--snapshots',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    report,receipt=native_packet(PHASE/'native_accounts_exact_stack')
    compatible,prior_receipt=native_packet(PHASE/'native_accounts')
    assert len(report['models'])==18 and not report['failed_attempts']
    parity={k:{'financial_result_exact':v['net_marked_usd']==compatible['models'][k]['net_marked_usd'],
        'trade_records_exact':v['trade_records_sha256']==compatible['models'][k]['trade_records_sha256']}
        for k,v in report['models'].items()}
    assert all(all(v.values()) for v in parity.values())
    frame,manifests=snapshots(a.snapshots)
    benchmarks={}
    for cap in (10_000.,10_000_000.):
        for cost in ('common_base','common_stress'):
            benchmarks[f'{cap:.0f}_{cost}']=passive(frame,cap,cost)
    policy=read(ROOT/'research/gold_oracle/phase04/shortlist_policy.json')
    decisions=[]
    for k,m in report['models'].items():
        if m['account_scope']!='STANDARDISED_CAPITAL_COMPARISON' or m['cost_scenario']!='common_stress':
            continue
        failures=screen(m,policy)
        decisions.append({'case':k,'id':m['id'],'family':'S016_DAILY_CLOSE_DONCHIAN' if m['id']=='S016' else 'S019_SMC_CASCADE',
            'variant':m['variant'],'observed_period_screen_passed':not failures,'screen_failures':failures,
            'stress_net_marked_usd':m['net_marked_usd'],'stress_return_pct':m['net_marked_usd']/m['initial_capital']*100,
            'stress_years':m['years'],'closed_trades':m['closed_trades'],
            'minute_close_drawdown_pct':m['minute_close_marked_drawdown_pct'],
            'worst_month_pct':m['worst_month_pct'],'profitable_months':m['profitable_months'],
            'closed_net_without_largest_winner_usd':m['closed_net_without_largest_winner_usd'],
            'passive_benchmark_net_usd':benchmarks['10000_common_stress']['net_marked_usd'],
            'beats_passive_net_return':m['net_marked_usd']>benchmarks['10000_common_stress']['net_marked_usd'],
            'historically_qualified':False,'paper_or_funded_activation_authorised':False})
    provisional=[d for d in decisions if d['observed_period_screen_passed']]
    provisional.sort(key=lambda d:(-sum(y['net_usd']>0 for y in d['stress_years']),-d['closed_trades'],d['minute_close_drawdown_pct']*-1))
    seen=set();ranked=[]
    for d in provisional:
        if d['family'] in seen:
            continue
        seen.add(d['family']);d['research_rank']=len(ranked)+1;ranked.append(d)
    earlier=read(BASE/'83_source_and_duplicate_audit.json')['rows']
    s010=next(r for r in earlier if r['id']=='S010')
    watch=[{'id':'S010','status':'EARLIER_PROFITABLE_DIAGNOSTICS; NATIVE_ACCOUNT/FUNDING_GATES_REMAIN',
        'period_results':[v for v in s010['batch01_common_results'] if v['scenario']=='stress'],
        'continuous_account':False,'historically_qualified':False,
        'reason_not_native_shortlist':'Source signals verified previously; original publisher return accounting differs from AIDY account and financing/margin unresolved'}]
    write(a.out/'shortlist.json',{'schema':'oracle.gold.phase04.research_shortlist.v1','policy':policy,
        'provisional_research_candidates':ranked,'all_evaluated_native_variants':decisions,
        'earlier_profitable_watchlist':watch,
        'historically_qualified':[],'trial_account_configurations':18,'original_ids_newly_replayed':2,
        'independent_families_newly_replayed':2,'notes':'Two S016 presets and two capital/cost comparisons are not independent winners. Ranking follows observed evidence, not preregistered or fresh OOS.',
        'canonical_native_ci':receipt,'compatible_runtime_ci':prior_receipt,'runtime_parity':parity})
    write(a.out/'benchmarks.json',{'models':benchmarks,'input_manifests':manifests,
        'interpretation':'Passive reference shares price history/cash-cost convention; different time exposure. Native strategy trails rising-gold passive return; positive P&L alone is not alpha.'})
    # Same36 observed months; no new portfolio or rescaled original account.
    series={}
    for key,m in report['models'].items():
        if m['account_scope']=='STANDARDISED_CAPITAL_COMPARISON' and m['cost_scenario'].startswith('common_'):
            series[key]=pd.Series({v['month']:v['return_pct'] for v in m['monthly']})
    phase03=read(BASE/'phase03/account_results_register.json')
    with zipfile.ZipFile(ROOT/phase03['committed_artifact']) as z:
        old=json.loads(z.read('results/report.json'))
    for k,m in old['models'].items():
        if '/common_' in k:
            series[k]=pd.Series({v['month']:v['return_pct'] for v in m['monthly']})
    for ident in ('S005','S006','S007','S008','S009','S010'):
        for cost in ('base','stress'):
            vals={}
            for year in (2023,2024,2025):
                with (BASE/f'batch01_common/{year}/{ident}_{cost}_monthly.csv').open() as f:
                    vals.update({v['month']:float(v['return_pct']) for v in csv.DictReader(f)})
            series[f'{ident}/common_{cost}']=pd.Series(vals)
    pairs=[]
    for cost in ('base','stress'):
        selected={k:v for k,v in series.items() if k.endswith('common_'+cost)}
        for (ka,sa),(kb,sb) in combinations(selected.items(),2):
            joined=pd.concat([sa,sb],axis=1).dropna()
            corr=joined.iloc[:,0].corr(joined.iloc[:,1])
            pairs.append({'a':ka,'b':kb,'cost':cost,'months':len(joined),
                'pearson_monthly_returns':None if pd.isna(corr) else float(corr),
                'both_negative_months':list(joined.index[(joined.iloc[:,0]<0)&(joined.iloc[:,1]<0)])})
    gold=frame.close.groupby(frame.index.strftime('%Y-%m')).last().pct_change()
    regimes=[]
    for k,m in report['models'].items():
        monthly=pd.DataFrame(m['monthly']).set_index('month')
        for up in (True,False):
            months=[v for v in monthly.index if v in gold.index and pd.notna(gold[v]) and bool(gold[v]>0)==up]
            regimes.append({'case':k,'regime':'GOLD_MONTH_UP' if up else 'GOLD_MONTH_NONPOSITIVE',
                'months':months,'strategy_net_usd':float(monthly.loc[months,'net_usd'].sum()),
                'profitable_strategy_months':int((monthly.loc[months,'net_usd']>0).sum())})
    write(a.out/'dependence_and_regimes.json',{'pairs':pairs,'regimes':regimes,
        'limits':['36 observed months, not fresh OOS','Old B01 annual resets differ from new continuous accounts',
                  'H1-complete and observed minute/daily aggregations differ','Source model capitals/exposures differ; do not sum accounts',
                  'Gold-month direction is descriptive analysis, not an added trading filter','High/low correlation is not proof of independence']})
    source_pins=read(ROOT/'research/gold_oracle/phase04/python_source_pins.json')
    write(a.out/'S016_source_and_packaging_readiness.json',{
        'schema':'oracle.gold.source_evidence_readiness.v1','strategy_id':'S016','family':'S016_DAILY_CLOSE_DONCHIAN',
        'selected_source_path':'strategies/gold_donchian_channel_strategy.py','source':source_pins['S016'],
        'native_engine_runtime_pin':'research/gold_oracle/phase04/backtrader_runtime_pin.json',
        'selected_parameters':{'entry_period':20,'exit_period':20,'atr_period':40,'atr_multiplier':4,'risk_percent':1.},
        'source_capital':10_000_000,'standardised_comparison_capital':10_000,'protective_stop':'NONE_IN_ORIGINAL',
        'source_version_and_adapter_evidence':receipt,'observed_period_screen_passed':True,
        'historically_qualified':False,'release_package_created':False,'execution_enabled':False,'real_money_enabled':False,
        'unresolved_readiness_gates':['No explicit upstream redistribution licence found at pinned commit',
            'Observed UTC daily XAUUSD application differs from publisher synthetic Gold Index OHLC loader',
            'Full broker calendar/quote/fill/lot/margin/funding contract not attested',
            'Cash stocklike source engine is not a broker CFD execution contract',
            'Two published variants examined on already-seen history; independent future validation required',
            'Trails passive gold net return; no independent alpha certificate',
            'No protective stop; downside beyond these observed periods unqualified'],
        'notes':'This is a source/version and readiness evidence manifest, not a distributable bot release or Oracle Hub admission.'})
    prior=read(BASE/'phase03/independent_strategy_register.json')
    comp=read(PHASE/'native_compile_attempt04/report.json')
    compile_by_id={}
    for item in comp['sources']:
        for ident in item['ids']:
            compile_by_id.setdefault(ident,[]).append(item)
    mql4=read(PHASE/'native_compile_attempt05/report.json')
    oldpairs=read(BASE/'phase03/125_duplicate_comparisons.json')['comparisons']
    rows=[]
    for r in prior['rows']:
        ident=r['id'];n=[k for k,m in report['models'].items() if m['id']==ident]
        blockers=r['blockers']
        if ident=='S016':
            blockers=read(a.out/'S016_source_and_packaging_readiness.json')['unresolved_readiness_gates']
        if ident=='S019':
            blockers=['Native default lost in observed2023/2025 and made no trades2024; only8 closed trades',
                      'Original lot, fill, swap and gap conventions are source placeholders, not a verified broker contract',
                      'Complete-calendar and fresh validation remain unqualified']
        if ident=='S018':
            blockers=['Available MetaEditor5 rejects MQL4 extension; this is not a valid native MQL4 compiler verdict',
                      'Original source also refers to two missing helpers in prior static audit; no silent repair',
                      'MQL4 compiler/platform and actual broker contract remain unverified']
        rows.append({'id':ident,'title':r['title'],'canonical_original_id':ident,
            'source_status':r['source_status'],'prior_audit_and_results':f'reports/gold_oracle/phase03/independent_strategy_register.json#/rows/id={ident}',
            'native_compilation':compile_by_id.get(ident,[]),'native_mql4_attempt':mql4['sources'] if ident=='S018' else [],
            'new_account_cases':n,'blockers':blockers,'provisional_shortlist':any(d['id']==ident for d in ranked),
            'new_case_evidence':[{'case':key,'ci_url':receipt['ci'],'archive':'reports/gold_oracle/phase04/native_accounts_exact_stack/ci_evidence.zip',
                'zip_sha256':receipt['zip_sha256'],'json_member':'results/report.json','trades_member':'results/'+key+'_trades.csv'} for key in n],
            'family':'S016_DAILY_CLOSE_DONCHIAN' if ident=='S016' else r['research_family'],
            'historically_qualified':False,'independent_profitable_edge_certified':False,'score':None,'execution_enabled':False})
    write(a.out/'83_strategy_register.json',{'schema':'oracle.gold.phase04.original83_register.v1','rows':rows,
        'source_obtained_ids':74,'source_blocked_ids':9,'all83_full_native_dependency_and_execution_verification':False,
        'new_native_account_ids':2,'new_unique_account_comparisons':18,'repeated_runtime_replay_is_not_new_strategies':True,
        'unresolved_duplicate_comparisons':[{'a':p['a'],'b':p['b'],'reason':'Original source still inaccessible; no new rule evidence'} for p in oldpairs if p['classification']=='UNRESOLVED_SOURCE_BLOCKED'],
        'native_mql5_source_files_compiled':17,'native_mql5_original_ids_covered':21,
        'provisional_research_families':len(ranked),'historically_qualified_families':0,
        'native_compilation_ci':'https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/40742985260',
        'native_accounts_ci':receipt['ci'],'dependency_inventory':'reports/gold_oracle/phase04/dependency_inventory_python312.json',
        'prior_evidence_unchanged':True,'deployment_or_trading_activation':False})
    lines=['# Phase04 source-native verification and research shortlist','',
        'Research remains OPEN. Prior source audits, losses and ledgers are unchanged.74 source-obtained systems remain the research priority; nine inaccessible sources do not block the others.','',
        '## Provisional research candidate','',
        '**S016, 20/20-day close-channel variant** is the only new family passing the observed-period screen. This is a provisional cash-model candidate, not Oracle Hub qualification. Its 95-day sibling is retained in the same family and loses in 2023. The screen is post-hoc; there is no fresh holdout.','',
        '| Account / stress costs | Net marked USD |2023 net|2024 net|2025 net|Closed trades|Minute-close DD|',
        '|---|---:|---:|---:|---:|---:|---:|']
    for key in ('S016_entry20_risk1_ORIGINAL_CAPITAL_common_stress','S016_entry20_risk1_STANDARDISED_CAPITAL_COMPARISON_common_stress','S016_entry95_risk2_STANDARDISED_CAPITAL_COMPARISON_common_stress','S019_default_cascade_D1_H1_M15_STANDARDISED_CAPITAL_COMPARISON_common_stress'):
        m=report['models'][key];ys=m['years']
        lines.append(f"|{m['id']} {m['variant']}, {m['initial_capital']:,.0f} initial|{m['net_marked_usd']:,.2f}|{ys[0]['net_usd']:,.2f}|{ys[1]['net_usd']:,.2f}|{ys[2]['net_usd']:,.2f}|{m['closed_trades']}|{m['minute_close_marked_drawdown_pct']:.3f}%|")
    chosen=ranked[0];benchmark=benchmarks['10000_common_stress']
    lines+=['',f"S01620/20 standard10k: {chosen['profitable_months']}/36 profitable months, worst month {chosen['worst_month_pct']:.3f}%, closed net after removing largest winner {chosen['closed_net_without_largest_winner_usd']:,.2f}USD. The last position remains open; no invented final liquidation.",'',
        f"Comparable passive95%-initial-cash gold benchmark: marked net {benchmark['net_marked_usd']:,.2f}USD, minute-close DD {benchmark['minute_close_drawdown_pct']:.3f}%. S016 trails this rising-gold passive return. Positive observed P&L does not establish alpha, fresh validation or broker execution readiness.",'',
        '## Actual native engineering','',
        f"[Exact source-dependency CI]({receipt['ci']}), code `{receipt['code_commit']}`:18 original/standardised-capital cases, no failed cases.13 AIDY tests and35 selected original S019 tests pass. Exact original S019 dependency pins satisfied. Every financial result and trade-record hash matches the earlier compatible-stack replay. These repeated cases are not additional strategies.",'',
        '[MetaEditor CI](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/40742985260):17 unchanged MQL5 files covering21 original IDs compile with the signed official compiler/SDK. Source/program/dependency hashes and logs retained. SessionRangeBreakout has two warnings; other files zero warnings. Compilation does not prove broker execution parity. The disposable SDK initialisation ran with terminal networking blocked, no account/EA/script supplied and trading disabled; no live server or broker account touched.','',
        '[S018 MQL4 attempt](https://github.com/dannythehat/Aidy-Gold-Signals/actions/runs/40744001451):MetaEditor5 rejects the MQL4 extension. This is a toolchain mismatch, not proof of a native MQL4 strategy failure. All initial404/SDK-path failures and earlier local harness failures remain archived.','',
        'Repository inventory checks17 pinned repositories and263 Python files for exact byte integrity and syntax without executing acquisition/optimisation drivers. This does not certify all optional imports or every strategy runtime.','',
        '## Evidence and admission gates','',
        '[Shortlist and losing siblings](shortlist.json), [all83 IDs/gates](83_strategy_register.json), [passive benchmarks](benchmarks.json), [156 correlation/co-loss pairs and gold-month regimes](dependence_and_regimes.json), [precise S016 source/version and packaging-readiness evidence](S016_source_and_packaging_readiness.json). Complete trade/monthly/year/loss/maximum-winner evidence is in the immutable native CI archives one directory above.','',
        'Zero historically qualified families. Packaging is blocked by source redistribution rights, input-calendar/venue/fill/funding verification and independent validation. The evidence manifest is not an executable release. No paper/funded activation, merge, deployment or new strategy parameters. Existing S010 remains a secondary research watch item under its earlier native-account/funding gates; its prior profitable diagnostics are unchanged.','',
        'All83 original IDs retained. Seven duplicate comparisons remain source-blocked. Native indicators with no account rules remain account-blocked, not assigned invented sizing or returns.']
    (a.out/'REVIEW.md').write_text('\n'.join(lines)+'\n')
    print('PHASE04_REVIEW',len(ranked),'provisional family;0 qualified;',len(pairs),'dependence pairs')


if __name__=='__main__':
    main()
