"""Extend the phase03 historical Pine account model with variable quantities.

S052/S066 source defaults and source metadata are fixed. This is an explicit
continuous-unit model, NOT native platform/quantity-rounding equivalence. The
documented OHLC path, next-tick fills and gap handling follow phase03. Never
infer a broker's margin, lot step, financing or authentic ASK from this BID tape.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.oracle_gold.history import digest
from scripts.oracle_gold.native_python_accounts import snapshots
from scripts.oracle_gold.phase05_native_accounts import performance
from scripts.oracle_gold.pine_fixed_accounts import rma
from scripts.oracle_gold.recover_sources import get

ROOT = Path(__file__).resolve().parents[2]
PINS = ROOT/'research/gold_oracle/phase05/pine_source_pins.json'
COSTS = {'source_declared': 0., 'common_base': .47, 'common_stress': 1.44}


def source(ident, root):
    pin = json.loads(PINS.read_text())[ident]['source']
    path = root/(ident+'.pine')
    if not path.exists():
        raw, _ = get(pin['endpoint'])
        value = json.loads(raw)
        if value.get('scriptAccess') != 'open_no_auth':
            raise ValueError('Source is not publicly executable')
        root.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value['source'].encode())
    if hashlib.sha256(path.read_bytes()).hexdigest() != pin['sha256']:
        raise ValueError('Original source bytes changed')


def supertrend(x):
    previous = x.close.shift()
    tr = pd.concat([x.high-x.low, (x.high-previous).abs(), (x.low-previous).abs()], axis=1).max(axis=1)
    atr = rma(tr, 10)
    upper = (x.high+x.low)/2+2*atr
    lower = (x.high+x.low)/2-2*atr
    line, direction = np.full(len(x), np.nan), np.ones(len(x))
    # Literal published Pine reference algorithm, including +1=downtrend.
    for i in range(len(x)):
        prev_upper = upper.iloc[i-1] if i and np.isfinite(upper.iloc[i-1]) else 0.
        prev_lower = lower.iloc[i-1] if i and np.isfinite(lower.iloc[i-1]) else 0.
        prev_close = previous.iloc[i]
        lower.iloc[i] = lower.iloc[i] if lower.iloc[i] > prev_lower or prev_close < prev_lower else prev_lower
        upper.iloc[i] = upper.iloc[i] if upper.iloc[i] < prev_upper or prev_close > prev_upper else prev_upper
        if i and np.isfinite(atr.iloc[i-1]):
            if line[i-1] == prev_upper:
                direction[i] = -1 if x.close.iloc[i] > upper.iloc[i] else 1
            else:
                direction[i] = 1 if x.close.iloc[i] < lower.iloc[i] else -1
        line[i] = lower.iloc[i] if direction[i] == -1 else upper.iloc[i]
    return line, direction


def features(frame, ident):
    minutes = 60 if ident == 'S052' else 5
    g = frame.resample(f'{minutes}min', label='left', closed='left')
    x = g.agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'})
    x = x.loc[g.close.count() == minutes].copy()
    tr = pd.concat([x.high-x.low, (x.high-x.close.shift()).abs(), (x.low-x.close.shift()).abs()], axis=1).max(axis=1)
    x['atr'] = rma(tr, 14)
    hours = x.index.tz_convert('America/New_York').hour
    if ident == 'S052':
        in_asia = (hours >= 0)&(hours < 8)
        in_kill = (hours >= 9)&(hours < 17)
        hi, lo, was_asia = 0., 0., False
        buys, sells = [], []
        for i, row in enumerate(x.itertuples()):
            if in_asia[i] and not was_asia:
                hi, lo = row.high, row.low
            elif in_asia[i]:
                hi, lo = max(hi, row.high), min(lo, row.low)
            was_asia = in_asia[i]
            buys.append(bool(i >= 2 and in_kill[i] and x.close.iloc[i-2] >= lo and x.close.iloc[i-1] < lo and row.close > lo))
            sells.append(bool(i >= 2 and in_kill[i] and x.close.iloc[i-2] <= hi and x.close.iloc[i-1] > hi and row.close < hi))
        x['buy'], x['sell'] = buys, sells
    else:
        x['st'], x['st_dir'] = supertrend(x)
        d = x.close.diff()
        gain, loss = rma(d.clip(lower=0), 14), rma((-d).clip(lower=0), 14)
        rsi = (100-100/(1+gain/loss)).mask(loss == 0, 100.).mask((gain == 0)&(loss != 0), 0.)
        x['session'] = (hours >= 7)&(hours < 19)
        x['buy'] = x.session&(x.st_dir == 1)&(rsi > 55)&(rsi.shift() <= 55)
        x['sell'] = x.session&(x.st_dir == -1)&(rsi < 45)&(rsi.shift() >= 45)
    return x


@dataclass
class Position:
    side: int
    quantity: float
    entry: float
    entry_time: str
    entry_fee: float
    stop: float | None
    target: float | None


def evaluate(x, ident, initial, scenario):
    fee = COSTS[scenario]/2
    minutes = 60 if ident == 'S052' else 5
    margin = 0. if ident == 'S052' else 100.  # language version5 vs6 source defaults
    balance, position, pending = initial, None, None
    trades, equity, rejected = [], [], []
    peak, worst, ties, max_notional = initial, 0., 0, 0.

    def marked(price):
        return balance+(position.side*(price-position.entry)*position.quantity if position else 0.)

    def track(price):
        nonlocal peak, worst, max_notional
        value = marked(price)
        peak = max(peak, value)
        worst = min(worst, (value/peak-1)*100)
        if position:
            max_notional = max(max_notional, position.quantity*price/value if value > 0 else 1e99)
            if margin and value+1e-8 < position.quantity*price*margin/100:
                raise ValueError('Native margin liquidation required; no invented stopout')

    def close(price, stamp, reason):
        nonlocal balance, position
        if not position:
            return
        p = position
        exit_fee = p.quantity*fee
        gross = p.side*(price-p.entry)*p.quantity
        balance += gross-exit_fee
        trades.append({'entry_ts': p.entry_time, 'exit_ts': stamp, 'direction': 'BUY' if p.side == 1 else 'SELL',
            'entry_reference': p.entry, 'exit_reference': price, 'units': p.quantity,
            'gross_usd': gross, 'trading_cost_usd': p.entry_fee+exit_fee,
            'pnl': gross-p.entry_fee-exit_fee, 'reason': reason})
        position = None

    def enter(side, quantity, price, stamp, bracket):
        nonlocal balance, position
        if position and position.side == side:
            return
        value = marked(price)
        if margin and value-quantity*fee < quantity*price*margin/100:
            rejected.append({'utc': stamp, 'reason': 'SOURCE_DEFAULT_MARGIN_AFFORDABILITY', 'requested_units': quantity,
                'required_margin': quantity*price*margin/100, 'equity': value})
            return
        if position:
            close(price, stamp, 'SOURCE_REVERSAL')
        entry_fee = quantity*fee
        balance -= entry_fee
        position = Position(side, quantity, price, stamp, entry_fee,
            bracket[0] if bracket else None, bracket[1] if bracket else None)

    for stamp, row in x.iterrows():
        ts = stamp.isoformat()
        if pending:
            enter(pending[0], pending[1], row.open, ts, pending[2])
            pending = None
        track(row.open)
        if abs(row.high-row.open) < abs(row.open-row.low):
            path = (row.open, row.high, row.low, row.close)
        else:
            ties += int(abs(row.high-row.open) == abs(row.open-row.low) and position is not None)
            path = (row.open, row.low, row.high, row.close)
        if position and position.stop is not None:
            hit_stop = position.side*(row.open-position.stop) <= 0
            hit_target = position.side*(row.open-position.target) >= 0
            if hit_stop or hit_target:
                close(row.open, ts, 'STOP_GAP' if hit_stop else 'TARGET_GAP')
        for a, b in pairwise(path):
            if position and position.stop is not None:
                levels = [(v, label) for v, label in ((position.stop, 'STOP'), (position.target, 'TARGET')) if min(a, b) <= v <= max(a, b)]
                if levels:
                    price, reason = min(levels, key=lambda z: abs(z[0]-a))
                    track(price)
                    close(price, ts, reason)
            track(b)
        end_time = (stamp+pd.Timedelta(minutes=minutes)).isoformat()
        side = 1 if row.buy else -1 if row.sell else 0
        if ident == 'S052' and side and np.isfinite(row.atr) and row.atr > 0:
            distance = row.atr*1.5
            quantity = marked(row.close)*.01/distance
            bracket = (row.close-side*distance, row.close+side*distance*2)
            if position and position.side == side:
                position.stop, position.target = bracket  # entry refused by pyramiding, exit still modified
            else:
                pending = (side, quantity, bracket)
        elif ident == 'S066':
            # Original script calculates exits using the visible old position,
            # then processes its market entry/reversal at this bar's close.
            if position and np.isfinite(row.st):
                risk = max(abs(position.entry-row.st), abs(row.close-row.st), .01*10)
                position.stop = position.entry-position.side*risk
                position.target = position.entry+position.side*risk*2
            if side and (not position or position.side != side):
                enter(side, 240000/row.close, row.close, end_time, None)
            if position and position.stop is not None:
                # process_orders_on_close also applies to an already-marketable
                # freshly replaced bracket. A reversal above removed old exits.
                crossed_stop = position.side*(row.close-position.stop) <= 0
                crossed_target = position.side*(row.close-position.target) >= 0
                if crossed_stop or crossed_target:
                    close(row.close, end_time, 'STOP_MARKETABLE_ON_CLOSE' if crossed_stop else 'TARGET_MARKETABLE_ON_CLOSE')
            if not row.session and position:
                close(row.close, end_time, 'SOURCE_SESSION_END')
        equity.append((stamp, marked(row.close)))
    series = pd.Series(dict(equity))
    t = pd.DataFrame(trades)
    realised = float(t.pnl.sum()) if len(t) else 0.
    if abs(balance-(initial+realised-(position.entry_fee if position else 0.))) > 1e-5:
        raise ValueError('Account cash ledger does not reconcile')
    stats = performance(series, t, initial)
    stats.update({'strategy_id': ident, 'scenario': scenario, 'initial_capital': initial,
        'net_marked_usd': float(series.iloc[-1]-initial), 'closed_net_usd': realised,
        'unrealised_reference_usd': float(series.iloc[-1]-balance),
        'open_positions_at_end': int(position is not None), 'rejected_entries': len(rejected),
        'max_modelled_pine_path_drawdown_pct': worst, 'max_notional_to_equity': max_notional,
        'equal_distance_path_bars_unverified': ties, 'original_quantity_formula_preserved': True,
        'quantity_precision': 'CONTINUOUS_SOURCE_FORMULA; native mincontract not attested',
        'native_platform_output_parity': False, 'funding_broker_terms_verified': False,
        'status': 'SOURCE_FORMULA_ACCOUNT_DIAGNOSTIC_NOT_NATIVE_QUALIFIED', 'ledger_sha256': digest(trades)})
    return stats, trades, rejected


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--snapshots', type=Path, required=True)
    p.add_argument('--sources', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        raise ValueError('Immutable result folder exists')
    a.out.mkdir(parents=True)
    frame, manifests = snapshots(a.snapshots)
    results, prefixes = {}, {}
    for ident, native in [('S052', 25000.), ('S066', 1000000.)]:
        source(ident, a.sources)
        x = features(frame, ident)
        prefixes[ident] = []
        for year in (2024, 2025):
            cut = pd.Timestamp(f'{year}-01-01', tz='UTC')
            part = features(frame.loc[frame.index < cut], ident)
            same = x.loc[part.index, ['buy', 'sell']].equals(part[['buy', 'sell']])
            prefixes[ident].append({'cut': cut.isoformat(), 'same': same})
        if not all(c['same'] for c in prefixes[ident]):
            raise ValueError('Signal prefix changed')
        for label, capital in [('original', native), ('standard10000', 10000.)]:
            for scenario in COSTS:
                key = f'{ident}_{label}_{scenario}'
                stats, trades, rejected = evaluate(x, ident, capital, scenario)
                pd.DataFrame(trades).to_csv(a.out/(key+'_trades.csv'), index=False)
                pd.DataFrame(rejected).to_csv(a.out/(key+'_rejected_entries.csv'), index=False)
                for interval in ('daily', 'weekly', 'monthly', 'yearly'):
                    pd.DataFrame(stats[interval]).to_csv(a.out/(key+'_'+interval+'.csv'), index=False)
                results[key] = stats
                print('PINE_SOURCE_FORMULA_ACCOUNT', key, stats['closed_trades'], stats['net_marked_usd'], flush=True)
    report = {'schema': 'oracle.gold.phase05.pine_variable_accounts.v1', 'models': results,
        'source_pins': json.loads(PINS.read_text()), 'signal_prefix_checks': prefixes, 'input_manifests': manifests,
        'scope': 'Two distinct original formula models. Native fractional rounding/platform parity is NOT verified. BID chart from prior authenticated M1, complete bars only; genuine gaps remain.',
        'costs': 'Source friction0 or separate existing AIDY .47/1.44 USD per ounce RT overlays; excludes unverified funding.',
        'source_rules_changed': False, 'qualified': False, 'packaging_ready': False, 'sealed_oos': False}
    (a.out/'report.json').write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+'\n')


if __name__ == '__main__':
    main()
