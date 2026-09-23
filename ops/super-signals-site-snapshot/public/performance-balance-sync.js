(()=>{
  const API='/account-api';
  const INTERVAL_MS=5000;
  const CACHE_KEY='smart-signals-performance-live-v2';
  const TZ=Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC';
  const target=document.querySelector('[data-end-balance]');
  const note=document.querySelector('[data-current-balance-note]');
  if(!target)return;

  let dashboardPromise=null;
  let identityPromise=null;

  function money(value,currency='USD'){
    const number=Number(value);
    if(!Number.isFinite(number))return null;
    try{return new Intl.NumberFormat(undefined,{style:'currency',currency:currency||'USD',minimumFractionDigits:2,maximumFractionDigits:2}).format(number);}
    catch{return `${currency||'$'} ${number.toFixed(2)}`;}
  }

  async function readJson(url){
    const response=await fetch(url,{credentials:'include',cache:'no-store',headers:{Accept:'application/json'}});
    if(!response.ok)return null;
    return response.json().catch(()=>null);
  }

  function getIdentity(){
    if(!identityPromise)identityPromise=readJson(`${API}/auth/me`);
    return identityPromise;
  }

  function getDashboard(){
    if(dashboardPromise)return dashboardPromise;
    const query=new URLSearchParams({timezone_name:TZ});
    dashboardPromise=readJson(`${API}/account/mt5/dashboard?${query}`).finally(()=>{
      window.setTimeout(()=>{dashboardPromise=null;},250);
    });
    return dashboardPromise;
  }

  function roleAllowed(role){
    const value=String(role||'').toLowerCase();
    return value==='owner'||value==='admin';
  }

  function updateBalance(dashboard){
    const accountValue=dashboard?.account?.equity??dashboard?.account?.balance;
    const formatted=money(accountValue,dashboard?.account?.currency||'USD');
    if(!formatted)return;
    target.textContent=formatted;
    if(note)note.textContent='Live account value · synced with Vantage';
  }

  function applyDashboardToPerformance(dashboard,role){
    if(!dashboard||!roleAllowed(role))return false;
    // The public 21:00-Sofia equity feed is the only calendar authority.
    // Signed-in dashboard refreshes may update the headline account value, but must
    // never overwrite calendar days with the dashboard's different aggregation path.
    updateBalance(dashboard);
    return true;
  }

  function applyWhenReady(dashboard,role,attempt=0){
    if(applyDashboardToPerformance(dashboard,role))return;
    if(attempt<80)window.setTimeout(()=>applyWhenReady(dashboard,role,attempt+1),25);
  }

  function writeCache(dashboard,role){
    if(!roleAllowed(role)||!Array.isArray(dashboard?.daily_profit))return;
    try{
      localStorage.setItem(CACHE_KEY,JSON.stringify({
        saved_at:Date.now(),
        role:String(role).toLowerCase(),
        account:dashboard.account||null,
        daily_profit:dashboard.daily_profit,
      }));
    }catch{}
  }

  function readCache(){
    try{
      const cached=JSON.parse(localStorage.getItem(CACHE_KEY)||'null');
      if(!cached||!roleAllowed(cached.role)||!Array.isArray(cached.daily_profit))return;
      const dashboard={account:cached.account||null,daily_profit:cached.daily_profit};
      updateBalance(dashboard);
      applyWhenReady(dashboard,cached.role);
    }catch{}
  }

  async function sync(){
    if(document.visibilityState!=='visible')return;
    try{
      const dashboardTask=getDashboard();
      const identityTask=getIdentity();
      const dashboard=await dashboardTask;
      if(!dashboard)return;
      updateBalance(dashboard);

      const cachedRole=(()=>{try{return JSON.parse(localStorage.getItem(CACHE_KEY)||'null')?.role||null;}catch{return null;}})();
      if(roleAllowed(cachedRole))applyWhenReady(dashboard,cachedRole);

      const identity=await identityTask;
      const role=identity?.role||cachedRole;
      if(roleAllowed(role)){
        writeCache(dashboard,role);
        applyWhenReady(dashboard,role);
      }
    }catch{}
  }

  readCache();
  sync();
  window.setInterval(sync,INTERVAL_MS);
  window.addEventListener('focus',sync);
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')sync();});
})();
