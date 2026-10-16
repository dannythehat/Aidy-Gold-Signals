"""CROSSFIRE fixed account risk overlays: original, legacy, hourly-updating sizing.

H1 BID source model, assumed execution costs. No verified broker swaps, margin
liquidation, or order execution. New overlay computed using only previous
COMPLETED H1 marks. Historical risk research only; NO MT5 orders.
"""
from __future__ import annotations
import math
import pandas as pd
from aidy.strategy_lab_s010_backtest import derive_signals

VERSIONS={'original':None,'prior_entry_only_half_guard':1.64,'hourly_state_half_new':1.64,'gentle_three_quarter_new':2.46,'half_new_plus_open_trim':1.64}
LEVERAGE=3.28
INIT=10000.
SPREAD=.30
SLIP=.05
COMM=.07

def replay(df, version:str, quote_mode='assumed'):
    if version not in VERSIONS: raise ValueError('No undeclared variants permitted')
    if quote_mode not in {'assumed','observed_histdata_ask'}:raise ValueError('invalid quote case')
    if quote_mode=='observed_histdata_ask' and 'observed_open_ask' not in df:raise ValueError('ASK not in genuine native source')
    d=derive_signals(df)
    equity=INIT
    qty=0.
    entry=None
    last_bid=None
    peak=INIT
    previous_closed_bar_dd=0.
    brake_active=False
    reduced_entries=0
    total_entries=0
    partial_trims=0
    intrabar_worst_dd=0.
    intrabar_equity_floor=float('inf')
    intrabar_nonpositive_hits=0
    fees_paid=0.
    trades=[]
    events=[]
    marks=[]
    for i,row in d.iterrows():
        bid_open=float(row['open'])
        bid_close=float(row['close'])
        time=row['open_time_utc'].isoformat()
        if qty and last_bid is not None:
            equity+=qty*(bid_open-last_bid)
        prior=int(d.iloc[i-1]['signal']) if i>0 else 0
        if qty and prior == -1:
            assert entry is not None
            exit_fee=qty*(SLIP+COMM/2)
            equity-=exit_fee;fees_paid+=exit_fee
            entry['gross']+=qty*(bid_open-entry['bid_entry'])
            entry['fees']+=exit_fee
            trades.append({'entry_utc':entry['time'],'exit_utc':time,'net_usd':round(entry['gross']-entry['fees'],4),
                'gross_usd':round(entry['gross'],4),'total_execution_cost_usd':round(entry['fees'],4),
                'trim_count':entry['trim_count'],'entry_leverage':entry['leverage']})
            events.append({'time':time,'event':'SOURCE_EXIT','units':round(qty,6)})
            qty=0.;entry=None
        # Last closed H1 account mark determines risk settings; never use current H1 close.
        if version not in ('original','prior_entry_only_half_guard'):
            brake_active = previous_closed_bar_dd>=5 if brake_active else previous_closed_bar_dd>=10
        elif version=='original':
            brake_active=False
        # Existing position: stop-risk-on-new-entry alone cannot reduce a dangerous running trade.
        # De-risk an open trade once; no buying back into that same trade until next entry.
        if version=='half_new_plus_open_trim' and qty and previous_closed_bar_dd>=10 and not entry['already_trimmed']:
            sale=qty/2.
            extra_fee=sale*(SLIP+COMM/2)
            equity-=extra_fee;fees_paid+=extra_fee
            entry['gross']+=sale*(bid_open-entry['bid_entry'])
            entry['fees']+=extra_fee
            entry['already_trimmed']=True
            entry['trim_count']+=1
            qty-=sale
            partial_trims+=1
            events.append({'time':time,'event':'REDUCE_EXISTING_RISK_50_PCT','units':round(sale,6),'reason':'PRIOR_CLOSE_MARKED_DD_GE_10'})
        if not qty and prior==1:
            if version=='prior_entry_only_half_guard':
                brake_active = previous_closed_bar_dd>=5 if brake_active else previous_closed_bar_dd>=10
            lev=LEVERAGE if not brake_active else VERSIONS[version]
            if not math.isfinite(lev) or not 0 < lev <= LEVERAGE:raise ValueError('invalid strategy leverage')
            spread=SPREAD if quote_mode=='assumed' else float(row['observed_open_ask'])-bid_open
            if spread<0 or not math.isfinite(spread):raise ValueError('Invalid source ask')
            ask=bid_open+spread+SLIP
            qty=equity*lev/ask
            cost=qty*(spread+SLIP+COMM/2)
            equity-=cost;fees_paid+=cost
            entry={'time':time,'bid_entry':bid_open,'fees':cost,'gross':0.,'trim_count':0,'already_trimmed':False,'leverage':lev}
            total_entries+=1
            reduced_entries+=int(lev<LEVERAGE)
            events.append({'time':time,'event':'LONG_ENTRY','units':round(qty,6),'lev':lev})
        # Diagnostic-only intrabar BID low: not used to change actions or profit.
        # With no protective original stop a broker's stop-out may occur before H1 close.
        if qty:
            low_equity=equity+qty*(float(row['low'])-bid_open)
            intrabar_equity_floor=min(intrabar_equity_floor,low_equity)
            intrabar_worst_dd=min(intrabar_worst_dd,100*(low_equity/peak-1))
            intrabar_nonpositive_hits+=int(low_equity <= 0)
            equity+=qty*(bid_close-bid_open)
        last_bid=bid_close
        if not math.isfinite(equity) or equity<=0:raise ValueError('Capital would be exhausted, broker liquidation not modelled')
        peak=max(INIT,peak,equity)
        previous_closed_bar_dd=100*(1-equity/peak)
        marks.append({'time':time,'equity':round(equity,4),'dd':round(-previous_closed_bar_dd,4),'exposure_oz':round(qty,6)})
    x=pd.Series([m['equity'] for m in marks])
    dd=(x/x.cummax().clip(lower=INIT)-1)*100
    month_ends={}
    for m in marks:month_ends[m['time'][:7]]=m['equity']
    monthly=[];before=INIT
    for month,ending in month_ends.items():
        monthly.append({'month':month,'start_equity':round(before,2),'end_equity':round(ending,2),'monthly_return_pct':round(100*(ending/before-1),3),'monthly_usd':round(ending-before,2)})
        before=ending
    winning=[t['net_usd'] for t in trades if t['net_usd']>0]
    losing=[t['net_usd'] for t in trades if t['net_usd']<0]
    return {'variant':version,'quote_case':quote_mode,'end_equity_usd':round(equity,2),'profit_usd':round(equity-INIT,2),
            'return_pct':round(100*(equity/INIT-1),3),'max_dd_pct':round(float(dd.min()),3),
            'closed_trades':len(trades),'wins':len(winning),'losers':len(losing),
            'profit_factor':round(sum(winning)/(-sum(losing)),3) if losing else None,
            'positive_months':sum(m['monthly_return_pct']>0 for m in monthly),
            'months_at_least_10_percent':sum(m['monthly_return_pct']>=10 for m in monthly),
            'reduced_entries':reduced_entries,'entries':total_entries,'partial_open_trims':partial_trims,
            'entry_plus_exit_costs_usd':round(fees_paid,2),
            'unclosed_position_at_end':bool(qty),
            'worst_h1_bid_low_equity_usd':round(intrabar_equity_floor,2) if intrabar_equity_floor!=float('inf') else None,
            'worst_h1_bid_low_drawdown_from_prior_close_peak_pct':round(intrabar_worst_dd,3),
            'intra_hour_equity_zero_or_below_observations':intrabar_nonpositive_hits,
            'monthly':monthly,'trades':trades,'equity':marks,'partial_events':events}

