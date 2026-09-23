import PERFORMANCE_JS from './performance-hotfix.txt';

const STATIC_ORIGIN='https://super-signals-website.dannythehat2.workers.dev';
const API_ORIGIN='https://super-signals-day-8.onrender.com';

const noStoreHeaders={
  'cache-control':'no-store, no-cache, must-revalidate, max-age=0',
  pragma:'no-cache',
  expires:'0'
};

function finiteNumber(value){
  return value!==null&&value!==undefined&&Number.isFinite(Number(value));
}

async function fetchJson(url){
  const controller=new AbortController();
  const timeout=setTimeout(()=>controller.abort(),8000);
  try{
    const response=await fetch(url,{
      headers:{accept:'application/json','cache-control':'no-cache'},
      cf:{cacheTtl:0,cacheEverything:false},
      signal:controller.signal
    });
    if(!response.ok)return null;
    return await response.json();
  }catch{
    return null;
  }finally{
    clearTimeout(timeout);
  }
}

async function mergedPerformance(){
  const stamp=Date.now();
  const [base,live]=await Promise.all([
    fetchJson(`${STATIC_ORIGIN}/data/public-performance.json?hotfix=${stamp}`),
    fetchJson(`${API_ORIGIN}/account/mt5/dashboard/public-performance?hotfix=${stamp}`)
  ]);
  if(!base||!Array.isArray(base.daily))return live||base||{daily:[]};
  if(!live||!Array.isArray(live.daily))return base;

  const byDay=new Map(base.daily.map(row=>[String(row.date),row]));
  for(const row of live.daily){
    const day=String(row?.day||'');
    if(!day||day<'2026-09-23')continue;
    if(!finiteNumber(row.opening_balance)||!finiteNumber(row.closing_balance))continue;
    const opening=Number(row.opening_balance);
    const closing=Number(row.closing_balance);
    byDay.set(day,{
      date:day,
      status:'verified',
      history_type:'verified',
      balance_start:Number(opening.toFixed(2)),
      cash_pnl:Number((closing-opening).toFixed(2)),
      balance_end:Number(closing.toFixed(2))
    });
  }

  base.daily=[...byDay.values()].sort((a,b)=>String(a.date).localeCompare(String(b.date)));
  const accountValue=Number(live.current_account_value);
  if(Number.isFinite(accountValue))base.current_recorded_balance=Number(accountValue.toFixed(2));
  base.live_updated_at=live.updated_at||null;
  base.live_source='vantage_equity_21_sofia_hotfix';
  return base;
}

async function proxyStatic(request){
  const incoming=new URL(request.url);
  const upstream=new URL(STATIC_ORIGIN);
  upstream.pathname=incoming.pathname;
  upstream.search=incoming.search;
  const response=await fetch(upstream.toString(),{
    method:request.method,
    headers:{accept:request.headers.get('accept')||'*/*'},
    cf:{cacheTtl:0,cacheEverything:false}
  });
  const headers=new Headers(response.headers);
  for(const [k,v] of Object.entries(noStoreHeaders))headers.set(k,v);
  headers.delete('etag');
  return new Response(response.body,{status:response.status,statusText:response.statusText,headers});
}

export default {
  async fetch(request){
    const url=new URL(request.url);

    if(url.pathname==='/data/public-performance.json'){
      const payload=await mergedPerformance();
      return new Response(JSON.stringify(payload),{
        status:200,
        headers:{'content-type':'application/json; charset=utf-8',...noStoreHeaders}
      });
    }

    if(url.pathname==='/performance-hotfix.js'||url.pathname==='/performance.js'){
      return new Response(PERFORMANCE_JS,{
        status:200,
        headers:{'content-type':'application/javascript; charset=utf-8',...noStoreHeaders}
      });
    }

    if(url.pathname==='/performance'||url.pathname==='/performance.html'){
      const upstream=await fetch(`${STATIC_ORIGIN}${url.pathname}?hotfix=${Date.now()}`,{
        cf:{cacheTtl:0,cacheEverything:false}
      });
      let html=await upstream.text();
      html=html.replace(
        /<script src="\/performance\.js\?[^"]*" defer><\/script>/,
        '<script src="/performance-hotfix.js?v=20260923-hotfix1" defer></script>'
      );
      return new Response(html,{
        status:upstream.status,
        headers:{'content-type':'text/html; charset=utf-8',...noStoreHeaders}
      });
    }

    return proxyStatic(request);
  }
};
