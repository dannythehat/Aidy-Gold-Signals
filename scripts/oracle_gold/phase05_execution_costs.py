"""Auditable execution sensitivity using S083's original account engine.

Keep every original result. Narrow in-memory execution changes only: gap-stop
fills use the worse observed opening quote; existing AIDY cash cost allowances
are debited BEFORE the next source equity-risk sizing. No strategy/parameter
change, invented financing or broker terms. This is not native equivalence.
"""
import argparse
import hashlib
import importlib
import inspect
import json
import sys
from pathlib import Path

import pandas as pd

from aidy.strategy_lab_s010_backtest import BASE, STRESS
from scripts.oracle_gold.phase05_native_accounts import build, performance, quotes, verify_source


def cost_engine(engine, allowance):
    native = inspect.getsource(engine.simulate)
    old = 'pnl = (exit_px - entry) * s.direction * size'
    new = 'pnl = (exit_px - entry) * s.direction * size - size * AIDY_CASH_ALLOWANCE'
    if native.count(old) != 1:
        raise ValueError('Original engine execution statement changed')
    changed = native.replace(old, new)
    scope = dict(engine.__dict__)
    scope['AIDY_CASH_ALLOWANCE'] = allowance
    original_walk = engine._walk

    def gap_floor(m1, direction, entry, stop, target, t_from, t_to, slip):
        result = original_walk(m1, direction, entry, stop, target, t_from, t_to, slip)
        if result and result[2] == 'stop':
            ts = result[0]
            # A long can only sell at BID; a short must buy at ASK. A price
            # already beyond a stop cannot magically fill at the old level.
            quote = float(m1.loc[ts, 'bid_o' if direction > 0 else 'ask_o'])
            price = min(stop, quote)-slip if direction > 0 else max(stop, quote)+slip
            return ts, price, result[2]
        return result

    scope['_walk'] = gap_floor
    exec(compile(changed, '<S083 original simulate; one disclosed cost expression>', 'exec'), scope)  # noqa: S102 - pinned, reviewed source function only
    return scope['simulate'], scope, {'native_function_sha256': hashlib.sha256(native.encode()).hexdigest(),
        'cost_function_sha256': hashlib.sha256(changed.encode()).hexdigest(),
        'exact_expression_change': {'before': old, 'after': new},
        'source_files_modified': False, 'strategy_parameters_changed': False,
        'gap_execution': 'Long min(stop,observed minute BID open)-source slippage; short max(stop,observed minute ASK open)+source slippage'}


