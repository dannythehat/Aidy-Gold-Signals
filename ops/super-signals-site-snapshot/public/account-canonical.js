const API_BASE='/account-api';
const TZ=Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC';
const q=new URLSearchParams({timezone_name:TZ});
const DASHBOARD_URL=`${API_BASE}/account/mt5/dashboard?${q}`;
const TODAY_URL=`${API_BASE}/account/mt5/dashboard/today?${q}`;
const TIMELINE_URL=`${API_BASE}/account/mt5/dashboard/performance/timeline?limit=100`;
const GOLD_URL='/api/gold-price';
const $=(s)=>document.querySelector(s);

const ui={
  name:$('[data-display-name]'),connection:$('[data-connection-status]'),mode:$('[data-account-mode]'),
  balance:$('[data-balance]'),balanceLabel:$('[data-balance-label]'),balanceNote:$('[data-balance-note]'),
  baselineRow:$('[data-baseline-row]'),baselinePnl:$('[data-baseline-pnl]'),baselineToday:$('[data-baseline-return]'),
  todayPnl:$('[data-today-pnl]'),netPips:$('[data-net-pips]'),tradeCount:$('[data-trade-count]'),winLoss:$('[data-win-loss]'),
  openCount:$('[data-open-count]'),openTrades:$('[data-open-trades]'),recentTrades:$('[data-recent-trades]'),recentSection:$('[data-recent-section]'),recentToggle:$('[data-recent-toggle]'),
  performance:$('[data-performance-grid]'),refresh:$('[data-refresh]'),signout:$('[data-signout]'),goldPrice:$('[data-gold-price]'),goldState:$('[data-gold-state]'),error:$('[data-account-error]')
};

let user=null,dashboard=null,timeline=null,refreshing=false,recentExpanded=false;

function money(value,currency='USD'){
  if(value===null||value===undefined||!Number.isFinite(Number(value)))return '—';
  try{return new Intl.NumberFormat(undefined,{style:'currency',currency:currency||'USD',minimumFractionDigits:2,maximumFractionDigits:2}).format(Number(value));}
  catch{return `${currency||'$'} ${Number(value).toFixed(2)}`;}
}
function signed(value,currency='USD'){
  if(value===null||value===undefined||!Number.isFinite(Number(value)))return '—';
  const n=Number(value);return `${n>=0?'+':'-'}${money(Math.abs(n),currency)}`;
}
function signedPercent(value){
  if(value===null||value===undefined||!Number.isFinite(Number(value)))return '—';
  const n=Number(value);return `${n>=0?'+':''}${n.toFixed(2)}%`;
}
function tone(el,value){if(!el)return;el.classList.remove('positive','negative');if(Number(value)>0)el.classList.add('positive');if(Number(value)<0)el.classList.add('negative');}
function fixed(value,digits=1){return value===null||value===undefined||!Number.isFinite(Number(value))?'—':Number(value).toFixed(digits);}
function setError(message=''){if(!ui.error)return;ui.error.textContent=message;ui.error.classList.toggle('hidden',!message);}
function modeLabel(environment){return environment==='demo'?'Paper account':environment==='live'?'Real account':'MT5 account';}
function period(key){return Array.isArray(dashboard?.performance)?dashboard.performance.find(x=>x.key===key):null;}
function finite(value){const n=Number(value);return Number.isFinite(n)?n:null;}

async function responseJson(url){
  const r=await fetch(url,{credentials:'include',cache:'no-store',headers:{Accept:'application/json'}});
  const body=await r.json().catch(()=>null);
  return {ok:r.ok,status:r.status,body};
}

function renderIdentity(){
  if(!user)return;
  if(ui.name)ui.name.textContent=user.display_name||user.email?.split('@')[0]||'Trader';
}

