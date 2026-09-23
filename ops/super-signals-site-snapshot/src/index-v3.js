import baseWorker from './index-v2.js';

const ACCOUNT_API_ORIGIN = 'https://super-signals-day-8.onrender.com';
const JOIN_PATHS = new Set(['/join', '/join.html', '/join-launch.html']);
const PRIVILEGED_ROLES = new Set(['owner', 'admin', 'trading_admin']);

function joinPath(pathname) {
  const normalized = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname;
  return JOIN_PATHS.has(normalized);
}

function manageMode(url) {
  const value = url.searchParams.get('manage');
  return value === '1' || value === 'true';
}

async function upstreamJson(request, path, timeoutMs = 4200) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const headers = new Headers();
    headers.set('accept', 'application/json');
    headers.set('cache-control', 'no-store');
    const cookie = request.headers.get('cookie');
    if (cookie) headers.set('cookie', cookie);
    const response = await fetch(`${ACCOUNT_API_ORIGIN}${path}`, {
      method: 'GET',
      headers,
      redirect: 'manual',
      signal: controller.signal,
    });
    const data = response.ok ? await response.json().catch(() => null) : null;
    return { ok: response.ok, status: response.status, data };
  } catch {
    return { ok: false, status: 0, data: null };
  } finally {
    clearTimeout(timeout);
  }
}

function mt5Connected(data) {
  return data?.connection?.status === 'connected' || Boolean(data?.account) || Boolean(data?.configured);
}

async function memberDisposition(request) {
  const auth = await upstreamJson(request, '/auth/me');
  if (auth.status === 401 || auth.status === 403) return 'anonymous';
  if (!auth.ok || !auth.data) return 'unknown';

  const role = String(auth.data.role || '').toLowerCase();
  if (PRIVILEGED_ROLES.has(role)) return 'complete';

  const [dashboard, subscription] = await Promise.all([
    upstreamJson(request, '/account/mt5/dashboard'),
    upstreamJson(request, '/account/mt5/subscription'),
  ]);

  const dashboardKnown = dashboard.ok || dashboard.status === 404;
  const subscriptionKnown = subscription.ok || subscription.status === 404;
  if (!dashboardKnown || !subscriptionKnown) return 'unknown';

  return dashboard.ok
    && mt5Connected(dashboard.data)
    && subscription.ok
    && Boolean(subscription.data?.active)
    ? 'complete'
    : 'incomplete';
}

function noStore(response) {
  const headers = new Headers(response.headers);
  headers.set('cache-control', 'no-store, no-cache, must-revalidate, max-age=0');
  headers.set('pragma', 'no-cache');
  headers.set('expires', '0');
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function checkingResponse() {
  const html = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#041019"><title>Opening Smart Signals</title><style>html,body{margin:0;min-height:100%;background:#041019;color:#f7fbff;font-family:Inter,system-ui,sans-serif}body{display:grid;place-items:center;min-height:100vh}.box{width:min(88vw,420px);padding:28px;border:1px solid rgba(80,235,223,.25);border-radius:24px;background:linear-gradient(145deg,rgba(7,36,45,.96),rgba(3,17,27,.98));box-shadow:0 22px 70px rgba(0,0,0,.4);text-align:center}.dot{display:inline-block;width:11px;height:11px;border-radius:50%;background:#4ef39a;box-shadow:0 0 22px #4ef39a;margin-right:8px}.box strong{font-size:1.35rem}.box p{color:#9eb0bd;line-height:1.55;margin:12px 0 0}</style><script src="/join-member-gate.js?v=20260831-permanent5" defer></script></head><body><div class="box"><strong><span class="dot"></span>Opening your account…</strong><p>Your Smart Signals session is active. We are checking your account state.</p></div></body></html>`;
  return noStore(new Response(html, { status: 200, headers: { 'content-type': 'text/html; charset=utf-8' } }));
}

async function serveCleanAccount(request, env) {
  const assetUrl = new URL(request.url);
  assetUrl.pathname = '/account.html';
  assetUrl.search = '';
  const response = await env.ASSETS.fetch(new Request(assetUrl.toString(), request));
  return noStore(response);
}

class JoinHeadInjector {
  element(element) {
    element.prepend('<script src="/join-login-lock.js?v=20260831-permanent5"></script>', { html: true });
  }
}

class JoinMemberGateInjector {
  element(element) {
    element.append('<script src="/join-member-gate.js?v=20260831-permanent5" defer></script>', { html: true });
  }
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const isJoin = joinPath(url.pathname);

    if (url.pathname === '/account' && (request.method === 'GET' || request.method === 'HEAD')) {
      return serveCleanAccount(request, env);
    }

    if (isJoin && !manageMode(url) && (request.method === 'GET' || request.method === 'HEAD')) {
      const disposition = await memberDisposition(request);
      if (disposition === 'complete') {
        return Response.redirect(new URL('/account', url.origin).toString(), 302);
      }
      if (disposition === 'unknown' && request.headers.get('cookie')) {
        return checkingResponse();
      }
    }

    const response = await baseWorker.fetch(request, env, ctx);
    const contentType = response.headers.get('content-type') || '';
    if (!isJoin || manageMode(url) || !contentType.includes('text/html')) return response;

    const transformed = new HTMLRewriter()
      .on('head', new JoinHeadInjector())
      .on('body', new JoinMemberGateInjector())
      .transform(response);
    return noStore(transformed);
  },
};
