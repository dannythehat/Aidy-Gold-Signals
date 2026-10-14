from datetime import UTC, datetime, timedelta
from decimal import Decimal
import pytest
from aidy.strategy_lab_data_quality import Bar, SourceContract, validate_bars, fingerprint, closed_source_bar_available_at

CONTRACT = SourceContract("histdata","XAUUSD",1,"bid","EST_FIXED_UTC_MINUS_05",
                          "aidy_histdata_source_aligned_v1","a"*64)
T = datetime(2025,1,6,12,tzinfo=UTC)
def bar(at=T, o="2650",h="2651",l="2649",c="2650"):
    return Bar(at,*(Decimal(x) for x in (o,h,l,c)))

def test_contiguous_and_stable_digest():
    rows=[bar(),bar(T+timedelta(minutes=1))]
    assert validate_bars(rows,CONTRACT)==[]
    assert fingerprint(CONTRACT,rows)==fingerprint(CONTRACT,rows)

def test_unclassified_gap_is_not_guessed_to_be_market_closed():
    gaps=validate_bars([bar(),bar(T+timedelta(minutes=4))],CONTRACT)
    assert len(gaps)==1 and gaps[0].missing_minutes==3
    assert gaps[0].classification=="UNCLASSIFIED"

@pytest.mark.parametrize("rows",[
    [bar(),bar()], [bar(),bar(T-timedelta(minutes=1))],
    [bar(o="2652",h="2651")],[bar(l="2652")],[bar(c="NaN")],
    [bar(c="-1")],[bar(T+timedelta(seconds=2))],
    [bar(datetime(2025,1,6,12))],
])
def test_invalid_rows_fail_closed(rows):
    with pytest.raises(ValueError):validate_bars(rows,CONTRACT)

def test_unqualified_source_contract_rejected():
    with pytest.raises(ValueError):
        validate_bars([bar()],SourceContract("histdata","XAUUSD",1,"bid","America/New_York","v1","a"*64))

def test_closed_higher_timeframe_not_available_early():
    assert closed_source_bar_available_at(T,60)==T+timedelta(hours=1)