def observed(engine, sig, m15, m1, cfg, allowance):
    run, scope, receipt = cost_engine(engine, allowance)
    original_walk = scope['_walk']
    calls = []

    def capture(*args):
        answer = original_walk(*args)
        calls.append((args[1:], answer))
        return answer

    scope['_walk'] = capture
    trades = run(sig, m15, m1, cfg)
    changes = pd.Series(0., index=m1.index)
    units = pd.Series(0., index=m1.index)
    basis = pd.Series(0., index=m1.index)
    capital, records = cfg.start_equity, []
    for row, (args, result) in zip(trades.itertuples(), calls, strict=True):
        direction, entry, stop, _target, ts, limit, _slip = args
        exit_ts, exit_price, reason = result if result else (limit, float(m15.loc[limit, 'bid_c' if direction > 0 else 'ask_c']), 'timeout')
        size = capital*cfg.risk_pct/100/abs(entry-stop)
        charge = size*allowance
        gross = (exit_price-entry)*direction*size
        net = gross-charge
        capital += net
        if abs(round(capital, 2)-row.equity) > .001 or abs(round(net, 2)-row.pnl) > .001:
            raise ValueError('Cost-aware source cash/sizing parity failed')
        # Observer books at first genuinely observed M1, never fabricates a
        # missing quote at the source-resampler's calendar bucket label.
        actual_entry = m1.index[m1.index.searchsorted(ts)]
        actual_exit = m1.index[m1.index.searchsorted(exit_ts)]
        changes.loc[actual_entry] -= charge/2
        changes.loc[actual_exit] += gross-charge/2
        units.loc[actual_entry] += direction*size
        units.loc[actual_exit] -= direction*size
        basis.loc[actual_entry] += direction*size*entry
        basis.loc[actual_exit] -= direction*size*entry
        records.append({'entry_ts': ts.isoformat(), 'exit_ts': exit_ts.isoformat(),
            'first_observed_entry_minute': actual_entry.isoformat(), 'first_observed_exit_minute': actual_exit.isoformat(),
            'direction': 'BUY' if direction > 0 else 'SELL', 'entry': entry, 'exit': exit_price,
            'units_exact': size, 'gross_exact_usd': gross, 'cash_cost_exact_usd': charge, 'pnl': net,
            'reason': reason, 'timeout_clock_defect': reason == 'timeout'})
    holding = units.cumsum()
    quote = m1.bid_c.where(holding >= 0, m1.ask_c)
    equity = cfg.start_equity+changes.cumsum()+holding*quote-basis.cumsum()
    if abs(float(equity.iloc[-1])-capital) > 1e-6:
        raise ValueError('Cost observer did not reconcile')
    return pd.DataFrame(records), equity, receipt


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--quotes', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        raise ValueError('Immutable result directory exists')
    a.out.mkdir(parents=True)
    pin = verify_source(a.source)
    sys.path.insert(0, str((a.source/'src').resolve()))
    dataset, strategy, engine = [importlib.import_module(n) for n in ('dataset', 'strategy', 'engine')]
    m1, receipts = quotes(a.quotes)
    m15, h4, d1 = build(m1, dataset)
    sig, _ = strategy.generate_signals(m15, h4, d1, 'B', 'ema50', True)
    results = {}
    for name, cost in [('common_base', BASE), ('common_stress', STRESS)]:
        allowance = cost.spread_usd_per_oz+2*cost.slippage_usd_per_oz_each_side+cost.commission_usd_per_oz_round_trip
        cfg = engine.Config(r_multiple=2., risk_pct=.25)
        trades, equity, receipt = observed(engine, sig, m15, m1, cfg, allowance)
        stats = performance(equity, trades, cfg.start_equity)
        stats.update({'net_marked_usd': float(equity.iloc[-1]-cfg.start_equity), 'closed_net_usd': float(trades.pnl.sum()),
            'cost_allowance_per_oz_roundtrip': allowance, 'net_costs_on_top_of_source_real_quotes_and_source_slippage': True,
            'account_initial': 10000., 'original_equals_standard10000': True,
            'execution_extension_receipt': receipt, 'timeout_defect_cases': int(trades.timeout_clock_defect.sum()),
            'total_cash_cost_usd': float(trades.cash_cost_exact_usd.sum()),
            'unverified_total_financing_budget_until_break_even_usd': max(0., float(trades.pnl.sum())),
            'funding_margin_lot_contract_verified': False, 'native_equivalence_claimed': False,
            'independent_qualification_passed': False})
        trades.to_csv(a.out/f'S083_{name}_exact_trades.csv', index=False)
        for label in ('daily', 'weekly', 'monthly', 'yearly'):
            pd.DataFrame(stats[label]).to_csv(a.out/f'S083_{name}_{label}.csv', index=False)
        results[name] = stats
        print('S083_COST_AWARE_ACCOUNT', name, len(trades), stats['net_marked_usd'], flush=True)
    (a.out/'report.json').write_text(json.dumps({'schema': 'oracle.gold.phase05.S083_execution_costs.v1',
        'source': pin, 'models': results, 'input_receipts': receipts,
        'scope': 'Disclosed narrow native-engine execution sensitivity; original strategy, defaults and net-equity percentage sizing retained. Original engine results preserved separately.',
        'cost_scope': 'Conservative existing AIDY .47/1.44 cash allowances ADD to actual quoted spreads/source slippage. Unverified financing is not assumed known or included.',
        'fresh_oos': False, 'packaging_ready': False}, indent=2, sort_keys=True, allow_nan=False)+'\n')


if __name__ == '__main__':
    main()
