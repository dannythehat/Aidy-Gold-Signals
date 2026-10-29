"""Native evidence and admission decisions; no promotion from profit alone."""
import copy
import hashlib
import json
import zipfile
from pathlib import Path

import backtrader

from scripts.oracle_gold.phase04_review import native_packet, screen

ROOT=Path(__file__).resolve().parents[1]
P=ROOT/'reports/gold_oracle/phase04'


def read(path):
    return json.loads(path.read_text())


def test_every_pre_phase04_evidence_byte_is_unchanged():
    pins=read(ROOT/'research/gold_oracle/phase04/protected_evidence.json')['file_sha256']
    assert len(pins)==256
    for path,digest in pins.items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest,path


def test_native_original_account_replays_and_runtime_lock_are_independently_reconciled():
    exact,_=native_packet(P/'native_accounts_exact_stack')
    prior,_=native_packet(P/'native_accounts')
    assert exact['source_manifests']['S019']['source_declared_runtime_lock']['all_satisfied'] is True
    assert len(exact['models'])==18 and not exact['failed_attempts']
    for key,m in exact['models'].items():
        assert m['net_marked_usd']==prior['models'][key]['net_marked_usd']
        assert m['trade_records_sha256']==prior['models'][key]['trade_records_sha256']
        assert m['source_rules_modified'] is False and m['native_broker_qualified'] is False
        if key.startswith('S019'):
            assert m['net_marked_usd']<0
        if 'ORIGINAL_CAPITAL' in key:
            assert m['initial_capital']==(10_000_000 if key.startswith('S016') else 100_000)
        else:
            assert m['initial_capital']==10_000


def test_repeatability_screen_rejects_positive_total_with_bad_year_or_single_winner():
    policy=read(ROOT/'research/gold_oracle/phase04/shortlist_policy.json')
    report,_=native_packet(P/'native_accounts_exact_stack')
    model=report['models']['S016_entry20_risk1_STANDARDISED_CAPITAL_COMPARISON_common_stress']
    assert not screen(model,policy)
    bad=copy.deepcopy(model);bad['years'][0]['net_usd']=-1.
    assert 'NONPOSITIVE_STRESS_PERIOD_2023' in screen(bad,policy)
    bad=copy.deepcopy(model);bad['closed_net_without_largest_winner_usd']=-1.
    assert 'CLOSED_PROFIT_DEPENDS_ON_LARGEST_WINNER_OR_IS_NONPOSITIVE' in screen(bad,policy)
    sibling=report['models']['S016_entry95_risk2_STANDARDISED_CAPITAL_COMPARISON_common_stress']
    assert 'NONPOSITIVE_STRESS_PERIOD_2023' in screen(sibling,policy)


def test_native_compile_success_is_exact_source_and_does_not_imply_mql4_or_broker_parity():
    r=read(P/'native_compile_attempt04/report.json')
    assert r['standard_library_available'] is True
    assert r['compiler']['signature']=='Valid'
    assert len(r['sources'])==17
    assert len({i for s in r['sources'] for i in s['ids']})==21
    assert r['terminal_processes_running']==0 and r['broker_connection'] is False
    assert r['sdk_initialisation']['network']=='INBOUND_AND_OUTBOUND_BLOCKED_BEFORE_START'
    with zipfile.ZipFile(P/'native_compile_attempt04/artifact.zip') as z:
        for s in r['sources']:
            assert s['status']=='NATIVE_COMPILED' and not s['source_modified']
            raw=z.read(s['path']+'.log')
            assert hashlib.sha256(raw).hexdigest()==s['log_sha256']
            assert 'Result: 0 errors' in raw.decode('utf-16')
    wrong=read(P/'native_compile_attempt05/report.json')
    assert wrong['sources'][0]['ids']==['S018']
    assert wrong['sources'][0]['status']=='NATIVE_COMPILE_FAILED'
    with zipfile.ZipFile(P/'native_compile_attempt05/artifact.zip') as z:
        assert 'unsupported file extension' in z.read('XAUUSD Breakout.mq4.log').decode('utf-16')


def test_backtrader_native_library_source_release_matches_pinned_files():
    pin=read(ROOT/'research/gold_oracle/phase04/backtrader_runtime_pin.json')
    assert backtrader.__version__==pin['version']
    root=Path(backtrader.__file__).parent
    for name,digest in pin['python_source_sha256'].items():
        assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,name


def test_all_original_ids_and_blockers_survive_provisional_shortlist_without_packaging():
    register=read(P/'review/83_strategy_register.json')
    assert [r['id'] for r in register['rows']]==[f'S{i:03}' for i in range(1,84)]
    assert len(register['unresolved_duplicate_comparisons'])==7
    assert sum(len(r['new_account_cases']) for r in register['rows'])==18
    assert register['historically_qualified_families']==0
    shortlist=read(P/'review/shortlist.json')
    assert len(shortlist['provisional_research_candidates'])==1
    assert shortlist['provisional_research_candidates'][0]['variant']=='entry20_risk1'
    assert shortlist['historically_qualified']==[]
    assert not shortlist['provisional_research_candidates'][0]['beats_passive_net_return']
    readiness=read(P/'review/S016_source_and_packaging_readiness.json')
    assert readiness['observed_period_screen_passed'] is True
    assert not readiness['historically_qualified'] and not readiness['release_package_created']
    assert readiness['execution_enabled'] is False and readiness['real_money_enabled'] is False
