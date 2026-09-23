const DATA_URL='/data/public-performance.json';
const API='/account-api';
const PUBLIC_LIVE_URL=`${API}/account/mt5/dashboard/public-performance-calendar`;
const PUBLIC_CACHE_KEY='smart-signals-public-performance-v10';
const LIVE_REFRESH_MS=5000;
const LIVE_FETCH_TIMEOUT_MS=8000;
const LIVE_CACHE_TTL_MS=30000;
const TZ=Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC';
const calendar=document.querySelector('[data-calendar]');
const monthLabel=document.querySelector('[data-month-label]');
const dayDetail=document.querySelector('[data-day-detail]');
const ledgerBody=document.querySelector('[data-ledger-body]');
const prev=document.querySelector('[data-month-prev]');
const next=document.querySelector('[data-month-next]');
const memberSection=document.querySelector('[data-member-trades]');
const memberTradeList=document.querySelector('[data-member-trade-list]');
const memberSync=document.querySelector('[data-member-sync]');
let data=null;
let publicLive=null;
let visible={year:2026,month:8};
let selectedDate=null;
let publicRefreshInFlight=false;
let followLatest=true;

const money=(v)=>{
  if(v===null||v===undefined||!Number.isFinite(Number(v)))return '—';
  return new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',minimumFractionDigits:2,maximumFractionDigits:2}).format(Number(v));
};
const signedMoney=(v)=>v===null||v===undefined||!Number.isFinite(Number(v))?'—':`${Number(v)>=0?'+':''}${money(v)}`;
const niceDate=(s)=>new Intl.DateTimeFormat('en-GB',{day:'numeric',month:'long',year:'numeric',timeZone:'UTC'}).format(new Date(`${s}T12:00:00Z`));
const shortTime=(s)=>{if(!s)return '—';const d=new Date(s);if(Number.isNaN(d.getTime()))return '—';return new Intl.DateTimeFormat('en-GB',{hour:'2-digit',minute:'2-digit'}).format(d)};

function records(){return Array.isArray(data?.daily)?data.daily:[]}
function monthRecords(y,m){return records().filter(r=>{const [ry,rm]=String(r.date).split('-').map(Number);return ry===y&&rm===m})}
function latestRecord(){return records().slice().sort((a,b)=>b.date.localeCompare(a.date))[0]||null}
function tradesForDate(date){return Array.isArray(publicLive?.trades)?publicLive.trades.filter(t=>String(t.day)===String(date)):[]}

function readPublicCache(){
  try{
    const raw=localStorage.getItem(PUBLIC_CACHE_KEY);
    if(!raw)return null;
    const parsed=JSON.parse(raw);
    const savedAt=Number(parsed?.saved_at||0);
    if(!parsed||!Array.isArray(parsed.daily)||!savedAt||Date.now()-savedAt>LIVE_CACHE_TTL_MS)return null;
    return parsed;
  }catch{return null;}
}
function writePublicCache(payload){
  try{localStorage.setItem(PUBLIC_CACHE_KEY,JSON.stringify({...payload,saved_at:Date.now()}));}catch{}
}

function renderSummary(){
  const historical=data?.historical_baseline||{};
  const live=data?.live_baseline||{};
  const liveStart=Number(live.starting_balance||historical.ending_balance||1517.23);
  const latest=latestRecord();
  const staticCurrent=Number(data?.current_recorded_balance);
  const endpointCurrent=Number(publicLive?.current_recorded_balance);
  // The public recorded balance must equal the latest daily ledger close. Live/static values are fallbacks only.
  const latestBalance=latest?Number(latest.balance_end):NaN;
  const current=Number.isFinite(latestBalance)?latestBalance:(Number.isFinite(endpointCurrent)?endpointCurrent:(Number.isFinite(staticCurrent)?staticCurrent:Number(historical.ending_balance||liveStart)));
  const historicalStart=Number(historical.starting_balance||1000);
  const totalPnl=current-historicalStart;
  const pct=historicalStart?totalPnl/historicalStart*100:0;
  const positiveDays=records().filter(r=>Number(r.cash_pnl)>0).length;
  const lossDays=records().filter(r=>Number(r.cash_pnl)<0).length;
  document.querySelector('[data-start-balance]').textContent=money(liveStart);
  document.querySelector('[data-end-balance]').textContent=money(current);
  document.querySelector('[data-net-pnl]').textContent=signedMoney(totalPnl);
  document.querySelector('[data-net-pnl]').className=totalPnl>=0?'positive':'negative';
  document.querySelector('[data-return-pct]').textContent=`${pct>=0?'+':''}${pct.toFixed(2)}%`;
  document.querySelector('[data-trading-days]').textContent=String(records().length);
  document.querySelector('[data-win-loss-days]').textContent=`${positiveDays} profit · ${lossDays} loss`;
  const note=document.querySelector('[data-current-balance-note]');
  if(note){
    if(publicLive?.updated_at)note.textContent=`Auto-updated · ${shortTime(publicLive.updated_at)}`;
    else if(latest?.history_type==='verified')note.textContent=`Verified through ${niceDate(latest.date)}`;
    else note.textContent='Historical close';
  }
}