function renderConnection(){
  const connected=dashboard?.connection?.status==='connected'||Boolean(dashboard?.account);
  const environment=dashboard?.connection?.account_environment;
  if(ui.connection){ui.connection.textContent=connected?'MT5 connected':'MT5 needs setup';ui.connection.classList.toggle('ok',connected);}
  if(ui.mode)ui.mode.textContent=modeLabel(environment);
}

function renderBalance(){
  const currency=dashboard?.account?.currency||'USD';
  const balance=dashboard?.account?.balance;
  const all=period('all')?.amount;
  const today=period('today')?.amount;
  if(ui.balanceLabel)ui.balanceLabel.textContent='Smart Signals trading balance';
  if(ui.balance)ui.balance.textContent=money(balance,currency);
  if(ui.balanceNote)ui.balanceNote.textContent=dashboard?.account?'Same live balance used in the Smart Signals app':'Connect MT5 to show your balance';
  if(ui.baselinePnl){ui.baselinePnl.textContent=signed(all,currency);tone(ui.baselinePnl,all);}
  if(ui.baselineToday){ui.baselineToday.textContent=signed(today,currency);tone(ui.baselineToday,today);}
  ui.baselineRow?.classList.toggle('hidden',!dashboard?.account);
}

function tradeReference(signalId=''){
  const compact=String(signalId).replaceAll('-','').toUpperCase();
  return compact?`SS-${compact.slice(0,10)}`:'Smart Signals';
}

function projectedAt(position,target,balance,targetKind){
  const entry=finite(position?.entry_price),level=finite(target),volume=finite(position?.volume);
  const side=String(position?.side||'').toUpperCase();
  const symbol=String(position?.symbol||'').toUpperCase();
  if(entry!==null&&level!==null&&volume!==null&&volume>0&&(side==='BUY'||side==='SELL')&&symbol==='XAUUSD'){
    const direction=side==='BUY'?1:-1;
    return (level-entry)*direction*volume*100;
  }
  const riskPct=finite(position?.planned_risk_percent);
  if(balance&&riskPct!==null&&riskPct>=0){
    const riskAmount=balance*riskPct/100;
    if(targetKind==='sl')return -riskAmount;
    const sl=finite(position?.stop_loss),tp=finite(position?.take_profit);
    if(entry!==null&&sl!==null&&tp!==null){
      const riskDistance=Math.abs(entry-sl),rewardDistance=Math.abs(tp-entry);
      if(riskDistance>0)return riskAmount*(rewardDistance/riskDistance);
    }
  }
  return null;
}

function signalProjection(signalId){
  const allPositions=Array.isArray(dashboard?.open_positions)?dashboard.open_positions:[];
  const positions=allPositions.filter(p=>String(p.signal_id)===String(signalId));
  if(!positions.length)return null;
  const balance=finite(dashboard?.account?.balance);
  const knownProfit=positions.map(p=>finite(p.profit)).filter(v=>v!==null);
  const current=knownProfit.length?knownProfit.reduce((a,b)=>a+b,0):null;
  const tpValues=positions.map(p=>projectedAt(p,p.take_profit,balance,'tp')).filter(v=>v!==null);
  const slValues=positions.map(p=>projectedAt(p,p.stop_loss,balance,'sl')).filter(v=>v!==null);
  const tp=tpValues.length===positions.length?tpValues.reduce((a,b)=>a+b,0):null;
  const sl=slValues.length===positions.length?slValues.reduce((a,b)=>a+b,0):null;
  return {
    current,tp,sl,
    currentPct:balance&&current!==null?current/balance*100:null,
    tpPct:balance&&tp!==null?tp/balance*100:null,
    slPct:balance&&sl!==null?sl/balance*100:null,
    currentPrice:positions.map(p=>finite(p.current_price)).find(v=>v!==null)??null,
    entryPrice:positions.map(p=>finite(p.entry_price)).find(v=>v!==null)??null,
    positionCount:positions.length,
  };
}

