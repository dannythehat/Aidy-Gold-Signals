"""Private native S040 signal trace preparation and independent comparison.

No account orders: only unchanged original CheckBreakout plus native iMA/iATR.
Custom-symbol UTC data is an explicit application, not a broker-clock receipt.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.oracle_gold.phase05_native_accounts import quotes


def prepare(root, common, private):
    frame, receipts = quotes(root)
    common.mkdir(parents=True, exist_ok=True)
    private.mkdir(parents=True, exist_ok=True)
    rows = frame[['bid_o', 'bid_h', 'bid_l', 'bid_c', 'ticks']].copy()
    rows.insert(0, 'epoch', frame.index.asi8//1000000000)
    rows.to_csv(common/'oracle_rates.csv', index=False, header=False)
    raw = frame.rename(columns={'bid_o': 'open', 'bid_h': 'high', 'bid_l': 'low', 'bid_c': 'close'})
    bars = raw.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
    bars.to_csv(private/'bars.csv')
    (private/'receipts.json').write_text(json.dumps({'source_receipts': receipts, 'm1_rows': len(frame),
        'h4_rows': len(bars), 'import_csv_sha256': hashlib.sha256((common/'oracle_rates.csv').read_bytes()).hexdigest(),
        'price_basis': 'AUTHENTIC_R2_BID; native M1 OHLC tick generation ONLY for bar-closed signals',
        'synthetic_volume': False, 'original_tick_count_used': True,
        'session_application': 'UTC custom-symbol H4; actual broker calendar/clock not asserted'}, indent=2)+'\n')


def compare(private, common, out):
    out.mkdir(parents=True, exist_ok=True)
    trace_path = common/'oracle_s040_native_trace.csv'
    if not trace_path.exists():
        (out/'parity.json').write_text(json.dumps({'status': 'BLOCKED_NATIVE_TRACE_MISSING', 'execution_qualified': False}))
        return
    trace = pd.read_csv(trace_path, sep=',')
    trace.index = pd.to_datetime(trace.pop('closed_epoch'), unit='s', utc=True)
    bars = pd.read_csv(private/'bars.csv', index_col=0, parse_dates=True)
    bars.index = pd.to_datetime(bars.index, utc=True)
    bars['ema200'] = bars.close.ewm(span=200, adjust=False).mean()
    tr = pd.concat([bars.high-bars.low, (bars.high-bars.close.shift()).abs(), (bars.low-bars.close.shift()).abs()], axis=1).max(axis=1)
    tr.iloc[0] = np.nan  # MT5 ATR's first TR requires a previous close.
    bars['atr20_sma'] = tr.rolling(20).mean()
    hi = bars.high.rolling(20).max().shift()
    buy = (bars.close > hi)&(bars.close.shift() <= hi.shift())&(bars.close >= bars.ema200)
    bars['reference_direction'] = buy.astype(int)
    joined = trace.join(bars, rsuffix='_reference', how='left')
    price_checks = {c: bool(np.allclose(joined[c], joined[c+'_reference'], atol=1e-7, rtol=0)) for c in ('open', 'high', 'low', 'close')}
    ema_error = float((joined.ema-joined.ema200).abs().max())
    atr_error = float((joined.atr-joined.atr20_sma).abs().max())
    tested = joined.function_tested.astype(bool) if 'function_tested' in joined else pd.Series(True, index=joined.index)
    mismatches = joined.loc[tested & (joined.direction != joined.reference_direction)]
    signals = trace.loc[(trace.direction != 0)&(trace.direction != 999)]
    signals.to_csv(out/'S040_native_entry_signals.csv')
    # Public output retains derived entry events, not the entire price history.
    report = {'schema': 'oracle.gold.phase05.S040_native_signal_parity.v1',
        'status': ('NATIVE_INDICATORS_AND_LATEST_ENTRY_PARITY_OBSERVED' if 'function_tested' in trace else 'NATIVE_ENTRY_FUNCTION_PARITY_OBSERVED') if len(trace) > 500 and all(price_checks.values()) and not len(mismatches) and ema_error < 1e-7 and atr_error < 1e-7 else 'PARITY_DIFFERENCE_PRESERVED',
        'native_closed_bars': len(trace), 'native_entry_signals': len(signals),
        'native_original_entry_function_rows_actually_executed': int(tested.sum()),
        'complete_historical_native_entry_trace': bool(tested.all()),
        'price_checks': price_checks, 'source_signal_mismatches': len(mismatches),
        'native_iMA200_vs_first_close_seeded_EMA_max_abs_error': ema_error,
        'native_iATR20_vs_TR_rolling_SMA_max_abs_error': atr_error,
        'private_trace_sha256': hashlib.sha256(trace_path.read_bytes()).hexdigest(),
        'input': json.loads((private/'receipts.json').read_text()),
        'source_function': 'Unchanged original S040 CheckBreakout; source OnInit creates actual native iMA/iATR. Original OnTick order path NEVER invoked.',
        'source_parameters': 'Original defaults:20entry/ATR20/EMA200/long only',
        'scope': 'Native indicators compared on every emitted bar. Original entry function compared ONLY on rows explicitly marked function_tested. Broker sessions/spread/risk/sizing/margin/order management/funding NOT covered.',
        'account_backtest': False, 'native_broker_execution_qualified': False, 'packaging_ready': False,
        'mismatch_examples': json.loads(mismatches.head(5).to_json(orient='table', date_format='iso'))['data']}
    (out/'parity.json').write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+'\n')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['prepare', 'compare'])
    p.add_argument('--quotes', type=Path)
    p.add_argument('--common', type=Path, required=True)
    p.add_argument('--private', type=Path, required=True)
    p.add_argument('--out', type=Path)
    a = p.parse_args()
    if a.mode == 'prepare':
        prepare(a.quotes, a.common, a.private)
    else:
        compare(a.private, a.common, a.out)


if __name__ == '__main__':
    main()
