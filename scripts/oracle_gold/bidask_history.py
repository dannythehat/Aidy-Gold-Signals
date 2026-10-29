"""Read-only original R2 ticks to confidential, immutable bid/ask M1 caches.

No synthetic quotes, gap repair or source writes. Earliest/latest timestamp and
original line resolve chronology inversions without changing original bytes.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from aidy.strategy_lab_crossfire_tick_2021 import parse_tick
from scripts.oracle_gold.history import digest
from scripts.oracle_gold.minute_history import prior_month


def derive(archive, period, out):
    if (out/'manifest.json').exists():
        raise ValueError('Immutable quote cache exists')
    archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    prior = prior_month(2023, int(period[4:])) if period.startswith('2023') else None
    if prior and archive_sha != prior['input_zip_sha256']:
        raise ValueError('Original2023 archive changed')
    minutes, days = {}, {}
    previous, inversions, count = None, 0, 0
    payload_sha = hashlib.sha256()
    with zipfile.ZipFile(archive) as z:
        names = [n for n in z.namelist() if n.lower().endswith('.csv')]
        if len(names) != 1:
            raise ValueError('Ambiguous tick CSV')
        with z.open(names[0]) as f:
            for block in iter(lambda: f.read(1024*1024), b''):
                payload_sha.update(block)
        with z.open(names[0]) as f:
            for line_num, line in enumerate(io.TextIOWrapper(f, encoding='utf-8-sig', newline=''), 1):
                if not line.strip():
                    continue
                epoch, micro, bid, ask = parse_tick(next(csv.reader([line])), month=period, day_cache=days)
                order = (epoch*1000000+micro, line_num)
                inversions += int(previous is not None and order[0] < previous)
                previous = order[0]
                count += 1
                key = epoch//60*60
                if key not in minutes:
                    minutes[key] = {'first': order, 'last': order, 'bid_o': bid, 'bid_h': bid,
                        'bid_l': bid, 'bid_c': bid, 'ask_o': ask, 'ask_h': ask,
                        'ask_l': ask, 'ask_c': ask, 'ticks': 1, 'spread_sum': ask-bid}
                else:
                    v = minutes[key]
                    for prefix, price in (('bid', bid), ('ask', ask)):
                        v[prefix+'_h'] = max(v[prefix+'_h'], price)
                        v[prefix+'_l'] = min(v[prefix+'_l'], price)
                        if order < v['first']:
                            v[prefix+'_o'] = price
                        if order >= v['last']:
                            v[prefix+'_c'] = price
                    v['first'], v['last'] = min(v['first'], order), max(v['last'], order)
                    v['ticks'] += 1
                    v['spread_sum'] += ask-bid
    if count < 1000 or (prior and (count != prior['source_tick_rows'] or payload_sha.hexdigest() != prior['original_csv_payload_sha256'])):
        raise ValueError('Tick payload integrity failed')
    rows = []
    for epoch, v in sorted(minutes.items()):
        rows.append({'open_time_utc': datetime.fromtimestamp(epoch, UTC).isoformat(),
            **{k: v[k] for k in ('bid_o', 'bid_h', 'bid_l', 'bid_c', 'ask_o', 'ask_h', 'ask_l', 'ask_c', 'ticks')},
            'spread_mean': v['spread_sum']/v['ticks']})
    receipt = {'period_fixed_est': period, 'archive_sha256': archive_sha,
        'payload_sha256': payload_sha.hexdigest(), 'original_ticks': count,
        'source_inversions': inversions, 'prior2023_identity_verified': prior is not None,
        'raw_modified': False, 'source_clock': 'EST_FIXED_UTC_MINUS05'}
    out.mkdir(parents=True, exist_ok=True)
    with (out/'bidask.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    manifest = {'schema': 'oracle.gold.bidask_m1.v1', 'receipt': receipt, 'rows': len(rows),
        'csv_sha256': hashlib.sha256((out/'bidask.csv').read_bytes()).hexdigest(),
        'first_utc': rows[0]['open_time_utc'], 'last_utc': rows[-1]['open_time_utc'],
        'calendar_complete': False, 'sealed_oos': False, 'broker_terms_verified': False}
    manifest['sha256'] = digest(manifest)
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True)+'\n')
    return manifest


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--period', required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    try:
        print(json.dumps(derive(a.archive, a.period, a.out), sort_keys=True), flush=True)
    except Exception as exc:  # noqa: BLE001 - redact potentially secret service errors
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out/'BLOCKED.json').write_text(json.dumps({'period': a.period, 'error_type': type(exc).__name__}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