function renderCalendar(){
  const {year,month}=visible;
  monthLabel.textContent=new Intl.DateTimeFormat('en-GB',{month:'long',year:'numeric',timeZone:'UTC'}).format(new Date(Date.UTC(year,month-1,1)));
  calendar.innerHTML='';
  const first=new Date(Date.UTC(year,month-1,1));
  const offset=(first.getUTCDay()+6)%7;
  const days=new Date(Date.UTC(year,month,0)).getUTCDate();
  const map=new Map(monthRecords(year,month).map(r=>[Number(r.date.slice(-2)),r]));
  for(let i=0;i<offset;i++){const e=document.createElement('div');e.className='cal-cell cal-cell--empty';calendar.appendChild(e)}
  for(let day=1;day<=days;day++){
    const date=new Date(Date.UTC(year,month-1,day));
    const dow=date.getUTCDay();
    const weekend=dow===0||dow===6;
    const r=map.get(day);
    const cell=document.createElement(r?'button':'div');
    cell.className='cal-cell';
    if(weekend)cell.classList.add('cal-cell--weekend');
    if(r){
      cell.type='button';
      const pnl=Number(r.cash_pnl||0);
      cell.classList.add(pnl>=0?'cal-cell--profit':'cal-cell--loss');
      if(selectedDate===r.date)cell.classList.add('cal-cell--active');
      cell.innerHTML=`<span class="cal-day">${day}</span><strong class="cal-value ${pnl>=0?'positive':'negative'}">${signedMoney(pnl)}</strong>`;
      cell.addEventListener('click',()=>{selectedDate=r.date;followLatest=r.date===latestRecord()?.date;renderCalendar();renderDay(r)});
    }else{
      cell.innerHTML=`<span class="cal-day">${day}</span>${weekend?'<strong class="cal-value">Closed</strong>':''}`;
    }
    calendar.appendChild(cell);
  }
}

function tradeRef(id=''){const compact=String(id).replaceAll('-','').toUpperCase();return compact?`SS-${compact.slice(0,10)}`:'SMART SIGNALS'}
function dayTradeMarkup(trade){
  const pnl=trade.cash_pnl;
  const pnlClass=Number(pnl)>0?'positive':Number(pnl)<0?'negative':'';
  const pips=trade.net_pips===null||trade.net_pips===undefined?'—':`${Number(trade.net_pips)>0?'+':''}${Number(trade.net_pips).toFixed(1)}`;
  const progress=[Number(trade.open_positions)>0?`${trade.open_positions} open`:'',Number(trade.pending_positions)>0?`${trade.pending_positions} pending`:'',Number(trade.closed_positions)>0?`${trade.closed_positions} closed`:''].filter(Boolean).join(' · ');
  const when=trade.opened_at?`Opened ${shortTime(trade.opened_at)}`:trade.closed_at?`Closed ${shortTime(trade.closed_at)}`:'';
  return `<article class="day-trade-row"><div class="day-trade-head"><div><strong>${trade.side||''} ${trade.symbol||'XAUUSD'}</strong><span>${tradeRef(trade.signal_id)}${when?` · ${when}`:''}</span></div><b>${trade.status_label||trade.status||'Trade'}</b></div><div class="day-trade-metrics"><div><span>P&amp;L</span><strong class="${pnlClass}">${pnl===null||pnl===undefined?'Open':signedMoney(pnl)}</strong></div><div><span>Net pips</span><strong>${pips}</strong></div><div><span>Positions</span><strong>${progress||trade.position_count||'—'}</strong></div></div></article>`;
}

function renderDay(r){
  selectedDate=r.date;
  const pnl=Number(r.cash_pnl||0);
  const trades=tradesForDate(r.date);
  const detailStart=String(publicLive?.trade_detail_start_date||'2026-09-03');
  let tradesHtml='';
  if(r.date>=detailStart){
    tradesHtml=`<div class="day-trade-log"><div class="day-trade-title"><span>Trade log</span><strong>${trades.length} trade${trades.length===1?'':'s'}</strong></div>${trades.length?trades.map(dayTradeMarkup).join(''):'<div class="day-trade-empty">No executed Smart Signals trades recorded for this day.</div>'}</div>`;
  }else if(r.history_type!=='reconstructed'){
    tradesHtml=`<div class="day-trade-empty">Individual trade logging starts from 3 September 2026. Daily P&amp;L remains recorded above.</div>`;
  }
  dayDetail.innerHTML=`<span class="label">${r.history_type==='reconstructed'?'Reconstructed day':'Verified live day'}</span><h3>${niceDate(r.date)}</h3><div class="day-stat"><span>Start balance</span><strong>${money(r.balance_start)}</strong></div><div class="day-stat"><span>Profit / loss</span><strong class="${pnl>=0?'positive':'negative'}">${signedMoney(pnl)}</strong></div><div class="day-stat"><span>End balance</span><strong>${money(r.balance_end)}</strong></div>${tradesHtml}`;
}

