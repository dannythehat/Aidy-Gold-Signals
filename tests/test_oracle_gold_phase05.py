import csv
import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts.oracle_gold.bidask_history import derive
from scripts.oracle_gold.phase05_native_accounts import simulate_observed

ROOT = Path(__file__).resolve().parents[1]


def test_all308_prior_files_unchanged():
    protected = json.loads((ROOT/'research/gold_oracle/phase05/protected_evidence.json').read_text())
    for name, sha in protected['files'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == sha, name


def test_bidask_chronology_no_synthetic_minutes(tmp_path):
    source = tmp_path/'original.zip'
    # Out of order ticks, ties resolved by source line; a full minute gap stays.
    raw = ('20240101 000030000,2002,2004\n'
           '20240101 000000000,2000,2001\n'
           '20240101 000030000,2003,2005\n'
           '20240101 000200000,2010,2011\n')*251
    with zipfile.ZipFile(source, 'w') as z:
        z.writestr('ticks.csv', raw)
    prior = source.read_bytes()
    result = derive(source, '202401', tmp_path/'out')
    rows = list(csv.DictReader((tmp_path/'out/bidask.csv').open()))
    assert len(rows) == 2
    assert rows[0]['open_time_utc'] == '2024-01-01T05:00:00+00:00'
    assert float(rows[0]['bid_o']) == 2000
    assert float(rows[0]['bid_c']) == 2003
    assert float(rows[0]['ask_h']) == 2005
    assert int(rows[0]['ticks']) == 753
    assert result['receipt']['source_inversions'] > 0
    assert source.read_bytes() == prior
    with pytest.raises(ValueError, match='Immutable'):
        derive(source, '202401', tmp_path/'out')


def test_crossed_quotes_fail_closed(tmp_path):
    source = tmp_path/'bad.zip'
    with zipfile.ZipFile(source, 'w') as z:
        z.writestr('ticks.csv', '20240101 000000,2001,2000\n')
    with pytest.raises(ValueError, match='reversed'):
        derive(source, '202401', tmp_path/'out')


def test_observer_restores_source_on_failure():
    class Engine:
        _walk = object()

        @staticmethod
        def simulate(*args):
            raise RuntimeError('source failure')
    original = Engine._walk
    with pytest.raises(RuntimeError, match='source failure'):
        simulate_observed(Engine, None, None, None, None)
    assert Engine._walk is original
