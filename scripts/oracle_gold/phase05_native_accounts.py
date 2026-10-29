"""S083 original001B reference engine on authentic archived bid/ask history.

Source engine, sizing, rounded reporting, gap-stop and timeout behaviour remain
unchanged. Observer receipts make defects visible, never silently repair them.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from scripts.oracle_gold.history import digest

ROOT = Path(__file__).resolve().parents[2]
PIN = ROOT/'research/gold_oracle/phase05/S083_source_pin.json'


def verify_source(root):
    pin = json.loads(PIN.read_text())
    for name, sha in pin['files'].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest() != sha:
            raise ValueError('S083 original file changed: '+name)
    return pin


def quotes(root):
    frames, receipts = [], []
    for year in (2023, 2024, 2025):
        for month in range(1, 13):
            period = f'{year}{month:02d}'
            folder = root/period
            manifest = json.loads((folder/'manifest.json').read_text())
            if digest({k: v for k, v in manifest.items() if k != 'sha256'}) != manifest['sha256']:
                raise ValueError('Quote manifest changed')
            if manifest['receipt']['period_fixed_est'] != period:
                raise ValueError('Quote period mismatch')
            if hashlib.sha256((folder/'bidask.csv').read_bytes()).hexdigest() != manifest['csv_sha256']:
                raise ValueError('Quote CSV changed')
            x = pd.read_csv(folder/'bidask.csv')
            if len(x) != manifest['rows']:
                raise ValueError('Quote row count changed')
            x.index = pd.to_datetime(x.pop('open_time_utc'), utc=True)
            frames.append(x)
            receipts.append(manifest)
    x = pd.concat(frames).sort_index()
    if x.index.has_duplicates:
        raise ValueError('Overlapping monthly source quotes')
    x = x.loc[(x.index >= '2023-01-01') & (x.index < '2026-01-01')].copy()
    x.index.name = 'ts'
    for s in ('o', 'h', 'l', 'c'):
        x[s] = (x['bid_'+s]+x['ask_'+s])/2  # original dataset.py chart construction
    return x, receipts


def build(m1, dataset):
    m15 = dataset.resample(m1, '15min')
    return m15.join(dataset.tag_sessions(m15.index)), dataset.resample(m1, '4h'), dataset.resample(m1, '1D')


def performance(equity, trades, initial):
    result = {}
    for freq, label in [('D', 'daily'), ('W-SUN', 'weekly'), ('ME', 'monthly'), ('YE', 'yearly')]:
        ends = equity.resample(freq).last().dropna()
        starts = ends.shift(fill_value=initial)
        result[label] = [{'period': t.isoformat(), 'start_equity': float(starts.loc[t]),
            'end_equity': float(v), 'net_usd': float(v-starts.loc[t]),
            'return_pct': float((v/starts.loc[t]-1)*100)} for t, v in ends.items()]
    pnl = trades.pnl if len(trades) else pd.Series(dtype=float)
    peak = pd.concat([pd.Series([initial]), equity.reset_index(drop=True)]).cummax()
    dd = pd.concat([pd.Series([initial]), equity.reset_index(drop=True)])/peak-1
    longest = run = 0
    for value in result['daily']:
        run = run+1 if value['end_equity'] < initial else 0
        longest = max(longest, run)
        initial = max(initial, value['end_equity'])
    losses = -float(pnl[pnl < 0].sum())
    result.update({'closed_trades': len(trades), 'win_rate_pct': float((pnl > 0).mean()*100) if len(pnl) else None,
        'profit_factor': float(pnl[pnl > 0].sum()/losses) if losses else None,
        'expectancy_usd': float(pnl.mean()) if len(pnl) else None,
        'largest_closed_winner_usd': max(0., float(pnl.max())) if len(pnl) else 0.,
        'closed_net_without_largest_winner_usd': float(pnl.sum()-max(0., pnl.max())) if len(pnl) else 0.,
        'max_minute_close_equity_drawdown_pct': float(dd.min()*100),
        'longest_observed_daily_underwater_period': longest,
        'average_trades_per_week': len(trades)/(len(equity.resample('W').last())),
        'long_net_usd': float(trades.loc[trades.direction == 'BUY', 'pnl'].sum()) if len(trades) else 0.,
        'short_net_usd': float(trades.loc[trades.direction == 'SELL', 'pnl'].sum()) if len(trades) else 0.})
    return result


def simulate_observed(engine, sig, m15, m1, cfg):
    calls = []
    original_walk = engine._walk

    def observe(*args, **kwargs):
        answer = original_walk(*args, **kwargs)
        calls.append((args[1:], answer))
        return answer

    engine._walk = observe
    try:
        trades = engine.simulate(sig, m15, m1, cfg)
    finally:
        engine._walk = original_walk
    if len(calls) != len(trades):
        raise ValueError('Original walk observer mismatch')
    changes = pd.Series(0., index=m1.index)
    holdings = pd.Series(0., index=m1.index)
    entry_cost_basis = pd.Series(0., index=m1.index)
    capital = cfg.start_equity
    observations = []
    for row, (args, answer) in zip(trades.itertuples(), calls, strict=True):
        direction, entry, stop, _target, t_entry, t_limit, _slip = args
        if answer is None:
            t_exit = t_limit
            price = float(m15.loc[t_exit].bid_c if direction > 0 else m15.loc[t_exit].ask_c)
            reason = 'timeout'
        else:
            t_exit, price, reason = answer
        size = capital*cfg.risk_pct/100/abs(entry-stop)
        net = (price-entry)*direction*size
        capital += net
        if abs(round(capital, 2)-row.equity) > .001 or abs(round(net, 2)-row.pnl) > .001:
            raise ValueError('Original source equity parity failed')
        # Mark-to-liquidation quotes while holding. Native timeout timestamp
        # remains intentionally defective and is explicitly counted below.
        changes.loc[t_exit] += net
        holdings.loc[t_entry] += direction*size
        holdings.loc[t_exit] -= direction*size
        entry_cost_basis.loc[t_entry] += direction*size*entry
        entry_cost_basis.loc[t_exit] -= direction*size*entry
        observations.append({'entry_ts': t_entry.isoformat(), 'exit_ts': t_exit.isoformat(),
            'entry_exact': entry, 'exit_exact': price, 'units_exact': size, 'pnl_exact': net,
            'gap_stop_inaccurate': bool(reason == 'stop' and ((direction > 0 and m1.loc[t_exit].bid_o < stop) or (direction < 0 and m1.loc[t_exit].ask_o > stop))),
            'timeout_close_price_at_open_timestamp': reason == 'timeout'})
    units = holdings.cumsum()
    liquidation_quote = m1.bid_c.where(units >= 0, m1.ask_c)
    equity = cfg.start_equity+changes.cumsum()+units*liquidation_quote-entry_cost_basis.cumsum()
    if abs(float(equity.iloc[-1])-capital) > 1e-6:
        raise ValueError('Observer marked ledger reconciliation failed')
    return trades, equity, observations


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--quotes', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        raise ValueError('Immutable result folder exists')
    a.out.mkdir(parents=True)
    pin = verify_source(a.source)
    sys.path.insert(0, str((a.source/'src').resolve()))
    dataset, strategy, engine, costs = [importlib.import_module(n) for n in ('dataset', 'strategy', 'engine', 'costs')]
    m1, receipts = quotes(a.quotes)
    m15, h4, d1 = build(m1, dataset)
    sig, rejected = strategy.generate_signals(m15, h4, d1, 'B', 'ema50', True)
    sig.to_csv(a.out/'S083_signals.csv', index=False)
    rejected.to_csv(a.out/'S083_refused_setups.csv', index=False)
    prefix = []
    for year in (2024, 2025):
        cut = pd.Timestamp(f'{year}-01-01', tz='UTC')
        p15, p4, pd1 = build(m1.loc[m1.index < cut], dataset)
        part, _ = strategy.generate_signals(p15, p4, pd1, 'B', 'ema50', True)
        full_known = sig.loc[sig.entry_ts < cut].reset_index(drop=True) if len(sig) else sig
        part_known = part.loc[part.entry_ts < cut].reset_index(drop=True) if len(part) else part
        same = full_known.to_json(date_format='iso') == part_known.to_json(date_format='iso')
        prefix.append({'cut': cut.isoformat(), 'full_known': len(full_known), 'partial_known': len(part_known), 'same': same})
    results = {}
    for scenario, spread, slip in [('source_real_spread', 1., .05), ('source_double_spread', 2., .05), ('source_stressed_spread_slippage', 2., .10)]:
        # Original $10k equals the requested standard comparison; one actual
        # computation, two labels, never counted as two independent trials.
        q1, q15 = costs.rescale(m1, spread), costs.rescale(m15, spread)
        cfg = engine.Config(r_multiple=2., risk_pct=.25)
        cfg.slippage = slip
        trades, equity, obs = simulate_observed(engine, sig, q15, q1, cfg)
        trades.to_csv(a.out/f'S083_{scenario}_trades.csv', index=False)
        (a.out/f'S083_{scenario}_observer.json').write_text(json.dumps(obs, indent=2)+'\n')
        stats = performance(equity, trades, cfg.start_equity)
        for label in ('daily', 'weekly', 'monthly', 'yearly'):
            pd.DataFrame(stats[label]).to_csv(a.out/f'S083_{scenario}_{label}.csv', index=False)
        stats.update({'config': asdict(cfg), 'net_marked_usd': float(equity.iloc[-1]-cfg.start_equity),
            'source_trade_ledger_sha256': hashlib.sha256((a.out/f'S083_{scenario}_trades.csv').read_bytes()).hexdigest(),
            'gap_stop_underfill_cases': sum(o['gap_stop_inaccurate'] for o in obs),
            'timeout_clock_defect_cases': sum(o['timeout_close_price_at_open_timestamp'] for o in obs),
            'observed_equity_parity': True, 'native_broker_execution_verified': False,
            'commission_swap_margin_lot_steps_verified': False, 'open_positions_at_end': 0,
            'account_labels': ['original10000', 'standard10000_same_account'],
            'status': 'SOURCE_NATIVE_ACCOUNT_DIAGNOSTIC_EXECUTION_GATES_BLOCKED'})
        results[scenario] = stats
        print('SOURCE_NATIVE_S083', scenario, len(trades), stats['net_marked_usd'], flush=True)
    report = {'schema': 'oracle.gold.phase05.S083_native.v1', 'source': pin, 'source_rules_changed': False,
        'original_strategy': '001B/ema50/session/2R/0.25percent', 'models': results, 'prefix_checks': prefix,
        'input_receipts': receipts, 'input_rows': len(m1), 'signals': len(sig), 'refused_setups': len(rejected),
        'complete_calendar_verified': False, 'previously_examined_period_not_sealed_oos': True,
        'cost_scope': 'Original engine quoted spreads and source slippage stress. Commission/funding/margin absent from source; not invented or called all-in broker net.',
        'input_application': 'Authentic HistData R2 ticks, not publisher Dukascopy chart feed; source-native resample and averaged bid/ask mid-chart retained.',
        'qualification_passed': False, 'packaging_ready': False}
    (a.out/'report.json').write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+'\n')


if __name__ == '__main__':
    main()
