import baseWorker from './index-v3.js';

const ACCOUNT_API_PREFIX = '/account-api';
const ACCOUNT_API_ORIGIN = 'https://super-signals-day-8.onrender.com';
const ALLOWED_METHODS = new Set(['GET', 'POST', 'PATCH', 'HEAD', 'OPTIONS']);
const TRANSIENT_ORIGIN_STATUSES = new Set([502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 530]);
const FRESH_PERFORMANCE_PATHS = new Set(['/performance', '/performance.html', '/performance.js', '/data/public-performance.json']);

function proxyPath(pathname) {
  const stripped = pathname.slice(ACCOUNT_API_PREFIX.length);
  return stripped || '/';
}

function retryableRequest(method, upstreamPath) {
  if (method === 'GET' || method === 'HEAD' || method === 'OPTIONS') return true;
  return method === 'POST' && upstreamPath === '/auth/login';
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function laxSessionCookie(headers) {
  const cookie = headers.get('set-cookie');
  if (!cookie) return;
  headers.set('set-cookie', cookie.replace(/SameSite=Strict/gi, 'SameSite=Lax'));
}

function noStoreResponse(response) {
  const headers = new Headers(response.headers);
  headers.set('cache-control', 'no-store, no-cache, must-revalidate, max-age=0');
  headers.set('pragma', 'no-cache');
  headers.set('expires', '0');
  headers.delete('etag');
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function unavailableResponse() {
  return new Response(JSON.stringify({
    detail: {
      code: 'account_service_temporarily_unavailable',
      message: 'Smart Signals account service is reconnecting. Please try again in a moment.',
    },
  }), {
    status: 503,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store, no-cache, must-revalidate, max-age=0',
      pragma: 'no-cache',
      'retry-after': '2',
    },
  });
}

async function fetchLivePublicPerformance() {
  const upstream = new URL('/account/mt5/dashboard/public-performance', ACCOUNT_API_ORIGIN);
  upstream.searchParams.set('worker_live', String(Date.now()));
  const delays = [0, 180, 550];

  for (let attempt = 0; attempt < delays.length; attempt += 1) {
    if (delays[attempt]) await sleep(delays[attempt]);
    try {
      const response = await fetch(upstream.toString(), {
        method: 'GET',
        headers: {
          accept: 'application/json',
          'cache-control': 'no-cache',
          'user-agent': 'SmartSignalsWebsite/1.0',
        },
        redirect: 'manual',
      });
      if (response.ok) return await response.json();
      if (!TRANSIENT_ORIGIN_STATUSES.has(response.status)) return null;
    } catch {}
  }
  return null;
}

function finiteNumber(value) {
  return value !== null && value !== undefined && Number.isFinite(Number(value));
}

async function livePerformanceData(request, env) {
  let staticPayload = null;
  let staticStatus = 200;
  try {
    const asset = await env.ASSETS.fetch(request);
    staticStatus = asset.status;
    if (asset.ok) staticPayload = await asset.json();
  } catch {}

  if (!staticPayload || !Array.isArray(staticPayload.daily)) {
    return new Response(JSON.stringify({ detail: { code: 'performance_asset_unavailable' } }), {
      status: staticStatus >= 400 ? staticStatus : 503,
      headers: {
        'content-type': 'application/json; charset=utf-8',
        'cache-control': 'no-store, no-cache, must-revalidate, max-age=0',
      },
    });
  }

  const live = await fetchLivePublicPerformance();
  if (live && Array.isArray(live.daily)) {
    const byDay = new Map(staticPayload.daily.map((row) => [String(row.date), row]));

    for (const row of live.daily) {
      const day = String(row?.day || '');
      if (!day || day < '2026-09-23') continue;
      if (!finiteNumber(row.opening_balance) || !finiteNumber(row.closing_balance)) continue;

      const opening = Number(row.opening_balance);
      const closing = Number(row.closing_balance);
      byDay.set(day, {
        date: day,
        status: 'verified',
        history_type: 'verified',
        balance_start: Number(opening.toFixed(2)),
        cash_pnl: Number((closing - opening).toFixed(2)),
        balance_end: Number(closing.toFixed(2)),
      });
    }

    staticPayload.daily = [...byDay.values()].sort((a, b) => String(a.date).localeCompare(String(b.date)));

    const accountValue = Number(live.current_account_value);
    if (Number.isFinite(accountValue)) {
      staticPayload.current_recorded_balance = Number(accountValue.toFixed(2));
    }
    staticPayload.live_updated_at = live.updated_at || null;
    staticPayload.live_source = 'vantage_equity_21_sofia';
  }

  return new Response(JSON.stringify(staticPayload), {
    status: 200,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store, no-cache, must-revalidate, max-age=0',
      pragma: 'no-cache',
      expires: '0',
    },
  });
}

async function resilientAccountProxy(request) {
  if (!ALLOWED_METHODS.has(request.method)) {
    return new Response('Method not allowed', { status: 405 });
  }

  const incoming = new URL(request.url);
  const upstreamPath = proxyPath(incoming.pathname);
  const upstream = new URL(ACCOUNT_API_ORIGIN);
  upstream.pathname = upstreamPath;
  upstream.search = incoming.search;

  const headers = new Headers(request.headers);
  headers.delete('host');
  headers.delete('origin');
  headers.set('accept-encoding', 'identity');
  headers.set('x-forwarded-host', incoming.host);
  headers.set('x-forwarded-proto', 'https');

  let body = null;
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    try {
      body = await request.arrayBuffer();
    } catch {
      return unavailableResponse();
    }
  }

  const canRetry = retryableRequest(request.method, upstreamPath);
  const attempts = canRetry ? 3 : 1;
  const delays = [0, 180, 550];

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    if (delays[attempt]) await sleep(delays[attempt]);
    try {
      const init = {
        method: request.method,
        headers,
        redirect: 'manual',
      };
      if (body !== null) init.body = body.slice(0);

      const upstreamResponse = await fetch(upstream.toString(), init);
      if (canRetry && TRANSIENT_ORIGIN_STATUSES.has(upstreamResponse.status) && attempt + 1 < attempts) {
        try { await upstreamResponse.body?.cancel(); } catch {}
        continue;
      }

      if (TRANSIENT_ORIGIN_STATUSES.has(upstreamResponse.status)) {
        return unavailableResponse();
      }

      const responseHeaders = new Headers(upstreamResponse.headers);
      responseHeaders.set('cache-control', 'no-store, no-cache, must-revalidate, max-age=0');
      responseHeaders.set('pragma', 'no-cache');
      responseHeaders.set('expires', '0');
      responseHeaders.delete('content-length');
      laxSessionCookie(responseHeaders);

      return new Response(upstreamResponse.body, {
        status: upstreamResponse.status,
        statusText: upstreamResponse.statusText,
        headers: responseHeaders,
      });
    } catch {
      if (attempt + 1 >= attempts) return unavailableResponse();
    }
  }

  return unavailableResponse();
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === ACCOUNT_API_PREFIX || url.pathname.startsWith(`${ACCOUNT_API_PREFIX}/`)) {
      return resilientAccountProxy(request);
    }
    if (url.pathname === '/data/public-performance.json' && (request.method === 'GET' || request.method === 'HEAD')) {
      return livePerformanceData(request, env);
    }
    const response = await baseWorker.fetch(request, env, ctx);
    return FRESH_PERFORMANCE_PATHS.has(url.pathname) ? noStoreResponse(response) : response;
  },
};