function renderTable(){
  ledgerBody.innerHTML=records().map(r=>{const pnl=Number(r.cash_pnl||0);return `<tr><td>${niceDate(r.date)}</td><td>${money(r.balance_start)}</td><td class="${pnl>=0?'positive':'negative'}">${signedMoney(pnl)}</td><td>${money(r.balance_end)}</td><td>${r.history_type==='reconstructed'?'Reconstructed':'Verified'}</td></tr>`}).join('');
}

function shift(delta){followLatest=false;const d=new Date(Date.UTC(visible.year,visible.month-1+delta,1));visible={year:d.getUTCFullYear(),month:d.getUTCMonth()+1};renderCalendar()}

async function read(url){
  const controller=new AbortController();
  const timeout=window.setTimeout(()=>controller.abort(),LIVE_FETCH_TIMEOUT_MS);
  try{
    const response=await fetch(url,{credentials:'include',cache:'no-store',headers:{Accept:'application/json','Cache-Control':'no-cache'},signal:controller.signal});
    if(!response.ok)return null;
    return response.json().catch(()=>null);
  }catch{
    return null;
  }finally{
    window.clearTimeout(timeout);
  }
}

function mergePublicDaily(payload){
  const liveRows=Array.isArray(payload?.daily)?payload.daily.slice().filter(item=>item?.day).sort((a,b)=>String(a.day).localeCompare(String(b.day))):[];
  const existing=new Map(records().map(row=>[String(row.date),row]));
  const historicalRows=records().filter(row=>row.history_type==='reconstructed');
  const verified=new Map(records().filter(row=>row.history_type==='verified').map(row=>[String(row.date),row]));
  const latestLiveDay=liveRows.length?String(liveRows[liveRows.length-1].day):null;
  const hasNumber=(value)=>value!==null&&value!==undefined&&value!==''&&Number.isFinite(Number(value));

  const previousClose=(day)=>{
    const prior=[...verified.values()]
      .filter(row=>String(row.date)<day&&hasNumber(row.balance_end))
      .sort((a,b)=>String(b.date).localeCompare(String(a.date)))[0];
    if(prior)return Number(prior.balance_end);
    const baseline=Number(payload?.live_starting_balance||data?.live_baseline?.starting_balance||1517.23);
    return Number.isFinite(baseline)?baseline:1517.23;
  };

  for(const item of liveRows){
    const day=String(item.day);
    const frozen=existing.get(day);

    // Published completed days are immutable. The live endpoint can contain
    // placeholder/zero rows for earlier dates; those must never erase the
    // verified calendar history already shipped with the site.
    if(frozen&&frozen.history_type==='verified'&&day!==latestLiveDay)continue;

    const hasOpening=hasNumber(item.opening_balance)&&Number(item.opening_balance)>0;
    const hasClosing=hasNumber(item.closing_balance)&&Number(item.closing_balance)>0;
    if(hasOpening&&hasClosing){
      const opening=Number(item.opening_balance);
      const closing=Number(item.closing_balance);
      verified.set(day,{
        date:day,
        balance_start:Number(opening.toFixed(2)),
        cash_pnl:Number((closing-opening).toFixed(2)),
        balance_end:Number(closing.toFixed(2)),
        history_type:'verified'
      });
      continue;
    }

    // If the endpoint does not have authoritative account values, keep any
    // already-published verified row rather than replacing it with a zero.
    if(frozen&&frozen.history_type==='verified')continue;

    if(hasNumber(item.pnl)){
      const pnl=Number(item.pnl);
      const start=Number(previousClose(day).toFixed(2));
      const end=Number((start+pnl).toFixed(2));
      verified.set(day,{date:day,balance_start:start,cash_pnl:pnl,balance_end:end,history_type:'verified'});
    }
  }

  data.daily=[...historicalRows,...verified.values()].sort((a,b)=>a.date.localeCompare(b.date));
}

function renderPublicState(){
  const latest=latestRecord();
  if(latest&&followLatest){
    selectedDate=latest.date;
    const [y,m]=latest.date.split('-').map(Number);
    visible={year:y,month:m};
  }else if(latest&&!selectedDate){
    selectedDate=latest.date;
  }
  renderSummary();renderCalendar();renderTable();
  const selected=selectedDate?records().find(r=>r.date===selectedDate):latest;
  if(selected)renderDay(selected);
}