function liveProjectionMarkup(projection,currency){
  if(!projection)return '';
  const currentCls=Number(projection.current)>0?'positive':Number(projection.current)<0?'negative':'';
  const tpCls=Number(projection.tp)>0?'positive':Number(projection.tp)<0?'negative':'';
  const slCls=Number(projection.sl)>0?'positive':Number(projection.sl)<0?'negative':'';
  return `<div class="signal-live-box">
    <div class="signal-live-head"><span><i></i>LIVE SIGNAL</span><small>${projection.positionCount} position${projection.positionCount===1?'':'s'} remaining</small></div>
    <div class="signal-live-grid">
      <div><span>Current P/L</span><strong class="${currentCls}">${signed(projection.current,currency)}</strong><small>${signedPercent(projection.currentPct)}</small></div>
      <div><span>TP estimate</span><strong class="${tpCls}">${signed(projection.tp,currency)}</strong><small>${signedPercent(projection.tpPct)}</small></div>
      <div><span>SL estimate</span><strong class="${slCls}">${signed(projection.sl,currency)}</strong><small>${signedPercent(projection.slPct)}</small></div>
    </div>
    <div class="signal-live-prices"><span>Entry ${projection.entryPrice===null?'—':fixed(projection.entryPrice,2)}</span><span>Now ${projection.currentPrice===null?'—':fixed(projection.currentPrice,2)}</span><em>Estimates update automatically from live balance, lot size, SL and TP.</em></div>
  </div>`;
}

function timelineRow(trade,currency){
  const projection=trade.status==='open'?signalProjection(trade.signal_id):null;
  const pnl=projection?.current??trade.cash_pnl;
  const cls=Number(pnl)>0?'positive':Number(pnl)<0?'negative':'';
  const status=trade.status_label||trade.status||'Trade';
  const positions=[];
  if(Number(trade.open_positions)>0)positions.push(`${trade.open_positions} open`);
  if(Number(trade.pending_positions)>0)positions.push(`${trade.pending_positions} pending`);
  if(Number(trade.closed_positions)>0)positions.push(`${trade.closed_positions} closed`);
  const positionText=positions.join(' · ')||`${trade.position_count||0} position${Number(trade.position_count)===1?'':'s'}`;
  const pips=trade.net_pips===null||trade.net_pips===undefined?'—':`${Number(trade.net_pips)>0?'+':''}${fixed(trade.net_pips,1)}`;
  return `<article class="trade-row"><div class="trade-main"><strong>${trade.side||''} ${trade.symbol||'XAUUSD'}</strong><span>${status} · ${tradeReference(trade.signal_id)}</span></div><div class="trade-cell"><span>Positions</span><strong>${positionText}</strong></div><div class="trade-cell"><span>Pips</span><strong>${pips}</strong></div><div class="trade-cell"><span>P&amp;L</span><strong class="${cls}">${signed(pnl,currency)}</strong></div>${liveProjectionMarkup(projection,currency)}</article>`;
}
function renderTrades(){
  const currency=dashboard?.account?.currency||'USD';
  const trades=Array.isArray(timeline?.trades)?timeline.trades:[];
  const ongoing=trades.filter(t=>t.status==='open'||t.status==='pending');
  const recent=trades.filter(t=>['won','lost','breakeven'].includes(t.status));
  if(ui.openCount)ui.openCount.textContent=String(ongoing.length);
  if(ui.openTrades)ui.openTrades.innerHTML=ongoing.length?ongoing.map(t=>timelineRow(t,currency)).join(''):'<div class="empty">No open trades right now.</div>';
  if(ui.recentSection)ui.recentSection.classList.toggle('hidden',recent.length===0);
  const visible=recentExpanded?recent:recent.slice(0,5);
  if(ui.recentTrades)ui.recentTrades.innerHTML=visible.map(t=>timelineRow(t,currency)).join('');
  if(ui.recentToggle){
    const expandable=recent.length>5;
    ui.recentToggle.classList.toggle('hidden',!expandable);
    ui.recentToggle.textContent=recentExpanded?'Show less':`Show ${recent.length-5} more`;
  }
}

