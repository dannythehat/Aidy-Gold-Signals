const API_BASE='/account-api';
const DASHBOARD_URL=`${API_BASE}/account/mt5/dashboard?timezone_name=Europe%2FLondon`;
const TODAY_URL=`${API_BASE}/account/mt5/dashboard/today?timezone_name=Europe%2FLondon`;
const PERFORMANCE_URL='/data/public-performance.json';
const GOLD_URL='/api/gold-price';
const PRIVILEGED_ROLES=new Set(['owner','admin']);

const $=(s)=>document.querySelector(s);
const ui={
  name:$('[data-display-name]'),connection:$('[data-connection-status]'),mode:$('[data-account-mode]'),
  balance:$('[data-balance]'),balanceLabel:$('[data-balance-label]'),balanceNote:$('[data-balance-note]'),
  baselineRow:$('[data-baseline-row]'),baselinePnl:$('[data-baseline-pnl]'),baselineReturn:$('[data-baseline-return]'),
  accountLabel:$('[data-account-label]'),login:$('[data-login-mask]'),server:$('[data-server]'),brokerStatus:$('[data-broker-status]'),
  brokerBalance:$('[data-broker-balance]'),equity:$('[data-equity]'),error:$('[data-account-error]'),
  todayPnl:$('[data-today-pnl]'),netPips:$('[data-net-pips]'),tradeCount:$('[data-trade-count]'),winLoss:$('[data-win-loss]'),
  openCount:$('[data-open-count]'),openTrades:$('[data-open-trades]'),recentTrades:$('[data-recent-trades]'),recentSection:$('[data-recent-section]'),
  performance:$('[data-performance-grid]'),refresh:$('[data-refresh]'),signout:$('[data-signout]'),goldPrice:$('[data-gold-price]'),goldState:$('[data-gold-state]')
};

let user=null,dashboard=null,publicPerformance=null,refreshing=false;