async function loadPublicLive(){
  if(publicRefreshInFlight||!data)return;
  publicRefreshInFlight=true;
  try{
    const stamp=Date.now();
    const live=await read(`${PUBLIC_LIVE_URL}?live=${stamp}`);
    if(live){
      publicLive=live;
      writePublicCache(live);
      mergePublicDaily(live);
      renderPublicState();
      return;
    }

    // Edge fallback: the Worker injects current MT5/Vantage equity into the
    // normal performance data file. This keeps the calendar live even if the
    // browser-to-account proxy is temporarily unavailable.
    const edge=await read(`${DATA_URL}?live=${stamp}`);
    if(edge&&Array.isArray(edge.daily)){
      data=edge;
      renderPublicState();
    }
  }finally{publicRefreshInFlight=false;}
}

function tradeCard(t){
  const pnl=t.cash_pnl;
  const pnlClass=Number(pnl)>0?'positive':Number(pnl)<0?'negative':'';
  const pips=t.net_pips===null||t.net_pips===undefined?'—':`${Number(t.net_pips)>0?'+':''}${Number(t.net_pips).toFixed(1)}`;
  const when=t.closed_at?`Closed ${shortTime(t.closed_at)}`:t.opened_at?`Opened ${shortTime(t.opened_at)}`:'Time unavailable';
  const status=t.status_label||t.status||'Trade';
  const progress=[Number(t.open_positions)>0?`${t.open_positions} open`:'',Number(t.pending_positions)>0?`${t.pending_positions} pending`:'',Number(t.closed_positions)>0?`${t.closed_positions} closed`:''].filter(Boolean).join(' · ');
  return `<article class="member-trade"><div class="member-trade-main"><span class="member-trade-status">${status}</span><strong>${t.side||''} ${t.symbol||'XAUUSD'}</strong><span class="member-trade-ref">${tradeRef(t.signal_id)}</span><span>${when}</span></div><div class="member-trade-stat"><span>Positions</span><strong>${progress||t.position_count||'—'}</strong></div><div class="member-trade-stat"><span>Pips</span><strong>${pips}</strong></div><div class="member-trade-stat"><span>P&amp;L</span><strong class="${pnlClass}">${money(pnl)}</strong></div></article>`;
}

function renderMemberTrades(timeline){
  if(!memberSection||!memberTradeList||!timeline)return;
  const trades=Array.isArray(timeline.trades)?timeline.trades:[];
  memberSection.hidden=false;
  memberTradeList.innerHTML=trades.length?trades.map(tradeCard).join(''):'<div class="member-trade-empty">No Smart Signals trades recorded yet.</div>';
  if(memberSync)memberSync.innerHTML=`<strong>LIVE</strong> · ${trades.length} trade${trades.length===1?'':'s'} synced`;
}

async function loadSignedInMemberHistory(){
  const me=await read(`${API}/auth/me`);
  if(!me)return;
  const timeline=await read(`${API}/account/mt5/dashboard/performance/timeline?limit=100`);
  if(timeline)renderMemberTrades(timeline);
}

async function load(){
  try{
    const livePromise=read(`${PUBLIC_LIVE_URL}?live=${Date.now()}`);
    const res=await fetch(`${DATA_URL}?v=20260921-publiclive9`,{cache:'no-store'});
    if(!res.ok)throw new Error('data');
    data=await res.json();

    const cached=readPublicCache();
    if(cached){publicLive=cached;mergePublicDaily(cached);}

    const latest=latestRecord();
    if(latest){const [y,m]=latest.date.split('-').map(Number);visible={year:y,month:m};selectedDate=latest.date;}
    renderSummary();renderCalendar();renderTable();if(latest)renderDay(latest);

    const live=await livePromise;
    if(live){
      publicLive=live;
      writePublicCache(live);
      mergePublicDaily(live);
      renderPublicState();
    }
    loadSignedInMemberHistory();
  }catch(e){console.error('Performance data failed',e);}
}

prev?.addEventListener('click',()=>shift(-1));
next?.addEventListener('click',()=>shift(1));
load();

async function liveRefreshLoop(){
  try{await loadPublicLive();}catch{}
  window.setTimeout(liveRefreshLoop,LIVE_REFRESH_MS);
}
window.setTimeout(liveRefreshLoop,LIVE_REFRESH_MS);

const refreshNow=()=>{loadPublicLive().catch(()=>{});};
window.addEventListener('focus',refreshNow);
window.addEventListener('pageshow',refreshNow);
window.addEventListener('online',refreshNow);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshNow();});