function renderToday(today){
  const currency=dashboard?.account?.currency||'USD';
  const pnl=Number(today?.realised_pnl||0),pips=Number(today?.net_pips||0);
  const wins=Number(today?.wins||0),losses=Number(today?.losses||0),breakeven=Number(today?.breakeven||0),open=Number(today?.open||0);
  const actualTrades=wins+losses+breakeven+open;
  if(ui.todayPnl){ui.todayPnl.textContent=money(pnl,currency);tone(ui.todayPnl,pnl);}
  if(ui.netPips){ui.netPips.textContent=`${pips>=0?'+':''}${fixed(pips,1)}`;tone(ui.netPips,pips);}
  if(ui.tradeCount)ui.tradeCount.textContent=String(actualTrades);
  if(ui.winLoss)ui.winLoss.textContent=`${wins} / ${losses}`;
}

function renderPerformance(){
  if(!ui.performance)return;
  const currency=dashboard?.account?.currency||'USD';
  const keys=[['today','Today'],['week','This week'],['month','This month'],['all','All time']];
  ui.performance.innerHTML=keys.map(([key,label])=>{
    const value=period(key)?.amount;
    const cls=Number(value)>0?'positive':Number(value)<0?'negative':'';
    return `<article class="metric"><span>${label}</span><strong class="${cls}">${signed(value,currency)}</strong></article>`;
  }).join('');
}

async function refreshGold(){
  try{
    const r=await fetch(GOLD_URL,{cache:'no-store',headers:{Accept:'application/json'}});
    const quote=await r.json();
    if(r.ok&&quote?.available&&Number.isFinite(Number(quote.price))){
      if(ui.goldPrice)ui.goldPrice.textContent=`$${Number(quote.price).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}`;
      if(ui.goldState)ui.goldState.textContent=quote.stale?'MARKET':'LIVE';
      return;
    }
  }catch{}
  if(ui.goldState)ui.goldState.textContent='—';
}

function setRefresh(active){if(!ui.refresh)return;ui.refresh.disabled=active;ui.refresh.textContent='↻';ui.refresh.classList.toggle('is-refreshing',active);}

async function refreshAll(){
  if(refreshing)return;
  refreshing=true;setRefresh(true);
  try{
    const [auth,dash,today,line]=await Promise.all([
      responseJson(`${API_BASE}/auth/me`),
      responseJson(DASHBOARD_URL),
      responseJson(TODAY_URL),
      responseJson(TIMELINE_URL),
    ]);
    if(auth.status===401||auth.status===403){location.replace('/join?mode=login');return;}
    if(!auth.ok||!auth.body){setError('Connection interrupted. Your session is still open — tap refresh to retry.');return;}
    user=auth.body;
    dashboard=dash.ok?dash.body:null;
    timeline=line.ok?line.body:null;
    renderIdentity();
    renderConnection();
    renderBalance();
    renderToday(today.ok?today.body:null);
    renderTrades();
    renderPerformance();
    setError(dash.ok&&line.ok?'':'Live trading data is updating. Tap refresh if it does not recover automatically.');
  }catch{
    setError('Connection interrupted. Your session is still open — tap refresh to retry.');
  }finally{
    refreshing=false;setRefresh(false);
  }
}

ui.refresh?.addEventListener('click',()=>refreshAll());
ui.recentToggle?.addEventListener('click',()=>{recentExpanded=!recentExpanded;renderTrades();});
ui.signout?.addEventListener('click',async()=>{try{await fetch(`${API_BASE}/auth/logout`,{method:'POST',credentials:'include',cache:'no-store'});}finally{location.replace('/');}});

refreshAll();refreshGold();
setInterval(()=>{if(!document.hidden)refreshGold();},5000);
setInterval(()=>{if(!document.hidden)refreshAll();},15000);
window.addEventListener('focus',()=>{refreshAll();refreshGold();});
window.addEventListener('pageshow',()=>{refreshAll();refreshGold();});