function usd(value){
  if(value===null||value===undefined||!Number.isFinite(Number(value))) return '—';
  const n=Number(value);return `${n<0?'-$':'$'}${Math.abs(n).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}`;
}
function money(value,currency='USD'){if(currency==='USD')return usd(value);try{return new Intl.NumberFormat(undefined,{style:'currency',currency,minimumFractionDigits:2,maximumFractionDigits:2}).format(Number(value));}catch{return `${currency} ${Number(value||0).toFixed(2)}`}}
function signed(value,currency='USD'){const n=Number(value||0);const m=money(Math.abs(n),currency);return `${n>=0?'+':'-'}${m}`}
function fixed(value,digits=1){return Number.isFinite(Number(value))?Number(value).toFixed(digits):'—'}
function tone(el,value){if(!el)return;el.classList.remove('positive','negative');if(Number(value)>0)el.classList.add('positive');if(Number(value)<0)el.classList.add('negative')}
function setError(message=''){if(!ui.error)return;ui.error.textContent=message;ui.error.classList.toggle('hidden',!message)}
function modeLabel(environment){return environment==='demo'?'Paper account':environment==='live'?'Real account':'MT5 account'}
function londonDate(){return new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/London',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())}
function parseDate(s){return new Date(`${s}T12:00:00Z`)}
function mondayOf(dateString){const d=parseDate(dateString);const day=(d.getUTCDay()+6)%7;d.setUTCDate(d.getUTCDate()-day);return d.toISOString().slice(0,10)}

async function fetchJson(url){
  try{
    const r=await fetch(url,{credentials:'include',cache:'no-store',headers:{Accept:'application/json'}});
    if(!r.ok)return null;
    return r.json().catch(()=>null);
  }catch{return null}
}

async function fetchAuth(){
  try{
    const r=await fetch(`${API_BASE}/auth/me`,{credentials:'include',cache:'no-store',headers:{Accept:'application/json'}});
    if(r.status===401||r.status===403)return{state:'unauthorized',data:null};
    if(!r.ok)return{state:'error',data:null};
    const data=await r.json().catch(()=>null);
    return data?{state:'ok',data}:{state:'error',data:null};
  }catch{return{state:'error',data:null}}
}

function referenceRecords(){return Array.isArray(publicPerformance?.daily)?publicPerformance.daily:[]}
function referenceBalance(){
  const live=publicPerformance?.live_baseline;
  if(!live)return null;
  const liveRows=referenceRecords().filter(r=>r.date>=live.start_date&&r.history_type!=='reconstructed').sort((a,b)=>a.date.localeCompare(b.date));
  return liveRows.length?Number(liveRows[liveRows.length-1].balance_end):Number(live.starting_balance);
}
function referencePnlBetween(start,end){return referenceRecords().filter(r=>r.date>=start&&r.date<=end).reduce((sum,r)=>sum+Number(r.cash_pnl||0),0)}
function referenceAllTime(){return referenceRecords().reduce((sum,r)=>sum+Number(r.cash_pnl||0),0)}

function renderIdentity(){if(!user)return;if(ui.name)ui.name.textContent=user.display_name||user.email?.split('@')[0]||'Trader'}

function renderConnection(){
  const connected=dashboard?.connection?.status==='connected'||Boolean(dashboard?.account);
  const environment=dashboard?.connection?.account_environment;
  const currency=dashboard?.account?.currency||'USD';
  if(ui.connection){ui.connection.textContent=connected?'MT5 connected':'MT5 needs setup';ui.connection.classList.toggle('ok',connected)}
  if(ui.mode)ui.mode.textContent=modeLabel(environment);
  if(ui.accountLabel)ui.accountLabel.textContent=modeLabel(environment);
  if(ui.login)ui.login.textContent=dashboard?.connection?.login_masked||'—';
  if(ui.server)ui.server.textContent=dashboard?.connection?.server||'—';
  if(ui.brokerStatus)ui.brokerStatus.textContent=connected?'Connected':'Needs setup';
  if(ui.brokerBalance)ui.brokerBalance.textContent=dashboard?.account?money(dashboard.account.balance,currency):'—';
  if(ui.equity)ui.equity.textContent=dashboard?.account?money(dashboard.account.equity,currency):'—';
}

function renderPrimaryBalance(){
  const privileged=PRIVILEGED_ROLES.has(String(user?.role||'').toLowerCase());
  const currency=dashboard?.account?.currency||'USD';
  if(privileged&&publicPerformance?.live_baseline){
    const balance=referenceBalance();
    const hist=publicPerformance.historical_baseline||{};
    if(ui.balanceLabel)ui.balanceLabel.textContent='Smart Signals performance balance';
    if(ui.balance)ui.balance.textContent=money(balance,'USD');
    if(ui.balanceNote)ui.balanceNote.textContent='Matches the public performance record';
    if(ui.baselinePnl){ui.baselinePnl.textContent=signed(hist.net_pnl||0,'USD');tone(ui.baselinePnl,hist.net_pnl)}
    if(ui.baselineReturn){const start=Number(hist.starting_balance||0);const pct=start?Number(hist.net_pnl||0)/start*100:0;ui.baselineReturn.textContent=`${pct>=0?'+':''}${pct.toFixed(2)}%`;tone(ui.baselineReturn,pct)}
    ui.baselineRow?.classList.remove('hidden');
  }else{
    if(ui.balanceLabel)ui.balanceLabel.textContent='Your broker balance';
    if(ui.balance)ui.balance.textContent=dashboard?.account?money(dashboard.account.balance,currency):'—';
    if(ui.balanceNote)ui.balanceNote.textContent=dashboard?.account?'Current connected MT5 balance':'Connect MT5 to show your balance';
    ui.baselineRow?.classList.add('hidden');
  }
}

function tradeRow(position,currency,completed=false){
  const pnl=completed?position.pnl_amount:position.profit;const cls=Number(pnl)>0?'positive':Number(pnl)<0?'negative':'';
  return `<article class="trade-row"><div class="trade-main"><strong>${position.symbol||'XAUUSD'} · ${position.side||''}</strong><span>${completed?'Completed':'Open'}${position.tp_index!=null?` · TP ${position.tp_index}`:''}</span></div><div class="trade-cell"><span>${completed?'Result':'Entry'}</span><strong>${completed?(position.close_reason||'Closed'):fixed(position.entry_price,2)}</strong></div><div class="trade-cell"><span>${completed?'Target':'Current'}</span><strong>${completed?`TP ${position.tp_index??'—'}`:fixed(position.current_price??position.entry_price,2)}</strong></div><div class="trade-cell"><span>P&amp;L</span><strong class="${cls}">${money(pnl,currency)}</strong></div></article>`;
}
function renderTrades(){
  const currency=dashboard?.account?.currency||'USD';const open=Array.isArray(dashboard?.open_positions)?dashboard.open_positions:[];const recent=Array.isArray(dashboard?.recent_completed)?dashboard.recent_completed:[];
  if(ui.openCount)ui.openCount.textContent=String(open.length);
  if(ui.openTrades)ui.openTrades.innerHTML=open.length?open.map(x=>tradeRow(x,currency,false)).join(''):'<div class="empty">No open trades right now.</div>';
  if(ui.recentSection)ui.recentSection.classList.toggle('hidden',!recent.length);
  if(ui.recentTrades)ui.recentTrades.innerHTML=recent.slice(0,6).map(x=>tradeRow(x,currency,true)).join('');
}

function renderToday(today){
  const currency=dashboard?.account?.currency||'USD';const pnl=Number(today?.realised_pnl||0),pips=Number(today?.net_pips||0);
  if(ui.todayPnl){ui.todayPnl.textContent=money(pnl,currency);tone(ui.todayPnl,pnl)}
  if(ui.netPips){ui.netPips.textContent=`${pips>=0?'+':''}${fixed(pips,1)}`;tone(ui.netPips,pips)}
  if(ui.tradeCount)ui.tradeCount.textContent=String(today?.trades??0);
  if(ui.winLoss)ui.winLoss.textContent=`${today?.wins??0} / ${today?.losses??0}`;
}

function renderPerformance(){
  if(!ui.performance)return;
  const privileged=PRIVILEGED_ROLES.has(String(user?.role||'').toLowerCase());
  if(privileged&&publicPerformance){
    const today=londonDate(),weekStart=mondayOf(today),monthStart=`${today.slice(0,7)}-01`;
    const values=[['Today',referencePnlBetween(today,today)],['This week',referencePnlBetween(weekStart,today)],['This month',referencePnlBetween(monthStart,today)],['All time',referenceAllTime()]];
    ui.performance.innerHTML=values.map(([label,value])=>`<article class="metric"><span>${label}</span><strong class="${value>0?'positive':value<0?'negative':''}">${signed(value,'USD')}</strong></article>`).join('');
    return;
  }
  const periods=Array.isArray(dashboard?.performance)?dashboard.performance:[];const preferred=['today','week','month','all'];
  const source=preferred.map(k=>periods.find(x=>x.key===k)).filter(Boolean);
  if(source.length)ui.performance.innerHTML=source.map(item=>`<article class="metric"><span>${item.label||item.key}</span><strong class="${Number(item.amount)>0?'positive':Number(item.amount)<0?'negative':''}">${signed(item.amount,dashboard?.account?.currency||'USD')}</strong></article>`).join('');
}

async function refreshGold(){
  try{const q=await fetchJson(GOLD_URL);if(q?.available&&Number.isFinite(Number(q.price))){if(ui.goldPrice)ui.goldPrice.textContent=`$${Number(q.price).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}`;if(ui.goldState)ui.goldState.textContent=q.stale?'MARKET':'LIVE';return}}catch{}
  if(ui.goldState)ui.goldState.textContent='—';
}

function setRefreshState(active){
  if(!ui.refresh)return;
  ui.refresh.disabled=active;
  ui.refresh.textContent='↻';
  ui.refresh.classList.toggle('is-refreshing',active);
  ui.refresh.setAttribute('aria-busy',active?'true':'false');
}

async function refreshAll(){
  if(refreshing)return;
  refreshing=true;
  setRefreshState(true);
  try{
    const [authResult,dash,today,perf]=await Promise.all([
      fetchAuth(),
      fetchJson(DASHBOARD_URL),
      fetchJson(TODAY_URL),
      fetchJson(PERFORMANCE_URL),
    ]);

    if(authResult.state==='unauthorized'){
      location.replace('/join?mode=login');
      return;
    }
    if(authResult.state!=='ok'){
      setError('Connection interrupted. Your session is still open — tap refresh to retry.');
      return;
    }

    user=authResult.data;
    dashboard=dash;
    publicPerformance=perf;
    renderIdentity();
    renderConnection();
    renderPrimaryBalance();
    renderToday(today);
    renderTrades();
    renderPerformance();
    setError(dash?'':'Account data is temporarily unavailable. Tap refresh to retry.');
  }catch{
    setError('Connection interrupted. Your session is still open — tap refresh to retry.');
  }finally{
    refreshing=false;
    setRefreshState(false);
  }
}

ui.refresh?.addEventListener('click',()=>refreshAll());
ui.signout?.addEventListener('click',async()=>{try{await fetch(`${API_BASE}/auth/logout`,{method:'POST',credentials:'include',cache:'no-store'})}finally{location.replace('/')}});

refreshAll();
refreshGold();
setInterval(()=>{if(!document.hidden)refreshGold()},5000);
setInterval(()=>{if(!document.hidden)refreshAll()},60000);
window.addEventListener('focus',()=>{refreshAll();refreshGold()});
window.addEventListener('pageshow',(event)=>{
  if(event.persisted){refreshAll();refreshGold()}
});